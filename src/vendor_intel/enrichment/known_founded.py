"""Founded-year sanitising for landscape rows.

Only market-agnostic validation remains: a Founded value is kept when it is a
plausible year, otherwise it becomes "Not publicly disclosed". There is no
hardcoded per-company year table.
"""
from __future__ import annotations

from typing import Any

def resolve_known_founded(company: str) -> int | None:  # noqa: ARG001
    """No canonical per-company founding years.

    This used to hold a hardcoded table of ~70 electrical-distributor
    founding years (with loose stem matching) that overrode the scraped
    value in EVERY market -- e.g. "Arrow Energy" got Arrow Electronics' 1935.
    Founded now always comes from the row's own researched value.
    """
    return None


def looks_cross_contaminated(company: str, year: int) -> bool:  # noqa: ARG001
    """Kept for callers; there is no per-brand year ownership table any more."""
    return False


def sanitize_founded_value(company: str, founded: Any) -> str:
    """Return cleaned Founded cell value (YYYY or Not publicly disclosed or '')."""
    from vendor_intel.enrichment.gap_fill.gaps import plausible_founded_year

    known = resolve_known_founded(company)
    cand = plausible_founded_year(founded)
    raw = str(founded or "").strip()

    if known is not None:
        # Always prefer canonical for known brands (fixes incorporation / contamination)
        if cand is None or cand != known or looks_cross_contaminated(company, cand):
            return str(known)
        return str(known)

    if cand is None:
        if not raw or raw.lower() in {
            "n/a",
            "na",
            "npd",
            "unknown",
            "not publicly disclosed",
            "-",
        }:
            return "Not publicly disclosed" if raw else ""
        return "Not publicly disclosed"

    if looks_cross_contaminated(company, cand):
        return "Not publicly disclosed"
    return str(cand)


def apply_known_founded_to_row(row: dict[str, Any]) -> dict[str, Any]:
    """Mutate/return landscape row with sanitized Founded."""
    out = dict(row)
    name = str(out.get("Company") or out.get("company") or out.get("brand") or "")
    current = out.get("Founded") or out.get("founded_year") or ""
    fixed = sanitize_founded_value(name, current)
    if fixed:
        out["Founded"] = fixed
        crawl = out.get("_crawl") if isinstance(out.get("_crawl"), dict) else {}
        crawl = dict(crawl)
        y = None
        try:
            from vendor_intel.enrichment.gap_fill.gaps import plausible_founded_year

            y = plausible_founded_year(fixed)
        except Exception:
            y = None
        if y is not None:
            crawl["founded_year"] = y
            out["_crawl"] = crawl
    return out
