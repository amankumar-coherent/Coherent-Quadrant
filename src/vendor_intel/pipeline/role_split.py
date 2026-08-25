"""Normalize landscape Role to a single label: Brand | Marketer | Solution Provider.

Never leave combined \"Brand / Marketer\" in Company Details.
"""
from __future__ import annotations

import re
from typing import Any

# Specialty materials / base-film marketers (not finished-pack converters)
_PACKAGING_MARKETER_STEMS = (
    "honeywell",
    "aclar",
    "kuraray",
    "eval",
    "mitsubishi chemical",
    "mitsubishi gas chemical",
    "mitsubishi polyester film",
    "mitsui chemicals",
    "mylar specialty",
    "3m scotchpak",
    "scotchpak",
    "dupont tyvek",
    "tyvek",
    "soarus",
    "soarnol",
    "nippon gohsei",
    "cosmo films",
    "cosmo first",
    "polyplex",
    "taghleef",
    "jindal films",
    "jindal poly films",
    "innovia",
    "treofan",
    "ester industries",
    "ester filmtech",
    "thai film industries",
    "srf limited",
    "chiripal poly",
    "vacmet",
    "garware",
    "skc",
    "kolon industries",
    "hyosung chemical",
    "nan ya plastics",
    "shinkong",
    "far eastern new century",
    "formosa idemitsu",
    "toray advanced film",
    "toray industries",
    "toyobo",
    "unitika",
    "futamura",
    "okura industrial",
    "asahi kasei packaging",
    "celplast",
    "plastic suppliers",
    "danafilms",
    "polifilm",
    "folienwerk wolfen",
    "buergofol",
    "allvac folien",
    "wentus",
    "folien fischer",
    "rkw",
    "sigma stretch",
    "charter next generation",
    "max speciality films",
    "toppan speciality films",
    "vitopel",
    "biofilm",
    "kureha",
    "sumitomo bakelite",
    "flex middle east",
    "flex america",
    "flex films (usa)",
)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


def is_packaging_market(query: str) -> bool:
    q = _norm(query)
    return any(t in q for t in ("packaging", "flex pack", "flexible pack", "pouch"))


def classify_packaging_role(company: str, brand: str = "") -> str:
    """Brand = converter/film OEM; Marketer = specialty material / regional marketing arm."""
    blob = _norm(f"{brand} {company}")
    for stem in _PACKAGING_MARKETER_STEMS:
        if stem in blob:
            return "Marketer"
    return "Brand"


def normalize_role_label(
    role: str,
    *,
    query: str = "",
    company: str = "",
    brand: str = "",
) -> str:
    """Collapse combined / fuzzy roles into one allowed label."""
    r = _norm(role)
    if not r or r in {"brand / marketer", "brand/marketer", "brand and marketer"}:
        if is_packaging_market(query):
            return classify_packaging_role(company, brand)
        # Non-packaging consumer markets: default Brand when LLM left combined
        return "Brand"
    # Hardware player-type: pass the canonical role straight through — do not
    # collapse it to "Brand" (that used to silently discard the hardware→
    # Manufacturer market-type classification upstream).
    if r == "manufacturer" or r.startswith("manufacturer "):
        return "Manufacturer"
    # Software / service player-type: same pass-through for the other two
    # roles that classification can produce.
    if r == "service provider" or r.startswith("service provider"):
        return "Service Provider"
    if r == "system integrator" or r.startswith("system integrator"):
        return "System Integrator"
    if "solution provider" in r or r in {"solution developer", "technology provider"}:
        return "Solution Provider"
    if r == "brand" or r.startswith("brand "):
        return "Brand"
    if r == "marketer" or "marketer" in r:
        return "Marketer"
    if is_packaging_market(query):
        return classify_packaging_role(company, brand)
    return "Brand"


def refine_row_role(row: dict[str, Any], query: str) -> str:
    company = str(row.get("Company") or row.get("name") or "").strip()
    brand = str(row.get("Brand") or company).strip()
    raw = str(row.get("Distribution Type") or row.get("Role") or "").strip()
    role = normalize_role_label(raw, query=query, company=company, brand=brand)
    row["Distribution Type"] = role
    row["Role"] = role
    return role
