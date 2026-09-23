"""Steer discovery rounds toward regions the market has not covered yet.

Left alone, AI Mode answers "brands in this market" with the same handful of
countries every round — USA, UK, Germany, Japan. The exclusion list stops it
repeating individual NAMES, but not the geographic habit: round 8 returns the
fifth-largest German company while an entire Latin American or Southeast Asian
brand set is never mentioned.

This module closes that loop. After each round the HQ strings already
collected are folded into region counts, and the next round's prompt names the
regions with the least coverage. It is a NUDGE, not a filter: a genuinely
global market may legitimately concentrate in one region, so nothing here
rejects a company for being in a well-covered region.

    round 1  no steer, see where the market naturally sits
    round 2+ "prefer companies headquartered in: Latin America, Africa, ..."

Regions follow the nine in the pipeline spec.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

# The nine regions the pipeline reports against. Ordered so that the
# under-covered set reads predictably in a prompt.
REGIONS: tuple[str, ...] = (
    "North America",
    "Latin America",
    "Europe",
    "Middle East",
    "Africa",
    "South Asia",
    "East Asia",
    "Southeast Asia",
    "Oceania",
)

# Major manufacturing / commercial countries per region, in rough order of how
# likely a region's companies are to sit there.
#
# A region is one query for a whole continent: asked for companies in "Africa",
# the model names the two obvious South African firms and stops, and a Nigerian
# or Egyptian producer is never reached. Naming the country is a different,
# narrower question, and it is what surfaces the national players that the
# regional ask skips.
#
# Not exhaustive by design — these are the countries with enough industrial
# base to hold a market participant. The list is a search order, not a claim
# about where companies must be.
COUNTRIES_BY_REGION: dict[str, tuple[str, ...]] = {
    "North America": ("the United States", "Canada", "Mexico"),
    "Latin America": ("Brazil", "Mexico", "Argentina", "Chile", "Colombia", "Peru"),
    "Europe": (
        "Germany", "the United Kingdom", "France", "Italy", "Spain",
        "the Netherlands", "Switzerland", "Sweden", "Poland", "Belgium",
        "Austria", "Denmark", "Finland", "Norway", "Czechia", "Turkey",
        "Russia", "Portugal", "Ireland",
    ),
    "Middle East": (
        "the United Arab Emirates", "Saudi Arabia", "Israel", "Qatar",
        "Kuwait", "Oman", "Iran",
    ),
    "Africa": (
        "South Africa", "Egypt", "Nigeria", "Morocco", "Kenya", "Tunisia",
        "Algeria", "Ghana", "Ethiopia",
    ),
    "South Asia": ("India", "Pakistan", "Bangladesh", "Sri Lanka", "Nepal"),
    "East Asia": (
        "China", "Japan", "South Korea", "Taiwan", "Hong Kong", "Mongolia",
    ),
    "Southeast Asia": (
        "Singapore", "Malaysia", "Thailand", "Indonesia", "Vietnam",
        "the Philippines", "Cambodia",
    ),
    "Oceania": ("Australia", "New Zealand"),
}


def countries_for(region: str) -> list[str]:
    """Countries to ask about individually once `region` stops yielding."""
    return list(COUNTRIES_BY_REGION.get(region, ()))


def all_countries_by_coverage(rows: Any) -> list[str]:
    """Every country, ordered so the least-covered regions come first.

    Within a region the fixed order above is kept, so a run is reproducible.
    """
    out: list[str] = []
    for region in under_covered(rows, limit=len(REGIONS)):
        out.extend(countries_for(region))
    return out

# --- single-country runs ----------------------------------------------------
#
# A run scoped to one country cannot use the region -> country ladder: every
# company is in the same country, so "prefer under-covered regions" steers
# nothing and the country tier is a single ask. The equivalent narrowing is
# one level down -- the states and metros where industry actually sits.
#
# Ordered by industrial base, so the rounds that matter most run first. Metro
# names are included alongside their state because companies describe their
# own HQ either way ("Bengaluru" far more often than "Karnataka").
STATES_BY_COUNTRY: dict[str, tuple[str, ...]] = {
    "india": (
        "Maharashtra (Mumbai and Pune)",
        "Karnataka (Bengaluru)",
        "Tamil Nadu (Chennai and Coimbatore)",
        "Delhi NCR (New Delhi, Gurugram and Noida)",
        "Telangana (Hyderabad)",
        "Gujarat (Ahmedabad, Surat and Vadodara)",
        "Uttar Pradesh (Lucknow, Kanpur and Noida)",
        "Haryana (Gurugram and Faridabad)",
        "West Bengal (Kolkata)",
        "Kerala (Kochi and Thiruvananthapuram)",
        "Rajasthan (Jaipur)",
        "Andhra Pradesh (Visakhapatnam and Vijayawada)",
        "Madhya Pradesh (Indore and Bhopal)",
        "Punjab (Ludhiana and Mohali)",
        "Odisha (Bhubaneswar)",
        "Chandigarh and Himachal Pradesh",
        "Bihar and Jharkhand (Patna and Ranchi)",
        "Assam and the North-Eastern states (Guwahati)",
        "Uttarakhand (Dehradun and Haridwar)",
        "Chhattisgarh and Goa",
    ),
}


def states_for(country: str) -> list[str]:
    """Sub-national areas to sweep when a run is scoped to one country.

    Empty for a country with no list, which leaves the caller on the existing
    region/country ladder rather than inventing place names.
    """
    # removeprefix, not lstrip: lstrip("the ") strips those CHARACTERS, which
    # turned "thailand" into "ailand".
    key = " ".join(str(country or "").split()).strip().lower().removeprefix("the ").strip()
    return list(STATES_BY_COUNTRY.get(key, ()))


def is_single_country(country: str) -> bool:
    """True when a run targets one country rather than the whole world."""
    key = " ".join(str(country or "").split()).strip().lower()
    return bool(key) and key not in ("global", "worldwide", "world", "all")


# Country -> region. Only the countries that actually show up as company
# headquarters are listed; anything unrecognised counts as "unknown" and
# steers nothing, which is the safe direction.
_COUNTRY_REGION: dict[str, str] = {
    # North America
    "usa": "North America", "united states": "North America",
    "united states of america": "North America", "us": "North America",
    "u.s.": "North America", "u.s.a": "North America", "america": "North America",
    "canada": "North America", "mexico": "North America",
    # Latin America
    "brazil": "Latin America", "argentina": "Latin America",
    "chile": "Latin America", "colombia": "Latin America",
    "peru": "Latin America", "uruguay": "Latin America",
    "ecuador": "Latin America", "venezuela": "Latin America",
    "costa rica": "Latin America", "panama": "Latin America",
    "bolivia": "Latin America", "paraguay": "Latin America",
    "guatemala": "Latin America", "dominican republic": "Latin America",
    # Europe
    "united kingdom": "Europe", "uk": "Europe", "britain": "Europe",
    "great britain": "Europe", "england": "Europe", "scotland": "Europe",
    "ireland": "Europe", "germany": "Europe", "france": "Europe",
    "italy": "Europe", "spain": "Europe", "portugal": "Europe",
    "netherlands": "Europe", "the netherlands": "Europe", "belgium": "Europe",
    "switzerland": "Europe", "austria": "Europe", "sweden": "Europe",
    "norway": "Europe", "denmark": "Europe", "finland": "Europe",
    "iceland": "Europe", "poland": "Europe", "czech republic": "Europe",
    "czechia": "Europe", "slovakia": "Europe", "hungary": "Europe",
    "romania": "Europe", "bulgaria": "Europe", "greece": "Europe",
    "croatia": "Europe", "slovenia": "Europe", "serbia": "Europe",
    "estonia": "Europe", "latvia": "Europe", "lithuania": "Europe",
    "luxembourg": "Europe", "malta": "Europe", "cyprus": "Europe",
    "russia": "Europe", "ukraine": "Europe", "belarus": "Europe",
    "turkey": "Europe", "turkiye": "Europe",
    # Middle East
    "uae": "Middle East", "united arab emirates": "Middle East",
    "saudi arabia": "Middle East", "israel": "Middle East",
    "qatar": "Middle East", "kuwait": "Middle East", "bahrain": "Middle East",
    "oman": "Middle East", "jordan": "Middle East", "lebanon": "Middle East",
    "iran": "Middle East", "iraq": "Middle East",
    # Africa
    "south africa": "Africa", "nigeria": "Africa", "egypt": "Africa",
    "kenya": "Africa", "morocco": "Africa", "tunisia": "Africa",
    "algeria": "Africa", "ghana": "Africa", "ethiopia": "Africa",
    "tanzania": "Africa", "uganda": "Africa", "zimbabwe": "Africa",
    "botswana": "Africa", "namibia": "Africa", "senegal": "Africa",
    # South Asia
    "india": "South Asia", "pakistan": "South Asia",
    "bangladesh": "South Asia", "sri lanka": "South Asia",
    "nepal": "South Asia", "bhutan": "South Asia", "maldives": "South Asia",
    # East Asia
    "china": "East Asia", "prc": "East Asia",
    "people's republic of china": "East Asia",
    "japan": "East Asia", "south korea": "East Asia", "korea": "East Asia",
    "republic of korea": "East Asia", "north korea": "East Asia",
    "taiwan": "East Asia", "hong kong": "East Asia", "macau": "East Asia",
    "mongolia": "East Asia",
    # Southeast Asia
    "singapore": "Southeast Asia", "malaysia": "Southeast Asia",
    "thailand": "Southeast Asia", "indonesia": "Southeast Asia",
    "vietnam": "Southeast Asia", "viet nam": "Southeast Asia",
    "philippines": "Southeast Asia", "the philippines": "Southeast Asia",
    "myanmar": "Southeast Asia", "burma": "Southeast Asia",
    "cambodia": "Southeast Asia", "laos": "Southeast Asia",
    "brunei": "Southeast Asia",
    # Oceania
    "australia": "Oceania", "new zealand": "Oceania", "fiji": "Oceania",
    "papua new guinea": "Oceania",
}

# US state names appear as the middle element of "City, State, USA". They must
# never be read as a country, so the country lookup takes the LAST element.
_UNKNOWN = ""


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower()).strip(" .,")


def country_of(headquarters: str) -> str:
    """Country name from a "City, Country" / "City, State, USA" HQ string.

    The LAST comma-separated element is the country by convention, so a US
    state in the middle position is never mistaken for one.
    """
    parts = [p for p in (headquarters or "").split(",") if _norm(p)]
    if not parts:
        return _UNKNOWN
    return _norm(parts[-1])


def region_of(headquarters: str) -> str:
    """Region for an HQ string, or "" when the country is not recognised.

    Returning "" rather than guessing keeps an unknown HQ from skewing the
    coverage counts toward whichever region happened to be the default.
    """
    return _COUNTRY_REGION.get(country_of(headquarters), _UNKNOWN)


def coverage(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    """Companies found per region, every region present (zeroes included).

    The zeroes are the point: a region with no companies is exactly the one
    the next round should ask about, and it cannot be spotted in a dict that
    only holds what was found.
    """
    counts = {r: 0 for r in REGIONS}
    for row in rows:
        hq = str(row.get("headquarters") or row.get("hq_location") or "")
        region = region_of(hq)
        if region:
            counts[region] += 1
    return counts


def under_covered(rows: Iterable[dict[str, Any]], *, limit: int = 3) -> list[str]:
    """The `limit` regions with the fewest companies so far, fewest first.

    Ties break on the REGIONS order, so the steer is deterministic and a run
    is reproducible.
    """
    counts = coverage(rows)
    order = {name: i for i, name in enumerate(REGIONS)}
    ranked = sorted(REGIONS, key=lambda r: (counts[r], order[r]))
    return ranked[: max(0, limit)]


def rotation_hint(rows: Iterable[dict[str, Any]], *, limit: int = 3) -> str:
    """Prompt fragment steering a round toward under-covered regions.

    Empty string before anything has been found — round 1 should see where the
    market naturally sits rather than being pushed somewhere arbitrary.
    """
    rows = list(rows)
    if not rows:
        return ""
    regions = under_covered(rows, limit=limit)
    if not regions:
        return ""
    return (
        "GEOGRAPHIC COVERAGE: this market's companies so far are concentrated "
        "elsewhere. PREFER brands headquartered in: "
        + ", ".join(regions)
        + ". Only name a company that genuinely operates in this market — do "
        "NOT invent one to satisfy a region, and do not skip a major global "
        "brand just because its region is already covered."
    )
