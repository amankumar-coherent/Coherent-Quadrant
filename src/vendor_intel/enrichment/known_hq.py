"""Headquarters sanitizer — enforce City, Country for Found in / Headquarters.

Uses known map (no network). Wikipedia resolve runs in the expand Found-in
enrichment step (``enrich_rows_city_country_hq``), not on every slim finalize.
"""
from __future__ import annotations

from typing import Any

from vendor_intel.enrichment.hq_city_country import (
    feature_enabled,
    is_city_country,
    lookup_known_hq,
    normalize_city_country,
)


def apply_known_hq_to_row(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    if not feature_enabled():
        return out
    name = str(out.get("Company") or out.get("Brand") or "").strip()
    current = str(out.get("Headquarters") or "").strip()
    if is_city_country(current):
        out["Headquarters"] = normalize_city_country(current) or current
        return out
    known = lookup_known_hq(name)
    if known:
        out["Headquarters"] = known
        return out
    # Country-only / discovery-geo pollution → clear so gap-fill / wiki step can refill
    if current and not is_city_country(current):
        out["Headquarters"] = ""
    return out
