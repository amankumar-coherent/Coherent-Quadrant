#!/usr/bin/env python3
"""Fill ONLY the specific parameters missing per company, one at a time.

Every other scoring script here re-asks a company's WHOLE axis (or all 10
parameters) even when 8 of them already succeeded -- wasteful once the gap
is down to a couple of parameters per company. This reads the merged,
most-complete record for every verified company, works out EXACTLY which
named parameters are still missing, and asks about only those -- one
parameter per query, the most reliable path, since these are the
parameters that already failed once or twice under a batched ask.

    .\\.venv\\Scripts\\python.exe scripts\\fill_missing_parameters.py ^
        --market "Marine Seismic Data Processing Services Market" ^
        --country global --slot 71 --shard 0 --shards 10 ^
        --fixed-axes config/marine_seismic_axes.json
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


def _row_name(r: dict) -> str:
    return str(r.get("Company") or r.get("company") or r.get("name") or "").strip()


def _row_hq(r: dict) -> str:
    return str(r.get("Headquarters") or r.get("headquarters") or "").strip()


def _row_summary(r: dict) -> str:
    return str(
        r.get("Summary") or r.get("snippet") or r.get("why_related") or ""
    ).strip()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--market", required=True)
    ap.add_argument("--country", default="global")
    ap.add_argument("--slot", type=int, required=True)
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--shards", type=int, default=1)
    ap.add_argument("--fixed-axes", required=True)
    ap.add_argument("--out-dir", default="")
    ap.add_argument(
        "--only-file", default="",
        help="JSON list of company names to check -- without it EVERY "
             "verified company is audited, which for a market whose long "
             "tail was never evidence-scored means thousands of slots",
    )
    args = ap.parse_args()

    profile = ROOT / "data" / f"ai_mode_batch_{args.slot:02d}"
    os.environ["GOOGLE_AI_MODE_PROFILE_DIR"] = str(profile)
    os.environ["GOOGLE_AI_MODE_BROWSER"] = "chromium"
    os.environ["GOOGLE_AI_MODE_ENABLED"] = "true"

    from vendor_intel.pipeline.web_expand import default_output_dir
    from vendor_intel.quadrant.ai_mode_scorer import (
        build_defined_small_group_query,
        build_forced_score_query,
        parse_small_group_scores,
    )
    from vendor_intel.scraping.google_ai_mode import ask as ai_ask

    spec = json.loads(Path(args.fixed_axes).read_text(encoding="utf-8"))
    x_params = list(spec["x"])
    y_params = list(spec["y"])
    x_defs = spec["parameter_definitions"]["x"]
    y_defs = spec["parameter_definitions"]["y"]
    market_definition = str(spec.get("market_definition") or "")

    out_dir = Path(args.out_dir) if args.out_dir else Path(
        default_output_dir(args.market, args.country)
    )
    ckpt_path = out_dir / "chatgpt_checkpoint_batch_all.json"
    state = json.loads(ckpt_path.read_text(encoding="utf-8"))
    data = state.get("data") or {}
    verified = data.get("verified") or []
    by_name: dict[str, dict] = {}
    for r in verified:
        n = _row_name(r)
        if n and n not in by_name:
            by_name[n] = r

    # Union parameters across ALL sidecars per company. A sidecar with a
    # smaller total parameter count (e.g. a targeted fill-gap run that only
    # ever asked about 2 parameters) can still hold the ONE parameter that
    # a "more complete" sidecar is missing -- picking a single "best"
    # sidecar per company (by highest param count) silently discards those,
    # which is exactly why an earlier audit undercounted progress here.
    merged_x: dict[str, dict] = {}
    merged_y: dict[str, dict] = {}
    for side in sorted(out_dir.glob("param_detail_prescored*.json")):
        try:
            part = json.loads(side.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        for name, rec in part.items():
            xp = (rec.get("x") or {}).get("parameters") or {}
            yp = (rec.get("y") or {}).get("parameters") or {}
            mx = merged_x.setdefault(name, {})
            my = merged_y.setdefault(name, {})
            for p, v in xp.items():
                mx.setdefault(p, v)
            for p, v in yp.items():
                my.setdefault(p, v)

    # Build the exact gap: {company: [(axis_key, axis_label, param_name), ...]}
    gaps: dict[str, list[tuple[str, str, str]]] = {}
    scope = (
        [n for n in json.loads(Path(args.only_file).read_text(encoding="utf-8")) if n in by_name]
        if args.only_file else list(by_name)
    )
    for name in scope:
        xp = merged_x.get(name, {})
        yp = merged_y.get(name, {})
        missing: list[tuple[str, str, str]] = []
        for p in x_params:
            if p not in xp:
                missing.append(("x", spec["axis_x"], p))
        for p in y_params:
            if p not in yp:
                missing.append(("y", spec["axis_y"], p))
        if missing:
            gaps[name] = missing

    company_list = sorted(gaps.keys())
    my_companies = company_list[args.shard::args.shards]
    total_slots = sum(len(gaps[n]) for n in my_companies)
    print(f"shard {args.shard}/{args.shards}: {len(my_companies)} companies, "
          f"{total_slots} missing parameter slots to fill")

    side_path = out_dir / f"param_detail_prescored_fillgap{args.shard}.json"
    results: dict[str, dict] = {}
    if side_path.exists():
        try:
            results = json.loads(side_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            results = {}

    def _ask_retry(prompt: str, attempts: int = 3) -> str:
        for i in range(1, attempts + 1):
            try:
                out = ai_ask(prompt)
                if out and len(str(out).strip()) > 80:
                    return out
            except Exception as err:  # noqa: BLE001
                print(f"    attempt {i}: {type(err).__name__}: {str(err)[:70]}",
                      flush=True)
            if i < attempts:
                time.sleep(30)
        return ""

    def _write_sidecar() -> None:
        tmp = side_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(results, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, side_path)

    ctx_by = {n: _row_summary(by_name[n]) for n in my_companies}
    hq_by = {n: _row_hq(by_name[n]) for n in my_companies}

    started = time.monotonic()
    done_slots = 0
    for name in my_companies:
        row_result = results.setdefault(name, {"x": {"parameters": {}}, "y": {"parameters": {}}})
        for axis_key, axis_label, pname in gaps[name]:
            if pname in (row_result[axis_key].get("parameters") or {}):
                continue
            defs = x_defs if axis_key == "x" else y_defs
            query = build_defined_small_group_query(
                name, [pname], defs, market=args.market,
                market_definition=market_definition,
                context=ctx_by.get(name, ""), headquarters=hq_by.get(name, ""),
            )
            answer = _ask_retry(query)
            got = parse_small_group_scores(answer, [pname], query) if answer else {}
            status = "OK" if pname in got else "MISS"
            if pname not in got:
                # Normal query left no "Score: NN / 100" line at all --
                # likely the model refused to score instead of missing the
                # format. Force it: absent evidence is a valid LOW score,
                # not a reason to withhold a number.
                forced_query = build_forced_score_query(
                    name, pname, defs, market=args.market,
                    market_definition=market_definition,
                    context=ctx_by.get(name, ""), headquarters=hq_by.get(name, ""),
                )
                forced_answer = _ask_retry(forced_query)
                got = (
                    parse_small_group_scores(forced_answer, [pname], forced_query)
                    if forced_answer else {}
                )
                status = "OK (forced)" if pname in got else "MISS"
            if pname in got:
                row_result[axis_key]["parameters"][pname] = got[pname]
                done_slots += 1
            _write_sidecar()
            mins = (time.monotonic() - started) / 60
            print(f"  [{done_slots}/{total_slots}] {name} / {pname}: {status} "
                  f"({mins:.1f}m elapsed)", flush=True)

    print(f"\ndone: filled {done_slots}/{total_slots} missing parameter slots")
    print(f"sidecar: {side_path}")
    print("merge this into the checkpoint the same way other sidecars merge "
          "(param_detail_prescored*.json glob already picks it up)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
