#!/usr/bin/env python3
"""Merge param_detail_prescored_shard*.json into one file.

Run once every prescore_verified.py --shards instance has finished.

    .\\.venv\\Scripts\\python.exe scripts\\merge_evidence_shards.py ^
        --market "Advanced Seismic Data Processing Solutions Market" ^
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--market", required=True)
    ap.add_argument("--country", default="global")
    args = ap.parse_args()

    from vendor_intel.pipeline.web_expand import default_output_dir

    out_dir = Path(default_output_dir(args.market, args.country))
    shards = sorted(out_dir.glob("param_detail_prescored_shard*.json"))
    if not shards:
        print("no shard files found", file=sys.stderr)
        return 2

    merged: dict[str, dict] = {}
    for path in shards:
        data = json.loads(path.read_text(encoding="utf-8"))
        overlap = set(data) & set(merged)
        if overlap:
            print(f"WARNING: {len(overlap)} companies in more than one "
                  f"shard: {list(overlap)[:5]}", file=sys.stderr)
        merged.update(data)
        have = sum(
            1 for v in data.values()
            if v.get("x", {}).get("parameters") and v.get("y", {}).get("parameters")
        )
        print(f"  {path.name}: {have}/{len(data)} with full evidence")

    final = out_dir / "param_detail_prescored.json"
    final.write_text(json.dumps(merged, ensure_ascii=False), encoding="utf-8")
    have = sum(
        1 for v in merged.values()
        if v.get("x", {}).get("parameters") and v.get("y", {}).get("parameters")
    )
    print(f"\nmerged {len(shards)} shards -> {len(merged)} companies "
          f"({have} with full evidence) -> {final}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
