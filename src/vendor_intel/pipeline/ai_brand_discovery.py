"""Google AI Overview–first brand discovery for Coherent Quadrant markets.

Flow:
  1) LLM understands market type (Food & Beverages, ICT, …)
  2) LLM writes Google search queries aimed at required table columns
     (Brand, Company, Founded in, …)
  3) Google AI scraper runs those queries
  4) Country-wise landscape pass (e.g. "avocado oil India", "avocado oil New Zealand")
     fills the wide Company Details table
  5) LLM extracts Brand + Company (+ founded location when present)
  6) Caller resolves domains → crawl → score X/Y (Quadrant / Overall)
"""
from __future__ import annotations

import json
import re
from typing import Any

from vendor_intel.quadrant.brand_meta import company_display_mode, plain_brand_name
from vendor_intel.quadrant.industry_select import select_industry

# Company Details columns that Google AI Overview can help fill.
# Quadrant / X / Y / Overall are scored later from crawl + criteria — not asked here.
REQUIRED_TABLE_COLUMNS = (
    "Brand",
    "Company",
    "Founded in",  # location, not year
)

_QUERY_PLAN_SYSTEM = """You write Google Search queries for an AI Overview scraper.

Goal: fill these Coherent Quadrant Company Details columns for a market:
- Brand — consumer / product brand name
- Company — legal company, manufacturer, OR parent (and "acquired by X" when owned)
- Founded in — founding / HQ LOCATION (city/country), NOT the year

Return JSON only:
{
  "queries": [
    {"q": "<google search bar query>", "fills": ["Brand", "Company"]},
    {"q": "<query>", "fills": ["Brand", "Company", "Founded in"]}
  ]
}

Rules:
- Write 4-6 short queries a human would type into Google Search.
- Always include at least one query that asks for brand WITH company/parent name.
- Include one query about where leading brands were founded / HQ location.
- Tailor wording to the industry (food vs technology). Tech: brand + solution provider (e.g. Gemini / Google). Food: brand + company / acquired-by.
- Do NOT invent company names in the queries — only search phrasing.
- Geography: respect the given country (use "worldwide" when global).
"""

_EXTRACT_SYSTEM = """You extract market brands AND their companies from a Google AI Overview.

Return JSON only:
{
  "brands": [
    {
      "brand": "<consumer/product brand or product line name>",
      "company": "<legal company / manufacturer / parent company name>",
      "founded_location": "<city/region/country where founded or HQ, else empty>",
      "note": "<short role e.g. retail leader — or empty>"
    }
  ]
}

Rules:
- Always fill BOTH brand and company when the text supports it.
- If brand and company are the same entity (e.g. Chosen Foods), set both to that name.
- If brand is owned/made by another firm (Gemini → Google, Horizon Organic → Danone),
  brand=product/brand, company=parent/manufacturer.
- founded_location is a PLACE (not a year). Leave empty if unknown.
- Prefer real commercial brands/companies in THIS market only.
- Max 20 entries. Deduplicate. Never invent names not supported by the text.
- Skip market-research firms, consultancies, news sites, directories.
"""

_BRAND_COLUMN_QUERY_SYSTEM = """You write Google Search queries to fill missing Company Details fields for ONE brand.

Required columns to fill (only those listed as missing):
- Company — parent / manufacturer / acquired-by owner
- Founded in — founding or HQ LOCATION (place, not year)

Return JSON only:
{"queries":[{"q":"<google query>","fills":["Company"]},{"q":"<google query>","fills":["Founded in"]}]}

Rules:
- 1-3 short queries. Include the brand name in every query.
- Tailor to market type (food vs tech).
- Do not invent answers — only search queries.
"""


# Major producing / consuming markets for wide Company Details discovery.
# Used when country=global: Google AI Overview runs one query per country.
DEFAULT_LANDSCAPE_COUNTRIES: tuple[str, ...] = (
    "India",
    "New Zealand",
    "United States",
    "Mexico",
    "Chile",
    "Peru",
    "South Africa",
    "Spain",
    "Italy",
    "Kenya",
    "Australia",
    "Canada",
    "United Kingdom",
    "Brazil",
    "China",
    "Japan",
    "France",
    "Germany",
    "Netherlands",
    "Colombia",
)

