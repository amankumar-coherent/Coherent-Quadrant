"""Detect and merge missing firmographic fields (gap-fill only)."""
from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Any

from vendor_intel.export.fmcg_landscape import crawl_snapshot, is_plausible_location

PLACEHOLDERS = frozenset(
    {
        "",
        "not publicly disclosed",
        "not specified",
        "unknown",
        "n/a",
        "na",
        "-",
        "none",
        "tbd",
        "null",
    }
)

# High-trust firmographic sources may commit Founded/HQ/Employees immediately.
HIGH_TRUST_SOURCES = frozenset(
    {
        "wikidata",
        "linkedin_mcp",
        "linkedin",
        "sec_edgar",
    }
)

# Require 2 agreeing low-trust sources (or high-trust / identity match) before commit.
CONSENSUS_FIELDS = frozenset({"founded_year", "headquarters", "employee_count"})
_FOUNDED_MIN_YEAR = 1600


def norm(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def is_empty_value(value: Any) -> bool:
    return norm(value).lower() in PLACEHOLDERS


def _crawl(row: dict[str, Any]) -> dict[str, Any]:
    c = row.get("_crawl")
    return c if isinstance(c, dict) else {}


def has_headquarters(row: dict[str, Any]) -> bool:
    """True when HQ looks like City, Country (bare country is incomplete)."""
    from vendor_intel.enrichment.hq_city_country import is_city_country

    crawl = _crawl(row)
    for key in ("headquarters", "contact_address"):
        val = norm(crawl.get(key))
        if val and is_city_country(val):
            return True
    hq = norm(row.get("Headquarters"))
    if hq and is_city_country(hq):
        return True
    return False


def plausible_founded_year(value: Any) -> int | None:
    """Return YYYY if in [1600, current_year], else None."""
    if value is None:
        return None
    raw = str(value).strip()
    m = re.search(r"(1[6-9]\d{2}|20\d{2})", raw)
    if not m:
        return None
    try:
        year = int(m.group(1))
    except (TypeError, ValueError):
        return None
    max_year = datetime.now().year + 1
    if _FOUNDED_MIN_YEAR <= year <= max_year:
        return year
    return None


def has_founded(row: dict[str, Any]) -> bool:
    return plausible_founded_year(_crawl(row).get("founded_year")) is not None


def _consensus_enabled() -> bool:
    raw = (os.getenv("GAP_FILL_CONSENSUS") or "true").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _norm_fact_key(field: str, value: Any) -> str:
    if field == "founded_year":
        y = plausible_founded_year(value)
        return str(y) if y is not None else ""
    if field == "employee_count":
        digits = re.sub(r"[^\d]", "", str(value or ""))
        return digits[:8] if digits else ""
    # headquarters / free text
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def identity_text_matches(
    company: str,
    domain: str,
    text: str,
    *,
    min_tokens: int = 1,
) -> bool:
    """True when evidence clearly refers to this company (name tokens and/or domain)."""
    blob = str(text or "").lower()
    if not blob.strip():
        return False
    dom = (
        str(domain or "")
        .lower()
        .removeprefix("https://")
        .removeprefix("http://")
        .removeprefix("www.")
        .split("/")[0]
        .strip()
    )
    if dom and len(dom) >= 4 and dom in blob:
        return True
    name = re.sub(r"[^a-z0-9\s]", " ", str(company or "").lower())
    tokens = [t for t in name.split() if len(t) >= 3 and t not in {
        "inc", "ltd", "llc", "corp", "corporation", "company", "co", "group",
        "the", "and", "of", "for", "international", "global", "holdings",
    }]
    if not tokens:
        return bool(dom)  # domain-only identity when name is generic
    hits = sum(1 for t in tokens if t in blob)
    need = min(min_tokens, max(1, len(tokens) // 2 + (1 if len(tokens) >= 2 else 0)))
    return hits >= need


def _buffer_fact_candidate(
    crawl: dict[str, Any],
    field: str,
    value: Any,
    source: str,
) -> bool:
    """Record a candidate. Return True if consensus reached (2+ agreeing sources)."""
    key = _norm_fact_key(field, value)
    if not key:
        return False
    pending = crawl.setdefault("_fact_candidates", {})
    if not isinstance(pending, dict):
        pending = {}
        crawl["_fact_candidates"] = pending
    field_map = pending.setdefault(field, {})
    if not isinstance(field_map, dict):
        field_map = {}
        pending[field] = field_map
    entry = field_map.setdefault(key, {"value": value, "sources": []})
    srcs = entry.setdefault("sources", [])
    if source and source not in srcs:
        srcs.append(source)
    entry["value"] = value
    return len(srcs) >= 2


def finalize_pending_facts(row: dict[str, Any]) -> list[str]:
    """Promote consensus candidates (2+ sources) into crawl. Call after gap_fill_row."""
    crawl = dict(_crawl(row))
    pending = crawl.get("_fact_candidates")
    if not isinstance(pending, dict) or not pending:
        return []
    promoted: list[str] = []
    extracted: dict[str, Any] = {}
    for field, field_map in pending.items():
        if field not in CONSENSUS_FIELDS or not isinstance(field_map, dict):
            continue
        if field == "founded_year" and has_founded(row):
            continue
        if field == "headquarters" and has_headquarters(row):
            continue
        if field == "employee_count" and has_employees(row):
            continue
        # Prefer key with most agreeing sources
        best = None
        best_n = 0
        for _k, entry in field_map.items():
            if not isinstance(entry, dict):
                continue
            n = len(entry.get("sources") or [])
            if n >= 2 and n > best_n:
                best = entry.get("value")
                best_n = n
        if best is not None:
            extracted[field] = best
    if not extracted:
        return []
    # Force-commit via high-trust path (bypass re-buffer)
    return merge_extracted(
        row,
        extracted,
        source="consensus",
        evidence_text="",
        force_commit=True,
    )


def has_employees(row: dict[str, Any]) -> bool:
    return not is_empty_value(_crawl(row).get("employee_count"))


def has_revenue(row: dict[str, Any]) -> bool:
    return not is_empty_value(_crawl(row).get("revenue"))


def has_offices(row: dict[str, Any]) -> bool:
    crawl = _crawl(row)
    for key in ("offices", "manufacturing_locations"):
        val = norm(crawl.get(key))
        if val and is_plausible_location(val, allow_country_only=False):
            return True
    return False


def has_linkedin(row: dict[str, Any]) -> bool:
    crawl = _crawl(row)
    for key in ("linkedin",):
        val = norm(crawl.get(key) or row.get(key))
        if val and "linkedin.com" in val.lower():
            return True
    raw = row.get("_crawl_raw") or {}
    contact = (raw.get("data") or {}).get("contact") or {}
    val = norm(contact.get("linkedin"))
    return bool(val and "linkedin.com" in val.lower())


def has_email(row: dict[str, Any]) -> bool:
    val = norm(_crawl(row).get("email"))
    return bool(val and "@" in val and not is_empty_value(val))


def has_phone(row: dict[str, Any]) -> bool:
    val = norm(_crawl(row).get("phone"))
    digits = re.sub(r"\D", "", val)
    return len(digits) >= 8


def has_contact_person(row: dict[str, Any]) -> bool:
    val = norm(_crawl(row).get("contact_person"))
    return bool(val and len(val) >= 3 and not is_empty_value(val))


def has_core_categories(row: dict[str, Any]) -> bool:
    val = norm(_crawl(row).get("core_categories") or row.get("key_products"))
    return bool(val and len(val) >= 3 and not is_empty_value(val))


def has_specialty_focus(row: dict[str, Any]) -> bool:
    val = norm(_crawl(row).get("specialty_focus"))
    if not val or is_empty_value(val):
        return False
    # Placeholder defaults from export are not "filled"
    low = val.lower()
    if low in {"industry manufacturer", "service provider", "distributor"}:
        return False
    return len(val) >= 3


def has_key_brands(row: dict[str, Any]) -> bool:
    val = norm(_crawl(row).get("key_brands_represented"))
    return bool(val and len(val) >= 2 and not is_empty_value(val))


def has_ownership(row: dict[str, Any]) -> bool:
    val = norm(_crawl(row).get("ownership"))
    return bool(val and len(val) >= 3 and not is_empty_value(val))


def has_distribution_type(row: dict[str, Any]) -> bool:
    val = norm(_crawl(row).get("distribution_type"))
    return bool(val and len(val) >= 3 and not is_empty_value(val))


def has_retail_ecommerce(row: dict[str, Any]) -> bool:
    val = norm(_crawl(row).get("retail_ecommerce"))
    return bool(val and len(val) >= 2 and not is_empty_value(val))


def has_regions_served(row: dict[str, Any]) -> bool:
    val = norm(_crawl(row).get("regions_served"))
    return bool(val and len(val) >= 2 and not is_empty_value(val))


def has_summary(row: dict[str, Any]) -> bool:
    val = norm(_crawl(row).get("summary"))
    if not val or is_empty_value(val):
        return False
    # Generic boilerplate summaries do not count as filled
    low = val.lower()
    if "channel company for this market" in low and "details filled via" in low:
        return False
    return len(val) >= 20


def has_website(row: dict[str, Any]) -> bool:
    val = norm(_crawl(row).get("website") or row.get("website") or row.get("domain"))
    return bool(val and ("." in val) and not is_empty_value(val))


def normalize_turnover_range(value: Any) -> str:
    """Convert a single revenue figure into a range band.

    Examples:
      $100M  → $80–100M
      50 million USD → $40–50M
      $1.2B → $960M–1.2B (or $0.96–1.2B)
      already '$80–100M' → kept
    """
    raw = norm(value)
    if not raw or is_empty_value(raw):
        return ""
    # Already a range
    if re.search(r"\d[\d,.]*.{0,8}(?:–|-|to)\s*\d", raw, re.I):
        return raw

    text = raw.replace(",", "").strip()
    m = re.search(
        r"(?P<sym>\$|USD|US\$|€|£)?\s*(?P<num>\d+(?:\.\d+)?)\s*(?P<unit>billion|million|bn|m|k|b)?",
        text,
        re.I,
    )
    if not m:
        return raw

    num = float(m.group("num"))
    unit_raw = (m.group("unit") or "").lower()
    sym = (m.group("sym") or "$").upper().replace("US$", "$").replace("USD", "$")
    if sym not in {"$", "€", "£"}:
        sym = "$"

    mult = 1.0
    unit_label = "M"
    if unit_raw in ("billion", "bn", "b"):
        mult = 1000.0  # work in millions
        unit_label = "B"
        # keep num in billions for display if >= 1B
    elif unit_raw in ("million", "m"):
        mult = 1.0
        unit_label = "M"
    elif unit_raw in ("k",):
        # express as millions if large, else keep K
        if num >= 1000:
            num = num / 1000.0
            unit_label = "M"
        else:
            unit_label = "K"
    else:
        # bare number — assume millions if >= 1 and looks like revenue
        unit_label = "M"

    # Convert to a common "millions" scale for banding when unit is B
    if unit_label == "B":
        high = num
        low = num * 0.8
        def _fmt(x: float) -> str:
            if x >= 10:
                return f"{x:.0f}"
            if x >= 1:
                return f"{x:.1f}".rstrip("0").rstrip(".")
            return f"{x:.2f}".rstrip("0").rstrip(".")
        return f"{sym}{_fmt(low)}–{_fmt(high)}B"

    if unit_label == "K":
        high = num
        low = num * 0.8
        return f"{sym}{low:.0f}–{high:.0f}K"

    # Millions: user wants e.g. 100M → 80–100
    high = num
    low = num * 0.8

    def _fmt_m(x: float) -> str:
        if abs(x - round(x)) < 0.05:
            return str(int(round(x)))
        return f"{x:.1f}".rstrip("0").rstrip(".")

    return f"{sym}{_fmt_m(low)}–{_fmt_m(high)}M"


CONTACT_SOURCES = frozenset({"contact_page", "leadership"})


def uses_contact_sources(sources: tuple[str, ...] | None) -> bool:
    return bool(sources and CONTACT_SOURCES.intersection(sources))


def missing_contact_fields(row: dict[str, Any]) -> list[str]:
    gaps: list[str] = []
    if not has_email(row):
        gaps.append("email")
    if not has_phone(row):
        gaps.append("phone")
    if not has_contact_person(row):
        gaps.append("contact_person")
    return gaps


def missing_fields(row: dict[str, Any]) -> list[str]:
    gaps: list[str] = []
    if not has_headquarters(row):
        gaps.append("headquarters")
    if not has_founded(row):
        gaps.append("founded_year")
    if not has_employees(row):
        gaps.append("employee_count")
    if not has_ownership(row):
        gaps.append("ownership")
    if not has_revenue(row):
        gaps.append("revenue")
    if not has_offices(row):
        gaps.append("offices")
    if not has_regions_served(row):
        gaps.append("regions_served")
    if not has_website(row):
        gaps.append("website")
    if not has_linkedin(row):
        gaps.append("linkedin")
    if not has_core_categories(row):
        gaps.append("core_categories")
    if not has_specialty_focus(row):
        gaps.append("specialty_focus")
    if not has_key_brands(row):
        gaps.append("key_brands_represented")
    if not has_distribution_type(row):
        gaps.append("distribution_type")
    if not has_retail_ecommerce(row):
        gaps.append("retail_ecommerce")
    if not has_contact_person(row):
        gaps.append("contact_person")
    if not norm(_crawl(row).get("contact_role")):
        gaps.append("contact_role")
    if not has_email(row):
        gaps.append("email")
    if not has_phone(row):
        gaps.append("phone")
    if not has_summary(row):
        gaps.append("summary")
    return gaps


def row_has_gaps(row: dict[str, Any], *, sources: tuple[str, ...] | None = None) -> bool:
    gaps = list(missing_fields(row))
    if uses_contact_sources(sources):
        for field in missing_contact_fields(row):
            if field not in gaps:
                gaps.append(field)
    return bool(gaps)


def sync_crawl_from_raw(row: dict[str, Any]) -> None:
    snap = crawl_snapshot(row.get("_crawl_raw"))
    row["_crawl"] = {**snap, **{k: v for k, v in (_crawl(row)).items() if v}}


def _accept_sensitive_fact(
    row: dict[str, Any],
    crawl: dict[str, Any],
    *,
    field: str,
    value: Any,
    source: str,
    evidence_text: str,
    force_commit: bool,
) -> bool:
    """Decide whether to commit a Founded/HQ/Employees value now (vs buffer)."""
    if force_commit or source in HIGH_TRUST_SOURCES or source == "consensus":
        return True
    if not _consensus_enabled():
        return True

    company = norm(row.get("company") or row.get("brand"))
    domain = domain_from_row(row)

    if evidence_text:
        if not identity_text_matches(company, domain, evidence_text):
            return False  # wrong-company contamination
        return True  # identity confirmed in evidence

    if not domain:
        # No domain yet — allow (early pipeline / unit tests); year/HQ validators still apply
        return True

    # Domain known but no evidence → require 2-source consensus
    reached = _buffer_fact_candidate(crawl, field, value, source)
    row["_crawl"] = crawl
    return reached


def merge_extracted(
    row: dict[str, Any],
    extracted: dict[str, Any],
    *,
    source: str,
    evidence_text: str = "",
    force_commit: bool = False,
) -> list[str]:
    """Merge LLM/search extracted fields into row (gap-fill only). Returns field names updated."""
    if not extracted:
        return []
    crawl = dict(_crawl(row))
    updates: list[str] = []

    hq = norm(extracted.get("headquarters"))
    if hq and not has_headquarters(row):
        from vendor_intel.enrichment.hq_city_country import is_city_country, normalize_city_country

        hq_norm = normalize_city_country(hq) or (hq if is_city_country(hq) else "")
        if hq_norm and is_plausible_location(hq_norm, allow_country_only=False):
            if _accept_sensitive_fact(
                row,
                crawl,
                field="headquarters",
                value=hq_norm,
                source=source,
                evidence_text=evidence_text,
                force_commit=force_commit,
            ):
                crawl["headquarters"] = hq_norm
                updates.append("headquarters")

    from vendor_intel.enrichment.known_founded import (
        looks_cross_contaminated,
        resolve_known_founded,
    )

    company_name = str(
        row.get("company") or row.get("brand") or row.get("Company") or ""
    ).strip()
    known_year = resolve_known_founded(company_name)
    if known_year is not None:
        cur = plausible_founded_year(crawl.get("founded_year"))
        if cur != known_year:
            crawl["founded_year"] = known_year
            updates.append("founded_year")
    else:
        founded = extracted.get("founded_year")
        if founded and not has_founded(row):
            year = plausible_founded_year(founded)
            if (
                year is not None
                and not looks_cross_contaminated(company_name, year)
                and _accept_sensitive_fact(
                    row,
                    crawl,
                    field="founded_year",
                    value=year,
                    source=source,
                    evidence_text=evidence_text,
                    force_commit=force_commit,
                )
            ):
                crawl["founded_year"] = year
                updates.append("founded_year")

    emp = norm(extracted.get("employee_count"))
    if emp and not is_empty_value(emp) and not has_employees(row):
        if _accept_sensitive_fact(
            row,
            crawl,
            field="employee_count",
            value=emp,
            source=source,
            evidence_text=evidence_text,
            force_commit=force_commit,
        ):
            crawl["employee_count"] = emp
            updates.append("employee_count")

    ownership = norm(extracted.get("ownership"))
    if ownership and not has_ownership(row):
        crawl["ownership"] = ownership
        updates.append("ownership")

    rev = norm(extracted.get("revenue") or extracted.get("turnover"))
    if rev and not is_empty_value(rev) and not has_revenue(row):
        crawl["revenue"] = normalize_turnover_range(rev) or rev
        updates.append("revenue")

    offices = norm(extracted.get("offices") or extracted.get("cities_regions"))
    if offices and not has_offices(row) and is_plausible_location(offices, allow_country_only=False):
        crawl["offices"] = offices
        updates.append("offices")

    regions = norm(extracted.get("regions_served") or extracted.get("continent_geography"))
    if regions and not has_regions_served(row):
        crawl["regions_served"] = regions
        updates.append("regions_served")

    website = norm(extracted.get("website") or extracted.get("official_website"))
    if website and not has_website(row) and "." in website:
        if not website.startswith("http"):
            website = "https://" + website.lstrip("/")
        crawl["website"] = website
        if not norm(row.get("website")):
            row["website"] = website
        updates.append("website")

    linkedin = norm(extracted.get("linkedin_url") or extracted.get("linkedin"))
    if linkedin and not has_linkedin(row) and "linkedin.com" in linkedin.lower():
        if not linkedin.startswith("http"):
            linkedin = "https://" + linkedin.lstrip("/")
        crawl["linkedin"] = linkedin
        row["linkedin"] = linkedin
        updates.append("linkedin")

    core = norm(extracted.get("core_categories") or extracted.get("products"))
    if core and not has_core_categories(row):
        crawl["core_categories"] = core
        updates.append("core_categories")

    specialty = norm(extracted.get("specialty_focus"))
    if specialty and not has_specialty_focus(row):
        crawl["specialty_focus"] = specialty
        updates.append("specialty_focus")

    brands = norm(
        extracted.get("key_brands_represented")
        or extracted.get("key_brands")
        or extracted.get("brands")
    )
    if brands and not has_key_brands(row):
        crawl["key_brands_represented"] = brands
        updates.append("key_brands_represented")

    dist = norm(extracted.get("distribution_type") or extracted.get("business_type"))
    if dist and not has_distribution_type(row):
        crawl["distribution_type"] = dist
        updates.append("distribution_type")

    retail = norm(
        extracted.get("retail_ecommerce")
        or extracted.get("retail_e_commerce")
        or extracted.get("retail")
    )
    if retail and not has_retail_ecommerce(row):
        crawl["retail_ecommerce"] = retail
        updates.append("retail_ecommerce")

    person = norm(extracted.get("contact_person"))
    if person and len(person) >= 3 and not has_contact_person(row):
        crawl["contact_person"] = person
        updates.append("contact_person")

    role = norm(extracted.get("contact_role") or extracted.get("role"))
    if role and not norm(crawl.get("contact_role")):
        crawl["contact_role"] = role
        updates.append("contact_role")

    email = norm(extracted.get("email"))
    if email and "@" in email and not has_email(row):
        crawl["email"] = email
        updates.append("email")

    phone = norm(extracted.get("phone") or extracted.get("office_no"))
    if phone and not has_phone(row):
        digits = re.sub(r"\D", "", phone)
        if len(digits) >= 8:
            crawl["phone"] = phone
            updates.append("phone")

    summary = norm(extracted.get("summary") or extracted.get("company_summary"))
    if summary and not has_summary(row) and len(summary) >= 20:
        crawl["summary"] = summary
        updates.append("summary")

    # Persist candidate buffer even when nothing committed yet
    if crawl.get("_fact_candidates") and not updates:
        row["_crawl"] = {**_crawl(row), "_fact_candidates": crawl["_fact_candidates"]}
        return []

    if not updates:
        return []

    # Keep any pending candidates that weren't promoted
    if crawl.get("_fact_candidates"):
        pass
    row["_crawl"] = crawl
    raw = dict(row.get("_crawl_raw") or {})
    data = dict(raw.get("data") or {})
    company = dict(data.get("company") or {})
    location = dict(data.get("location") or {})
    financials = dict(data.get("financials") or {})
    contact = dict(data.get("contact") or {})
    people = dict(data.get("people") or {}) if isinstance(data.get("people"), dict) else {}

    if "headquarters" in updates:
        location["headquarters"] = crawl["headquarters"]
    if "founded_year" in updates:
        company["founded_year"] = crawl["founded_year"]
    if "employee_count" in updates:
        financials["employee_count"] = crawl["employee_count"]
    if "revenue" in updates:
        financials["revenue"] = crawl["revenue"]
    if "offices" in updates:
        loc_off = location.get("offices")
        if isinstance(loc_off, list):
            loc_off = list(loc_off)
        elif loc_off:
            loc_off = [str(loc_off)]
        else:
            loc_off = []
        for part in crawl["offices"].split(","):
            p = part.strip()
            if p and p not in loc_off:
                loc_off.append(p)
        location["offices"] = loc_off
    if "linkedin" in updates:
        contact["linkedin"] = crawl["linkedin"]
    if "core_categories" in updates:
        company["core_categories"] = crawl["core_categories"]
        company["products"] = crawl["core_categories"]
    if "specialty_focus" in updates:
        company["specialty_focus"] = crawl["specialty_focus"]
    if "key_brands_represented" in updates:
        company["key_brands_represented"] = crawl["key_brands_represented"]
    if "contact_person" in updates or "contact_role" in updates:
        leadership = list(people.get("leadership") or [])
        if not isinstance(leadership, list):
            leadership = []
        entry = {
            "name": crawl.get("contact_person") or "",
            "title": crawl.get("contact_role") or "",
        }
        if entry["name"] and not any(
            isinstance(p, dict) and norm(p.get("name")).lower() == entry["name"].lower()
            for p in leadership
        ):
            leadership.insert(0, entry)
        people["leadership"] = leadership
        contact["name"] = crawl.get("contact_person") or contact.get("name") or ""

    data["company"] = company
    data["location"] = location
    data["financials"] = financials
    data["contact"] = contact
    data["people"] = people
    raw["data"] = data
    row["_crawl_raw"] = raw

    src = str(row.get("enrichment_source") or "")
    if source and source not in src:
        row["enrichment_source"] = f"{src}+{source}".strip("+")

    sync_crawl_from_raw(row)
    return updates


def merge_contact_extracted(row: dict[str, Any], extracted: dict[str, Any], *, source: str) -> list[str]:
    """Merge contact / leadership fields (gap-fill only)."""
    if not extracted:
        return []
    crawl = dict(_crawl(row))
    updates: list[str] = []

    email = norm(extracted.get("email"))
    if email and "@" in email and not has_email(row):
        crawl["email"] = email.lower()
        updates.append("email")

    phone = norm(extracted.get("phone"))
    if phone and len(re.sub(r"\D", "", phone)) >= 8 and not has_phone(row):
        crawl["phone"] = phone
        updates.append("phone")

    person = norm(extracted.get("contact_person"))
    if person and len(person) >= 3 and not has_contact_person(row):
        crawl["contact_person"] = person
        updates.append("contact_person")

    role = norm(extracted.get("contact_role"))
    if role and not norm(crawl.get("contact_role")):
        crawl["contact_role"] = role
        updates.append("contact_role")

    addr = norm(extracted.get("contact_address"))
    if addr and not norm(crawl.get("contact_address")) and is_plausible_location(addr, allow_country_only=True):
        crawl["contact_address"] = addr
        updates.append("contact_address")

    for url_key in ("contact_source_url", "leadership_source_url"):
        url = norm(extracted.get(url_key))
        if url:
            crawl[url_key] = url

    if not updates:
        return []

    row["_crawl"] = crawl
    raw = dict(row.get("_crawl_raw") or {})
    data = dict(raw.get("data") or {})
    contact = dict(data.get("contact") or {})
    people = dict(data.get("people") or {}) if isinstance(data.get("people"), dict) else {}

    if "email" in updates:
        contact["email"] = crawl["email"]
    if "phone" in updates:
        contact["phone"] = crawl["phone"]
    if "contact_address" in updates:
        contact["address"] = crawl["contact_address"]
    if "contact_person" in updates or "contact_role" in updates:
        leadership = list(people.get("leadership") or [])
        if not isinstance(leadership, list):
            leadership = []
        entry = {
            "name": crawl.get("contact_person") or "",
            "title": crawl.get("contact_role") or "",
        }
        if entry["name"] and not any(
            isinstance(p, dict) and norm(p.get("name")).lower() == entry["name"].lower() for p in leadership
        ):
            leadership.insert(0, entry)
        people["leadership"] = leadership

    data["contact"] = contact
    data["people"] = people
    raw["data"] = data
    row["_crawl_raw"] = raw

    src = str(row.get("enrichment_source") or "")
    if source and source not in src:
        row["enrichment_source"] = f"{src}+{source}".strip("+")

    sync_crawl_from_raw(row)
    return updates


def is_apollo_protected_row(row: dict[str, Any], protected_keys: frozenset[str]) -> bool:
    """Row already filled by a prior Apollo enrich run — do not call Apollo again."""
    if company_key(row) in protected_keys:
        return True
    crawl = _crawl(row)
    if norm(crawl.get("apollo_person_id")):
        return True
    return False


def is_apollo_found_contact(row: dict[str, Any], cache_entry: dict[str, Any] | None = None) -> bool:
    """Row has a contact person that Apollo identified (this run or prior enrich)."""
    if not has_contact_person(row):
        return False
    crawl = _crawl(row)
    if norm(crawl.get("apollo_person_id")):
        return True
    if "apollo" in str(row.get("enrichment_source") or "").lower():
        return True
    cached = cache_entry if isinstance(cache_entry, dict) else {}
    if cached.get("contact_person") and not cached.get("error") and not cached.get("skipped"):
        return True
    return False


def needs_apollo_fields(row: dict[str, Any], fields: frozenset[str]) -> bool:
    if "contact_person" in fields and not has_contact_person(row):
        return True
    if "email" in fields and not has_email(row):
        return True
    if "linkedin" in fields and not has_linkedin(row):
        return True
    if "contact_role" in fields and is_empty_value(_crawl(row).get("contact_role")):
        return True
    if "phone" in fields and not has_phone(row):
        return True
    return False


def merge_apollo_contact(
    row: dict[str, Any],
    extracted: dict[str, Any],
    *,
    source: str = "apollo",
    name_only: bool = False,
    fill_empty_only: bool = True,
    fields: frozenset[str] | None = None,
) -> list[str]:
    """Merge Apollo contact data into a company row.

    When ``name_only=True``, only ``contact_person`` is written.
    ``fields`` limits which columns are written (e.g. contact_person + email + linkedin).
    When ``fill_empty_only=True`` (default), existing values are not overwritten.
    """
    if not extracted or extracted.get("error"):
        return []
    if fields is None:
        fields = frozenset({"contact_person"}) if name_only else frozenset(
            {"contact_person", "contact_role", "email", "linkedin", "phone"}
        )
    crawl = dict(_crawl(row))
    updates: list[str] = []
    existing_person = norm(crawl.get("contact_person"))

    if "contact_person" in fields:
        person = norm(extracted.get("contact_person"))
        allow_obfuscated = extracted.get("apollo_name_obfuscated") == "true"
        if person and len(person) >= 3 and (allow_obfuscated or "*" not in person):
            if fill_empty_only and has_contact_person(row):
                # Gap-fill: never downgrade full → partial; do upgrade partial → full.
                if "*" not in existing_person:
                    person = ""
                elif "*" in existing_person and "*" in person:
                    person = ""
            elif existing_person and "*" not in existing_person and "*" in person:
                person = ""
            if person:
                crawl["contact_person"] = person
                updates.append("contact_person")

    if name_only or fields == frozenset({"contact_person"}):
        if not updates:
            return []
        row["_crawl"] = crawl
        raw = dict(row.get("_crawl_raw") or {})
        data = dict(raw.get("data") or {})
        people = dict(data.get("people") or {}) if isinstance(data.get("people"), dict) else {}
        leadership = [
            {
                "name": crawl["contact_person"],
                "title": crawl.get("contact_role") or "",
                "source": source,
            }
        ]
        people["leadership"] = leadership
        people["primary_contact"] = leadership[0]
        data["people"] = people
        raw["data"] = data
        row["_crawl_raw"] = raw
        src = str(row.get("enrichment_source") or "")
        tag = source or "apollo"
        if tag not in src.split("+"):
            row["enrichment_source"] = f"{src}+{tag}".strip("+")
        sync_crawl_from_raw(row)
        return updates

    if "contact_role" in fields:
        role = norm(extracted.get("contact_role"))
        if role and (not fill_empty_only or is_empty_value(crawl.get("contact_role"))):
            crawl["contact_role"] = role
            updates.append("contact_role")

    if "linkedin" in fields:
        linkedin = norm(extracted.get("linkedin"))
        if linkedin and "linkedin.com" in linkedin.lower():
            if not fill_empty_only or not has_linkedin(row):
                if not linkedin.startswith("http"):
                    linkedin = "https://" + linkedin.lstrip("/")
                crawl["linkedin"] = linkedin
                row["linkedin"] = linkedin
                updates.append("linkedin")

    if "email" in fields:
        email = norm(extracted.get("email"))
        if email and "@" in email:
            if not fill_empty_only or not has_email(row):
                crawl["email"] = email.lower()
                updates.append("email")

    if "phone" in fields:
        phone = norm(extracted.get("phone"))
        if phone and len(re.sub(r"\D", "", phone)) >= 8:
            if not fill_empty_only or not has_phone(row):
                crawl["phone"] = phone
                updates.append("phone")

    apollo_id = norm(extracted.get("apollo_person_id"))
    if apollo_id:
        crawl["apollo_person_id"] = apollo_id
    apollo_url = norm(extracted.get("apollo_source_url"))
    if apollo_url:
        crawl["apollo_source_url"] = apollo_url
        crawl["contact_source_url"] = apollo_url

    if not updates:
        return []

    row["_crawl"] = crawl
    raw = dict(row.get("_crawl_raw") or {})
    data = dict(raw.get("data") or {})
    contact = dict(data.get("contact") or {})
    people = dict(data.get("people") or {}) if isinstance(data.get("people"), dict) else {}

    if "email" in updates:
        contact["email"] = crawl["email"]
    if "phone" in updates:
        contact["phone"] = crawl["phone"]
    if "linkedin" in updates:
        contact["linkedin"] = crawl["linkedin"]
    if "contact_person" in updates or "contact_role" in updates:
        leadership = [
            {
                "name": crawl.get("contact_person") or "",
                "title": crawl.get("contact_role") or "",
                "source": source,
            }
        ]
        people["leadership"] = leadership
        people["primary_contact"] = leadership[0]

    data["contact"] = contact
    data["people"] = people
    raw["data"] = data
    row["_crawl_raw"] = raw

    src = str(row.get("enrichment_source") or "")
    tag = source or "apollo"
    if tag not in src.split("+"):
        row["enrichment_source"] = f"{src}+{tag}".strip("+")

    sync_crawl_from_raw(row)
    return updates


def company_key(row: dict[str, Any]) -> str:
    return norm(row.get("company") or row.get("brand")).lower()


def domain_from_row(row: dict[str, Any]) -> str:
    raw = norm(row.get("domain") or row.get("website") or "")
    return raw.removeprefix("https://").removeprefix("http://").removeprefix("www.").split("/")[0]
