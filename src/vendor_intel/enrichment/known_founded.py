"""Canonical founding years for major channel brands.

Why Excel had wrong Founded values:
  1) LLM/Google AI often returns *incorporation* year (Edmundson 1991) instead of
     business founding (1801).
  2) Batch fill cross-contaminates years across similar names (Rexel India got
     WESCO's 1922).
  3) Country subsidiaries get random local years instead of the parent group year.
  4) Off-by-a-few approximations (Blackwoods 1876 vs 1878).

This module overrides/fills Founded when the company name clearly matches a
known parent brand. Unknown companies are left unchanged (still require evidence).
"""
from __future__ import annotations

import re
from typing import Any

# Longest-stem-first matching. Year = public business founding (not IPO / re-incorporation).
# Special cases handled in resolve_known_founded().
_KNOWN_FOUNDED: list[tuple[str, int]] = [
    ("consolidated electrical distributors", 1957),
    ("city electrical factors", 1951),
    ("edmundson electrical", 1801),
    ("border states electric", 1952),
    ("acklands grainger", 1889),
    ("acklands-grainger", 1889),
    ("w w grainger", 1927),
    ("ww grainger", 1927),
    ("digi key electronics", 1972),
    ("digi-key electronics", 1972),
    ("digi key", 1972),
    ("digi-key", 1972),
    ("rs components", 1937),
    ("arrow electronics", 1935),
    ("cable wholesale", 1996),
    ("phoenix contact", 1923),  # group founding; local arms still OEM-filtered elsewhere
    ("wesco international", 1922),
    ("anixter", 1957),
    ("graybar electric", 1869),
    ("graybar", 1869),
    ("sonepar", 1969),
    ("rexel", 1967),
    ("wesco", 1922),
    ("fastenal", 1967),
    ("screwfix", 1979),
    ("grainger", 1927),
    ("farnell", 1939),
    ("element14", 1939),  # Farnell element14 brand / A.C. Farnell 1939
    ("avnet", 1921),
    ("blackwoods", 1878),
    ("wesfarmers industrial", 1914),
    ("wesfarmers", 1914),
    ("bunnings", 1886),
    ("al futtaim", 1939),
    ("al-futtaim", 1939),
    ("actom", 1903),
    ("apar industries", 1958),
    ("lawrence hanson", 1886),
    ("lawrence & hanson", 1886),
    ("l&h group", 1886),
    ("middy's electrical", 1928),
    ("middys electrical", 1928),
    ("corys electrical", 1920),
    ("capitol light", 1926),
    ("elektroland24", 2003),
    ("placemakers", 1981),
    ("plumb center", 1985),
    ("wolseley canada", 1958),
    ("wolseley uk", 1887),
    ("bunzl", 1854),
    ("wuerth", 1945),
    ("würth", 1945),
    ("khimji ramdas", 1870),
    ("juma al majid", 1950),
    ("easa saleh al gurg", 1960),
    ("al gurg group", 1960),
    ("bin dasmal", 1976),
    ("hussain ali alireza", 1906),
    ("haji husein alireza", 1906),
    ("haymans electrical", 1916),  # Metal Manufactures / MMEM parent
    ("awm electrical", 1916),
    ("tle electrical", 1916),
    ("litecor", 1985),
    ("laser electrical", 1983),
    ("weidmuller", 1850),
    ("weidmüller", 1850),
    ("guillevin", 1906),
    ("westburne", 1926),
    ("nedco", 1911),  # Northern Electric Distribution roots 1911 (Rexel Canada banner)
    ("wurth elektronik", 1989),  # distinct from Adolf Würth wholesale (1945)
    ("wuerth elektronik", 1989),
]

# Years that belong to a specific brand — used to detect cross-contamination.
_YEAR_OWNERS: dict[int, tuple[str, ...]] = {
    1922: ("wesco",),
    1967: ("rexel", "fastenal"),  # both legitimately 1967
    1969: ("sonepar",),
    1869: ("graybar",),
    1957: ("anixter", "consolidated electrical", "ced"),
    1937: ("rs components", "rs group"),
    1972: ("digi",),
}


def _norm_company(name: str) -> str:
    s = str(name or "").lower()
    # Fold common diacritics so Würth / Grosshandel match ASCII stems
    for src, dst in (
        ("ä", "a"),
        ("ö", "o"),
        ("ü", "u"),
        ("ß", "ss"),
        ("é", "e"),
        ("è", "e"),
        ("á", "a"),
        ("í", "i"),
        ("ó", "o"),
        ("ú", "u"),
        ("ñ", "n"),
    ):
        s = s.replace(src, dst)
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    s = re.sub(
        r"\b(co ltd|ltd|limited|pvt ltd|inc|corp|corporation|gmbh|ag|group|ulc|llc|"
        r"international|electronics|as distributor|as separate entity)\b",
        " ",
        s,
    )
    return re.sub(r"\s+", " ", s).strip()


def resolve_known_founded(company: str) -> int | None:
    """Return canonical founding year when company clearly matches a known brand."""
    raw = str(company or "").strip()
    if not raw:
        return None
    # Prefer local trading name before parenthetical owner, e.g.
    # "Guillevin (Sonepar Canada)" / "Westburne (Rexel Canada)"
    base = re.sub(r"\s*\([^)]*\)\s*$", "", raw).strip() or raw
    key = _norm_company(base)
    if not key:
        return None
    # Graybar Canada traces to Harris & Roome 1920 (not US 1869)
    if "graybar" in key and "canada" in key:
        return 1920
    # Prefer longest stem match (substring with word boundaries)
    best: tuple[int, int] | None = None  # (stem_len, year)
    padded = f" {key} "
    for stem, year in _KNOWN_FOUNDED:
        stem_n = _norm_company(stem)
        if not stem_n:
            continue
        if padded.find(f" {stem_n} ") >= 0 or key == stem_n or key.startswith(stem_n + " "):
            if best is None or len(stem_n) > best[0]:
                best = (len(stem_n), year)
    # Plain country subsidiaries with no local brand: "Rexel Norway" → Rexel 1967
    if best is None:
        key2 = _norm_company(raw)
        padded2 = f" {key2} "
        for stem, year in _KNOWN_FOUNDED:
            stem_n = _norm_company(stem)
            if not stem_n:
                continue
            if padded2.find(f" {stem_n} ") >= 0 or key2.startswith(stem_n + " "):
                if best is None or len(stem_n) > best[0]:
                    best = (len(stem_n), year)
    return best[1] if best else None


def looks_cross_contaminated(company: str, year: int) -> bool:
    """True when year is a famous brand year that does not match this company."""
    key = _norm_company(company)
    owners = _YEAR_OWNERS.get(int(year))
    if not owners:
        return False
    if any(o in key for o in owners):
        return False
    # Year is "owned" by another brand family and this company is also a known brand
    known = resolve_known_founded(company)
    if known is not None and known != year:
        return True
    # Rexel row with WESCO year, etc.
    if year == 1922 and "rexel" in key:
        return True
    if year == 1967 and "wesco" in key:
        return True
    if year == 1969 and "rexel" in key:
        return True
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
