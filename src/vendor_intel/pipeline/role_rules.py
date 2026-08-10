"""Canonical company roles, and which roles belong in a given market.

Three jobs, all driven by ``config/industry_role_rules.yaml``:

1. **Normalise.** The classifier returns free text, so one live run produced
   ``Distributor`` 26 times and ``distributor`` 3 times as separate roles, plus
   ``EPC Contractor`` / ``EPC / Engineering`` / ``Engineering firm`` for the same
   thing. Sections and counts silently fragment. Everything maps to one canonical
   set here.

2. **Rank.** A company that operates in several parts of the value chain — a brand
   that also manufactures — is the most strategically interesting row in the
   report and belongs at the top, not buried alphabetically in one section.

3. **Scope by industry.** A robotics report wants brands, not their contract
   manufacturers; a software report wants who builds the solution, not who resells
   it; an industrial market wants the whole chain. That judgement is per-market and
   lives in config, not in code.
"""
from __future__ import annotations

import functools
import re
from pathlib import Path
from typing import Any


def _config_path() -> Path:
    return Path(__file__).resolve().parents[3] / "config" / "industry_role_rules.yaml"


@functools.lru_cache(maxsize=1)
def load_rules() -> dict[str, Any]:
    """Load the rules file. A parse error is announced, never swallowed.

    Returning {} quietly on a bad file means every role passes through
    unnormalised and every industry filter silently allows everything — a single
    missing space after a YAML key disabled the whole feature with no signal.
    """
    try:
        import yaml

        return yaml.safe_load(_config_path().read_text(encoding="utf-8")) or {}
    except Exception as exc:
        print(
            f"  [roles] WARNING: {_config_path().name} could not be read ({exc}); "
            f"role normalisation and industry role filters are DISABLED",
            flush=True,
        )
        return {}


@functools.lru_cache(maxsize=1)
def _alias_index() -> list[tuple[str, str]]:
    """(alias, canonical) sorted longest-first so 'raw material supplier' beats 'supplier'."""
    pairs: list[tuple[str, str]] = []
    for canon, aliases in (load_rules().get("aliases") or {}).items():
        pairs.append((canon.lower(), canon))
        for a in aliases or []:
            pairs.append((str(a).lower(), canon))
    pairs.sort(key=lambda p: -len(p[0]))
    return pairs


def normalize_role(role: str) -> str:
    """Free-text role -> canonical role. Unknown text is title-cased, not discarded."""
    text = re.sub(r"\s+", " ", str(role or "").strip().lower())
    if not text:
        return ""
    for alias, canon in _alias_index():
        if text == alias:
            return canon
    for alias, canon in _alias_index():
        if re.search(rf"\b{re.escape(alias)}\b", text):
            return canon
    return str(role).strip().title()


def profile_for(market: str) -> dict[str, Any]:
    """The first profile whose `match` list hits this market text."""
    text = str(market or "").lower()
    default: dict[str, Any] = {}
    for prof in load_rules().get("profiles") or []:
        patterns = [str(m).lower() for m in (prof.get("match") or [])]
        if "*" in patterns:
            default = prof
            continue
        if any(p and p in text for p in patterns):
            return prof
    return default


def allowed_roles(market: str) -> set[str] | None:
    """Canonical roles allowed in this market, or None when everything is allowed."""
    keep = (profile_for(market) or {}).get("keep")
    if not keep or (isinstance(keep, str) and keep.lower() == "all"):
        return None
    return {normalize_role(r) for r in keep}


def roles_of(row: dict[str, Any]) -> list[str]:
    """Every canonical role this company plays, primary first.

    A multi-segment company carries one role per segment; the flat `role` field
    only ever holds one of them.
    """
    out: list[str] = []
    primary = normalize_role(row.get("role") or row.get("market_role") or "")
    if primary:
        out.append(primary)
    for seg in row.get("multi_segments") or []:
        r = normalize_role((seg or {}).get("role") or "")
        if r and r not in out:
            out.append(r)
    return out


def normalize_rows(rows: list[dict[str, Any]]) -> int:
    """Rewrite each row's role to its canonical form. Returns how many changed."""
    changed = 0
    for row in rows:
        before = str(row.get("role") or "")
        after = normalize_role(before)
        if after and after != before:
            row["role"] = after
            changed += 1
        for seg in row.get("multi_segments") or []:
            if isinstance(seg, dict) and seg.get("role"):
                seg["role"] = normalize_role(seg["role"])
        row["roles_all"] = roles_of(row)
    return changed


def filter_by_industry(
    rows: list[dict[str, Any]], market: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Drop rows whose roles are all out of scope for this market's profile.

    A company is kept if ANY of its roles is allowed — a brand that also
    manufactures stays in a brands-only report.
    """
    allowed = allowed_roles(market)
    if allowed is None:
        return list(rows), []
    kept, dropped = [], []
    for row in rows:
        roles = roles_of(row) or [""]
        if any(r in allowed for r in roles):
            kept.append(row)
        else:
            dropped.append({**row, "export_reject": f"role_not_in_scope:{roles[0] or 'unknown'}"})
    return kept, dropped


def canonicalize_sections(rows: list[dict[str, Any]]) -> int:
    """Collapse section names that differ only by case or spacing.

    A live run split one section into "Manufacturers of Rupture Discs" (42 rows)
    and "Manufacturers of rupture discs" (5) — two headings in the report for one
    thing. The most-used spelling wins, so the canonical form is the one the
    classifier actually settled on.
    """
    import collections

    counts: collections.Counter[str] = collections.Counter()
    for row in rows:
        name = str(row.get("value_chain_section") or "").strip()
        if name:
            counts[name] += 1
    canon: dict[str, str] = {}
    for name, n in counts.most_common():          # most frequent spelling first
        canon.setdefault(re.sub(r"\s+", " ", name.lower()), name)

    changed = 0
    for row in rows:
        name = str(row.get("value_chain_section") or "").strip()
        if not name:
            continue
        best = canon.get(re.sub(r"\s+", " ", name.lower()), name)
        if best != name:
            row["value_chain_section"] = best
            changed += 1
        for seg in row.get("multi_segments") or []:
            s = str((seg or {}).get("section") or "").strip()
            if s:
                seg["section"] = canon.get(re.sub(r"\s+", " ", s.lower()), s)
    return changed


def multi_role_rank(row: dict[str, Any]) -> tuple[int, int, str]:
    """Sort key putting the most cross-cutting companies first.

    Sorts by distinct roles desc, then segments desc, then name — so "brand AND
    manufacturer" outranks a single-role company, which is what makes a row
    strategically interesting.
    """
    roles = roles_of(row)
    segs = len(row.get("multi_segments") or [])
    return (-len(set(roles)), -segs, str(row.get("company") or "").lower())


def sort_multi_role_first(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=multi_role_rank)


def split_multi_role(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(multi_role, single_role). Multi = 2+ distinct roles or 2+ segments."""
    multi, single = [], []
    for row in rows:
        if len(set(roles_of(row))) >= 2 or len(row.get("multi_segments") or []) >= 2:
            multi.append(row)
        else:
            single.append(row)
    return sort_multi_role_first(multi), single