_GEO_COUNTRY_SYSTEM = """You pick countries for a market landscape Google Search pass.

Return JSON only:
{"countries":["India","New Zealand","United States",...]}

Rules:
- 8-16 country names (English, title case).
- Prefer producing / consuming / HQ-heavy markets for THIS product category.
- For edible oils / avocado oil include New Zealand, Mexico, Chile, Peru, India, USA, South Africa, Spain, Kenya when relevant.
- Do not invent regions as countries (no "Europe" / "APAC").
- No duplicates.
"""


def market_short_name(market: str) -> str:
    m = (market or "").strip() or "market"
    return re.sub(r"\s+market\s*$", "", m, flags=re.I).strip() or m


def google_overview_queries(market: str, country: str = "global") -> list[str]:
    """Fallback queries when LLM query planning is unavailable."""
    m_short = market_short_name(market)
    geo = (country or "global").strip() or "global"
    geo_bit = "" if geo.lower() in ("", "global", "worldwide") else f" in {geo}"
    qs = [
        f"Top brands with company names in the {m_short} market{geo_bit}",
        f"Leading {m_short} brands and their parent companies{geo_bit}",
        f"Top {m_short} brand list with manufacturer or company name{geo_bit}",
        f"Where were leading {m_short} brands founded headquarters location{geo_bit}",
    ]
    out: list[str] = []
    seen: set[str] = set()
    for q in qs:
        key = q.lower()
        if key not in seen:
            seen.add(key)
            out.append(q)
    return out


def parse_geo_countries(raw: str | list[str] | None) -> list[str]:
    """Parse comma/newline-separated country override list."""
    if isinstance(raw, list):
        items = [str(x).strip() for x in raw if str(x).strip()]
    else:
        text = str(raw or "").strip()
        if not text:
            return []
        items = [p.strip() for p in re.split(r"[,;\n]+", text) if p.strip()]
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        key = item.lower()
        if key in seen or key in ("global", "worldwide", "world", "international"):
            continue
        seen.add(key)
        out.append(item)
    return out


def plan_landscape_countries(
    market: str,
    *,
    country: str = "global",
    settings: Any = None,
    override: str | list[str] | None = None,
    max_countries: int = 16,
) -> list[str]:
    """
    Countries for table landscape Google AI queries.

    - Explicit override wins
    - If run country is a single nation, use that only
    - Else LLM (optional) + DEFAULT_LANDSCAPE_COUNTRIES fallback
    """
    max_countries = max(1, min(int(max_countries), 24))
    forced = parse_geo_countries(override)
    if forced:
        return forced[:max_countries]

    geo = (country or "global").strip() or "global"
    if geo.lower() not in ("", "global", "worldwide", "world", "international"):
        return [geo][:max_countries]

    from vendor_intel.clients.claude import ClaudeClient

    client = ClaudeClient(settings) if settings is not None else None
    if client is not None and getattr(client, "available", False):
        try:
            raw = client.complete_json(
                _GEO_COUNTRY_SYSTEM,
                json.dumps({"market": market, "hint_default": list(DEFAULT_LANDSCAPE_COUNTRIES[:12])}),
                max_tokens=600,
            )
            planned = parse_geo_countries(
                list(raw.get("countries") or []) if isinstance(raw, dict) else []
            )
            if planned:
                print(
                    f"  [ai-discover] LLM geo countries ({len(planned)}): "
                    f"{', '.join(planned[:12])}{'…' if len(planned) > 12 else ''}",
                    flush=True,
                )
                return planned[:max_countries]
        except Exception as exc:
            print(f"  [ai-discover] geo country LLM failed: {exc} — using defaults", flush=True)

    return list(DEFAULT_LANDSCAPE_COUNTRIES[:max_countries])


