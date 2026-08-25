"""Expand market gate — drop wrong-industry / fake / R&D / regional-dupe / acquired shells.

Runs inside chatgpt_expand (after mid + final verify) so FINAL Excel never needs a
manual purge for the patterns caught here.

Enable: EXPAND_MARKET_GATE=1 (default on for chatgpt_expand).
Config: config/expand_market_gates.yaml
"""
from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_COUNTRY_REGION_TOKENS = (
    "australia",
    "india",
    "mexico",
    "canada",
    "chile",
    "brazil",
    "china",
    "japan",
    "korea",
    "taiwan",
    "singapore",
    "malaysia",
    "thailand",
    "indonesia",
    "vietnam",
    "philippines",
    "uae",
    "saudi",
    "egypt",
    "nigeria",
    "kenya",
    "south africa",
    "uk",
    "usa",
    "us",
    "germany",
    "france",
    "italy",
    "spain",
    "netherlands",
    "belgium",
    "sweden",
    "norway",
    "finland",
    "poland",
    "turkey",
    "israel",
    "latin america",
    "middle east",
    "apac",
    "emea",
    "nordics",
)

_ACQUIRED_SHELL = re.compile(
    r"\((?:now(?:\s+part\s+of)?|acquired by|merged into|subsidiary of)\s+[^)]+\)|"
    r"\(already listed\)",
    re.I,
)

_REGIONAL_SUFFIX = re.compile(
    r"""
    ^(?P<stem>.+?)
    (?:
        \s*[\(\-–—:,]\s*(?P<geo>[^)\-]{2,40})\)?\s*$
        |
        \s+(?P<geo2>australia|india|mexico|canada|chile|brazil|china|japan|
            korea|taiwan|singapore|malaysia|thailand|uae|egypt|kenya|
            nigeria|uk|usa|germany|france|italy|spain|israel)
        \s*$
    )
    """,
    re.I | re.X,
)


