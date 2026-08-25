#!/usr/bin/env python3
"""Re-run Coherent Quadrant synthesis from a "chatgpt_expand" checkpoint JSON.

The chatgpt_expand discovery scripts (scripts/expand_*_to_200*.py) write a
checkpoint with their own row schema (Company/Summary/Specialty Focus/...)
and their own provisional X/Y/Overall estimate — that estimate is NOT the
same as the real Coherent Quadrant scoring in
src/vendor_intel/quadrant/synthesize.py (axis_define + LLM question scoring
+ matrix rollup). This script converts that checkpoint's company rows into
the shape synthesize_quadrant() expects and re-runs the REAL scoring
pipeline against them — including the value-chain operator filter — without
re-discovering companies or re-crawling the web.

Example (LNG market, using the checkpoint already on disk):
  $env:PYTHONPATH = "src"
  .venv\\Scripts\\python.exe scripts\\run_quadrant_from_chatgpt_checkpoint.py \\
    --checkpoint "output/chatgpt_expand/global_liquefied_natural_gas_market_global/chatgpt_checkpoint_batch_all.json" \\
    --industry "Global Liquefied Natural Gas Market" \\
    --country global \\
    --out-dir "output/chatgpt_expand/global_liquefied_natural_gas_market_global"
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def _underscore_slug(industry: str, country: str) -> str:
    """Match the output/chatgpt_expand/<slug>/ naming convention (underscores, geo suffix)."""
    import re as _re

    base = _re.sub(r"[^a-z0-9]+", "_", industry.lower()).strip("_")
    geo = _re.sub(r"[^a-z0-9]+", "_", (country or "global").lower()).strip("_")
    return f"{base}_{geo}"


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


def _rows_from_checkpoint(checkpoint: dict, *, source_key: str) -> list[dict]:
    """Convert xy_rows/final_kept records into synthesize_quadrant row shape."""
    records = list((checkpoint.get("data") or {}).get(source_key) or [])
    rows: list[dict] = []
    for rec in records:
        company = str(rec.get("Company") or "").strip()
        if not company:
            continue
        website = str(rec.get("Website") or "").strip()
        domain = _domain_from_website(website)
        summary = str(rec.get("Summary") or "").strip()
        specialty = str(rec.get("Specialty Focus") or "").strip()
        categories = str(rec.get("Core Categories") or "").strip()
        distribution_type = str(rec.get("Distribution Type") or "").strip()
        commercial_role = str(rec.get("commercial_role") or "Brand").strip()
        page_text = " ".join(t for t in (summary, specialty, categories) if t)
        rows.append(
            {
                "company": company,
                "brand": company,
                "domain": domain,
                "website": website,
                "geography": str(rec.get("Continent / Geography") or "global").strip(),
                "hq_location": str(rec.get("Headquarters") or "").strip(),
                "founded_location": str(rec.get("Headquarters") or "").strip(),
                "commercial_role": commercial_role or "Brand",
                "company_function": distribution_type,
                "summary": summary,
                "is_relevant": True,
                "evidence_snapshot": {
                    "domain": domain,
                    "page_text": page_text,
                    "data": {
                        "company": {"name": company, "brand": company, "website": website},
                        "business": {
                            "functionality": distribution_type,
                            "specialty_focus": specialty,
                            "core_categories": categories,
                        },
                        "intel": {"summary": summary},
                    },
                    "discovery_snippets": (
                        [{"title": company, "url": website, "snippet": (summary or specialty)[:400]}]
                        if (summary or specialty)
                        else []
                    ),
                    "classify_summary": summary,
                    "company_function": distribution_type,
                },
            }
        )
    return rows


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
            "quadrant_table_companies": int(args.table_companies),
        }
    )

    path = Path(args.checkpoint)
    if not path.is_file():
        path = ROOT / args.checkpoint
    if not path.is_file():
        raise SystemExit(f"Checkpoint not found: {args.checkpoint}")

    checkpoint = json.loads(path.read_text(encoding="utf-8"))
    rows = _rows_from_checkpoint(checkpoint, source_key=args.source_key)
    if not rows:
        raise SystemExit(f"No usable rows under data.{args.source_key} in {path.name}")

    print(f"  [checkpoint] {path.name}: {len(rows)} companies from data.{args.source_key}", flush=True)

    result = await synthesize_quadrant(
        rows,
        query_context={"industry": args.industry, "country": args.country},
        scope={"market": args.industry, "geography": args.country},
        settings=settings,
        write_output=True,
    )
    out = result.get("output_path") or ""
    brands = result.get("brands") or []
    print("\n=== Quadrant complete ===", flush=True)
    print(f"  Brands scored: {len(brands)}", flush=True)
    # synthesize_quadrant() always writes to output/quadrant/<slug>_*; copy the
    # results next to the original checkpoint too, so the existing report path
    # this market's earlier reports lived at stays up to date.
    for key, label in (
        ("output_path", "quadrant JSON"),
        ("companies_csv_path", "companies CSV"),
        ("html_report_path", "HTML report"),
        ("questions_path", "questions JSON"),
    ):
        src = result.get(key)
        if not src:
            continue
        print(f"  {label}: {src}", flush=True)
        if args.out_dir:
            dest_dir = Path(args.out_dir)
            dest_dir.mkdir(parents=True, exist_ok=True)
            # Rename to the output/chatgpt_expand/<slug>_<file-suffix> convention
            # this market's earlier reports already use, so the same file paths
            # you've been opening stay current.
            suffix = Path(src).name.split("_", 1)[-1] if "_" in Path(src).name else Path(src).name
            slug = _underscore_slug(args.industry, args.country)
            dest = dest_dir / f"{slug}_{suffix}"
            dest.write_bytes(Path(src).read_bytes())
            print(f"    -> copied to {dest}", flush=True)
    for b in brands[:30]:
        print(
            f"    {b.get('brand')}: X={b.get('execution')} Y={b.get('innovation')} "
            f"{b.get('quadrant')} {b.get('tier')} overall={b.get('overall')}",
            flush=True,
        )
    if len(brands) > 30:
        print(f"    … +{len(brands) - 30} more", flush=True)
    return 0 if out else 1


def main() -> None:
    p = argparse.ArgumentParser(description="Re-run Coherent Quadrant from a chatgpt_expand checkpoint JSON")
    p.add_argument("--checkpoint", required=True, help="Path to chatgpt_checkpoint_batch_all.json")
    p.add_argument("--source-key", default="xy_rows", choices=["xy_rows", "final_kept"])
    p.add_argument("--industry", required=True)
    p.add_argument("--country", default="global")
    p.add_argument("--max-companies", type=int, default=20, help="Chart size (top N per quadrant group)")
    p.add_argument("--table-companies", type=int, default=300)
    p.add_argument("--out-dir", default=None, help="Defaults to the checkpoint's own folder")
    args = p.parse_args()
    if args.out_dir is None:
        args.out_dir = str(Path(args.checkpoint).resolve().parent)
    raise SystemExit(asyncio.run(_amain(args)))


if __name__ == "__main__":
    main()