def country_landscape_queries(
    market: str,
    countries: list[str],
    *,
    queries_per_country: int = 2,
) -> list[dict[str, Any]]:
    """
    Build Google AI scraper queries like:
      avocado oil India
      top avocado oil brands companies India
    """
    m_short = market_short_name(market)
    n = max(1, min(int(queries_per_country), 3))
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for country in countries:
        c = str(country or "").strip()
        if not c:
            continue
        templates = [
            f"{m_short} {c}",
            f"top {m_short} brands companies {c}",
            f"{m_short} manufacturers producers {c}",
        ]
        for q in templates[:n]:
            key = q.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(
                {
                    "q": q,
                    "fills": list(REQUIRED_TABLE_COLUMNS),
                    "country": c,
                }
            )
    return out


def is_market_geo_artifact(brand: str, market: str) -> bool:
    """True for fake brands like 'Avocado Oil India' / 'Avocado Oil New Zealand'."""
    b = plain_brand_name(brand)
    if not b:
        return True
    m = market_short_name(market).lower().strip()
    bl = b.lower().strip()
    if not m:
        return False
    if bl == m:
        return True
    # "{market} {country}" or "{market} in {country}"
    for sep in (" ", " - ", " – ", " | ", ": "):
        prefix = m + sep
        if bl.startswith(prefix):
            rest = bl[len(prefix) :].strip()
            if rest and len(rest) < 40 and not any(ch.isdigit() for ch in rest):
                # Country/region-only suffix → query artifact, not a brand
                if rest.count(" ") <= 3:
                    return True
    # "Top avocado oil brands India" style leftovers
    if bl.startswith("top ") and m in bl:
        return True
    return False


def plan_column_fill_queries(
    market: str,
    *,
    country: str = "global",
    settings: Any = None,
    industry: dict[str, Any] | None = None,
    max_queries: int = 6,
) -> list[dict[str, Any]]:
    """
    LLM creates Google search-bar queries aimed at required table columns.

    Returns [{"q": str, "fills": ["Brand", "Company", ...]}, ...]
    """
    from vendor_intel.clients.claude import ClaudeClient

    industry = industry or {}
    client = ClaudeClient(settings) if settings is not None else None
    fallback = [
        {"q": q, "fills": list(REQUIRED_TABLE_COLUMNS)}
        for q in google_overview_queries(market, country)[:max_queries]
    ]
    if client is None or not getattr(client, "available", False):
        return fallback

    user = json.dumps(
        {
            "market": market,
            "country": country or "global",
            "industry_group": industry.get("industry_group"),
            "industry_category": industry.get("industry_category"),
            "company_display_mode": industry.get("company_display_mode"),
            "required_columns": list(REQUIRED_TABLE_COLUMNS),
            "note": "Quadrant, X, Y, Overall are scored later — do not write queries for scores.",
        },
        ensure_ascii=False,
    )
    try:
        raw = client.complete_json(_QUERY_PLAN_SYSTEM, user, max_tokens=1200)
    except Exception as exc:
        print(f"  [ai-discover] query plan LLM failed: {exc} — using defaults", flush=True)
        return fallback

    planned: list[dict[str, Any]] = []
    if isinstance(raw, dict):
        for item in raw.get("queries") or []:
            if isinstance(item, str) and item.strip():
                planned.append({"q": item.strip(), "fills": list(REQUIRED_TABLE_COLUMNS)})
                continue
            if not isinstance(item, dict):
                continue
            q = str(item.get("q") or item.get("query") or "").strip()
            if not q:
                continue
            fills = [
                str(f).strip()
                for f in (item.get("fills") or REQUIRED_TABLE_COLUMNS)
                if str(f).strip()
            ]
            planned.append({"q": q, "fills": fills or list(REQUIRED_TABLE_COLUMNS)})

    if not planned:
        return fallback

    print(
        f"  [ai-discover] LLM wrote {len(planned)} Google queries for columns "
        f"{', '.join(REQUIRED_TABLE_COLUMNS)}",
        flush=True,
    )
    for p in planned[:8]:
        print(f"    · fills={p.get('fills')} ← {p.get('q')!r}", flush=True)
    return planned[: max(1, max_queries)]


