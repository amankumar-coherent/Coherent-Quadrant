#!/usr/bin/env python3
"""Re-ask ONLY the parameters that have a score but no assessed_on text.

Confirmed live for Global Wearable Glucometer Market: AI Mode consistently
omits the "Assessed on:" sentence specifically for its highest-confidence
answers (score >= ~93) on well-documented companies -- the evidence and
score are real and correct, just missing the required reasoning line. This
re-asks exactly those (company, parameter) pairs, one at a time, using
build_forced_score_query()'s stronger "you MUST end with Score: NN/100"
framing, and keeps the existing score/evidence if the new answer parses
without a change worth trusting more.

    .\\.venv\\Scripts\\python.exe scripts\\fill_missing_assessed_on.py ^
        --market "Global Wearable Glucometer Market" --country global ^
        --slot 41 --fixed-axes config/wearable_glucometer_axes.json ^
        --only-file scratch_glucometer_top20_candidates.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--market", required=True)
    ap.add_argument("--country", default="global")
    ap.add_argument("--slot", type=int, required=True)
    ap.add_argument("--fixed-axes", required=True)
    ap.add_argument("--only-file", required=True,
                     help="JSON list of company names to check/fix")
    ap.add_argument("--shard", type=int, default=0,
                     help="this instance's shard index (0-based), for "
                          "splitting the gap list across several browsers")
    ap.add_argument("--shards", type=int, default=1,
                     help="total number of shards -- the gap list (company, "
                          "axis, parameter) slots are divided by fixed "
                          "position, so shards can run concurrently without "
                          "ever picking the same slot")
    args = ap.parse_args()

    profile = ROOT / "data" / f"ai_mode_batch_{args.slot:02d}"
    os.environ["GOOGLE_AI_MODE_PROFILE_DIR"] = str(profile)
    os.environ["GOOGLE_AI_MODE_BROWSER"] = "chromium"
    os.environ["GOOGLE_AI_MODE_ENABLED"] = "true"

    from vendor_intel.pipeline.web_expand import default_output_dir
    from vendor_intel.quadrant.ai_mode_scorer import (
        build_forced_score_query,
        parse_small_group_scores,
    )
    from vendor_intel.scraping.google_ai_mode import ask as ai_ask

    spec = json.loads(Path(args.fixed_axes).read_text(encoding="utf-8"))
    x_defs = spec["parameter_definitions"]["x"]
    y_defs = spec["parameter_definitions"]["y"]
    market_definition = str(spec.get("market_definition") or "")

    out_dir = Path(default_output_dir(args.market, args.country))
    wanted = set(json.loads(Path(args.only_file).read_text(encoding="utf-8")))

    # Find every (company, axis, param) with a score but no assessed_on,
    # across ALL sidecars -- unioned the same way the report builder does.
    # Track EVERY sidecar that holds this exact gap, not just the last one
    # seen: the same gap commonly exists in more than one sidecar (e.g. a
    # company scored by two different runs), and fixing only one copy left
    # the completeness audit still finding the gap via the untouched copy
    # -- confirmed live twice this session before this fix.
    gap_keys: list[tuple[str, str, str]] = []
    sidecars_of: dict[tuple[str, str, str], list[Path]] = {}
    for side in sorted(out_dir.glob("param_detail_prescored*.json")):
        try:
            part = json.loads(side.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        for name, rec in part.items():
            if name not in wanted:
                continue
            for axis_key in ("x", "y"):
                params = (rec.get(axis_key) or {}).get("parameters") or {}
                for pname, v in params.items():
                    if not isinstance(v, dict):
                        continue
                    if v.get("score") is not None and not v.get("assessed_on"):
                        key = (name, axis_key, pname)
                        if key not in sidecars_of:
                            gap_keys.append(key)
                        sidecars_of.setdefault(key, []).append(side)

    my_keys = gap_keys[args.shard::args.shards]
    total = len(my_keys)
    print(f"shard {args.shard}/{args.shards}: {len(gap_keys)} total gap slots, "
          f"{total} assigned to this shard")

    def ask_retry(prompt: str, attempts: int = 3) -> str:
        for i in range(1, attempts + 1):
            try:
                out = ai_ask(prompt)
                if out and len(str(out).strip()) > 80:
                    return out
            except Exception as err:  # noqa: BLE001
                print(f"    attempt {i}: {type(err).__name__}: {str(err)[:70]}", flush=True)
            if i < attempts:
                time.sleep(30)
        return ""

    done = 0
    for name, axis_key, pname in my_keys:
        defs = x_defs if axis_key == "x" else y_defs
        query = build_forced_score_query(
            name, pname, defs, market=args.market,
            market_definition=market_definition,
        )
        answer = ask_retry(query)
        got = parse_small_group_scores(answer, [pname], query) if answer else {}
        entry = got.get(pname)
        status = "MISS"
        if entry and entry.get("assessed_on"):
            # Write the fix into EVERY sidecar that had this same gap, so
            # no copy is left stale for the completeness audit to still
            # flag.
            for side in sidecars_of[(name, axis_key, pname)]:
                part = json.loads(side.read_text(encoding="utf-8"))
                part[name][axis_key]["parameters"][pname] = entry
                tmp = side.with_suffix(".json.tmp")
                tmp.write_text(json.dumps(part, ensure_ascii=False), encoding="utf-8")
                os.replace(tmp, side)
            status = "OK"
            done += 1
        print(f"  [{done}/{total}] {name} / {pname} ({axis_key}): {status}", flush=True)

    print(f"\nfixed {done}/{total} missing-reasoning slots (this shard)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
