#!/usr/bin/env python3
"""Supporting points for the PARTS of a parameter the evidence leaves bare.

A parameter name often joins two or three measures ("Revenue & Growth").
When its supporting points cover only one (revenue figures, nothing on
growth), this asks AI Mode about the missing part alone and adds what it
finds to that parameter's supporting points -- every copy of the parameter in
the evidence files, under the shared-file lock. The score and the "why" line
are left as they are. Each part is asked once per market
(``_pipeline/part_fill_asked.json``), so a part with nothing documented is not
asked again on every round. Owner 2026-10-15.

The orchestrator runs it per evidence round over the companies in
``_pipeline/part_fill_todo.json`` ({name: [[axis, parameter, part], ...]}).
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


def _row_name(r: dict) -> str:
    return str(r.get("Company") or r.get("company") or r.get("name") or "").strip()


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

    os.environ["GOOGLE_AI_MODE_PROFILE_DIR"] = str(ROOT / "data" / f"ai_mode_batch_{args.slot:02d}")
    os.environ["GOOGLE_AI_MODE_BROWSER"] = "chromium"
    os.environ["GOOGLE_AI_MODE_ENABLED"] = "true"

    from vendor_intel.pipeline.quadrant_pipeline import PART_ASKED_FILE, update_json_locked
    from vendor_intel.pipeline.web_expand import default_output_dir
    from vendor_intel.quadrant.ai_mode_scorer import build_part_query, parse_part_evidence
    from vendor_intel.scraping.google_ai_mode import ask as ai_ask

    spec = json.loads(Path(args.fixed_axes).read_text(encoding="utf-8"))
    defs = {"x": spec["parameter_definitions"]["x"], "y": spec["parameter_definitions"]["y"]}
    out_dir = Path(default_output_dir(args.market, args.country))
    pipe = out_dir / "_pipeline"
    todo = json.loads((pipe / "part_fill_todo.json").read_text(encoding="utf-8"))
    names = [n for n in json.loads(Path(args.only_file).read_text(encoding="utf-8")) if n in todo]
    mine = names[args.shard::args.shards]
    rows = {}
    try:
        state = json.loads((out_dir / "chatgpt_checkpoint_batch_all.json").read_text(encoding="utf-8"))
        rows = {_row_name(r): r for r in (state.get("data") or {}).get("verified") or []}
    except (OSError, ValueError):
        pass
    total = sum(len(todo[n]) for n in mine)
    print(f"shard {args.shard}/{args.shards}: {len(mine)} companies, {total} parameter parts to fill")

    done = added_total = 0
    for name in mine:
        row = rows.get(name, {})
        for axis, param, part in todo[name]:
            query = build_part_query(
                name, param, part, str(defs[axis].get(param) or ""), market=args.market,
                context=str(row.get("Summary") or row.get("snippet") or row.get("why_related") or ""),
                headquarters=str(row.get("Headquarters") or row.get("headquarters") or ""))
            found = []
            for attempt in (1, 2):
                try:
                    answer = ai_ask(query)
                    found = parse_part_evidence(answer, query)
                    break
                except Exception as err:  # noqa: BLE001
                    print(f"    attempt {attempt}: {type(err).__name__}: {str(err)[:80]}", flush=True)
            added = 0
            if found:
                def mutate(data: dict, name=name, axis=axis, param=param, found=found) -> None:
                    nonlocal added
                    v = (((data.get(name) or {}).get(axis) or {}).get("parameters") or {}).get(param)
                    if not isinstance(v, dict):
                        return
                    have = {str(e.get("claim") or "").strip().lower() for e in v.get("evidence") or []
                            if isinstance(e, dict)}
                    # The new findings replace an absence-only bullet for the parameter.
                    ev = [e for e in v.get("evidence") or [] if not (
                        isinstance(e, dict) and str(e.get("claim") or "").strip().lower().startswith("not available"))]
                    new = [e for e in found if str(e.get("claim") or "").strip().lower() not in have]
                    v["evidence"] = ev + new
                    added = max(added, len(new))
                for side in sorted(out_dir.glob("param_detail_prescored*.json")):
                    try:
                        has = param in ((((json.loads(side.read_text(encoding="utf-8")).get(name) or {})
                                          .get(axis) or {}).get("parameters")) or {})
                    except (OSError, ValueError):
                        continue
                    if has:
                        update_json_locked(side, mutate)

            def mark(data: dict, key=f"{name}|{param}|{part}") -> None:
                data.setdefault("asked", [])
                if key not in data["asked"]:
                    data["asked"].append(key)
            path = pipe / PART_ASKED_FILE
            if not path.exists():
                path.write_text(json.dumps({"asked": []}), encoding="utf-8")
            update_json_locked(path, mark)
            done += 1
            added_total += added
            print(f"  [{done}/{total}] {name} / {param} / {part}: +{added} supporting point(s)", flush=True)
            time.sleep(0.2)
    print(f"done: {done} parts asked, {added_total} supporting points added")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
