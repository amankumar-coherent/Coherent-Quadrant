#!/usr/bin/env python3
r"""One-line-per-market progress for a queued batch.

Reads each market's own checkpoint, so it is accurate whether the batch is
running, paused or finished, and it never touches a browser or the network.

    .\.venv\Scripts\python.exe scripts\batch_status.py --markets-file queries\drone_25.tsv --country India
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
    ap.add_argument("--markets-file", required=True)
    ap.add_argument("--country", "-c", default="India")
    args = ap.parse_args()

    from vendor_intel.pipeline.web_expand import default_output_dir

    markets = []
    for line in Path(args.markets_file).read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        markets.append(line.partition("\t")[0].strip())

    done = total_rows = total_scored = 0
    for market in markets:
        ckpt = (
            Path(default_output_dir(market, args.country))
            / "chatgpt_checkpoint_batch_all.json"
        )
        if not ckpt.exists():
            print(f"  {'not started':<14} {'':>9}  {market}")
            continue
        try:
            state = json.loads(ckpt.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - a half-written checkpoint is normal
            print(f"  {'writing...':<14} {'':>9}  {market}")
            continue
        rows = (state.get("data") or {}).get("detail_rows") or []
        scored = sum(1 for r in rows if str(r.get("X") or "").strip())
        status = str(state.get("status") or "?")
        step = str(state.get("step") or "")
        complete = bool(rows) and scored == len(rows) and status == "done"
        done += complete
        total_rows += len(rows)
        total_scored += scored
        label = "DONE" if complete else f"{status}/{step}"[:14]
        print(f"  {label:<14} {scored:>4}/{len(rows):<4}  {market}")

    print(f"\n{done}/{len(markets)} markets complete · {total_scored}/{total_rows} rows scored")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
