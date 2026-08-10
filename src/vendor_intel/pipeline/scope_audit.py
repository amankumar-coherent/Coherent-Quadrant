"""Scope audit — use collected AI Overview evidence to catch companies that do not
belong in the market at all.

Every gate in the pipeline judges a company on *its own* material: the entity gate
reads its domain, the classifier reads its website, the export gate reads the
crawl. All of those answer "does this company look like it fits?" — and a
brake-pad brand's site genuinely does look like a disc business. Textar, ATI
Metals, Noshok and eighteen others cleared every one of them on a real run.

Google's AI Overview answers a question none of those gates ask: *does the wider
web say this company operates in this market?* When it does not, it tends to say
so in the first sentence — "Textar does not operate in the rupture disc market."
That statement is the signal this module harvests.

Two stages, because the cheap one is not accurate enough alone:

1. **Screen** (free, regex). Find answers containing a negative claim about the
   market. Fast, and it narrows an LLM pass to a handful of rows.
2. **Adjudicate** (one LLM call per candidate). A regex cannot tell
   "does not manufacture rupture discs, but distributes them" (a distributor —
   in scope) from "does not operate in the rupture disc market" (out). Nor can it
   tell that ATI Metals, which "does not manufacture finished rupture discs",
   is still legitimately a raw-material supplier in the value chain. The
   adjudicator gets the evidence *and* the company's assigned section, so it can
   judge against the analyst's own market definition.

Nothing is dropped silently: every verdict carries the sentence that triggered it
and the citation URL, so a reviewer can overrule it.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Any

# Phrases an AI Overview uses when the premise of the question is wrong. Kept
# deliberately broad — this is the cheap screen, and the adjudicator is what
# decides. Missing a candidate costs more than passing a false one through.
_NEGATIVE = re.compile(
    r"(?:"
    r"does not (?:operate|participate|manufacture|produce|make|supply|sell|offer|appear|"
    r"specialali[sz]e|specciali[sz]e|speciali[sz]e|compete)"
    r"|is not (?:a |an )?(?:known |major |direct )?(?:manufacturer|producer|supplier|"
    r"participant|player|vendor|company|entity|part of)"
    r"|no(?:t)? (?:a )?(?:known |major |direct )?(?:player|participant|presence|involvement)"
    r"|false premise|misunderstanding in the premise|slight misunderstanding"
    r"|there (?:is|appears to be) (?:a |an )?(?:slight |possible )?"
    r"(?:misunderstanding|confusion|error|mix-?up)"
    r"|appears to be (?:a )?confusion"
    r"|unrelated to the"
    r")",
    re.I,
)

# A negative that is immediately rescued: the company does not MAKE the product
# but does distribute / stock / integrate it, which is a real value-chain role.
_RESCUE = re.compile(
    r"\b(?:but|however|instead|although|though|rather)\b[^.]{0,160}?"
    r"\b(?:distribut|resell|suppl|stock|sell|offer|provid|integrat|represent|"
    r"servic|install|source)",
    re.I,
)

_SYSTEM = """You decide whether a company belongs in a market landscape report.

You are given: the market, the company, the value-chain section an analyst assigned
it to, and what Google's AI Overview says about it.

A company IS in scope when it plays any real role in this market's value chain —
manufacturer, distributor, reseller, integrator, service provider, or supplier of
materials/components specific to this market.

A company is OUT of scope when it operates in a different market entirely and was
matched by a coincidence of wording (e.g. a brake-disc brand caught by "disc", a
disk-drive maker caught by "disk"), or when the evidence states plainly that it has
no involvement in this market.

Do not mark a company out of scope merely because it does not MANUFACTURE the
product — distributors and material suppliers belong in the landscape.

