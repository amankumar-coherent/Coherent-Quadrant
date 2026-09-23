#!/usr/bin/env python3
"""Merge composite_scores_fast_shard*.json into one file for scoring to use.

Each shard writes its own file (see fast_composite_score.py) so three
concurrent browsers never race on one JSON. This combines them once all
shards report done.

    .\.venv\Scripts\python.exe scripts\merge_composite_shards.py ^
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
    shards = sorted(out_dir.glob("composite_scores_fast_shard*.json"))
    if not shards:
        print("no shard files found", file=sys.stderr)
        return 2

    merged: dict[str, list] = {}
    for path in shards:
        data = json.loads(path.read_text(encoding="utf-8"))
        overlap = set(data) & set(merged)
        if overlap:
            print(f"WARNING: {len(overlap)} companies appear in more than "
                  f"one shard: {list(overlap)[:5]}", file=sys.stderr)
        merged.update(data)
        scored = sum(1 for v in data.values() if v[0] is not None and v[1] is not None)
        print(f"  {path.name}: {scored}/{len(data)} scored")

    final = out_dir / "composite_scores_fast.json"
    final.write_text(json.dumps(merged, ensure_ascii=False), encoding="utf-8")
    got = sum(1 for v in merged.values() if v[0] is not None and v[1] is not None)
    print(f"\nmerged {len(shards)} shards -> {len(merged)} companies "
          f"({got} scored) -> {final}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
