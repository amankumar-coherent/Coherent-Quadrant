"""Dual fact enrichment: Google AI scraper + LLM for ownership / founded / location.

For each brand in a market cohort we collect:

* Who acquired / owns the brand
* Founded year
* Founded / HQ location

Sources (both used when enabled):

1. **Google AI scraper** (``GOOGLE_AI_SCRAPER_ENABLED``) — live ask on :15551
2. **LLM** — structured extract from scraper markdown + crawl evidence_snapshot
3. Cache / Chrome bridge queue (``AI_OVERVIEW_*``) — answers land in AiOverviewStore
"""
from __future__ import annotations

import json
import re
from typing import Any

from vendor_intel.quadrant.brand_meta import plain_brand_name

_SYSTEM = """You extract company facts for a market landscape / Coherent Quadrant.

Given a brand name and evidence text (Google AI Overview and/or website crawl), return JSON only:
{
  "brand": "<canonical brand name>",
  "owner": "<parent/acquirer company or empty if independent>",
  "relation": "acquired_by"|"subsidiary_of"|"merged_into"|"independent"|"",
  "ownership_year": "<YYYY or empty>",
  "founded_year": "<YYYY or empty>",
  "founded_location": "<city/region/country where founded, or empty>",
  "hq_location": "<current headquarters city/country, or empty>",
  "confidence": 0.0-1.0
}

Rules:
- Only report completed ownership of THIS brand (not brands it acquired).
- Prefer explicit evidence; if independent, relation=independent and owner empty.
- founded_location is where the company started; hq_location is current HQ (may differ).
- If unknown, use empty strings. Never invent owners or years.
"""


def ownership_question(brand: str) -> str:
    return f"Has {brand} been acquired by or merged with another company? Who owns {brand} now?"


def founded_question(brand: str) -> str:
    return f"{brand} company founded year founding location and headquarters address"


def market_brands_question(market: str, country: str = "global") -> str:
    geo = (country or "global").strip() or "global"
    m = (market or "").strip() or "market"
    m_short = re.sub(r"\s+market\s*$", "", m, flags=re.I).strip() or m
    if geo.lower() == "global":
        return f"Top brands with company names in the {m_short} market"
    return f"Top brands with company names in the {m_short} market in {geo}"


