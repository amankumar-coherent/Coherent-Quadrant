#!/usr/bin/env python3
"""Apply gap_fill_shard*.json fills onto the checkpoint's `recalled` rows.

Run once every ai_mode_gap_fill.py shard has finished. Matches each fill
back onto its row by the ORIGINAL company name (the dict key each shard
wrote under). Handles two row shapes -- the user-list rows use lowercase
keys (company/brand/headquarters/website), the discovery-sweep rows use the
pipeline's own PascalCase keys (Company/Market Offering/brand_name/
Headquarters) -- and two sidecar kinds: the plain gap_fill_shard*.json
(website/headquarters/ownership/brand, for rows with no website at all) and
gap_fill_shard*_brand.json (--refresh-brand-only, brand ONLY, for rows that
already had a website but got a bare trimmed-company-name brand).

    .\\.venv\\Scripts\\python.exe scripts\\merge_gap_fill.py ^
        --market "Marine Seismic Data Processing Services Market" ^
        --country global
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))


def _row_name(r: dict) -> str:
    return str(r.get("company") or r.get("Company") or r.get("name") or "").strip()


def _set_brand(row: dict, brand: str) -> None:
    """Write brand under whichever key(s) this row shape uses."""
    if "brand" in row or "company" in row:
        row["brand"] = brand
    if "brand_name" in row or "Market Offering" in row or "Company" in row:
        row["brand_name"] = brand
        row["Market Offering"] = brand


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--market", required=True)
    ap.add_argument("--country", default="global")
    ap.add_argument("--out-dir", default="")
    args = ap.parse_args()

    from vendor_intel.pipeline.web_expand import default_output_dir

    out_dir = Path(args.out_dir) if args.out_dir else Path(default_output_dir(args.market, args.country))
    ckpt_path = out_dir / "chatgpt_checkpoint_batch_all.json"
    all_shards = sorted(out_dir.glob("gap_fill_shard*.json"))
    brand_shards = [p for p in all_shards if p.stem.endswith("_brand")]
    fill_shards = [p for p in all_shards if p not in brand_shards]
    if not all_shards:
        print("no shard files found", file=sys.stderr)
        return 2

    state = json.loads(ckpt_path.read_text(encoding="utf-8"))
    data = state.setdefault("data", {})
    recalled = data.get("recalled") or []
    by_name = {_row_name(r): r for r in recalled}

    applied = 0
    missing_website = 0
    if fill_shards:
        fills: dict[str, dict] = {}
        for path in fill_shards:
            part = json.loads(path.read_text(encoding="utf-8"))
            fills.update(part)
            print(f"  {path.name}: {len(part)} fills")
        for name, fill in fills.items():
            row = by_name.get(name)
            if not row:
                continue
            clean_company = fill.get("clean_company") or ""
            if clean_company:
                row["company"] = clean_company
            if fill.get("brand"):
                _set_brand(row, fill["brand"])
            if fill.get("website"):
                row["website"] = fill["website"]
            else:
                missing_website += 1
            if fill.get("headquarters"):
                row["headquarters"] = fill["headquarters"]
            row["ownership"] = fill.get("ownership") or "Independent"
            row["ownership_confidence"] = fill.get("ownership_confidence") or "low"
            applied += 1

    brand_applied = 0
    if brand_shards:
        brand_fills: dict[str, dict] = {}
        for path in brand_shards:
            part = json.loads(path.read_text(encoding="utf-8"))
            brand_fills.update(part)
            print(f"  {path.name}: {len(part)} brand fills")
        for name, fill in brand_fills.items():
            row = by_name.get(name)
            if not row or not fill.get("brand"):
                continue
            _set_brand(row, fill["brand"])
            brand_applied += 1

    data["recalled"] = recalled
    ckpt_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    print(f"\napplied {applied} full fills "
          f"({missing_website} still have no verifiable website)")
    print(f"applied {brand_applied} brand-only refreshes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
