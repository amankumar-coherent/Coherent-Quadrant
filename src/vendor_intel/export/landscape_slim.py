"""Canonical landscape SLIM columns shared by run_batch + OpenAI expand.

Matches the curated 6-market Excel layout:
  Company → Website → Founded → Headquarters → Continent / Geography →
  Operational Presence → Ownership → Employees → Core Categories →
  Specialty Focus → Key Brands Represented → Retail / E-commerce / Both →
  Distribution Type → Contact Person → Role → Email → LinkedIn → Office No. →
  Country Code → Region Code → Summary

Contact fields stay empty when unknown (pipeline does not invent them).
Continent / Geography is formatted as REGION(Country[, Country…]).
"""
from __future__ import annotations

import re
from collections import OrderedDict

SLIM_COLUMNS: tuple[str, ...] = (
    "Company",
    "Website",
    "Founded",
    "Headquarters",
    "Continent / Geography",
    "Operational Presence",
    "Ownership",
    "Employees",
    "Core Categories",
    "Specialty Focus",
    "Key Brands Represented",
    "Retail / E-commerce / Both",
    "Distribution Type",
    "Contact Person",
    "Role",
    "Email",
    "LinkedIn",
    "Office No.",
    "Country Code",
    "Region Code",
    "Summary",
)

REGION_ORDER = ("NA", "EU", "ME", "AF", "LATAM", "APAC")

COUNTRY_ISO: dict[str, str] = {
    "united states": "US",
    "usa": "US",
    "u.s.": "US",
    "u.s.a.": "US",
    "canada": "CA",
    "mexico": "MX",
    "brazil": "BR",
    "brasil": "BR",
    "argentina": "AR",
    "chile": "CL",
    "colombia": "CO",
    "peru": "PE",
    "ecuador": "EC",
    "uruguay": "UY",
    "paraguay": "PY",
    "bolivia": "BO",
    "venezuela": "VE",
    "costa rica": "CR",
    "panama": "PA",
    "guatemala": "GT",
    "honduras": "HN",
    "el salvador": "SV",
    "nicaragua": "NI",
    "belize": "BZ",
    "cuba": "CU",
    "dominican republic": "DO",
    "jamaica": "JM",
    "puerto rico": "PR",
    "bermuda": "BM",
    "united kingdom": "GB",
    "uk": "GB",
    "england": "GB",
    "scotland": "GB",
    "wales": "GB",
    "ireland": "IE",
    "germany": "DE",
    "france": "FR",
    "italy": "IT",
    "spain": "ES",
    "netherlands": "NL",
    "holland": "NL",
    "belgium": "BE",
    "switzerland": "CH",
    "austria": "AT",
    "sweden": "SE",
    "norway": "NO",
    "denmark": "DK",
    "finland": "FI",
    "iceland": "IS",
    "poland": "PL",
    "portugal": "PT",
    "czech republic": "CZ",
    "czechia": "CZ",
    "hungary": "HU",
    "romania": "RO",
    "greece": "GR",
    "croatia": "HR",
    "slovenia": "SI",
    "slovakia": "SK",
    "serbia": "RS",
    "bulgaria": "BG",
    "estonia": "EE",
    "lithuania": "LT",
    "latvia": "LV",
    "luxembourg": "LU",
    "malta": "MT",
    "cyprus": "CY",
    "ukraine": "UA",
    "russia": "RU",
    "turkey": "TR",
    "türkiye": "TR",
    "turkiye": "TR",
    "united arab emirates": "AE",
    "uae": "AE",
    "saudi arabia": "SA",
    "qatar": "QA",
    "kuwait": "KW",
    "bahrain": "BH",
    "oman": "OM",
    "jordan": "JO",
    "lebanon": "LB",
    "israel": "IL",
    "iraq": "IQ",
    "iran": "IR",
    "syria": "SY",
    "egypt": "EG",
    "south africa": "ZA",
    "nigeria": "NG",
    "kenya": "KE",
    "morocco": "MA",
    "tunisia": "TN",
    "algeria": "DZ",
    "ghana": "GH",
    "tanzania": "TZ",
    "ethiopia": "ET",
    "uganda": "UG",
    "rwanda": "RW",
    "botswana": "BW",
    "namibia": "NA",
    "mauritius": "MU",
    "india": "IN",
    "china": "CN",
    "japan": "JP",
    "south korea": "KR",
    "korea": "KR",
    "singapore": "SG",
    "malaysia": "MY",
    "indonesia": "ID",
    "thailand": "TH",
    "vietnam": "VN",
    "philippines": "PH",
    "taiwan": "TW",
    "hong kong": "HK",
    "australia": "AU",
    "new zealand": "NZ",
    "pakistan": "PK",
    "bangladesh": "BD",
    "sri lanka": "LK",
    "nepal": "NP",
    "cambodia": "KH",
    "laos": "LA",
    "myanmar": "MM",
}

ISO_REGION: dict[str, str] = {}
for _iso in ("US", "CA", "BM"):
    ISO_REGION[_iso] = "NA"
