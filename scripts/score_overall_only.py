#!/usr/bin/env python3
"""Direct Overall score only, no per-parameter evidence -- for the long tail.

Other Noticeable Player never shows per-parameter breakdowns or evidence,
only the Strength bubble (derived from Overall score) -- so scoring it with
the full 10-parameter evidence pipeline is wasted work.

First version of this script asked AI Mode for a bare "reply with ONLY the
number" per axis (build_score_query). Confirmed live at scale: that format
failed almost completely (6/167 companies scored) -- AI Mode mostly echoed
the prompt back with no answer at all, unlike the structured "Evidence +
Assessed on + Score" format that has been reliable all session. This
version reuses THAT reliable format (build_defined_small_group_query, 2
parameters per query, same as the proven fallback path used everywhere
else) but only keeps the numeric score per parameter -- evidence and
assessed_on text is read and immediately discarded, never written to the
sidecar or any other file.

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
        build_defined_small_group_query,
        parse_small_group_scores,
    )
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

    def axis_mean(name: str, params: list[str], defs: dict[str, str]) -> float | None:
        """Ask 2 parameters at a time (the reliable format all session),
        keep only the numeric score, discard evidence/assessed_on
        immediately -- nothing from `got` beyond the score ever survives
        this function."""
        scores: list[int] = []
        for i in range(0, len(params), 2):
            group = params[i : i + 2]
            query = build_defined_small_group_query(
                name, group, defs, market=args.market,
                market_definition=market_definition,
            )
            answer = ask_retry(query)
            got = parse_small_group_scores(answer, group, query) if answer else {}
            missing = [p for p in group if p not in got]
            for p in missing:  # retry any miss singly, same as the proven fallback
                one_query = build_defined_small_group_query(
                    name, [p], defs, market=args.market,
                    market_definition=market_definition,
                )
                one_answer = ask_retry(one_query)
                one_got = parse_small_group_scores(one_answer, [p], one_query) if one_answer else {}
                got.update(one_got)
            scores.extend(v["score"] for v in got.values() if v.get("score") is not None)
        return sum(scores) / len(scores) if scores else None

    done = 0
    for name in my_companies:
        if name in already:
            continue

        x_mean = axis_mean(name, x_params, x_defs)
        y_mean = axis_mean(name, y_params, y_defs)

        if x_mean is None or y_mean is None:
            print(f"  {name}: MISS (x={x_mean} y={y_mean})", flush=True)
            continue

        x_score, y_score = round(x_mean), round(y_mean)
        overall = round((x_score + y_score) / 2)
        results[name] = {"x_score": x_score, "y_score": y_score, "overall": overall}
        write_sidecar()
        done += 1
        print(f"  [{done}/{len(my_companies)}] {name}: X={x_score} Y={y_score} O={overall}", flush=True)

    print(f"\ndone: {done}/{len(my_companies)} scored this shard -> {side_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
