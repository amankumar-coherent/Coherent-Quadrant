#!/usr/bin/env python3
"""Run Coherent Quadrant from a market-roles CSV (sectioned export).

Example:
  PYTHONPATH=src python scripts/run_quadrant_from_csv.py \\
    --csv smartphones_market_global.csv \\
    --industry "Smartphone Market" \\
    --country global \\
    --prefer-section "Smartphone Brands"
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def _domain_from_website(website: str) -> str:
    w = (website or "").strip()
    if not w:
        return ""
    if "://" not in w:
        w = "https://" + w
    try:
        host = (urlparse(w).hostname or "").lower()
    except Exception:
        host = ""
    return host.removeprefix("www.")


def _parse_sectioned_csv(path: Path) -> list[dict]:
    """Parse CMI market-roles CSV with `=== Section (N) ===` banners."""
    text = path.read_text(encoding="utf-8-sig")
    # Normalize possible multiline quoted fields via csv reader on lines without banners first
    section = "Unknown"
    rows: list[dict] = []
    header: list[str] | None = None

    # Rebuild a clean CSV stream: keep header once, drop banner lines
    buffer_lines: list[str] = []
    section_for_line: list[tuple[str, str]] = []  # (section, line) for data lines only

    for raw in text.splitlines():
        line = raw.rstrip("\n")
        if not line.strip():
            continue
        m = re.match(r"^===\s*(.+?)\s*(?:\((\d+)\))?\s*===\s*$", line.strip())
        if m:
            section = m.group(1).strip()
            continue
        if line.startswith("#,") or line.lower().startswith("company,"):
            if header is None:
                # strip leading "#" column name if present
                header = next(csv.reader([line.lstrip("#")]))
                if header and header[0] == "":
                    header[0] = "#"
            continue
        section_for_line.append((section, line))
        buffer_lines.append(line)

    if not header:
        raise SystemExit(f"No CSV header found in {path}")

    # Map header: expected Company,Brand,...,Summary
    # Some files start with "#,Company,..."
    norm_header = [h.strip() for h in header]
    if norm_header and norm_header[0] in ("#", ""):
        # keep index column
        pass

    for section_name, line in section_for_line:
        try:
            values = next(csv.reader([line]))
        except Exception:
            continue
        if len(values) < len(norm_header):
            values = values + [""] * (len(norm_header) - len(values))
        rec = dict(zip(norm_header, values[: len(norm_header)]))
        company = str(rec.get("Company") or "").strip()
        if not company or company.isdigit():
            continue
        brand = str(rec.get("Brand") or company).strip()
        website = str(rec.get("Website") or "").strip()
        summary = str(rec.get("Summary") or "").strip()
        functionality = str(rec.get("Functionality") or "").strip()
        geo = str(rec.get("Geography") or "global").strip()
        relevant = str(rec.get("Is_Relevant") or "yes").strip().lower() in (
            "yes",
            "y",
            "true",
            "1",
        )
        domain = _domain_from_website(website)
        rows.append(
            {
                "company": company,
                "brand": brand,
                "domain": domain,
                "website": website,
                "geography": geo,
                "is_relevant": relevant,
                "company_function": functionality,
                "summary": summary,
                "section": section_name,
                "parent_or_independent": str(rec.get("Parent_or_Independent") or "").strip(),
                "evidence_snapshot": {
                    "domain": domain,
                    "page_text": summary,
                    "data": {
                        "company": {"name": company, "brand": brand, "website": website},
                        "business": {"functionality": functionality, "section": section_name},
                        "intel": {"summary": summary},
                    },
                    "discovery_snippets": (
                        [{"title": brand or company, "url": website, "snippet": summary[:400]}]
                        if summary
                        else []
                    ),
                    "classify_summary": summary,
                    "company_function": functionality,
                },
            }
        )
    return rows


def _prefer_sections(rows: list[dict], prefer: list[str]) -> list[dict]:
    if not prefer:
        return rows
    prefer_l = [p.lower() for p in prefer]

    def score(r: dict) -> tuple:
        sec = str(r.get("section") or "").lower()
        hit = 0
        for i, p in enumerate(prefer_l):
            if p in sec:
                hit = len(prefer_l) - i
                break
        # OEM / brand sections get a quality boost for _pick_companies
        return (-hit, str(r.get("company") or "").lower())

    ranked = sorted(rows, key=score)
    for r in ranked:
        sec = str(r.get("section") or "").lower()
        boost = 0.5
        for i, p in enumerate(prefer_l):
            if p in sec:
                boost = 0.95 - i * 0.05
                break
        r["quality_score"] = boost
        r["confidence"] = boost
    return ranked


async def _amain(args: argparse.Namespace) -> int:
    from vendor_intel.config import Settings
    from vendor_intel.placeholders.load_keys import apply_env_overrides
    from vendor_intel.quadrant import synthesize_quadrant

    apply_env_overrides()
    settings = Settings.load()
    settings = settings.model_copy(
        update={
            "use_mock_data": False,
            "mock_mode": False,
            "quadrant_enabled": True,
            "quadrant_max_companies": int(args.max_companies),
        }
    )

    csv_path = Path(args.csv)
    if not csv_path.is_file():
        csv_path = ROOT / args.csv
    if not csv_path.is_file():
        raise SystemExit(f"CSV not found: {args.csv}")

    rows = _parse_sectioned_csv(csv_path)
    prefer = args.prefer_section or [
        "Smartphone Brands",
        "OEM",
        "Multi-Segment",
        "Original Design",
    ]
    rows = _prefer_sections(rows, prefer)
    relevant = [r for r in rows if r.get("is_relevant", True)]
    print(f"  [csv] parsed {len(rows)} rows ({len(relevant)} relevant) from {csv_path.name}", flush=True)
    for r in relevant[:15]:
        print(
            f"    - {r['brand'] or r['company']} [{r.get('section')}] q={r.get('quality_score')}",
            flush=True,
        )
    if len(relevant) > 15:
        print(f"    … +{len(relevant) - 15} more", flush=True)

    result = await synthesize_quadrant(
        relevant,
        query_context={"industry": args.industry, "country": args.country},
        scope={"market": args.industry, "geography": args.country},
        settings=settings,
        write_output=True,
    )
    out = result.get("output_path") or ""
    brands = result.get("brands") or []
    print("\n=== Quadrant complete ===", flush=True)
    print(f"  Brands scored: {len(brands)}", flush=True)
    print(f"  Output: {out}", flush=True)
    for b in brands:
        print(
            f"    {b.get('brand')}: X={b.get('execution')} Y={b.get('innovation')} "
            f"{b.get('quadrant')} {b.get('tier')} overall={b.get('overall')}",
            flush=True,
        )
    return 0 if out else 1


def main() -> None:
    p = argparse.ArgumentParser(description="Coherent Quadrant from market CSV")
    p.add_argument("--csv", required=True, help="Path to sectioned market CSV")
    p.add_argument("--industry", default="Smartphone Market", help="Market name")
    p.add_argument("--country", default="global", help="Geography")
    p.add_argument("--max-companies", type=int, default=12, help="Cap brands to score")
    p.add_argument(
        "--prefer-section",
        action="append",
        default=None,
        help="Prefer CSV section substring (repeatable). Default: Smartphone Brands / OEM / Multi-Segment",
    )
    args = p.parse_args()
    raise SystemExit(asyncio.run(_amain(args)))


if __name__ == "__main__":
    main()