for _iso in (
    "MX", "BR", "AR", "CL", "CO", "PE", "EC", "UY", "PY", "BO", "VE",
    "CR", "PA", "GT", "HN", "SV", "NI", "BZ", "CU", "DO", "JM", "PR",
):
    ISO_REGION[_iso] = "LATAM"
for _iso in (
    "GB", "IE", "DE", "FR", "IT", "ES", "NL", "BE", "CH", "AT", "SE", "NO",
    "DK", "FI", "IS", "PL", "PT", "CZ", "HU", "RO", "GR", "HR", "SI", "SK",
    "RS", "BG", "EE", "LT", "LV", "LU", "MT", "CY", "UA", "RU", "TR",
):
    ISO_REGION[_iso] = "EU"
for _iso in ("AE", "SA", "QA", "KW", "BH", "OM", "JO", "LB", "IL", "IQ", "IR", "SY"):
    ISO_REGION[_iso] = "ME"
for _iso in (
    "EG", "ZA", "NG", "KE", "MA", "TN", "DZ", "GH", "TZ", "ET", "UG", "RW",
    "BW", "NA", "MU",
):
    ISO_REGION[_iso] = "AF"
for _iso in (
    "IN", "CN", "JP", "KR", "SG", "MY", "ID", "TH", "VN", "PH", "TW", "HK",
    "AU", "NZ", "PK", "BD", "LK", "NP", "KH", "LA", "MM",
):
    ISO_REGION[_iso] = "APAC"

_DISPLAY = {
    "usa": "United States",
    "u.s.": "United States",
    "u.s.a.": "United States",
    "uk": "United Kingdom",
    "england": "United Kingdom",
    "scotland": "United Kingdom",
    "wales": "United Kingdom",
    "holland": "Netherlands",
    "korea": "South Korea",
    "uae": "United Arab Emirates",
    "brasil": "Brazil",
    "czechia": "Czech Republic",
    "türkiye": "Turkey",
    "turkiye": "Turkey",
}

_US_HINTS = (
    "california", "new york", "texas", "florida", "illinois", "washington",
    "massachusetts", "pennsylvania", "ohio", "colorado", "arizona", "nevada",
    "virginia", "michigan", "minnesota", "georgia", "new jersey", "seattle",
    "san francisco", "los angeles", "chicago", "boston", "miami", "irvine",
    "melville", "alpharetta", "bentonville",
)


def _norm(s: object) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


def country_display(name: str) -> str:
    k = _norm(name)
    if k in _DISPLAY:
        return _DISPLAY[k]
    s = str(name or "").strip()
    return s if s[:1].isupper() else s.title()


def hq_to_iso(hq: str) -> str:
    low = _norm(hq)
    if not low or low in {"npd", "n/a", "unknown", "global", "not publicly disclosed"}:
        return ""
    for name in sorted(COUNTRY_ISO.keys(), key=len, reverse=True):
        if re.search(rf"\b{re.escape(name)}\b", low):
            return COUNTRY_ISO[name]
    if any(h in low for h in _US_HINTS):
        return "US"
    if "dubai" in low or "abu dhabi" in low:
        return "AE"
    if "johannesburg" in low or "gauteng" in low:
        return "ZA"
    return ""


def iso_to_region(iso: str) -> str:
    return ISO_REGION.get(iso, "")


def country_to_region(country: str) -> str:
    iso = hq_to_iso(country) or COUNTRY_ISO.get(_norm(country), "")
    return iso_to_region(iso)


def parse_country_list(raw: object) -> list[str]:
    """Extract country names from free text / REGION(…) / semicolon lists."""
    s = str(raw or "").strip()
    if not s or s.lower() in {"npd", "n/a", "unknown", "global", "worldwide", "regional"}:
        return []
    out: list[str] = []
    seen: set[str] = set()

    for m in re.finditer(r"(NA|EU|ME|AF|LATAM|APAC)\(([^)]*)\)", s, flags=re.I):
        for part in re.split(r"[,;/|]", m.group(2)):
            c = country_display(part)
            k = _norm(c)
            if c and k not in seen:
                seen.add(k)
                out.append(c)
        s = s[: m.start()] + " " + s[m.end() :]

    for part in re.split(r"[,;/|]", s):
        part = part.strip().strip("'\"")
        if not part:
            continue
        if _norm(part) in {
            "global", "worldwide", "international", "europe", "asia", "africa",
            "middle east", "north america", "latin america", "apac", "emea", "latam",
        }:
            continue
        # Prefer known country tokens inside longer strings
        mapped_iso = hq_to_iso(part)
        if mapped_iso:
            c = iso_to_country_name(mapped_iso)
            k = _norm(c)
            if k not in seen:
                seen.add(k)
                out.append(c)
            continue
        c = country_display(part)
        k = _norm(c)
        if len(c) < 3 or k in seen:
            continue
        if country_to_region(c):
            seen.add(k)
            out.append(c)
    return out