def _citations_to_dicts(raw: list[Any]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for c in raw or []:
        if isinstance(c, dict):
            out.append({"title": str(c.get("title") or ""), "url": str(c.get("url") or "")})
        elif isinstance(c, str) and c.strip():
            out.append({"title": "", "url": c.strip()})
    return out


def _store_answer(
    store: Any,
    question: str,
    market: str,
    *,
    markdown: str,
    citations: list[dict[str, str]] | None = None,
    error: str = "",
    purpose: str = "",
    subject: str = "",
) -> None:
    from vendor_intel.evidence.ai_overview import Question

    q = Question(
        text=question,
        market=market,
        layer="fact_enrich",
        purpose=purpose or "facts",
        subject=subject,
    )
    store.put(
        q,
        markdown or "",
        citations=_citations_to_dicts(citations or []),
        overview_missing=not bool((markdown or "").strip()),
        error=error or "",
        source="google_ai_scraper",
    )


def _ask_scraper(question: str) -> dict[str, Any]:
    from vendor_intel.evidence.google_ai_scraper import ask, scraper_enabled

    if not scraper_enabled():
        return {"markdown": "", "citations": [], "error": "scraper_disabled", "query": question}
    return ask(question, close_thread=True)


def _evidence_blob(row: dict[str, Any], scraper_md: str) -> str:
    parts: list[str] = []
    if scraper_md.strip():
        parts.append("GOOGLE AI OVERVIEW:\n" + scraper_md.strip()[:4000])
    snap = row.get("evidence_snapshot")
    if isinstance(snap, dict):
        page = str(snap.get("page_text") or "")[:2500]
        if page.strip():
            parts.append("WEBSITE CRAWL:\n" + page.strip())
        data = snap.get("data") if isinstance(snap.get("data"), dict) else {}
        company = data.get("company") if isinstance(data.get("company"), dict) else {}
        if company:
            parts.append("CRAWL COMPANY INTEL:\n" + json.dumps(company, ensure_ascii=False)[:1200])
        classify = snap.get("classify") if isinstance(snap.get("classify"), dict) else {}
        if classify.get("summary"):
            parts.append("CLASSIFY SUMMARY:\n" + str(classify.get("summary"))[:800])
    for key in ("summary", "company_summary", "parent", "parent_or_independent"):
        val = row.get(key)
        if val:
            parts.append(f"{key.upper()}: {val}")
    return "\n\n".join(parts)[:8000]


def _llm_extract(
    brand: str,
    evidence: str,
    *,
    settings: Any = None,
    client: Any = None,
) -> dict[str, Any]:
    if not evidence.strip():
        return {}
    if client is None:
        try:
            from vendor_intel.clients.claude import ClaudeClient

            client = ClaudeClient(settings) if settings is not None else None
        except Exception:
            client = None
    if client is None or not getattr(client, "available", False):
        return {}
    try:
        raw = client.complete_json(
            _SYSTEM,
            json.dumps({"brand": brand, "evidence": evidence}, ensure_ascii=False),
            model=getattr(settings, "classifier_model", None),
            max_tokens=400,
        )
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")


def _regex_founded(text: str) -> tuple[str, str]:
    """Cheap fallback: founded year + short location hint from overview text."""
    year = ""
    loc = ""
    m = re.search(
        r"(?:founded|established|incorporated)\s+(?:in\s+)?(?:(\w[\w\s,]+?)\s+in\s+)?(\d{4})\b",
        text or "",
        re.I,
    )
    if m:
        loc = (m.group(1) or "").strip(" ,")
        year = m.group(2) or ""
    if not year:
        m2 = re.search(
            r"(?:founded|established|incorporated)\s+(?:in\s+)?(\d{4})",
            text or "",
            re.I,
        )
        if m2:
            year = m2.group(1)
    return year, loc


def _apply_facts(row: dict[str, Any], facts: dict[str, Any], *, source: str) -> None:
    owner = str(facts.get("owner") or "").strip()
    relation = str(facts.get("relation") or "").strip()
    own_year = str(facts.get("ownership_year") or "").strip()
    founded = str(facts.get("founded_year") or "").strip()
    founded_loc = str(facts.get("founded_location") or "").strip()
    hq = str(facts.get("hq_location") or "").strip()

    if owner and relation not in ("independent", ""):
        row["parent_owner"] = owner
        row["ownership_relation"] = relation if relation.startswith(("acquired", "subsid", "merged")) else "acquired_by"
        if own_year:
            row["ownership_year"] = own_year
        row["parent"] = f"Acquired by {owner}" if "acquir" in row["ownership_relation"] else f"Subsidiary of {owner}"
        row.setdefault("company_raw", plain_brand_name(row))
        # Keep brand identity plain — "acquired by" goes in Company column only
        row["company"] = row.get("company_raw") or plain_brand_name(row)
        row["acquired_by_display"] = f"acquired by {owner}"

    if founded and not row.get("founded_year"):
        row["founded_year"] = founded
    if founded_loc:
        row["founded_location"] = founded_loc
    if hq:
        row["hq_location"] = hq
        if not row.get("founded_location"):
            row["founded_location"] = hq

    sources = list(row.get("fact_sources") or [])
    if source not in sources:
        sources.append(source)
    row["fact_sources"] = sources


def enrich_brand_facts(
    rows: list[dict[str, Any]],
    market: str,
    *,
    settings: Any = None,
    use_scraper: bool | None = None,
    use_llm: bool | None = None,
    store: Any = None,
) -> dict[str, int]:
    """
    Enrich each brand with ownership / founded / location via scraper + LLM.

    Returns counters: ``{scraper_ok, llm_ok, queued, failed}``.
    """
    import os

    from vendor_intel.evidence.ai_overview import AiOverviewStore, default_cache_dir
    from vendor_intel.evidence.google_ai_scraper import health, scraper_enabled

    if use_scraper is None:
        use_scraper = scraper_enabled()
    if use_llm is None:
        use_llm = (os.getenv("FACT_ENRICH_LLM") or "true").strip().lower() not in (
            "0",
            "false",
            "no",
            "off",
        )

    store = store or AiOverviewStore(default_cache_dir(market))
    stats = {"scraper_ok": 0, "llm_ok": 0, "queued": 0, "failed": 0, "brands": 0}

    scraper_up = False
    if use_scraper:
        h = health()
        scraper_up = bool(h.get("ok"))
        if not scraper_up:
            print(
                f"  [facts] Google AI scraper not reachable ({h.get('error') or h}) "
                f"— will queue for Chrome bridge + use LLM/crawl",
                flush=True,
            )
        else:
            print(
                f"  [facts] Google AI scraper OK "
                f"(extension_connected={h.get('extension_connected')})",
                flush=True,
            )

    client = None
    if use_llm:
        try:
            from vendor_intel.clients.claude import ClaudeClient

            client = ClaudeClient(settings) if settings is not None else None
        except Exception:
            client = None

    for row in rows:
        brand = plain_brand_name(row)
        if not brand:
            continue
        stats["brands"] += 1
        md_parts: list[str] = []

        missing: list[str] = []
        if not str(row.get("parent_owner") or "").strip() and not str(
            row.get("acquired_by_display") or ""
        ).strip():
            missing.append("Company")
        loc0 = str(row.get("founded_location") or row.get("founded_in") or "").strip()
        if not loc0 or re.fullmatch(r"(19|20)\d{2}", loc0):
            missing.append("Founded in")

        planned_qs: list[tuple[str, str]] = []
        if missing and use_scraper and scraper_up:
            try:
                from vendor_intel.pipeline.ai_brand_discovery import plan_brand_column_queries

                for p in plan_brand_column_queries(
                    brand, market, missing=missing, settings=settings
                ):
                    qtxt = str(p.get("q") or "").strip()
                    fills = list(p.get("fills") or missing)
                    purpose = "ownership" if "Company" in fills else "founded"
                    if qtxt:
                        planned_qs.append((purpose, qtxt))
                        print(
                            f"  [facts] LLM query [{', '.join(fills)}] ← {qtxt[:72]!r}",
                            flush=True,
                        )
            except Exception as exc:
                print(f"  [facts] column query plan skipped: {exc}", flush=True)

        if not planned_qs:
            planned_qs = [
                ("ownership", ownership_question(brand)),
                ("founded", founded_question(brand)),
            ]

        for purpose, question in planned_qs:
            md = ""
            cites: list[dict[str, str]] = []
            err = ""

            if use_scraper and scraper_up:
                print(f"  [facts] scraper ← {purpose}: {brand[:40]}", flush=True)
                res = _ask_scraper(question)
                md = str(res.get("markdown") or "")
                cites = _citations_to_dicts(list(res.get("citations") or []))
                err = str(res.get("error") or "")
                if md.strip() and not err:
                    stats["scraper_ok"] += 1
                    _store_answer(
                        store,
                        question,
                        market,
                        markdown=md,
                        citations=cites,
                        purpose=purpose,
                        subject=brand,
                    )
                elif err:
                    stats["failed"] += 1

            if not md.strip():
                # Queue for Coherent extension bridge (:15552) / reuse cache
                from vendor_intel.evidence.ai_overview import Question

                q = Question(
                    text=question,
                    market=market,
                    layer="fact_enrich",
                    purpose=purpose,
                    subject=brand,
                )
                cached = store.get(q)
                if cached is not None and getattr(cached, "ok", False):
                    md = str(cached.markdown or "")
                else:
                    store.enqueue(q)
                    stats["queued"] += 1

            if md.strip():
                md_parts.append(md)

        blob = _evidence_blob(row, "\n\n".join(md_parts))
        facts: dict[str, Any] = {}
        if use_llm and blob.strip():
            facts = _llm_extract(brand, blob, settings=settings, client=client)
            if facts:
                stats["llm_ok"] += 1
                _apply_facts(row, facts, source="llm+scraper" if md_parts else "llm")

        # Regex fallback from scraper text if LLM missed founded
        if md_parts and (not row.get("founded_year") or not row.get("founded_location")):
            year, loc = _regex_founded("\n".join(md_parts))
            if year and not row.get("founded_year"):
                row["founded_year"] = year
                row["founded_in"] = year
            if loc and not row.get("founded_location"):
                row["founded_location"] = loc
            if year or loc:
                sources = list(row.get("fact_sources") or [])
                if "scraper_regex" not in sources:
                    sources.append("scraper_regex")
                row["fact_sources"] = sources

    print(
        f"  [facts] done brands={stats['brands']} scraper_ok={stats['scraper_ok']} "
        f"llm_ok={stats['llm_ok']} queued={stats['queued']} failed={stats['failed']}",
        flush=True,
    )
    return stats


def discover_brands_via_scraper(
    market: str,
    country: str = "global",
    *,
    settings: Any = None,
    store: Any = None,
) -> list[str]:
    """Ask Google AI for leading brands; LLM extracts a name list. Returns brand names."""
    from vendor_intel.evidence.ai_overview import AiOverviewStore, default_cache_dir
    from vendor_intel.evidence.google_ai_scraper import health, scraper_enabled

    if not scraper_enabled():
        return []
    h = health()
    if not h.get("ok"):
        return []

    q = market_brands_question(market, country)
    print(f"  [facts] scraper market brands: {q[:80]}", flush=True)
    res = _ask_scraper(q)
    md = str(res.get("markdown") or "")
    if not md.strip():
        return []

    store = store or AiOverviewStore(default_cache_dir(market))
    _store_answer(
        store,
        q,
        market,
        markdown=md,
        citations=_citations_to_dicts(list(res.get("citations") or [])),
        purpose="discovery",
        subject=market,
    )

    try:
        from vendor_intel.clients.claude import ClaudeClient

        client = ClaudeClient(settings) if settings is not None else None
        if client is None or not getattr(client, "available", False):
            return []
        raw = client.complete_json(
            "Extract company/brand names from the text. Return JSON: "
            '{"brands": ["Name1", "Name2", ...]}. Max 25 names. JSON only.',
            json.dumps({"market": market, "text": md[:6000]}, ensure_ascii=False),
            max_tokens=500,
        )
        if isinstance(raw, dict):
            brands = [str(x).strip() for x in (raw.get("brands") or []) if str(x).strip()]
            print(f"  [facts] scraper discovery extracted {len(brands)} brands", flush=True)
            return brands
    except Exception as exc:
        print(f"  [facts] brand list LLM extract skipped: {exc}", flush=True)
    return []
