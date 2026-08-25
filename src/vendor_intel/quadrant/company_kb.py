"""Build per-company knowledge base from pipeline evidence_snapshot only (no web search)."""
from __future__ import annotations

import json
import re
from typing import Any

from vendor_intel.config import Settings
from vendor_intel.quadrant.criteria_catalog import load_scoring_weights

_REVENUE_RE = re.compile(
    r"(?:revenue|sales|turnover)[^\n\.]{0,40}?(\$?\s?\d+(?:\.\d+)?\s*(?:billion|million|bn|mn|b|m)\b)",
    re.I,
)
_YOY_RE = re.compile(
    r"(?:yoy|year[- ]over[- ]year|grew|growth)[^\n\.]{0,40}?([+\-]?\s?\d+(?:\.\d+)?\s*%)",
    re.I,
)

_CRITERION_KEYWORDS = (
    "organic",
    "non-gmo",
    "usda",
    "certif",
    "sustainab",
    "esg",
    "fair trade",
    "rspo",
    "retail",
    "distributor",
    "where to buy",
    "grocery",
    "walmart",
    "costco",
    "amazon",
    "partner",
    "acquisition",
    "subsidiary",
    "revenue",
    "million",
    "billion",
    "export",
    "region",
    "global",
    "north america",
    "europe",
    "asia",
    "sku",
    "extra virgin",
    "cold press",
    "product",
    "portfolio",
    "pricing",
    "wholesale",
    "foodservice",
)


def _clip(text: str, n: int) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())
    return t[:n]


def _is_fnb_market(market: str) -> bool:
    m = (market or "").lower()
    return any(
        k in m
        for k in (
            "food",
            "beverage",
            "dairy",
            "milk",
            "oil",
            "avocado",
            "protein",
            "plant",
            "snack",
            "grocery",
            "edible",
        )
    )


def _chunk_priority(text: str, origin: str) -> int:
    t = (text or "").lower()
    score = sum(1 for k in _CRITERION_KEYWORDS if k in t)
    # Prefer structured crawl INTEL over discovery fluff
    boost = {
        "crawl": 8,
        "facts": 10,
        "page_text": 4,
        "ai_overview": 3,
        "classify": 2,
        "discovery": 1,
    }.get(origin or "", 0)
    return score * 2 + boost


def _chunks_from_data(data: dict[str, Any], *, domain: str, chunk_chars: int) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    if not isinstance(data, dict):
        return out
    for key in ("company", "business", "financials", "relationships", "intel", "location", "media"):
        section = data.get(key)
        if section is None:
            continue
        try:
            text = json.dumps(section, ensure_ascii=False)
        except Exception:
            text = str(section)
        if len(text) < 20:
            continue
        out.append(
            {
                "source_url": domain or "crawl://company",
                "text": _clip(text, chunk_chars),
                "origin": "crawl",
            }
        )
    return out


