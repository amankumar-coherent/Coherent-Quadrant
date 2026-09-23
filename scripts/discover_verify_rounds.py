#!/usr/bin/env python3
"""Discover a batch -> verify it -> repeat until N verified companies.

Discovery normally collects to its target and verifies once at the end, so
the number of companies that SURVIVE verification is left to chance. This
loop works against the number that matters: after every batch it verifies
only the new companies, counts the verified set after dedupe (one row per
real company), and discovers another batch only if it is still short.

Each round:
  1. count   verified companies after dedupe -> stop if >= --keep
  2. size    next batch from the deficit and the keep rate so far
             (a market that rejects half its candidates asks for twice as many)
  3. discover that many more (Google AI Mode rounds; every company already
             seen -- verified OR rejected -- is excluded, so nothing is re-checked)
  4. verify  only the new companies, append to the checkpoint's verified list

Stops when the target is reached, when discovery comes back with nothing new
(the market is exhausted), or after --max-rounds.

Works on the checkpoint run_chatgpt_expand.py wrote, so it only tops up a
market that has been discovered once. run_quadrant_pipeline.py --keep calls
it automatically.

    .\\.venv\\Scripts\\python.exe scripts\\discover_verify_rounds.py ^
        --market "Global Wearable Glucometer Market" --country global --keep 120
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def log(msg: str) -> None:
    print(f"[rounds {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--market", required=True)
    ap.add_argument("--country", default="global")
    ap.add_argument("--keep", type=int, required=True,
                    help="verified companies wanted (after dedupe)")
    ap.add_argument("--min-batch", type=int, default=25,
                    help="smallest discovery batch per round")
    ap.add_argument("--max-rounds", type=int, default=10)
    ap.add_argument("--slot", type=int, default=41, help="browser profile slot")
    args = ap.parse_args()

    os.environ["GOOGLE_AI_MODE_PROFILE_DIR"] = str(ROOT / "data" / f"ai_mode_batch_{args.slot:02d}")
    os.environ["GOOGLE_AI_MODE_BROWSER"] = "chromium"
    os.environ["GOOGLE_AI_MODE_ENABLED"] = "true"

    from vendor_intel.config import Settings
    from vendor_intel.pipeline import chatgpt_expand as ce
    from vendor_intel.pipeline.openai_expand_checkpoint import ExpandCheckpoint
    from vendor_intel.pipeline.quadrant_pipeline import dedupe_companies
    from vendor_intel.pipeline.web_expand import default_output_dir, market_family

    out_dir = Path(default_output_dir(args.market, args.country))
    ckpt_path = out_dir / "chatgpt_checkpoint_batch_all.json"
    if not ckpt_path.exists():
        log(f"no checkpoint at {ckpt_path} -- run discovery first")
        return 2
    ckpt = ExpandCheckpoint(ckpt_path, json.loads(ckpt_path.read_text(encoding="utf-8")))
    data = ckpt.state.setdefault("data", {})

    # Same company type as the first batch: restore Step 0c's B2B/B2C read.
    market_analysis = dict(data.get("market_analysis") or {})
    if market_analysis.get("market_type"):
        ce.publish_discovery_market(market_analysis)
    family = market_family(args.market)

    settings = Settings()
    client, model = ce._client(settings), ce._model(settings)

    def key(row: dict) -> str:
        return ce._dedupe_key(str(row.get("name") or row.get("Company") or ""))

    for rnd in range(1, args.max_rounds + 1):
        verified = list(data.get("verified") or [])
        rejected = list(data.get("rejected_mid") or [])
        have = len(dedupe_companies(verified)[0])
        if have >= args.keep:
            log(f"target reached: {have} verified companies (need {args.keep})")
            return 0

        checked = len(verified) + len(rejected)
        rate = len(verified) / checked if checked else 0.5
        deficit = args.keep - have
        # Ask for enough that the expected survivors cover the deficit, with a
        # 20% margin; a floor on the rate stops a harsh first batch asking for
        # an absurd number.
        batch = max(args.min_batch, math.ceil(deficit / max(rate, 0.2) * 1.2))
        recalled = list(data.get("recalled") or [])
        log(f"round {rnd}: {have}/{args.keep} verified (keep rate {rate:.0%}) -> "
            f"discovering {batch} more")

        recalled = ce.discover_companies_rounds(
            client, model, query=args.market, family=family,
            target=len(recalled) + batch, country=args.country, ckpt=ckpt,
        )
        seen = {key(r) for r in verified} | {key(r) for r in rejected}
        new = [r for r in recalled if key(r) and key(r) not in seen]
        if not new:
            log(f"discovery found nothing new -- market exhausted at {have} verified")
            return 1

        log(f"round {rnd}: verifying {len(new)} new companies")
        kept, rej = ce.gpt_verify_market(
            client, model, query=args.market, family=family, companies=new,
            country=args.country,
        )
        data["verified"] = verified + list(kept)
        data["rejected_mid"] = rejected + list(rej)
        ckpt.save(note=f"discover/verify round {rnd}: +{len(kept)} verified, "
                       f"{len(rej)} rejected")
        log(f"round {rnd}: +{len(kept)} verified, {len(rej)} rejected")

    have = len(dedupe_companies(list(data.get("verified") or []))[0])
    log(f"stopped after {args.max_rounds} rounds at {have}/{args.keep} verified")
    return 0 if have >= args.keep else 1


if __name__ == "__main__":
    raise SystemExit(main())
