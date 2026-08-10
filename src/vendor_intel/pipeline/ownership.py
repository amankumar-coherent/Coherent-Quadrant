"""Acquisition and merger detection — annotate a company with who now owns it.

A landscape that lists Oseco and Elfab as separate independent firms is stale:
they are one business, OsecoElfab, under Halma. Ownership churn is exactly the
kind of fact a company's own website is slowest to admit and a crawl therefore
never sees — but it is the first thing an AI Overview answer mentions.

So this reads the cached AI Overview evidence the extension already collects and
turns it into a display suffix:

    Oseco  ->  Oseco (acquired by Halma plc)

Two stages, same shape as the scope audit: a free regex screen that finds the
handful of companies whose evidence talks about ownership, then one LLM call per
candidate to extract *who* and *when* and to reject the false positives a regex
cannot see — "Fike acquired a competitor" is the acquirer, not the acquired, and
"plans to acquire" has not closed.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Any

# Sentences that talk about ownership changing hands. Broad on purpose — the
# adjudicator decides direction and status.
_OWNERSHIP = re.compile(
    r"\b(?:"
    r"acquired by|was acquired|has been acquired|were acquired"
    r"|purchased by|bought by|taken over by|absorbed by"
    r"|merged with|merged into|merger with"
    r"|is (?:now )?(?:a )?(?:wholly[- ]owned )?subsidiary of"
    r"|(?:now )?owned by|part of the .{0,40} group"
    r"|operates? (?:as part of|under) "
    r"|rebranded as|renamed to|now trades as|now known as"
    r"|divested to|spun off"
    r")\b",
    re.I,
)

# Ownership language that has NOT completed, or is about the company acquiring
# someone else. Screened out early so the LLM sees fewer candidates.
_NOT_YET = re.compile(
    r"\b(?:plans to acquire|intends to acquire|agreed to acquire|proposed|pending|"
    r"rumou?red|reportedly (?:in talks|exploring)|may acquire|could acquire)\b", re.I
)

_SYSTEM = """You extract CURRENT ownership for a company in a market landscape.

Given the company name and what Google's AI Overview says, decide whether THIS company
has been acquired by, merged into, or is now a subsidiary of another company.

Rules:
- Only report ownership of THIS company. If the text says this company ACQUIRED someone
  else, that is not a change of its own ownership — return owned=false.
- Only completed transactions. Announced, pending, rumoured or proposed deals are not
  ownership — return owned=false.
- The owner must be a named company, not a description.
- If the company is independent, or the text does not say, return owned=false.

