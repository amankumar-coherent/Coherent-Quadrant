"""Landscape Excel export — market-vertical-aware column sets.

Originally a fixed 30-column FMCG/food-market schema (AVOCADO_OIL_COLUMNS).
Now schema-driven via config/export_schemas.yaml, selected by `market_type`
("fmcg" preserves the exact original 30 columns; "general" is the safe
default for non-FMCG verticals — see that file's header comment for the
rationale). row_from_verdict() is unchanged either way — it always computes
the full field set; market_type only controls which columns get written.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

AVOCADO_OIL_COLUMNS: tuple[str, ...] = (
    "Founded",
    "Headquarters",
    "Cities / Regions",
    "Ownership",
    "Business Type",
    "Employees",
    "Turnover / Scale",
    "Contact Person",
    "Role",
    "Email",
    "Phone / WhatsApp",
    "LinkedIn",
    "Website",
    "Core Categories",
    "Specialty Focus",
    "Price Segment",
    "Key Brands Represented",
    "Exclusivity",
    "Partnership Duration",
    "Retail Chains",
    "Specialty Grocers",
    "Foodservice / HoReCa",
    "E-commerce",
    "Channel Strength",
    "Distribution Type",
    "Regions Served",
    "Regional Extensions",
    "Warehouse / Logistics",
    "Delivery / Storage",
    "Competitive Benchmark",
)

_META_COLUMNS: tuple[str, ...] = (
    "Company",
    "Data Confidence",
    "Quality Score",
    "Data Sources",
)

# Legacy alias — the original fixed 30-column schema, kept so any external
# code importing this constant directly still sees the exact original value.
_EXPORT_COLUMNS: tuple[str, ...] = ("Company",) + AVOCADO_OIL_COLUMNS + _META_COLUMNS[1:] + ("Summary",)

_DEFAULT_MARKET_TYPE = "fmcg"
_FALLBACK_MARKET_TYPE = "general"


@lru_cache(maxsize=1)
def _load_export_schemas() -> dict[str, list[str]]:
    from vendor_intel.config import _project_root

    path = _project_root() / "config" / "export_schemas.yaml"
    if not path.exists():
        return {}
    import yaml

    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return {k: list(v) for k, v in data.items() if isinstance(v, list)}


def _export_columns(market_type: str) -> tuple[str, ...]:
    """Full column list for landscape Excel.

    Prefer ``slim_full`` (canonical curated columns matching the 6-market
    Excel). Older market_type keys still work but no longer append
    Data Confidence / Quality Score / Data Sources unless slim_full is absent.
    """
    from vendor_intel.export.landscape_slim import SLIM_COLUMNS

    schemas = _load_export_schemas()
    if schemas.get("slim_full"):
        return tuple(schemas["slim_full"])
    if not schemas:
        return SLIM_COLUMNS
    middle = schemas.get(market_type) or schemas.get(_FALLBACK_MARKET_TYPE)
    if not middle:
        return SLIM_COLUMNS
    # If middle already looks like a full schema (starts with Company), use as-is
    if middle and str(middle[0]).strip() == "Company":
        return tuple(middle)
    return ("Company",) + tuple(middle) + ("Summary",)


_RETAIL_KW = re.compile(
    r"\b(?:walmart|costco|target|kroger|safeway|albertsons|tesco|sainsbury|"
    r"carrefour|auchan|lidl|aldi|whole\s*foods|amazon|retail\s+chain|supermarket|"
    r"grocery\s+chain|mass\s+market)\b",
    re.I,
)
_SPECIALTY_KW = re.compile(
    r"\b(?:trader\s+joe|sprouts|natural\s+grocers|holland\s+&?\s*barrett|"
    r"specialty\s+groc|organic\s+store|health\s+food\s+store|fresh\s+market)\b",
    re.I,
)
_FOODSERVICE_KW = re.compile(
    r"\b(?:foodservice|food\s+service|horeca|restaurant|catering|hotel|"
    r"institutional|bulk\s+supply|commercial\s+kitchen|chef)\b",
    re.I,
)
_ECOM_KW = re.compile(
    r"\b(?:e-?commerce|online\s+shop|shop\s+now|add\s+to\s+cart|direct\s+to\s+consumer|"
    r"d2c|buy\s+online|our\s+store)\b",
    re.I,
)
_PREMIUM_KW = re.compile(
    r"\b(?:organic|premium|extra\s+virgin|cold\s+pressed|cold-pressed|artisan|"
    r"gourmet|high\s+quality|virgin\s+avocado)\b",
    re.I,
)
_BULK_KW = re.compile(
    r"\b(?:bulk|commodity|industrial|tanker|drum|pallet|moq|minimum\s+order|"
    r"wholesale\s+volume|export\s+volume)\b",
    re.I,
)
_LOGISTICS_KW = re.compile(
    r"\b(?:warehouse|fulfillment|logistics|distribution\s+center|cold\s+chain|"
    r"storage|3pl|third.party\s+logistics)\b",
    re.I,
)
_DELIVERY_KW = re.compile(
    r"\b(?:delivery|shipping|freight|tanker|bulk\s+delivery|last\s+mile)\b",
    re.I,
)
_EXCLUSIVITY_EXCLUSIVE = re.compile(
    r"\b(?:exclusive(?:ly)?\s+(?:distribut|partner|agent|represent|rights?|dealership)|"
    r"sole\s+(?:distribut|agent|represent|partner)|only\s+(?:authorised|authorized)\s+distribut)\b",
    re.I,
)
_EXCLUSIVITY_NON = re.compile(
    r"\b(?:non[- ]exclusive|not\s+exclusive|multiple\s+distribut)\b",
    re.I,
)
_FOUNDED_YEAR = re.compile(
    r"\b(?:founded|established|since|in\s+business\s+since)\s+(?:in\s+)?((?:19|20)\d{2})\b",
    re.I,
)
_LOCATION_REJECT_KW = re.compile(
    r"\b(?:avocado|bottle|bottles|recipe|ingredients?|serves|delivery|quantity|"
    r"ssd|ratings?|usd|shop(?:ping)?|cart|oz\b|every\s+one|days\s+only|"
    r"walking\s+workout|next\s+level|farm\s+to\s+table|logo\s*\||"
    r"miller\s+projection|map\s+of\s+(?:the\s+)?world|orthographic|mercator|"
    r"equirectangular|wikimedia|svg\s+map)\b",
    re.I,
)
_STREET_SUFFIX = re.compile(
    r"\b(?:st(?:reet)?|ave(?:nue)?|rd|road|blvd|boulevard|dr|drive|ln|lane|"
    r"way|suite|ste|floor|fl|camino|plaza|parkway|pkwy|highway|hwy)\b",
    re.I,
)
_CITY_STATE_ZIP = re.compile(
    r"[A-Za-z][A-Za-z\s.'-]{2,40},\s*(?:[A-Z]{2}|[A-Za-z][A-Za-z\s.'-]{2,30})"
    r"(?:\s*,?\s*\d{4,6}|\s*,?\s*[A-Z]\d[A-Z]\s?\d[A-Z]\d)?",
)
_EMPLOYEE_COUNT = re.compile(
    r"\b((?:\d[\d,]*\+?)\s*(?:employees?|staff|team\s+members?|people))\b",
    re.I,
)
_REVENUE = re.compile(
    r"\b((?:USD|US\$|\$|€|£)\s*[\d,.]+\s*(?:million|billion|m|bn|k)?|"
    r"[\d,.]+\s*(?:million|billion)\s+(?:USD|dollars?|in\s+revenue))\b",
    re.I,
)
_PRODUCT_PHRASES = re.compile(
    r"\b(?:organic\s+)?(?:extra\s+virgin\s+)?avocado\s+oil(?:\s+\w+){0,4}|"
    r"\bavocado\s+oil\s+(?:mayo|dressing|spray|shortening|squeeze)\b|"
    r"\bcold[- ]pressed\s+avocado\b|"
    r"\brefined\s+avocado\s+oil\b|"
    r"\bcrude\s+avocado\s+oil\b|"
    r"\bavocado\s+(?:pulp|butter|spread)\b",
    re.I,
)

_WHATSAPP = re.compile(r"(?:wa\.me/[\d+]+|whatsapp[:\s]+[\d+\s()-]{8,})", re.I)
_EMAIL = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_PHONE = re.compile(r"(?:\+?\d[\d\s().-]{7,}\d)")


def _join(items: Any, sep: str = "; ") -> str:
    if not items:
        return ""
    if isinstance(items, str):
        return items.strip()
    if isinstance(items, list):
        parts = [str(x).strip() for x in items if str(x).strip()]
        return sep.join(parts)
    return str(items).strip()


def _first_leader(people: dict[str, Any]) -> tuple[str, str]:
    for block in ("leadership", "board", "advisors"):
        rows = people.get(block) or []
        if not isinstance(rows, list):
            continue
        for person in rows:
            if not isinstance(person, dict):
                continue
            name = str(person.get("name") or "").strip()
            title = str(person.get("title") or "").strip()
            if name:
                return name, title
    return "", ""


def _crawl_text(smart_data: dict[str, Any] | None) -> str:
    if not smart_data:
        return ""
    from vendor_intel.intelligence.signal_extractor import _collect_value_text

    parts: list[str] = []
    structured = _collect_value_text(smart_data).strip()
    domain_only = str(smart_data.get("domain") or "").strip()
    if structured and structured.lower() != domain_only.lower():
        parts.append(structured)
    for page in smart_data.get("pages") or []:
        if isinstance(page, dict):
            t = str(page.get("text") or "").strip()
            if t:
                parts.append(t[:8000])
    data = smart_data.get("data") or {}
    if isinstance(data, dict):
        intel = data.get("intel") or {}
        if isinstance(intel, dict):
            summary = str(intel.get("summary") or "").strip()
            if summary:
                parts.append(summary)
    return " ".join(parts)[:12000]


def crawl_snapshot(smart_data: dict[str, Any] | None) -> dict[str, Any]:
    """Flatten smart_crawl output for export (stored on pipeline verdict rows)."""
    if not smart_data:
        return {}
    data = smart_data.get("data") or {}
    if not isinstance(data, dict):
        data = {}
    company = data.get("company") or {}
    location = data.get("location") or {}
    contact = data.get("contact") or {}
    financials = data.get("financials") or {}
    business = data.get("business") or {}
    people = data.get("people") or {}
    relationships = data.get("relationships") or {}
    contact_person, contact_role = _first_leader(people if isinstance(people, dict) else {})

    products: list[str] = []
    for p in business.get("products") or []:
        if isinstance(p, dict):
            n = str(p.get("name") or "").strip()
            if n:
                products.append(n)
        elif p:
            products.append(str(p).strip())

    contact_address = str(contact.get("address") or "").strip()
    hq_structured = str(location.get("headquarters") or "").strip() or contact_address

    return {
        "founded_year": company.get("founded_year"),
        "headquarters": hq_structured,
        "contact_address": contact_address,
        "offices": _join(location.get("offices")),
        "manufacturing_locations": _join(location.get("manufacturing_locations")),
        "regions_served": _join(location.get("regions_served")),
        "countries": _join(location.get("countries")),
        "ownership_parent": relationships.get("parent_company") or "",
        "company_type": company.get("type") or "",
        "employee_count": financials.get("employee_count") or "",
        "revenue": financials.get("revenue") or "",
        "key_numbers": _join(financials.get("key_numbers")),
        "contact_person": contact_person,
        "contact_role": contact_role,
        "email": contact.get("email") or "",
        "phone": contact.get("phone") or "",
        "linkedin": contact.get("linkedin") or "",
        "website": company.get("website") or "",
        "industries": _join(business.get("industries")),
        "products": _join(products) or _join(business.get("key_markets")),
        "certifications": _join(business.get("certifications")),
        "distributors": _join(relationships.get("distributors")),
        "customers": _join(relationships.get("customers")),
        "partnerships": _join(relationships.get("partnerships")),
        "crawl_text": _crawl_text(smart_data)[:12000],
    }


def _detect_channels(text: str) -> dict[str, str]:
    t = text or ""
    retail = "Yes" if _RETAIL_KW.search(t) else ""
    specialty = "Yes" if _SPECIALTY_KW.search(t) else ""
    foodservice = "Yes" if _FOODSERVICE_KW.search(t) else ""
    ecom = "Yes" if _ECOM_KW.search(t) else ""
    score = sum(bool(x) for x in (retail, specialty, foodservice, ecom))
    strength = str(min(5, max(1, score + (1 if _BULK_KW.search(t) else 0)))) if score else "1"
    return {
        "retail_chains": retail,
        "specialty_grocers": specialty,
        "foodservice": foodservice,
        "ecommerce": ecom,
        "channel_strength": strength,
    }


def _price_segment(text: str) -> str:
    t = text or ""
    premium = bool(_PREMIUM_KW.search(t))
    bulk = bool(_BULK_KW.search(t))
    if premium and bulk:
        return "Premium + Bulk"
    if premium:
        return "Premium / Organic"
    if bulk:
        return "Commodity / Bulk"
    return ""


def _distribution_type(verdict: dict[str, Any], text: str) -> str:
    role = str(verdict.get("role") or "").lower()
    fn = str(verdict.get("company_function") or "").lower()
    if "distribut" in fn or "distribut" in role:
        return "Distributor"
    if "retail" in fn or "retail" in role:
        return "Direct retail / Retailer"
    if "export" in fn:
        return "Export"
    if "wholesal" in fn:
        return "Wholesale"
    if "manufactur" in fn or "manufactur" in role:
        return "Direct / Manufacturer-led"
    if _BULK_KW.search(text):
        return "Bulk B2B"
    return ""


def _benchmark_tier(verdict: dict[str, Any], channel_strength: str) -> str:
    q = float(verdict.get("quality_score") or verdict.get("confidence") or 0)
    ch = int(channel_strength or "1")
    if q >= 0.7 and ch >= 3:
        return "Leader"
    if q >= 0.5 or ch >= 2:
        return "Mid-tier"
    return "Niche / Emerging"


def is_plausible_location(text: str, *, allow_country_only: bool = False) -> bool:
    """Return True when text looks like a real address or place name, not marketing copy."""
    val = re.sub(r"\s+", " ", str(text or "").strip())
    if len(val) < 3 or len(val) > 200:
        return False
    if _LOCATION_REJECT_KW.search(val):
        return False
    if _STREET_SUFFIX.search(val):
        return True
    if _CITY_STATE_ZIP.search(val):
        return True
    if re.search(r"\d{1,5}\s+\w", val) and "," in val:
        return True
    if allow_country_only and "," not in val and 3 <= len(val) <= 60:
        if re.match(r"^[A-Za-z][A-Za-z\s.'-]+$", val):
            return True
    return False


def _validated_location(text: str, *, allow_country_only: bool = False) -> str:
    val = str(text or "").strip()
    if val and is_plausible_location(val, allow_country_only=allow_country_only):
        return val
    return ""


def _resolve_headquarters(crawl: dict[str, Any], signals: dict[str, Any]) -> str:
    from vendor_intel.enrichment.hq_city_country import is_city_country, normalize_city_country

    for candidate in (
        crawl.get("headquarters"),
        crawl.get("contact_address"),
        signals.get("hq_country"),
    ):
        raw = str(candidate or "").strip()
        if not raw:
            continue
        hq = normalize_city_country(raw)
        if hq:
            return hq
        # Accept only City, Country — never bare country for Headquarters / Found in
        if is_city_country(raw) and is_plausible_location(raw, allow_country_only=False):
            return raw
    return ""


def _normalize_place_key(text: str) -> str:
    s = re.sub(r"\s+", " ", str(text or "").lower()).strip(" .,;")
    s = re.sub(r"\b(united states|usa|u\.s\.a\.|u\.s\.)\b", "us", s)
    return s


def _places_equivalent(a: str, b: str) -> bool:
    aa, bb = _normalize_place_key(a), _normalize_place_key(b)
    if not aa or not bb:
        return False
    return aa == bb or aa in bb or bb in aa


def _resolve_cities_regions(crawl: dict[str, Any], *, headquarters: str = "") -> str:
    """Office/city list for Cities / Regions — never duplicate HQ or map junk."""
    hq = str(headquarters or crawl.get("headquarters") or crawl.get("contact_address") or "").strip()
    out: list[str] = []
    seen: set[str] = set()
    for candidate in (
        crawl.get("cities_regions"),
        crawl.get("offices"),
        crawl.get("manufacturing_locations"),
    ):
        raw = str(candidate or "").strip()
        if not raw:
            continue
        for part in re.split(r"[;|]", raw):
            part = part.strip()
            if not part:
                continue
            if _LOCATION_REJECT_KW.search(part):
                continue
            if hq and _places_equivalent(part, hq):
                continue
            # Keep broad region labels (Europe, Asia Pacific) as-is for distributor footprints.
            if re.fullmatch(
                r"(?i)global|worldwide|europe|asia(?:\s*pacific)?|americas?|emea|latam|"
                r"north america|south america|middle east(?:\s*&\s*africa)?|africa",
                part.strip(),
            ):
                cities = part.strip()
            else:
                cities = _validated_location(part, allow_country_only=False)
            if not cities:
                continue
            key = _normalize_place_key(cities)
            if key in seen:
                continue
            seen.add(key)
            out.append(cities)
        if out:
            break
    if out:
        return "; ".join(out[:8])
    # Fall back so Cities / Regions is never blank when HQ or crawl cities exist.
    raw = str(crawl.get("cities_regions") or "").strip()
    if raw and not _LOCATION_REJECT_KW.search(raw) and len(raw) < 220:
        return raw
    return hq


def _resolve_regions_served(
    crawl: dict[str, Any],
    signals: dict[str, Any],
    verdict: dict[str, Any],
) -> str:
    for candidate in (
        crawl.get("regions_served"),
        crawl.get("countries"),
    ):
        regions = _validated_location(str(candidate or ""), allow_country_only=True)
        if regions:
            return regions
    mentioned = signals.get("mentioned_countries") or []
    if mentioned:
        return ", ".join(str(c).strip() for c in mentioned[:8] if str(c).strip())
    return str(verdict.get("geography") or verdict.get("country_presence") or "").strip()


def _extract_founded_year(text: str) -> str:
    m = _FOUNDED_YEAR.search(text or "")
    return m.group(1) if m else ""


def _extract_employee_count(text: str) -> str:
    m = _EMPLOYEE_COUNT.search(text or "")
    return m.group(1).strip() if m else ""


def _extract_revenue(text: str) -> str:
    m = _REVENUE.search(text or "")
    return m.group(1).strip() if m else ""


def _infer_core_categories(text: str, existing: str) -> str:
    if existing:
        return existing
    found: list[str] = []
    seen: set[str] = set()
    for m in _PRODUCT_PHRASES.finditer(text or ""):
        phrase = re.sub(r"\s+", " ", m.group(0).strip())
        key = phrase.lower()
        if key not in seen and len(phrase) >= 8:
            seen.add(key)
            found.append(phrase.title() if phrase.islower() else phrase)
    return "; ".join(found[:6])


def _detect_exclusivity(text: str, crawl: dict[str, Any]) -> str:
    partnerships = str(crawl.get("partnerships") or "")
    combined = f"{text} {partnerships}"
    if _EXCLUSIVITY_EXCLUSIVE.search(combined):
        return "Exclusive distribution / partnership indicated"
    if _EXCLUSIVITY_NON.search(combined):
        return "Non-exclusive distribution"
    return "Not publicly disclosed"


def _confidence(verdict: dict[str, Any], crawl: dict[str, Any]) -> str:
    filled = sum(
        1
        for k in (
            "headquarters",
            "email",
            "phone",
            "employee_count",
            "products",
            "founded_year",
        )
        if crawl.get(k)
    )
    q = float(verdict.get("quality_score") or verdict.get("confidence") or 0)
    if filled >= 4 and q >= 0.55:
        return "High"
    if filled >= 2 or q >= 0.45:
        return "Medium"
    return "Low"


def _clean_specialty(val: str) -> str:
    """Filter out ISO certifications and general quality standards from Specialty Focus."""
    if not val:
        return ""
    parts = [p.strip() for p in re.split(r"[;,\n]", val) if p.strip()]
    cleaned = []
    for p in parts:
        lower_p = p.lower()
        if any(k in lower_p for k in (
            "iso ", "iso-", "haccp", "gmp", "fda ", "brc", "ifs", 
            "halal", "kosher", "certified", "certification", 
            "standards", "compliance", "quality standard", "safety"
        )):
            continue
        cleaned.append(p)
    return "; ".join(cleaned)


def row_from_verdict(verdict: dict[str, Any]) -> dict[str, str]:
    """Map one pipeline verdict (+ optional _crawl snapshot) to export columns."""
    crawl = verdict.get("_crawl") or {}
    if not crawl and verdict.get("_crawl_raw"):
        crawl = crawl_snapshot(verdict.get("_crawl_raw"))

    enrich = verdict.get("_presentation_enrich") or {}

    company = str(verdict.get("company") or verdict.get("brand") or "").strip()
    signals = verdict.get("signals") or {}
    text = " ".join(
        filter(
            None,
            [
                crawl.get("crawl_text") or "",
                str(verdict.get("role_description") or ""),
                str(verdict.get("key_products") or ""),
                str(verdict.get("operational_presence") or ""),
                str(verdict.get("company_summary") or ""),
                str(verdict.get("summary") or ""),
            ],
        )
    )
    channels = _detect_channels(text)

    hq = _resolve_headquarters(crawl, signals)
    cities = _resolve_cities_regions(crawl, headquarters=hq)

    ownership = enrich.get("ownership") or str(
        crawl.get("ownership_parent")
        or verdict.get("parent")
        or verdict.get("parent_or_independent")
        or ""
    ).strip()
    if not ownership or ownership.lower() in ("unknown", "none", "not publicly disclosed", "n/a"):
        ownership = "Private"

    # Channel Partner Intelligence: Business Type = clean Channel Type only
    # (the final classifier role). Do not append the discovery-stage
    # company_function in parentheses (e.g. "Distributor (Manufacturer)").
    business_type = str(verdict.get("role") or crawl.get("company_type") or "").strip()
    if not business_type:
        fn = str(verdict.get("company_function") or "").replace("_", " ").strip()
        if fn and fn.lower() not in ("unknown", "vendor"):
            business_type = fn

    turnover = str(crawl.get("revenue") or crawl.get("key_numbers") or "").strip()
    if not turnover:
        turnover = _extract_revenue(text)
    # Prefer range bands in Excel (e.g. $100M → $80–100M)
    if turnover:
        try:
            from vendor_intel.enrichment.gap_fill.gaps import normalize_turnover_range

            turnover = normalize_turnover_range(turnover) or turnover
        except Exception:
            pass
    employees = str(crawl.get("employee_count") or "").strip()
    if not employees:
        employees = _extract_employee_count(text)

    email = str(crawl.get("email") or "").strip()
    phone = str(crawl.get("phone") or "").strip()
    if not email:
        m = _EMAIL.search(text)
        email = m.group(0) if m else ""
    if not phone:
        m = _PHONE.search(text)
        phone = m.group(0).strip() if m else ""
    whatsapp = ""
    wm = _WHATSAPP.search(text)
    if wm:
        whatsapp = wm.group(0)
    phone_cell = phone
    if whatsapp and whatsapp not in phone_cell:
        phone_cell = f"{phone}; {whatsapp}" if phone_cell else whatsapp

    website = str(verdict.get("website") or crawl.get("website") or verdict.get("domain") or "").strip()
    if website and not website.startswith("http"):
        website = f"https://{website}"

    linkedin = str(crawl.get("linkedin") or "").strip()
    core_cats = str(
        crawl.get("core_categories")
        or verdict.get("key_products")
        or crawl.get("products")
        or ""
    ).strip()
    if not crawl.get("core_categories"):
        core_cats = _infer_core_categories(text, core_cats)
    from vendor_intel.pipeline.csv_fields import sanitize_key_products, sanitize_key_brands

    # Only soft-sanitize when categories did not come from curated crawl.
    if not str(crawl.get("core_categories") or "").strip():
        core_cats = sanitize_key_products(
            core_cats, company=company, brand=str(verdict.get("brand") or "")
        )
    
    specialty = enrich.get("specialty_focus") or str(crawl.get("specialty_focus") or "").strip()
    if not specialty:
        specialty = str(crawl.get("certifications") or crawl.get("industries") or "").strip()
        if _PREMIUM_KW.search(text) and "organic" not in specialty.lower():
            specialty = f"{specialty}; Organic/Premium".strip("; ")
    specialty = _clean_specialty(specialty)
    if not specialty:
        specialty = "Industry manufacturer" if "manufactur" in business_type.lower() else "Service provider"

    brands = str(verdict.get("brand") or "").strip()
    # Prefer explicit key_brands_represented (never the company/brand name alone).
    key_brands = str(crawl.get("key_brands_represented") or "").strip()
    if not key_brands and brands and brands.lower() != company.lower():
        key_brands = brands
    if not key_brands:
        key_brands = crawl.get("distributors") or crawl.get("customers") or ""
    if not key_brands:
        key_brands = str(crawl.get("partnerships") or "").strip()
    if not key_brands and core_cats and (
        "distribut" in business_type.lower() or "retail" in business_type.lower()
    ):
        key_brands = core_cats
    if not str(crawl.get("key_brands_represented") or "").strip():
        key_brands = sanitize_key_brands(str(key_brands or ""), company=company, brand=brands)
    else:
        key_brands = str(key_brands or "")

    regions = str(crawl.get("regions_served") or "").strip()
    if not regions:
        regions = _resolve_regions_served(crawl, signals, verdict)
    # Prefer curated crawl regions_served as-is (do not overwrite with auto-resolve).

    founded = str(crawl.get("founded_year") or "").strip()
    if not founded:
        founded = _extract_founded_year(text)

    exclusivity = _detect_exclusivity(text, crawl)

    def _channel_cell(enrich_key: str, crawl_key: str, fallback: str) -> str:
        # Prefer curated crawl values over auto-detect / presentation enrich.
        raw = crawl.get(crawl_key)
        if raw is None or str(raw).strip() == "":
            raw = enrich.get(enrich_key)
        if raw is None or str(raw).strip() == "":
            raw = fallback
        val = str(raw or "").strip()
        if val.lower() in ("none", "null"):
            return ""
        if val.lower() in ("n/a", "na"):
            return "Not applicable"
        if val.lower() == "no":
            return "No"
        return val

    retail_chains = _channel_cell("retail_chains", "retail_chains", channels["retail_chains"])
    specialty_grocers = _channel_cell(
        "specialty_grocers", "specialty_grocers", channels["specialty_grocers"]
    )
    foodservice = _channel_cell("foodservice", "foodservice", channels["foodservice"])
    ecommerce = _channel_cell("ecommerce", "ecommerce", channels["ecommerce"])

    channel_strength = str(
        crawl.get("channel_strength") or enrich.get("channel_strength") or ""
    ).strip()
    if not channel_strength:
        channel_strength = channels["channel_strength"]

    price_segment = str(crawl.get("price_segment") or enrich.get("price_segment") or "").strip()
    if not price_segment:
        price_segment = _price_segment(text)

    dist_type = str(crawl.get("distribution_type") or "").strip()
    if not dist_type:
        dist_type = _distribution_type(verdict, text)

    regional_ext = str(crawl.get("regional_extensions") or "").strip()
    if not regional_ext:
        regional_ext = _resolve_cities_regions(crawl, headquarters=hq) or ""

    warehouse = str(crawl.get("warehouse_logistics") or "").strip()
    if not warehouse:
        warehouse = "Yes" if _LOGISTICS_KW.search(text) else ""

    delivery = str(crawl.get("delivery_storage") or "").strip()
    if not delivery:
        delivery = "Yes" if _DELIVERY_KW.search(text) else ""

    competitive_benchmark = str(crawl.get("competitive_benchmark") or "").strip()
    if not competitive_benchmark:
        competitive_benchmark = _benchmark_tier(verdict, channel_strength)

    summary = str(
        crawl.get("summary")
        or verdict.get("polished_summary")
        or verdict.get("company_summary")
        or verdict.get("summary")
        or crawl.get("linkedin_about")
        or crawl.get("about")
        or ""
    ).strip()

    from vendor_intel.export.landscape_slim import (
        country_and_region_codes,
        format_continent_geography,
        operational_presence_text,
        parse_country_list,
        retail_ecommerce_both,
    )

    # Continent / Geography = markets served (REGION(countries…))
    geo_countries = parse_country_list(regions)
    if not geo_countries:
        geo_countries = parse_country_list(cities)
    if not geo_countries:
        geo_countries = parse_country_list(hq)
    continent_geo = format_continent_geography(geo_countries)

    # Operational Presence = physical footprint (HQ / offices / plants)
    op_raw = (
        crawl.get("operational_presence")
        or verdict.get("operational_presence")
        or crawl.get("geographic_presence")
        or ""
    )
    op_presence = operational_presence_text(hq or "", op_raw, regions or cities)

    retail_ecom = retail_ecommerce_both(retail_chains, ecommerce)
    country_code, region_code = country_and_region_codes(hq or "")

    # Contact columns: only fill when evidence exists (stay empty otherwise)
    contact_person = str(crawl.get("contact_person") or "").strip()
    contact_role = str(crawl.get("contact_role") or "").strip()
    office_no = str(phone or "").strip()  # Office No. — leave blank if unknown

    return {
        "Company": company,
        "Website": website,
        "Founded": founded,
        "Headquarters": hq or "Not publicly disclosed",
        "Continent / Geography": continent_geo,
        "Operational Presence": op_presence,
        "Ownership": ownership or "Private",
        "Business Type": business_type,
        "Employees": employees or "Not publicly disclosed",
        "Turnover / Scale": turnover or "Not publicly disclosed",
        "Contact Person": contact_person,
        "Role": contact_role,
        "Email": email,
        "Phone / WhatsApp": phone_cell,
        "LinkedIn": linkedin,
        "Office No.": office_no,
        "Core Categories": core_cats,
        "Specialty Focus": specialty,
        "Price Segment": price_segment,
        "Key Brands Represented": str(key_brands or ""),
        "Exclusivity": exclusivity,
        "Partnership Duration": "Not publicly disclosed",
        "Retail Chains": retail_chains,
        "Specialty Grocers": specialty_grocers,
        "Foodservice / HoReCa": foodservice,
        "E-commerce": ecommerce,
        "Retail / E-commerce / Both": retail_ecom,
        "Channel Strength": channel_strength,
        "Distribution Type": dist_type,
        "Regions Served": regions,
        "Regional Extensions": regional_ext,
        "Warehouse / Logistics": warehouse,
        "Delivery / Storage": delivery,
        "Competitive Benchmark": competitive_benchmark,
        "Country Code": country_code,
        "Region Code": region_code,
        "Data Confidence": _confidence(verdict, crawl),
        "Quality Score": str(round(float(verdict.get("quality_score") or verdict.get("confidence") or 0), 3)),
        "Data Sources": str(verdict.get("data_sources") or ""),
        "Summary": summary,
    }


def export_fmcg_xlsx(
    result: dict[str, Any], path: str | Path, *, market_type: str = _DEFAULT_MARKET_TYPE
) -> str:
    """Write a landscape Excel from a pipeline result dict.

    Always exports the slim_full column set (21 curated columns) from
    config/export_schemas.yaml. ``market_type`` is kept for callers but
    slim_full takes precedence when present.
    """
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill, Border, Side
        from openpyxl.utils import get_column_letter
    except ImportError as exc:
        raise ImportError(
            "openpyxl is required for Excel export. "
            "Install: pip install openpyxl"
        ) from exc

    cols = _export_columns(market_type)
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)

    rows_raw = result.get("relevant_companies") or result.get("all_classified") or []
    rows = [row_from_verdict(r) for r in rows_raw if r.get("is_relevant", True)]

    wb = Workbook()
    ws = wb.active
    ctx = result.get("query_context") or {}
    market = str(ctx.get("industry") or result.get("query") or "Market")
    country = str(ctx.get("country") or "global")
    short_title = market.replace("Global ", "").replace(" Market", "")[:31] or "Companies"
    ws.title = f"{short_title} Companies"[:31]
    ws["A1"] = f"{market} — {country.title()} landscape"
    ws["A1"].font = Font(bold=True, size=14)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(cols))

    header_row = 3
    header_fill = PatternFill("solid", fgColor="1F4E79")
    header_font = Font(bold=True, color="FFFFFF", size=10)

    # Style definitions
    thin_side = Side(style='thin', color='D3D3D3')
    thin_border = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)

    # Set header row height
    ws.row_dimensions[header_row].height = 28

    for col_idx, col_name in enumerate(cols, 1):
        cell = ws.cell(row=header_row, column=col_idx, value=col_name)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
        cell.border = thin_border

    for row_idx, row in enumerate(rows, header_row + 1):
        for col_idx, col_name in enumerate(cols, 1):
            val = row.get(col_name, "")
            cell = ws.cell(row=row_idx, column=col_idx, value=val)
            cell.alignment = Alignment(wrap_text=True, vertical="center", horizontal="left")
            cell.border = thin_border

    ws.freeze_panes = ws.cell(row=header_row + 1, column=1)
    ws.auto_filter.ref = (
        f"A{header_row}:{get_column_letter(len(cols))}{header_row + len(rows)}"
    )

    for col_idx in range(1, len(cols) + 1):
        letter = get_column_letter(col_idx)
        max_len = len(str(ws.cell(row=header_row, column=col_idx).value or ""))
        for row_idx in range(header_row + 1, header_row + 1 + len(rows)):
            v = ws.cell(row=row_idx, column=col_idx).value
            if v:
                max_len = max(max_len, min(48, len(str(v))))
        ws.column_dimensions[letter].width = max(10, max_len + 2)

    meta = wb.create_sheet("Run Summary")
    meta.append(["Field", "Value"])
    meta.append(["Query", market])
    meta.append(["Geography", country])
    meta.append(["Companies exported", str(len(rows))])
    meta.append(["Completed", str(result.get("completed_at") or "")])
    meta.append(["Elapsed minutes", str(result.get("elapsed_minutes") or "")])
    # Add basic styling to metadata sheet
    for r_idx in range(1, 7):
        for c_idx in range(1, 3):
            cell = meta.cell(row=r_idx, column=c_idx)
            cell.border = thin_border
            cell.alignment = Alignment(vertical="center", horizontal="left")
            if r_idx == 1:
                cell.font = Font(bold=True)

    mr = result.get("market_research")
    if isinstance(mr, list) and mr:
        ws_mr = wb.create_sheet("Market Research")
        mr_cols = (
            "Source",
            "Title",
            "URL",
            "Market Size",
            "CAGR",
            "Key Players",
            "Regions",
            "Segments",
            "Notes",
        )
        ws_mr.row_dimensions[1].height = 28
        for col_idx, col_name in enumerate(mr_cols, 1):
            cell = ws_mr.cell(row=1, column=col_idx, value=col_name)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
            cell.border = thin_border
        for row_idx, item in enumerate(mr, 2):
            if not isinstance(item, dict):
                continue
            ws_mr.cell(row=row_idx, column=1, value=str(item.get("source") or ""))
            ws_mr.cell(row=row_idx, column=2, value=str(item.get("title") or ""))
            ws_mr.cell(row=row_idx, column=3, value=str(item.get("source_url") or item.get("url") or ""))
            ws_mr.cell(row=row_idx, column=4, value=str(item.get("market_size") or ""))
            ws_mr.cell(row=row_idx, column=5, value=str(item.get("cagr") or ""))
            kp = item.get("key_players")
            ws_mr.cell(
                row=row_idx,
                column=6,
                value=", ".join(kp) if isinstance(kp, list) else str(kp or ""),
            )
            reg = item.get("regions")
            ws_mr.cell(
                row=row_idx,
                column=7,
                value=", ".join(reg) if isinstance(reg, list) else str(reg or ""),
            )
            seg = item.get("segments")
            ws_mr.cell(
                row=row_idx,
                column=8,
                value=", ".join(seg) if isinstance(seg, list) else str(seg or ""),
            )
            ws_mr.cell(row=row_idx, column=9, value=str(item.get("notes") or item.get("snippet") or ""))
            
            for col_idx in range(1, len(mr_cols) + 1):
                cell = ws_mr.cell(row=row_idx, column=col_idx)
                cell.alignment = Alignment(wrap_text=True, vertical="center", horizontal="left")
                cell.border = thin_border
                
        ws_mr.freeze_panes = "A2"
        for col_idx in range(1, len(mr_cols) + 1):
            letter = get_column_letter(col_idx)
            ws_mr.column_dimensions[letter].width = 18 if col_idx > 3 else 22

    try:
        wb.save(out)
    except PermissionError:
        from datetime import datetime, timezone

        alt = out.with_name(
            f"{out.stem}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}{out.suffix}"
        )
        wb.save(alt)
        print(f"  [fmcg] Excel locked ({out.name}) — saved: {alt.resolve()}", flush=True)
        return str(alt.resolve())

    return str(out.resolve())