def format_continent_geography(countries: list[str] | object) -> str:
    """APAC(India, Singapore); EU(Germany, France)"""
    if isinstance(countries, str):
        countries = parse_country_list(countries)
    groups: OrderedDict[str, list[str]] = OrderedDict()
    for c in countries or []:
        c = country_display(str(c))
        reg = country_to_region(c)
        if not reg:
            continue
        groups.setdefault(reg, [])
        if c not in groups[reg]:
            groups[reg].append(c)
    parts: list[str] = []
    for reg in REGION_ORDER:
        if reg in groups:
            parts.append(f"{reg}({', '.join(groups[reg])})")
    for reg, cs in groups.items():
        if reg not in REGION_ORDER:
            parts.append(f"{reg}({', '.join(cs)})")
    return "; ".join(parts)


def iso_to_country_name(iso: str) -> str:
    """Best display name for an ISO code."""
    preferred = {
        "US": "United States",
        "GB": "United Kingdom",
        "AE": "United Arab Emirates",
        "KR": "South Korea",
        "ZA": "South Africa",
        "CZ": "Czech Republic",
        "NL": "Netherlands",
    }
    if iso in preferred:
        return preferred[iso]
    for name, code in COUNTRY_ISO.items():
        if code == iso and len(name) >= 4:
            return country_display(name)
    return iso


def operational_presence_text(hq: str, op_raw: object = "", regions_hint: object = "") -> str:
    """Physical footprint countries (semicolon list). Always include HQ country."""
    countries = parse_country_list(op_raw)
    hint = parse_country_list(regions_hint)
    hq_iso = hq_to_iso(hq)
    hq_c = iso_to_country_name(hq_iso) if hq_iso else ""

    if not countries:
        if hint and len(hint) == 1:
            countries = list(hint)
        elif hq_c:
            countries = [hq_c]
        elif hint:
            countries = hint[:1]
        else:
            countries = []
    elif hq_c and _norm(hq_c) not in {_norm(x) for x in countries}:
        countries = [hq_c] + list(countries)

    seen: set[str] = set()
    out: list[str] = []
    for c in countries:
        k = _norm(c)
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(country_display(c))
    return "; ".join(out)


def retail_ecommerce_both(retail: object, ecommerce: object) -> str:
    def present(val: object) -> bool:
        s = _norm(val)
        if not s:
            return False
        if s in {"no", "n", "none", "n/a", "na", "nil", "-", "false", "0", "not applicable"}:
            return False
        if s.startswith("no ") or "not applicable" in s:
            return False
        return True

    r, e = present(retail), present(ecommerce)
    if r and e:
        return "Both"
    if r:
        return "Retail"
    if e:
        return "Ecommerce"
    return "No"


def country_and_region_codes(hq: str) -> tuple[str, str]:
    iso = hq_to_iso(hq)
    if not iso:
        return "", ""
    return iso, iso_to_region(iso)


def finalize_slim_row(row: dict[str, str]) -> dict[str, str]:
    """Normalize Continent/Geography, Operational Presence, Country/Region codes."""
    from vendor_intel.enrichment.known_channel_fields import apply_known_channel_fields_to_row
    from vendor_intel.enrichment.known_founded import apply_known_founded_to_row
    from vendor_intel.enrichment.known_hq import apply_known_hq_to_row
    from vendor_intel.enrichment.known_employees import sanitize_employees
    from vendor_intel.enrichment.known_ownership import sanitize_ownership

    out = apply_known_hq_to_row(apply_known_founded_to_row(dict(row)))
    name = str(out.get("Company") or "")
    out["Ownership"] = sanitize_ownership(name, out.get("Ownership"))
    out["Employees"] = sanitize_employees(name, out.get("Employees"))
    out = apply_known_channel_fields_to_row(out)
    hq = str(out.get("Headquarters") or "")
    geo_raw = out.get("Continent / Geography") or out.get("Regions Served") or ""
    op_raw = out.get("Operational Presence") or out.get("Cities / Regions") or ""

    countries = parse_country_list(geo_raw)
    if not countries:
        countries = parse_country_list(hq)
    out["Continent / Geography"] = format_continent_geography(countries) if countries else (
        format_continent_geography([iso_to_country_name(hq_to_iso(hq))]) if hq_to_iso(hq) else ""
    )

    out["Operational Presence"] = operational_presence_text(hq, op_raw, geo_raw)

    cc, rc = country_and_region_codes(hq)
    if cc:
        out["Country Code"] = cc
    if rc:
        out["Region Code"] = rc

    # Prefer Office No. over legacy phone column
    if not str(out.get("Office No.") or "").strip() and out.get("Phone / WhatsApp"):
        out["Office No."] = str(out.get("Phone / WhatsApp") or "").strip()

    # Retail combo from legacy columns if needed
    if not str(out.get("Retail / E-commerce / Both") or "").strip():
        out["Retail / E-commerce / Both"] = retail_ecommerce_both(
            out.get("Retail Chains"), out.get("E-commerce")
        )

    return out
