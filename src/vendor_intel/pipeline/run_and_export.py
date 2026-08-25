"""Seed / discovery-query helpers used by ChatGPT expand (slim copy)."""
from __future__ import annotations

import re
from pathlib import Path

from vendor_intel.config import _project_root


def slugify(query: str, country: str) -> str:
    text = f"{query}_{country}".lower()
    return "".join(c if c.isalnum() else "_" for c in text).strip("_")[:80]


_GENERIC_MARKET_TOKENS = frozenset(
    {
        "global",
        "world",
        "worldwide",
        "international",
        "market",
        "markets",
        "industry",
        "industries",
        "sector",
        "sectors",
        "report",
        "analysis",
        "outlook",
        "forecast",
        "size",
        "share",
        "growth",
        "trends",
        "the",
        "and",
        "for",
        "with",
    }
)


def _slug_tokens(text: str) -> set[str]:
    return {t for t in text.lower().split("_") if len(t) > 2}


def _distinctive_tokens(tokens: set[str]) -> set[str]:
    return {t for t in tokens if t not in _GENERIC_MARKET_TOKENS}


def _best_curated_file(run_slug: str, files: list[Path]) -> Path | None:
    run_distinct = _distinctive_tokens(_slug_tokens(run_slug))
    if not run_distinct:
        return None

    best_file: Path | None = None
    best_score = 0
    for f in files:
        f_distinct = _distinctive_tokens(_slug_tokens(f.stem))
        if not f_distinct:
            continue
        overlap = f_distinct & run_distinct
        if overlap != f_distinct:
            continue
        score = len(overlap)
        if score > best_score:
            best_file, best_score = f, score
    return best_file


def parse_sections(raw: str | None) -> list[str]:
    if not raw or not raw.strip():
        return []
    sep = ";" if ";" in raw else ","
    return [s.strip() for s in raw.split(sep) if s.strip()]


_SEED_DOMAIN_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?[a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)+/?$", re.I
)


def _looks_like_domain(s: str) -> bool:
    s = (s or "").strip()
    return bool(s) and " " not in s and bool(_SEED_DOMAIN_RE.match(s))


def _clean_domain(s: str) -> str:
    return (
        (s or "")
        .strip()
        .lower()
        .replace("https://", "")
        .replace("http://", "")
        .removeprefix("www.")
        .rstrip("/")
    )


def load_seeds_file(path: str | None) -> list[tuple[str, str | None, str | None]]:
    if not path or not path.strip():
        return []
    p = Path(path)
    if not p.exists():
        print(f"  WARNING: seeds file not found: {path}")
        return []
    rows: list[tuple[str, str | None, str | None]] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "|" in line:
            parts = [f.strip() for f in line.split("|")]
            name = parts[0]
            domain: str | None = None
            section: str | None = None
            for f in parts[1:]:
                if not f:
                    continue
                if domain is None and _looks_like_domain(f):
                    domain = _clean_domain(f)
                elif section is None:
                    section = f
            if name:
                rows.append((name, domain, section))
        else:
            for n in parse_sections(line):
                rows.append((n, None, None))
    return rows


def auto_seed_names(query: str, country: str) -> list[tuple[str, str | None, str | None]]:
    seeds_dir = _project_root() / "queries" / "seeds"
    if not seeds_dir.exists():
        return []
    best_file = _best_curated_file(
        slugify(query, country),
        list(seeds_dir.glob("*.txt")),
    )
    return load_seeds_file(str(best_file)) if best_file else []


def auto_discovery_queries(query: str, country: str) -> list[str]:
    qdir = _project_root() / "queries" / "discovery"
    if not qdir.exists():
        return []
    best_file = _best_curated_file(
        slugify(query, country),
        list(qdir.glob("*.txt")),
    )
    if not best_file:
        return []
    out: list[str] = []
    for line in best_file.read_text(encoding="utf-8").splitlines():
        s = line.split("#", 1)[0].strip()
        if s:
            out.append(s)
    return list(dict.fromkeys(out))
