#!/usr/bin/env python3
"""Verify what discovery has found so far, then top up to the target.

The pipeline discovers to its target and only then verifies, so a market
with a tight scope spends hundreds of queries collecting companies that
verification is about to reject. Running verify FIRST answers the question
that decides everything after it: what fraction of this pool actually
qualifies?

With that ratio known, the raw target needed for N verified companies is
arithmetic rather than guesswork, and the top-up rounds are spent against a
number that means something.

Verified companies are written back to the checkpoint, so the normal
pipeline resumes from them rather than re-verifying.

    .\\.venv\\Scripts\\python.exe scripts\\verify_then_topup.py ^
        --market "Advanced Seismic Data Processing Solutions Market" ^
        --country global --target 300
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))


def _scope_for(market: str) -> str:
    """The market's scope line from any queries/*.tsv that lists it."""
    for path in sorted((ROOT / "queries").glob("*.tsv")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            name, _, scope = line.partition("\t")
            if name.strip().lower() == market.strip().lower():
                return " ".join(scope.split())
    return ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--market", required=True)
    ap.add_argument("--country", default="global")
    ap.add_argument("--target", type=int, default=300)
    ap.add_argument(
        "--dry-run", action="store_true",
        help="report the keep rate without writing it back",
    )
    ap.add_argument(
        "--slot", type=int, default=9,
        help=(
            "browser profile slot. Without this the run takes the SHARED "
            "default profile, which an already-running pipeline may hold a "
            "lock on -- the launch then dies immediately."
        ),
    )
    args = ap.parse_args()

    profile = ROOT / "data" / f"ai_mode_batch_{args.slot:02d}"
    os.environ["GOOGLE_AI_MODE_PROFILE_DIR"] = str(profile)
    os.environ["GOOGLE_AI_MODE_BROWSER"] = "chromium"
    os.environ["GOOGLE_AI_MODE_ENABLED"] = "true"

    from vendor_intel.config import Settings
    from vendor_intel.pipeline import chatgpt_expand as ce
    from vendor_intel.pipeline.web_expand import default_output_dir

    scope = _scope_for(args.market)
    if scope:
        os.environ["MARKET_SCOPE"] = scope
        print(f"scope ({len(scope)} chars): {scope[:120]}...")
    else:
        print("WARNING: no scope found for this market — verify will judge on "
              "the market title alone")

    out_dir = Path(default_output_dir(args.market, args.country))
    ckpt_path = out_dir / "chatgpt_checkpoint_batch_all.json"
    if not ckpt_path.exists():
        print(f"ERROR: no checkpoint at {ckpt_path}", file=sys.stderr)
        return 2

    state = json.loads(ckpt_path.read_text(encoding="utf-8"))
    data = state.get("data") or {}
    pool = data.get("recalled") or []
    already = data.get("verified") or []
    if not pool:
        print("nothing discovered yet")
        return 1

    print(f"\npool: {len(pool)} discovered, {len(already)} already verified")
    print(f"verifying {len(pool)} companies against the scope...\n")

    settings = Settings()
    client = ce._client(settings)
    model = ce._model(settings)

    kept, rejected = ce.gpt_verify_market(
        client, model,
        query=args.market,
        family="technology",
        companies=pool,
    )

    rate = len(kept) / max(1, len(pool))
    print("\n" + "=" * 72)
    print(f"  kept     : {len(kept)}/{len(pool)}  ({rate * 100:.0f}%)")
    print(f"  rejected : {len(rejected)}")
    if rate > 0:
        need_raw = int(args.target / rate)
        print(f"\n  to reach {args.target} VERIFIED companies at this rate,")
        print(f"  discovery needs roughly {need_raw} raw companies")
        print(f"  ({need_raw - len(pool)} more than the {len(pool)} found so far)")
    print("=" * 72)

    by_reason: dict[str, int] = {}
    for r in rejected:
        key = str(r.get("reason") or "")[:60] or "(no reason)"
        by_reason[key] = by_reason.get(key, 0) + 1
    if by_reason:
        print("\n  top rejection reasons:")
        for reason, n in sorted(by_reason.items(), key=lambda kv: -kv[1])[:8]:
            print(f"    {n:3}x {reason}")

    if args.dry_run:
        print("\n(dry run — checkpoint not written)")
        return 0

    state["data"]["verified"] = kept
    state["data"]["rejected_mid"] = rejected
    ckpt_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    print(f"\nwrote {len(kept)} verified companies to the checkpoint")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