def plan_brand_column_queries(
    brand: str,
    market: str,
    *,
    missing: list[str],
    settings: Any = None,
    industry_category: str = "",
) -> list[dict[str, Any]]:
    """LLM queries to fill missing Company / Founded-in for one brand."""
    from vendor_intel.clients.claude import ClaudeClient

    miss = [m for m in missing if m in ("Company", "Founded in")]
    if not miss:
        return []

    fallback: list[dict[str, Any]] = []
    if "Company" in miss:
        fallback.append(
            {
                "q": f"Has {brand} been acquired by or merged with another company? Who owns {brand} now?",
                "fills": ["Company"],
            }
        )
    if "Founded in" in miss:
        fallback.append(
            {
                "q": f"{brand} company founded location headquarters city country",
                "fills": ["Founded in"],
            }
        )

    client = ClaudeClient(settings) if settings is not None else None
    if client is None or not getattr(client, "available", False):
        return fallback

    user = json.dumps(
        {
            "brand": brand,
            "market": market,
            "industry_category": industry_category,
            "missing_columns": miss,
        },
        ensure_ascii=False,
    )
    try:
        raw = client.complete_json(_BRAND_COLUMN_QUERY_SYSTEM, user, max_tokens=600)
    except Exception:
        return fallback

    planned: list[dict[str, Any]] = []
    if isinstance(raw, dict):
        for item in raw.get("queries") or []:
            if isinstance(item, str) and item.strip():
                planned.append({"q": item.strip(), "fills": miss})
                continue
            if not isinstance(item, dict):
                continue
            q = str(item.get("q") or item.get("query") or "").strip()
            if not q:
                continue
            fills = [str(f).strip() for f in (item.get("fills") or miss) if str(f).strip()]
            planned.append({"q": q, "fills": fills or miss})
    return planned[:3] or fallback


def understand_market(
    market: str,
    *,
    country: str = "global",
    settings: Any = None,
) -> dict[str, Any]:
    """LLM / keyword industry leaf + company-column display mode."""
    industry = select_industry(market, geography=country, settings=settings)
    mode = company_display_mode(
        market,
        industry_group=str(industry.get("industry_group") or ""),
        industry_category=str(industry.get("industry_category") or ""),
    )
    industry["company_display_mode"] = mode
    industry["required_columns"] = list(REQUIRED_TABLE_COLUMNS)
    print(
        f"  [ai-discover] market understanding: "
        f"{industry.get('industry_group')}/{industry.get('industry_category')} "
        f"(mode={mode}, via {industry.get('selection_method')})",
        flush=True,
    )
    print(
        f"  [ai-discover] columns to fill via Google AI: "
        f"{', '.join(REQUIRED_TABLE_COLUMNS)} "
        f"(Quadrant/X/Y/Overall from scoring later)",
        flush=True,
    )
    return industry


def _ask_scraper(question: str) -> dict[str, Any]:
    from vendor_intel.evidence.google_ai_scraper import ask, scraper_enabled

    if not scraper_enabled():
        return {"markdown": "", "citations": [], "error": "scraper_disabled", "query": question}
    return ask(question, close_thread=True)


def _cache_overview(
    market: str,
    question: str,
    res: dict[str, Any],
    *,
    purpose: str,
) -> None:
    try:
        from vendor_intel.evidence.ai_overview import AiOverviewStore, Question, default_cache_dir

        store = AiOverviewStore(default_cache_dir(market))
        cites = []
        for c in list(res.get("citations") or []):
            if isinstance(c, dict):
                cites.append(
                    {
                        "title": str(c.get("title") or ""),
                        "url": str(c.get("url") or c.get("link") or ""),
                    }
                )
        store.put(
            Question(text=question, market=market, layer="discovery", purpose=purpose),
            str(res.get("markdown") or ""),
            citations=cites,
            overview_missing=not bool(str(res.get("markdown") or "").strip()),
            error=str(res.get("error") or ""),
            source="google_ai_scraper",
        )
    except Exception:
        pass


