#!/usr/bin/env python3
"""Merge broad_sweep_shard*.json into the checkpoint's `recalled` list.

Run once every parallel_broad_sweep.py shard has finished. Every shard asks
the SAME unconstrained question, so heavy duplication across shards is
expected here (unlike the country/city sweeps, which split the work by
region) -- this is the one place it gets deduped.

    .\\.venv\\Scripts\\python.exe scripts\\merge_broad_sweep.py ^
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
    shards = sorted(out_dir.glob("broad_sweep_shard*.json"))
    if not shards:
        print("no shard files found", file=sys.stderr)
        return 2

    state = json.loads(ckpt_path.read_text(encoding="utf-8"))
    data = state.setdefault("data", {})
    existing = data.get("recalled") or []
    seen = {_key(r) for r in existing if _key(r)}

    added = 0
    for path in shards:
        rows = json.loads(path.read_text(encoding="utf-8"))
        shard_added = 0
        for row in rows:
            key = _key(row)
            if not key or key in seen:
                continue
            seen.add(key)
            existing.append(row)
            added += 1
            shard_added += 1
        print(f"  {path.name}: {len(rows)} candidate rows, "
              f"{shard_added} genuinely new")

    data["recalled"] = existing
    ckpt_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    print(f"\nmerged {len(shards)} shards -> +{added} new companies "
          f"(pool now {len(existing)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
