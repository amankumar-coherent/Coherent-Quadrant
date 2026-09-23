#!/usr/bin/env python3
"""Apply verify_shard*.json verdicts to the checkpoint's verified/rejected.

Run once every ai_mode_verify.py shard has finished. A company that got
in_market=true keeps its full row (moved into `verified`); a company that
got in_market=false is recorded in `rejected_mid` with its reason, not
silently dropped, so the decision stays auditable.

    .\\.venv\\Scripts\\python.exe scripts\\merge_verify.py ^
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--market", required=True)
    ap.add_argument("--country", default="global")
    ap.add_argument("--out-dir", default="")
    args = ap.parse_args()

    from vendor_intel.pipeline.web_expand import default_output_dir

    out_dir = Path(args.out_dir) if args.out_dir else Path(default_output_dir(args.market, args.country))
    ckpt_path = out_dir / "chatgpt_checkpoint_batch_all.json"
    shards = sorted(out_dir.glob("verify_shard*.json"))
    if not shards:
        print("no shard files found", file=sys.stderr)
        return 2

    state = json.loads(ckpt_path.read_text(encoding="utf-8"))
    data = state.setdefault("data", {})
    recalled = data.get("recalled") or []
    by_name: dict[str, dict] = {}
    for r in recalled:
        nm = _row_name(r)
        if nm and nm not in by_name:
            by_name[nm] = r

    verdicts: dict[str, dict] = {}
    for path in shards:
        part = json.loads(path.read_text(encoding="utf-8"))
        verdicts.update(part)
        kept = sum(1 for v in part.values() if v.get("in_market"))
        print(f"  {path.name}: {len(part)} verdicts, {kept} kept")

    verified: list[dict] = []
    rejected: list[dict] = []
    for name, row in by_name.items():
        verdict = verdicts.get(name)
        if verdict is None:
            continue  # never verified -- leave out of both lists
        if verdict.get("in_market"):
            verified.append(row)
        else:
            rejected.append({
                "name": name,
                "reason": verdict.get("reason") or "",
                "confidence": verdict.get("confidence") or "low",
            })

    data["verified"] = verified
    data["rejected_mid"] = rejected
    ckpt_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    print(f"\nverified (kept): {len(verified)}")
    print(f"rejected: {len(rejected)}")
    print(f"never verified (no verdict): {len(by_name) - len(verified) - len(rejected)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