def _extract_with_llm(
    market: str,
    markdown: str,
    *,
    settings: Any,
    industry: dict[str, Any],
) -> list[dict[str, str]]:
    from vendor_intel.clients.claude import ClaudeClient

    client = ClaudeClient(settings) if settings is not None else None
    if client is None or not getattr(client, "available", False):
        return []
    user = json.dumps(
        {
            "market": market,
            "industry_category": industry.get("industry_category"),
            "company_display_mode": industry.get("company_display_mode"),
            "required_columns": list(REQUIRED_TABLE_COLUMNS),
            "ai_overview": (markdown or "")[:7000],
        },
        ensure_ascii=False,
    )
    raw = client.complete_json(_EXTRACT_SYSTEM, user, max_tokens=2500)
    rows: list[dict[str, str]] = []
    if not isinstance(raw, dict):
        return rows
    for item in raw.get("brands") or []:
        if isinstance(item, str):
            name = item.strip()
            if name:
                rows.append({"brand": name, "company": "", "founded_location": "", "note": ""})
            continue
        if not isinstance(item, dict):
            continue
        brand = str(item.get("brand") or item.get("name") or "").strip()
        company = str(item.get("company") or item.get("parent") or "").strip()
        founded_loc = str(
            item.get("founded_location") or item.get("hq_location") or item.get("location") or ""
        ).strip()
        if founded_loc and re.fullmatch(r"(19|20)\d{2}", founded_loc):
            founded_loc = ""
        note = str(item.get("note") or "").strip()
        if brand:
            rows.append(
                {
                    "brand": brand,
                    "company": company,
                    "founded_location": founded_loc,
                    "note": note,
                }
            )
    return rows


def _extract_fallback(markdown: str) -> list[dict[str, str]]:
    from vendor_intel.discovery.entity_extract import is_plausible_company_name
    from vendor_intel.evidence.ai_overview import extract_entries

    rows: list[dict[str, str]] = []
    for entry in extract_entries(markdown, max_words=8, limit=40):
        name = plain_brand_name(entry.name)
        if not name or not is_plausible_company_name(name):
            continue
        rows.append(
            {
                "brand": name,
                "company": "",
                "founded_location": "",
                "note": (entry.description or "")[:160],
            }
        )
    return rows


