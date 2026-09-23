#!/usr/bin/env python3
"""Quick X/Y scores for every verified company -- ranks the pool before the
Top 20 are chosen (5 per quadrant), and feeds the long tail's Strength bubbles.

Two AI Mode queries per company: one Product Capability scorecard (all 5 X
parameters, one line each) and one Business Capability scorecard (all 5 Y
parameters) -- build_axis_scorecard_query. X = mean of the X parameter
scores, Y = mean of the Y scores, Overall = (X + Y) / 2. Verified live: 4/4
scorecard queries returned 5/5 parameter scores.

Any parameter a scorecard answer leaves out is re-asked on its own with the
proven 1-parameter format (build_defined_small_group_query), so a partial
answer costs one extra query rather than a re-score. (A bare "reply with ONLY
the number" format failed at scale -- AI Mode echoed the prompt -- which is
why each scorecard line carries a short reason.)

No evidence is kept here: per-parameter evidence and reasoning are gathered
later for the Top 20 only. The per-parameter quick scores are stored with
X/Y/Overall in overall_only_shard<N>.json.

    .\\.venv\\Scripts\\python.exe scripts\\score_overall_only.py ^
        --market "Global Wearable Glucometer Market" --country global ^
        --slot 41 --shard 0 --shards 10 ^
        --fixed-axes config/wearable_glucometer_axes.json ^
        --only-file scratch_glucometer_others167.json
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
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--shards", type=int, default=1)
    ap.add_argument("--fixed-axes", required=True)
    ap.add_argument("--only-file", required=True)
    args = ap.parse_args()

    profile = ROOT / "data" / f"ai_mode_batch_{args.slot:02d}"
    os.environ["GOOGLE_AI_MODE_PROFILE_DIR"] = str(profile)
    os.environ["GOOGLE_AI_MODE_BROWSER"] = "chromium"
    os.environ["GOOGLE_AI_MODE_ENABLED"] = "true"

    from vendor_intel.pipeline.web_expand import default_output_dir
    from vendor_intel.quadrant.ai_mode_scorer import (
        build_axis_scorecard_query,
        build_defined_small_group_query,
        parse_axis_scorecard,
        parse_small_group_scores,
    )
    from vendor_intel.quadrant.quadrant_language import AXIS_X_TITLE, AXIS_Y_TITLE
    from vendor_intel.scraping.google_ai_mode import ask as ai_ask

    spec = json.loads(Path(args.fixed_axes).read_text(encoding="utf-8"))
    x_params, y_params = spec["x"], spec["y"]
    x_defs, y_defs = spec["parameter_definitions"]["x"], spec["parameter_definitions"]["y"]
    market_definition = str(spec.get("market_definition") or "")

    out_dir = Path(default_output_dir(args.market, args.country))
    wanted = json.loads(Path(args.only_file).read_text(encoding="utf-8"))
    my_companies = wanted[args.shard::args.shards]
    print(f"shard {args.shard}/{args.shards}: {len(my_companies)} companies "
          f"(Overall score only, no evidence)")

    side_path = out_dir / f"overall_only_shard{args.shard}.json"
    results: dict[str, dict] = {}
    if side_path.exists():
        try:
            results = json.loads(side_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            results = {}
    # A company already scored by ANY earlier shard (a previous run may
    # have used a different shard count) is not asked again.
    already: set[str] = set(results)
    for other in out_dir.glob("overall_only_shard*.json"):
        try:
            already.update(json.loads(other.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            continue

    def ask_retry(prompt: str, attempts: int = 3) -> str:
        for i in range(1, attempts + 1):
            try:
                out = ai_ask(prompt)
                if out:
                    return out
            except Exception as err:  # noqa: BLE001
                print(f"    attempt {i}: {type(err).__name__}: {str(err)[:70]}", flush=True)
            if i < attempts:
                time.sleep(20)
        return ""

    def write_sidecar() -> None:
        tmp = side_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(results, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, side_path)

    def axis_scores(name: str, title: str, params: list[str],
                    defs: dict[str, str]) -> dict[str, int]:
        """{parameter: score} from ONE scorecard query for the whole axis;
        only parameters the answer left out are re-asked singly."""
        query = build_axis_scorecard_query(
            name, title, params, defs, market=args.market,
            market_definition=market_definition,
        )
        answer = ask_retry(query)
        got = parse_axis_scorecard(answer, params, query) if answer else {}
        for p in [p for p in params if p not in got]:
            one_query = build_defined_small_group_query(
                name, [p], defs, market=args.market,
                market_definition=market_definition,
            )
            one_answer = ask_retry(one_query)
            one = parse_small_group_scores(one_answer, [p], one_query) if one_answer else {}
            if (one.get(p) or {}).get("score") is not None:
                got[p] = int(one[p]["score"])
        return got

    done = 0
    for name in my_companies:
        if name in already:
            continue

        x_got = axis_scores(name, AXIS_X_TITLE, x_params, x_defs)
        y_got = axis_scores(name, AXIS_Y_TITLE, y_params, y_defs)
        if not x_got or not y_got:
            print(f"  {name}: MISS (x={len(x_got)}/{len(x_params)} "
                  f"y={len(y_got)}/{len(y_params)} parameters)", flush=True)
            continue

        x_score = round(sum(x_got.values()) / len(x_got))
        y_score = round(sum(y_got.values()) / len(y_got))
        overall = round((x_score + y_score) / 2)
        results[name] = {"x_score": x_score, "y_score": y_score, "overall": overall,
                         "x_params": x_got, "y_params": y_got}
        write_sidecar()
        done += 1
        print(f"  [{done}/{len(my_companies)}] {name}: X={x_score} Y={y_score} O={overall}", flush=True)

    print(f"\ndone: {done}/{len(my_companies)} scored this shard -> {side_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