def _chunks_from_snapshot(snapshot: dict[str, Any], *, chunk_chars: int) -> list[dict[str, str]]:
    """Expand evidence_snapshot into KB chunks (pipeline data only)."""
    out: list[dict[str, str]] = []
    if not isinstance(snapshot, dict):
        return out

    domain = str(snapshot.get("domain") or "")
    data = snapshot.get("data")
    if isinstance(data, dict):
        out.extend(_chunks_from_data(data, domain=domain, chunk_chars=chunk_chars))

    page_text = str(snapshot.get("page_text") or "").strip()
    if len(page_text) >= 40:
        # Keep more of the crawl than before (was ~8 chunks / ~6k chars)
        max_page_chars = max(chunk_chars * 24, 20000)
        step = max(chunk_chars - 100, chunk_chars // 2)
        for i in range(0, min(len(page_text), max_page_chars), step):
            piece = page_text[i : i + chunk_chars]
            if len(piece) < 40:
                break
            out.append(
                {
                    "source_url": domain or "ssc://page",
                    "text": _clip(piece, chunk_chars),
                    "origin": "page_text",
                }
            )

    for sn in snapshot.get("discovery_snippets") or []:
        if not isinstance(sn, dict):
            continue
        title = str(sn.get("title") or "")
        snippet = str(sn.get("snippet") or "")
        url = str(sn.get("url") or "")
        text = _clip(f"{title}. {snippet}".strip(". "), chunk_chars)
        if len(text) < 20:
            continue
        out.append({"source_url": url, "text": text, "origin": "discovery"})

    classify = snapshot.get("classify")
    if isinstance(classify, dict):
        for key in ("summary", "role_description", "key_products"):
            val = classify.get(key)
            if val and str(val).strip():
                out.append(
                    {
                        "source_url": domain,
                        "text": _clip(str(val), chunk_chars),
                        "origin": "classify",
                    }
                )
    return out


def _chunks_from_facts(row: dict[str, Any], *, chunk_chars: int) -> list[dict[str, str]]:
    """Inject Phase B2 ownership / founded / HQ facts into the scoring KB."""
    domain = str(row.get("website") or row.get("domain") or "")
    parts: list[str] = []
    mapping = (
        ("parent_owner", "Parent / owner"),
        ("ownership_relation", "Ownership relation"),
        ("company_legal_name", "Legal company name"),
        ("founded_year", "Founded year"),
        ("founded_location", "Founded / based in"),
        ("hq_location", "Headquarters"),
        ("hq_city", "HQ city"),
        ("hq_country", "HQ country"),
    )
    for key, label in mapping:
        val = row.get(key)
        if val is None:
            continue
        s = str(val).strip()
        if s:
            parts.append(f"{label}: {s}")
    sources = row.get("fact_sources")
    if isinstance(sources, list) and sources:
        parts.append("Fact sources: " + "; ".join(str(s) for s in sources[:8] if s))
    elif isinstance(sources, dict) and sources:
        parts.append("Fact sources: " + json.dumps(sources, ensure_ascii=False)[:500])
    if not parts:
        return []
    return [
        {
            "source_url": domain or "facts://enrich",
            "text": _clip(" | ".join(parts), chunk_chars),
            "origin": "facts",
        }
    ]


def _chunks_from_row(row: dict[str, Any], *, chunk_chars: int) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    domain = str(row.get("website") or row.get("domain") or "")
    for key in ("summary", "company_summary", "role_description", "key_products", "Functionality"):
        val = row.get(key)
        if val and str(val).strip():
            out.append(
                {
                    "source_url": domain,
                    "text": _clip(str(val), chunk_chars),
                    "origin": "classify",
                }
            )

    out.extend(_chunks_from_facts(row, chunk_chars=chunk_chars))

    snap = row.get("evidence_snapshot")
    if isinstance(snap, dict):
        out.extend(_chunks_from_snapshot(snap, chunk_chars=chunk_chars))
    else:
        # Legacy: raw enrich payload under _enriched
        enriched = row.get("_enriched")
        if isinstance(enriched, dict):
            data = enriched.get("data") if isinstance(enriched.get("data"), dict) else enriched
            if isinstance(data, dict):
                out.extend(_chunks_from_data(data, domain=domain, chunk_chars=chunk_chars))
    return out


def extract_financials_from_kb(kb: dict[str, Any]) -> dict[str, str]:
    """Pull free-text revenue / yoy from KB chunks when present."""
    blob = " ".join(str(c.get("text") or "") for c in (kb.get("chunks") or []))
    revenue = ""
    yoy = ""
    m = _REVENUE_RE.search(blob)
    if m:
        revenue = m.group(1).strip()
    m2 = _YOY_RE.search(blob)
    if m2:
        yoy = m2.group(1).replace(" ", "")
        if yoy and not yoy.startswith(("+", "-")):
            yoy = f"+{yoy}"
    return {"revenue": revenue, "yoy_growth": yoy}


def extract_founded_from_kb(kb: dict[str, Any]) -> str:
    """Pull founded year from KB chunks when present."""
    from vendor_intel.quadrant.brand_meta import extract_founded_from_kb as _extract

    return _extract(kb)


def kb_text_blob(kb: dict[str, Any], *, max_chars: int) -> str:
    parts: list[str] = []
    for c in kb.get("chunks") or []:
        url = c.get("source_url") or ""
        text = c.get("text") or ""
        parts.append(f"[{url}] {text}")
    return _clip("\n".join(parts), max_chars)


def _overview_questions(brand: str, market: str) -> list[tuple[str, str]]:
    scope = f" in the {market}" if market else ""
    qs: list[tuple[str, str]] = [
        ("company_overview", f"What does {brand} do{scope}?"),
        ("products", f"What products and services does {brand} offer{scope}?"),
        ("market_position", f"What is {brand}'s market position and reputation{scope}?"),
        ("financials", f"What is {brand}'s revenue and recent growth?"),
        ("innovation", f"What recent innovation, R&D or expansion has {brand} announced?"),
    ]
    if _is_fnb_market(market):
        qs.extend(
            [
                (
                    "sustainability",
                    f"What sustainability, organic, non-GMO or certifications does {brand} have{scope}?",
                ),
                (
                    "distribution",
                    f"Where is {brand} sold (retailers, distributors, foodservice, e-commerce){scope}?",
                ),
                (
                    "regions",
                    f"Which countries or regions does {brand} manufacture in or sell to{scope}?",
                ),
                (
                    "partners",
                    f"Who are {brand}'s key retail partners, distributors or parent company{scope}?",
                ),
                (
                    "pricing",
                    f"How is {brand} positioned on price (premium, mid, value){scope}?",
                ),
            ]
        )
    return qs


def _chunks_from_ai_overview(
    brand: str,
    market: str,
    *,
    chunk_chars: int,
    settings: Settings | None = None,
) -> list[dict[str, str]]:
    """Cached Google AI Overview answers about this brand, as KB chunks.

    Read-only: a cache miss enqueues the question for the Chrome extension and
    returns nothing, so scoring never blocks on a browser. The next run picks up
    whatever the extension answered in the meantime.
    """
    out: list[dict[str, str]] = []
    if not brand or not market or settings is None:
        return out
    if not bool(getattr(settings, "ai_overview_enabled", False)):
        return out
    try:
        from vendor_intel.evidence.ai_overview import (
            AiOverviewStore,
            Question,
            default_cache_dir,
        )
    except Exception:
        return out

    try:
        store = AiOverviewStore(default_cache_dir(market))
        for purpose, text in _overview_questions(brand, market):
            answer = store.ask(
                Question(text=text, layer="quadrant", purpose=purpose, subject=brand, market=market)
            )
            if answer is None or not answer.ok:
                continue
            out.append(
                {
                    "source_url": (answer.urls[0] if answer.urls else "google://ai-overview"),
                    "text": _clip(answer.markdown, chunk_chars),
                    "origin": "ai_overview",
                }
            )
    except Exception:
        return out
    return out


async def build_company_kb(
    row: dict[str, Any],
    *,
    market: str = "",
    settings: Settings | None = None,
    do_search: bool = False,
) -> dict[str, Any]:
    """
    Build KB from pipeline-stored evidence, plus cached AI Overview answers.

    `do_search` is ignored (kept for call-site compatibility) — the quadrant still
    performs no outbound search of its own. AI Overview chunks come from the local
    cache the Chrome extension fills; a miss just queues the question.
    """
    _ = do_search  # unused — no outbound search from this module
    cfg = load_scoring_weights()
    chunk_chars = int(cfg.get("kb_chunk_chars") or 800)
    max_chunks = int(cfg.get("kb_max_chunks") or 40)

    brand = str(row.get("company") or row.get("brand") or "").strip()
    domain = str(row.get("domain") or row.get("website") or "").strip()

    chunks = _chunks_from_row(row, chunk_chars=chunk_chars)
    # Appended after crawl chunks: pipeline evidence about the company itself
    # outranks a third-party summary when the KB gets truncated.
    chunks.extend(
        _chunks_from_ai_overview(brand, market, chunk_chars=chunk_chars, settings=settings)
    )

    # Deduplicate, then keep criterion-relevant chunks first so truncation
    # does not drop sustainability / distribution / financial evidence.
    seen: set[str] = set()
    unique: list[dict[str, str]] = []
    for c in chunks:
        key = (c.get("text") or "")[:120].lower()
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(c)

    unique.sort(
        key=lambda c: _chunk_priority(str(c.get("text") or ""), str(c.get("origin") or "")),
        reverse=True,
    )
    unique = unique[:max_chunks]

    origins = {c.get("origin") for c in unique}
    kb = {
        "brand": brand,
        "domain": domain,
        "chunks": unique,
        "source": (
            "pipeline_evidence_snapshot+ai_overview"
            if "ai_overview" in origins
            else "pipeline_evidence_snapshot"
        ),
    }
    fin = extract_financials_from_kb(kb)
    kb["revenue"] = fin.get("revenue") or ""
    kb["yoy_growth"] = fin.get("yoy_growth") or ""
    kb["founded_year"] = extract_founded_from_kb(kb)
    return kb