Return JSON only:
{"owned": true|false, "owner": "<company name or empty>", "relation": "acquired_by"|"merged_into"|"subsidiary_of"|"", "year": "<YYYY or empty>", "confidence": 0.0-1.0}"""


@dataclass
class Ownership:
    brand: str
    owner: str
    relation: str
    year: str = ""
    confidence: float = 0.0
    evidence: str = ""
    url: str = ""

    @property
    def suffix(self) -> str:
        """The bracketed annotation appended to the company name."""
        verb = {
            "acquired_by": "acquired by",
            "merged_into": "merged into",
            "subsidiary_of": "subsidiary of",
        }.get(self.relation, "acquired by")
        year = f", {self.year}" if self.year else ""
        return f"({verb} {self.owner}{year})"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def screen(markdown: str) -> tuple[bool, str]:
    """Cheap pass: does this evidence discuss a completed ownership change?"""
    for sentence in re.split(r"(?<=[.!?])\s+", markdown or ""):
        if not _OWNERSHIP.search(sentence):
            continue
        if _NOT_YET.search(sentence):
            continue  # announced or rumoured, not closed
        return True, sentence.strip()[:400]
    return False, ""


def extract(
    brand: str,
    evidence: str,
    trigger: str,
    *,
    client: Any = None,
    settings: Any = None,
) -> Ownership | None:
    """One LLM call to pull owner + relation out of a screened candidate."""
    if client is None or not getattr(client, "available", False):
        return None  # never guess an owner from the regex alone
    try:
        raw = client.complete_json(
            _SYSTEM,
            json.dumps({"company": brand, "evidence": (evidence or "")[:2500]}, ensure_ascii=False),
            model=getattr(settings, "classifier_model", None),
            max_tokens=300,
        )
    except Exception:
        return None
    if not isinstance(raw, dict) or not raw.get("owned"):
        return None
    owner = str(raw.get("owner") or "").strip()
    if not owner or owner.lower() == brand.lower():
        return None
    try:
        confidence = max(0.0, min(1.0, float(raw.get("confidence") or 0)))
    except (TypeError, ValueError):
        confidence = 0.0
    return Ownership(
        brand=brand,
        owner=owner,
        relation=str(raw.get("relation") or "acquired_by").strip(),
        year=str(raw.get("year") or "").strip(),
        confidence=confidence,
        evidence=trigger,
    )


def ownership_question(brand: str) -> str:
    """The question that actually surfaces a deal.

    The KB questions ask what a company *does* — none of them mention ownership,
    so a first pass over that cache found one acquisition in 122 companies. Asking
    directly is what makes this work.
    """
    return f"Has {brand} been acquired by or merged with another company?"


def enqueue_questions(rows: list[dict[str, Any]], market: str, *, store: Any = None) -> int:
    """Queue an ownership question per company for the Chrome extension.

    Returns how many were newly queued (already-answered companies are skipped).
    """
    from vendor_intel.evidence.ai_overview import (
        AiOverviewStore,
        Question,
        default_cache_dir,
    )

    store = store or AiOverviewStore(default_cache_dir(market))
    queued = 0
    for row in rows:
        brand = str(row.get("company_raw") or row.get("company") or row.get("brand") or "").strip()
        if not brand:
            continue
        q = Question(text=ownership_question(brand), layer="ownership",
                     purpose="ownership", subject=brand, market=market)
        if store.get(q) is None:
            store.enqueue(q)
            queued += 1
    return queued


def _ownership_evidence(brand: str, market: str, store: Any) -> tuple[str, str]:
    """Prefer the dedicated ownership answer; fall back to the general KB text."""
    from vendor_intel.evidence.ai_overview import Question
    from vendor_intel.pipeline.scope_audit import evidence_for

    direct = store.get(Question(text=ownership_question(brand), market=market))
    if direct is not None and direct.ok:
        return direct.markdown, (direct.urls[0] if direct.urls else "")
    return evidence_for(brand, market, store)


def detect(
    rows: list[dict[str, Any]],
    market: str,
    *,
    settings: Any = None,
    store: Any = None,
    min_confidence: float = 0.7,
) -> list[Ownership]:
    """Find companies whose cached evidence shows a completed ownership change."""
    from vendor_intel.evidence.ai_overview import AiOverviewStore, default_cache_dir

    store = store or AiOverviewStore(default_cache_dir(market))
    client = None
    try:
        from vendor_intel.clients.claude import ClaudeClient

        client = ClaudeClient(settings) if settings is not None else None
    except Exception:
        client = None

    found: list[Ownership] = []
    for row in rows:
        brand = str(row.get("company") or row.get("brand") or "").strip()
        if not brand:
            continue
        evidence, url = _ownership_evidence(brand, market, store)
        if not evidence:
            continue
        is_candidate, trigger = screen(evidence)
        if not is_candidate:
            continue
        own = extract(brand, evidence, trigger, client=client, settings=settings)
        if own and own.confidence >= min_confidence:
            own.url = url
            found.append(own)
    return found


def annotate(rows: list[dict[str, Any]], owners: list[Ownership]) -> int:
    """Append "(acquired by X)" to display names. Returns how many were annotated.

    The raw name stays in ``company_raw`` so downstream joins and dedupe keys —
    which match on the plain name — keep working.
    """
    import re as _re

    def key(n: str) -> str:
        return _re.sub(r"[^a-z0-9]", "", str(n or "").lower())

    by_key = {key(o.brand): o for o in owners}
    n = 0
    for row in rows:
        name = str(row.get("company") or row.get("brand") or "")
        own = by_key.get(key(name))
        if not own or own.suffix in name:
            continue
        row.setdefault("company_raw", name)
        row["company"] = f"{name} {own.suffix}"
        row["parent_owner"] = own.owner
        row["ownership_relation"] = own.relation
        row["ownership_year"] = own.year
        row["ownership_evidence_url"] = own.url
        n += 1
    return n