Return JSON only:
{"verdict": "in_scope" | "out_of_scope" | "unclear", "confidence": 0.0-1.0, "reason": "one short sentence"}"""


@dataclass
class Verdict:
    brand: str
    verdict: str          # in_scope | out_of_scope | unclear
    confidence: float
    reason: str
    evidence: str = ""    # the sentence that triggered the screen
    url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _first_match(text: str) -> tuple[str, str]:
    """The first sentence making a negative claim, plus the sentence after it.

    The rescue clause routinely lands in the NEXT sentence rather than the same
    one — "…does not manufacture finished rupture discs. Instead it supplies the
    nickel alloys used to produce them." Checking only the triggering sentence
    would drop a legitimate raw-material supplier.
    """
    sentences = re.split(r"(?<=[.!?])\s+", text or "")
    for i, sentence in enumerate(sentences):
        if _NEGATIVE.search(sentence):
            following = sentences[i + 1] if i + 1 < len(sentences) else ""
            return sentence.strip()[:400], following
    return "", ""


def screen(markdown: str) -> tuple[bool, str]:
    """Cheap pass: does this evidence contain an unrescued negative claim?

    Returns (is_candidate, triggering_sentence).
    """
    sentence, following = _first_match(markdown or "")
    if not sentence:
        return False, ""
    # "does not manufacture X, but distributes X" — a real role, not a rejection.
    if _RESCUE.search(sentence) or _RESCUE.search(following):
        return False, sentence
    return True, sentence


def evidence_for(brand: str, market: str, store: Any) -> tuple[str, str]:
    """The AI Overview answer describing what this company does, plus a citation."""
    from vendor_intel.evidence.ai_overview import Question

    for text in (
        f"What does {brand} do in the {market}?",
        f"What products and services does {brand} offer in the {market}?",
        f"What is {brand}'s market position and reputation in the {market}?",
    ):
        answer = store.get(Question(text=text, market=market))
        if answer is not None and answer.ok:
            return answer.markdown, (answer.urls[0] if answer.urls else "")
    return "", ""


def adjudicate(
    brand: str,
    market: str,
    section: str,
    evidence: str,
    trigger: str,
    *,
    client: Any = None,
    settings: Any = None,
) -> Verdict:
    """One LLM call to judge a screened candidate. Falls back to the screen alone."""
    if client is None or not getattr(client, "available", False):
        # No LLM: trust the screen but flag low confidence so nothing is auto-dropped.
        return Verdict(brand, "unclear", 0.4, "screened by phrase match; no LLM to adjudicate", trigger)
    payload = {
        "market": market,
        "company": brand,
        "assigned_section": section or "(none)",
        "evidence": (evidence or "")[:2500],
    }
    try:
        raw = client.complete_json(
            _SYSTEM,
            json.dumps(payload, ensure_ascii=False),
            model=getattr(settings, "classifier_model", None),
            max_tokens=400,
        )
    except Exception as exc:
        return Verdict(brand, "unclear", 0.0, f"adjudication failed: {exc}", trigger)
    if not isinstance(raw, dict):
        return Verdict(brand, "unclear", 0.0, "adjudicator returned no JSON", trigger)
    verdict = str(raw.get("verdict") or "unclear").strip().lower()
    if verdict not in ("in_scope", "out_of_scope", "unclear"):
        verdict = "unclear"
    try:
        confidence = max(0.0, min(1.0, float(raw.get("confidence") or 0)))
    except (TypeError, ValueError):
        confidence = 0.0
    return Verdict(brand, verdict, confidence, str(raw.get("reason") or "")[:300], trigger)


def audit_rows(
    rows: list[dict[str, Any]],
    market: str,
    *,
    settings: Any = None,
    store: Any = None,
    min_confidence: float = 0.7,
) -> tuple[list[Verdict], list[Verdict]]:
    """Audit exported rows against cached AI Overview evidence.

    Returns (all_verdicts, confident_out_of_scope). Only cached evidence is read —
    this never drives a browser and never blocks a run.
    """
    from vendor_intel.evidence.ai_overview import AiOverviewStore, default_cache_dir

    store = store or AiOverviewStore(default_cache_dir(market))
    client = None
    try:
        from vendor_intel.clients.claude import ClaudeClient

        client = ClaudeClient(settings) if settings is not None else None
    except Exception:
        client = None

    verdicts: list[Verdict] = []
    for row in rows:
        brand = str(row.get("company") or row.get("brand") or "").strip()
        if not brand:
            continue
        evidence, url = evidence_for(brand, market, store)
        if not evidence:
            continue
        is_candidate, trigger = screen(evidence)
        if not is_candidate:
            continue
        section = str(row.get("value_chain_section") or row.get("role") or "")
        v = adjudicate(
            brand, market, section, evidence, trigger, client=client, settings=settings
        )
        v.url = url
        verdicts.append(v)

    out = [
        v for v in verdicts
        if v.verdict == "out_of_scope" and v.confidence >= min_confidence
    ]
    return verdicts, out


def apply_audit(
    rows: list[dict[str, Any]], out_of_scope: list[Verdict]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split rows into (kept, dropped) using confident out-of-scope verdicts."""
    import re as _re

    def key(n: str) -> str:
        return _re.sub(r"[^a-z0-9]", "", str(n or "").lower())

    drop = {key(v.brand): v for v in out_of_scope}
    kept, dropped = [], []
    for row in rows:
        v = drop.get(key(row.get("company") or row.get("brand")))
        if v is None:
            kept.append(row)
        else:
            dropped.append({
                **row,
                "export_reject": f"out_of_scope:{v.reason}",
                "scope_evidence": v.evidence,
                "scope_evidence_url": v.url,
            })
    return kept, dropped
