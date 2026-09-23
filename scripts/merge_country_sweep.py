#!/usr/bin/env python3
"""Merge country_sweep_shard*.json into the checkpoint's `recalled` list.

Run once every parallel_country_sweep.py shard has finished. Dedupes on
company name (case-insensitive) against what is already in the checkpoint,
so re-running this after a partial merge is safe.

    .\\.venv\\Scripts\\python.exe scripts\\merge_country_sweep.py ^
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


def _key(row: dict) -> str:
    return str(row.get("company") or row.get("name") or "").strip().lower()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--market", required=True)
    ap.add_argument("--country", default="global")
    ap.add_argument("--out-dir", default="")
    args = ap.parse_args()

    from vendor_intel.pipeline.web_expand import default_output_dir

    out_dir = Path(args.out_dir) if args.out_dir else Path(default_output_dir(args.market, args.country))
    ckpt_path = out_dir / "chatgpt_checkpoint_batch_all.json"
    shards = sorted(out_dir.glob("country_sweep_shard*.json"))
    if not shards:
        print("no shard files found", file=sys.stderr)
        return 2

    state = json.loads(ckpt_path.read_text(encoding="utf-8"))
    data = state.setdefault("data", {})
    existing = data.get("recalled") or []
    seen = {_key(r) for r in existing if _key(r)}

    added = 0
    countries_swept = 0
    for path in shards:
        rows = json.loads(path.read_text(encoding="utf-8"))
        for row in rows:
            if row.get("_empty"):
                countries_swept += 1
                continue
            key = _key(row)
            if not key or key in seen:
                continue
            seen.add(key)
            row.pop("_swept_country", None)
            existing.append(row)
            added += 1
        n_countries = len({r.get("_swept_country") for r in rows})
        print(f"  {path.name}: {n_countries} countries swept, "
              f"{sum(1 for r in rows if not r.get('_empty'))} candidate rows")

    data["recalled"] = existing
    ckpt_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    print(f"\nmerged {len(shards)} shards -> +{added} new companies "
          f"(pool now {len(existing)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
