"""Normalize landscape Role to a single label: Brand | Marketer | Solution Provider.

Never leave combined \"Brand / Marketer\" in Company Details.
"""
from __future__ import annotations

import re
from typing import Any


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


def normalize_role_label(
    role: str,
    *,
    query: str = "",
    company: str = "",
    brand: str = "",
) -> str:
    """Collapse combined / fuzzy roles into one allowed label.

    Uses the verifier's own role answer only -- the same rule for every
    market (no market-name branches or company tables). ``query``, ``company``
    and ``brand`` are kept for callers' signatures.
    """
    r = _norm(role)
    if not r or r in {"brand / marketer", "brand/marketer", "brand and marketer"}:
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
    return "Brand"


def refine_row_role(row: dict[str, Any], query: str) -> str:
    company = str(row.get("Company") or row.get("name") or "").strip()
    brand = str(row.get("Brand") or company).strip()
    raw = str(row.get("Distribution Type") or row.get("Role") or "").strip()
    role = normalize_role_label(raw, query=query, company=company, brand=brand)
    row["Distribution Type"] = role
    row["Role"] = role
    return role