def gate_enabled() -> bool:
    return (os.getenv("EXPAND_MARKET_GATE") or "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


@lru_cache(maxsize=1)
def _load_profiles() -> list[dict[str, Any]]:
    path = _repo_root() / "config" / "expand_market_gates.yaml"
    if not path.is_file():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return []
    profiles = data.get("profiles") or []
    return [p for p in profiles if isinstance(p, dict)]


def _norm(s: str) -> str:
    s = str(s or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s


def _company_name(row: dict[str, Any]) -> str:
    for k in ("Company", "Brand", "name", "company"):
        v = str(row.get(k) or "").strip()
        if v:
            return v
    return ""


def profile_for_query(query: str) -> dict[str, Any]:
    q = _norm(query)
    profiles = _load_profiles()
    default: dict[str, Any] = {}
    for p in profiles:
        matches = p.get("match") or []
        if "*" in matches or "all" in [str(m).lower() for m in matches]:
            default = p
            continue
        for m in matches:
            if _norm(str(m)) and _norm(str(m)) in q:
                return p
    return default or (profiles[-1] if profiles else {})


def _is_geo_token(text: str) -> bool:
    t = _norm(text).strip("()[] .,")
    if not t:
        return False
    if t in _COUNTRY_REGION_TOKENS:
        return True
    for tok in _COUNTRY_REGION_TOKENS:
        if t == tok or t.startswith(tok + " ") or t.endswith(" " + tok):
            return True
    # "semiconductor r&d", "canadian operations", "middle east"
    if re.search(
        r"\b(operations|operation|r&d|rd|sales|office|branch|subsidiary|"
        r"region|regional|latam|apac|emea)\b",
        t,
    ):
        return True
    return False


def _stem_hit(name: str, stems: list[str]) -> str | None:
    n = _norm(name)
    for stem in sorted((str(s).strip().lower() for s in stems if s), key=len, reverse=True):
        if not stem:
            continue
        if n == stem or n.startswith(stem + " ") or n.startswith(stem + "(") or stem in n:
            # Avoid over-match short stems inside unrelated words
            if len(stem) < 4 and n != stem:
                continue
            return stem
    return None


def _regex_hit(name: str, patterns: list[str]) -> str | None:
    n = str(name or "")
    for pat in patterns or []:
        try:
            if re.search(str(pat), n, re.I):
                return str(pat)
        except re.error:
            continue
    return None


def _parse_regional(name: str) -> tuple[str, str] | None:
    """Return (parent_stem, geo) when name looks like a regional arm."""
    raw = str(name or "").strip()
    if not raw:
        return None
    # Explicit "(already listed)"
    if re.search(r"\(already listed\)", raw, re.I):
        stem = re.sub(r"\(already listed\)", "", raw, flags=re.I).strip()
        return (_norm(stem), "already_listed") if stem else None
    m = _REGIONAL_SUFFIX.match(raw)
    if not m:
        return None
    stem = (m.group("stem") or "").strip()
    geo = (m.group("geo") or m.group("geo2") or "").strip()
    if not stem or not geo or not _is_geo_token(geo):
        return None
    # Don't treat "GlobalFoundries" etc. as regional
    if len(stem) < 3:
        return None
    return _norm(stem), _norm(geo)


def classify_expand_row(
    row: dict[str, Any],
    query: str,
    *,
    profile: dict[str, Any] | None = None,
    kept_names: set[str] | None = None,
) -> tuple[bool, str]:
    """Return (keep, reason). reason empty when keep=True."""
    name = _company_name(row)
    if not name:
        return False, "empty_name"
    prof = profile if profile is not None else profile_for_query(query)
    n = _norm(name)

    # Acquired / "already listed" shells
    if _ACQUIRED_SHELL.search(name) or "(already listed)" in n:
        return False, "acquired_or_already_listed"

    hit = _stem_hit(name, list(prof.get("drop_name_stems") or []))
    if hit:
        return False, f"drop_stem:{hit}"

    rx = _regex_hit(name, list(prof.get("drop_name_regex") or []))
    if rx:
        return False, f"drop_regex:{rx[:60]}"

    # Generic country+market fake (any market): "Algeria Semiconductor"
    from vendor_intel.pipeline.ai_brand_discovery import is_market_geo_artifact

    if is_market_geo_artifact(name, query):
        return False, "geo_artifact"

    # Country + core market noun as entire name
    if re.match(
        r"^(algeria|egypt|egyptian|tunisia|morocco|moroccan|ethiopia|kenya|"
        r"nigeria|ghana|uganda|rwanda|sudan|libya|senegal|namibia|botswana|"
        r"zimbabwe|tanzania|south african?)\s+"
        r"(semiconductor|microelectronics|electronics|packaging|wearable|"
        r"medical|lng|glp|market)\b",
        n,
    ):
        return False, "country_market_placeholder"

    # Regional duplicate when parent already kept
    if prof.get("drop_regional_of_parent", True) and kept_names is not None:
        parsed = _parse_regional(name)
        if parsed:
            stem, geo = parsed
            parent_stems = [_norm(s) for s in (prof.get("regional_parent_stems") or []) if s]
            # Always drop if parent stem is configured OR parent name already in kept set
            parent_present = any(
                kn == stem or kn.startswith(stem + " ") or stem.startswith(kn)
                for kn in kept_names
            )
            configured = any(stem == ps or stem.startswith(ps + " ") or ps in stem for ps in parent_stems)
            if parent_present or configured:
                # If configured parent stem matches, drop regional even before parent seen
                # (parent may appear later — still drop regional arms)
                if configured or parent_present:
                    return False, f"regional_dupe:{stem}/{geo}"

    return True, ""


def filter_expand_market_rows(
    rows: list[dict[str, Any]],
    query: str,
    *,
    name_key_priority: tuple[str, ...] = ("Company", "Brand", "name", "company"),
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Filter landscape/verified rows. Returns (kept, dropped_with_reason)."""
    if not gate_enabled():
        return list(rows), []
    prof = profile_for_query(query)
    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    kept_names: set[str] = set()

    # First pass: non-regional hard drops; collect keepers
    pending_regional: list[dict[str, Any]] = []
    for row in rows:
        name = ""
        for k in name_key_priority:
            name = str(row.get(k) or "").strip()
            if name:
                break
        if not name:
            dropped.append({**row, "gate_reason": "empty_name", "company": name})
            continue
        # Defer regional decisions until we know parents
        if _parse_regional(name) and not _ACQUIRED_SHELL.search(name):
            # Still apply stem/regex first
            ok, reason = classify_expand_row(
                row, query, profile=prof, kept_names=None
            )
            # classify without kept_names still applies stems/regex/acquired;
            # regional check skipped when kept_names is None — handle below
            if not ok and not reason.startswith("regional"):
                dropped.append(
                    {
                        "company": name,
                        "reason": reason,
                        "gate_reason": reason,
                    }
                )
                continue
            pending_regional.append(row)
            continue
        ok, reason = classify_expand_row(row, query, profile=prof, kept_names=kept_names)
        if ok:
            kept.append(row)
            kept_names.add(_norm(name))
            # Also index plain stem without Inc/Ltd
            plain = re.sub(
                r"\b(inc|ltd|llc|gmbh|ag|sa|plc|co|corp|corporation|limited)\b\.?",
                "",
                _norm(name),
            )
            plain = re.sub(r"\s+", " ", plain).strip(" ,.")
            if plain:
                kept_names.add(plain)
        else:
            dropped.append({"company": name, "reason": reason, "gate_reason": reason})

    for row in pending_regional:
        name = _company_name(row)
        ok, reason = classify_expand_row(row, query, profile=prof, kept_names=kept_names)
        if ok:
            # Also drop if parent stem already kept
            parsed = _parse_regional(name)
            if parsed:
                stem, geo = parsed
                parent_stems = [_norm(s) for s in (prof.get("regional_parent_stems") or []) if s]
                if any(stem == ps or stem.startswith(ps) for ps in parent_stems):
                    if any(kn == stem or kn.startswith(stem) or stem.startswith(kn) for kn in kept_names):
                        dropped.append(
                            {
                                "company": name,
                                "reason": f"regional_dupe:{stem}/{geo}",
                                "gate_reason": f"regional_dupe:{stem}/{geo}",
                            }
                        )
                        continue
                    # Configured regional parent: drop even if parent not yet in list
                    dropped.append(
                        {
                            "company": name,
                            "reason": f"regional_arm:{stem}/{geo}",
                            "gate_reason": f"regional_arm:{stem}/{geo}",
                        }
                    )
                    continue
            kept.append(row)
            kept_names.add(_norm(name))
        else:
            dropped.append({"company": name, "reason": reason, "gate_reason": reason})

    return kept, dropped