def _merge_brand_rows(batches: list[list[dict[str, str]]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for batch in batches:
        for row in batch:
            brand = plain_brand_name(row.get("brand") or "")
            if not brand:
                continue
            key = re.sub(r"[^a-z0-9]", "", brand.lower())
            if len(key) < 3 or key in seen:
                if key in seen:
                    for existing in out:
                        if re.sub(r"[^a-z0-9]", "", existing["brand"].lower()) == key:
                            if not existing.get("company") and row.get("company"):
                                existing["company"] = str(row.get("company") or "").strip()
                            if not existing.get("founded_location") and row.get("founded_location"):
                                existing["founded_location"] = str(
                                    row.get("founded_location") or ""
                                ).strip()
                            break
                continue
            seen.add(key)
            out.append(
                {
                    "brand": brand,
                    "company": str(row.get("company") or "").strip(),
                    "founded_location": str(row.get("founded_location") or "").strip(),
                    "note": str(row.get("note") or "").strip(),
                }
            )
    return out


_EXTRACT_LANDSCAPE_SYSTEM = """You extract market brands AND their companies from a Google AI Overview for ONE country.

Return JSON only:
{
  "brands": [
    {
      "brand": "<consumer/product brand or product line name>",
      "company": "<legal company / manufacturer / parent company name>",
      "founded_location": "<city/region/country where founded or HQ, else empty>",
      "note": "<short role e.g. retail leader — or empty>"
    }
  ]
}

Rules:
- Always fill BOTH brand and company when the text supports it.
- Prefer brands/companies active in the given country for THIS market.
- founded_location is a PLACE (not a year). Leave empty if unknown.
- Max 30 entries. Deduplicate. Never invent names not supported by the text.
- Skip market-research firms, consultancies, news sites, directories.
"""


def _rows_to_companies(
    cleaned: list[dict[str, str]],
    *,
    discovery_source: str,
    geo_country: str = "",
) -> list[dict[str, Any]]:
    companies: list[dict[str, Any]] = []
    for row in cleaned:
        brand = row["brand"]
        parent = row.get("company") or ""
        item: dict[str, Any] = {
            "company": brand,
            "company_raw": brand,
            "brand": brand,
            "domain": "",
            "website": "",
            "discovery_source": discovery_source,
            "is_seed": discovery_source == "google_ai_overview",
            "company_function": "brand owner",
            "ai_overview_note": row.get("note") or "",
        }
        if geo_country:
            item["discovery_country"] = geo_country
            item["geo_hint"] = geo_country
        if row.get("founded_location"):
            item["founded_location"] = row["founded_location"]
            item["founded_in"] = row["founded_location"]
        if parent and parent.lower() != brand.lower():
            item["parent_owner"] = parent
            item["parent"] = f"Acquired by {parent}"
            item["ownership_relation"] = "acquired_by"
        elif parent:
            item["legal_name"] = parent
        companies.append(item)
    return companies


def discover_brands_from_google_ai(
    market: str,
    *,
    country: str = "global",
    settings: Any = None,
    max_brands: int = 18,
    max_queries: int = 4,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Understand market → LLM column queries → Google AI Overview → extract brands.

    Returns at most ``max_brands`` rows (hard-capped at 20).
    """
    max_brands = max(1, min(int(max_brands), 20))
    max_queries = max(1, min(int(max_queries), 5))
    from vendor_intel.discovery.entity_extract import is_plausible_company_name
    from vendor_intel.evidence.google_ai_scraper import health, scraper_enabled

    industry = understand_market(market, country=country, settings=settings)

    if not scraper_enabled():
        print("  [ai-discover] GOOGLE_AI_SCRAPER_ENABLED=false — skip", flush=True)
        return [], industry

    h = health()
    if not h.get("ok"):
        print(
            f"  [ai-discover] Google AI scraper not reachable ({h.get('error') or h})",
            flush=True,
        )
        return [], industry

    print(
        f"  [ai-discover] Google AI scraper OK "
        f"(extension_connected={h.get('extension_connected')})",
        flush=True,
    )

    planned = plan_column_fill_queries(
        market,
        country=country,
        settings=settings,
        industry=industry,
        max_queries=max_queries,
    )
    batches: list[list[dict[str, str]]] = []
    for item in planned:
        q = str(item.get("q") or "").strip()
        fills = item.get("fills") or list(REQUIRED_TABLE_COLUMNS)
        if not q:
            continue
        print(
            f"  [ai-discover] Google AI Overview ← {q!r}  [fills: {', '.join(fills)}]",
            flush=True,
        )
        res = _ask_scraper(q)
        md = str(res.get("markdown") or "")
        err = str(res.get("error") or "")
        _cache_overview(market, q, res, purpose="column_fill")
        if err and not md.strip():
            print(f"  [ai-discover] ask failed: {err[:140]}", flush=True)
            continue
        if not md.strip():
            print("  [ai-discover] empty AI Overview", flush=True)
            continue
        print(f"  [ai-discover] overview {len(md)} chars", flush=True)
        try:
            extracted = _extract_with_llm(market, md, settings=settings, industry=industry)
        except Exception as exc:
            print(f"  [ai-discover] LLM extract failed: {exc}", flush=True)
            extracted = []
        if len(extracted) < 3:
            extracted = _merge_brand_rows([extracted, _extract_fallback(md)])
        batches.append(extracted)

    merged = _merge_brand_rows(batches)
    cleaned: list[dict[str, str]] = []
    for row in merged:
        brand = row["brand"]
        if not is_plausible_company_name(brand):
            continue
        if is_market_geo_artifact(brand, market):
            continue
        low = brand.lower()
        if any(x in low for x in ("pornhub", "xvideos", "whatsapp", "wikipedia")):
            continue
        cleaned.append(row)
    cleaned = cleaned[: max(1, min(int(max_brands), 20))]

    print(
        f"  [ai-discover] extracted {len(cleaned)} brands from Google AI Overview "
        f"(cap {min(int(max_brands), 20)})",
        flush=True,
    )
    for row in cleaned[:12]:
        bits = [row["brand"]]
        if row.get("company"):
            bits.append(f"company={row['company']}")
        if row.get("founded_location"):
            bits.append(f"founded_in={row['founded_location']}")
        print(f"    • {' | '.join(bits)}", flush=True)

    return _rows_to_companies(cleaned, discovery_source="google_ai_overview"), industry


def _extract_landscape_batch(
    market: str,
    markdown: str,
    *,
    country: str,
    settings: Any,
    industry: dict[str, Any],
) -> list[dict[str, str]]:
    from vendor_intel.clients.claude import ClaudeClient

    client = ClaudeClient(settings) if settings is not None else None
    if client is None or not getattr(client, "available", False):
        return _extract_fallback(markdown)
    user = json.dumps(
        {
            "market": market,
            "country": country,
            "industry_category": industry.get("industry_category"),
            "company_display_mode": industry.get("company_display_mode"),
            "required_columns": list(REQUIRED_TABLE_COLUMNS),
            "ai_overview": (markdown or "")[:7000],
        },
        ensure_ascii=False,
    )
    raw = client.complete_json(_EXTRACT_LANDSCAPE_SYSTEM, user, max_tokens=3500)
    rows: list[dict[str, str]] = []
    if not isinstance(raw, dict):
        return _extract_fallback(markdown)
    for item in raw.get("brands") or []:
        if isinstance(item, str):
            name = item.strip()
            if name:
                rows.append({"brand": name, "company": "", "founded_location": "", "note": ""})
            continue
        if not isinstance(item, dict):
            continue
        brand = str(item.get("brand") or item.get("name") or "").strip()
        company = str(item.get("company") or item.get("parent") or "").strip()
        founded_loc = str(
            item.get("founded_location") or item.get("hq_location") or item.get("location") or ""
        ).strip()
        if founded_loc and re.fullmatch(r"(19|20)\d{2}", founded_loc):
            founded_loc = ""
        note = str(item.get("note") or "").strip()
        if brand:
            rows.append(
                {
                    "brand": brand,
                    "company": company,
                    "founded_location": founded_loc or country,
                    "note": note,
                }
            )
    if len(rows) < 3:
        rows = _merge_brand_rows([rows, _extract_fallback(markdown)])
    return rows


def discover_landscape_from_google_ai(
    market: str,
    *,
    country: str = "global",
    settings: Any = None,
    industry: dict[str, Any] | None = None,
    max_brands: int = 240,
    max_countries: int = 16,
    queries_per_country: int = 2,
    countries_override: str | list[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Country-wise Google AI Overview discovery for the wide Company Details table.

    Example queries: ``avocado oil India``, ``avocado oil New Zealand``.
    """
    from vendor_intel.discovery.entity_extract import is_plausible_company_name
    from vendor_intel.evidence.google_ai_scraper import health, scraper_enabled

    max_brands = max(1, min(int(max_brands), 800))
    if not scraper_enabled():
        print("  [ai-geo] GOOGLE_AI_SCRAPER_ENABLED=false — skip country landscape", flush=True)
        return []

    h = health()
    if not h.get("ok"):
        print(f"  [ai-geo] scraper not reachable ({h.get('error') or h})", flush=True)
        return []

    industry = industry or understand_market(market, country=country, settings=settings)
    countries = plan_landscape_countries(
        market,
        country=country,
        settings=settings,
        override=countries_override,
        max_countries=max_countries,
    )
    planned = country_landscape_queries(
        market, countries, queries_per_country=queries_per_country
    )
    print(
        f"  [ai-geo] country-wise Google AI landscape: "
        f"{len(countries)} countries × ~{queries_per_country} queries "
        f"= {len(planned)} asks (cap {max_brands} brands)",
        flush=True,
    )
    for c in countries:
        print(f"    · {market_short_name(market)} {c}", flush=True)

    batches: list[list[dict[str, str]]] = []
    for item in planned:
        q = str(item.get("q") or "").strip()
        geo = str(item.get("country") or "").strip()
        if not q:
            continue
        print(f"  [ai-geo] Google AI Overview ← {q!r}", flush=True)
        res = _ask_scraper(q)
        md = str(res.get("markdown") or "")
        err = str(res.get("error") or "")
        _cache_overview(market, q, res, purpose=f"geo_{geo or 'landscape'}")
        if err and not md.strip():
            print(f"  [ai-geo] ask failed: {err[:140]}", flush=True)
            continue
        if not md.strip():
            print("  [ai-geo] empty AI Overview", flush=True)
            continue
        print(f"  [ai-geo] overview {len(md)} chars ({geo})", flush=True)
        try:
            extracted = _extract_landscape_batch(
                market, md, country=geo, settings=settings, industry=industry
            )
        except Exception as exc:
            print(f"  [ai-geo] LLM extract failed: {exc}", flush=True)
            extracted = _extract_fallback(md)
        # Stamp empty founded_location with query country as a soft hint
        stamped: list[dict[str, str]] = []
        for row in extracted:
            r = dict(row)
            if geo and not r.get("founded_location"):
                r["founded_location"] = geo
            stamped.append(r)
        batches.append(stamped)

    merged = _merge_brand_rows(batches)
    cleaned: list[dict[str, str]] = []
    for row in merged:
        brand = row["brand"]
        if not is_plausible_company_name(brand):
            continue
        if is_market_geo_artifact(brand, market):
            continue
        low = brand.lower()
        if any(x in low for x in ("pornhub", "xvideos", "whatsapp", "wikipedia")):
            continue
        cleaned.append(row)
        if len(cleaned) >= max_brands:
            break

    print(
        f"  [ai-geo] extracted {len(cleaned)} landscape brands from country-wise Google AI",
        flush=True,
    )
    for row in cleaned[:15]:
        bits = [row["brand"]]
        if row.get("company"):
            bits.append(f"company={row['company']}")
        if row.get("founded_location"):
            bits.append(f"founded_in={row['founded_location']}")
        print(f"    • {' | '.join(bits)}", flush=True)

    return _rows_to_companies(cleaned, discovery_source="google_ai_geo")


def resolve_domains_for_brands(
    companies: list[dict[str, Any]],
    *,
    settings: Any,
    market: str = "",
) -> list[dict[str, Any]]:
    """Fill official domains via LLM knowledge (same approach as Phase-1 seeds)."""
    del market
    if not companies:
        return companies
    try:
        from vendor_intel.discovery.entity_extract import is_blocked_domain
        from vendor_intel.pipeline.plan_seeds import _llm_seed_domains, _nk
        from vendor_intel.utils.domain_corrections import crawl_host_for_domain

        names = [str(c.get("company_raw") or c.get("company") or "") for c in companies]
        mapping = _llm_seed_domains(names, settings)
        for c in companies:
            name = str(c.get("company_raw") or c.get("company") or "")
            key = _nk(name)
            dom = mapping.get(key) or ""
            if dom:
                host = crawl_host_for_domain(dom) or dom
                if host and not is_blocked_domain(host):
                    c["domain"] = host
                    c["website"] = host
                    print(f"  [ai-discover] domain {name[:40]} → {host}", flush=True)
                else:
                    print(f"  [ai-discover] blocked/skip domain for {name[:40]}: {dom}", flush=True)
            else:
                print(f"  [ai-discover] no domain for {name[:40]}", flush=True)
    except Exception as exc:
        print(f"  [ai-discover] domain resolve skipped: {exc}", flush=True)
    return companies
