#!/usr/bin/env python3
"""Broad "give me N more" discovery rounds on several browsers at once.

For a market where GEOGRAPHY-gated asks ("headquartered in Norway") return
nothing once the exclusion list is long, the productive channel is the
UNCONSTRAINED broad round -- confirmed live on Marine Seismic Data
Processing Services: geography sweeps found 0 across 64 countries, while
plain "give me 15 more" rounds surfaced real independent specialists
immediately. A single browser's rounds naturally slow as the easy answers
run out; running several rounds in parallel, each against the checkpoint's
CURRENT exclusion list refreshed before every round, keeps the discovery
rate up without waiting on one browser's pacing.

Each shard runs its own round loop and appends straight into its own
sidecar (never the checkpoint directly -- same non-atomic-write hazard as
every other parallel sweep here). Unlike the country/city sweeps, there is
no natural "slice" to split across shards: every shard asks the SAME broad
question, so duplicates across shards are expected and are deduped by
merge_broad_sweep.py, not by dividing the work up front.

    .\\.venv\\Scripts\\python.exe scripts\\parallel_broad_sweep.py ^
        --market "Marine Seismic Data Processing Services Market" ^
        --country global --slot 41 --shard 0 --rounds 20 --batch 15
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


def _scope_for(market: str) -> str:
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
    ap.add_argument("--slot", type=int, required=True)
    ap.add_argument("--shard", type=int, required=True)
    ap.add_argument("--batch", type=int, default=15)
    ap.add_argument("--rounds", type=int, default=20)
    ap.add_argument(
        "--empty-stop", type=int, default=3,
        help="stop this shard after this many consecutive empty rounds",
    )
    ap.add_argument("--player-type", default="Solution Provider")
    ap.add_argument(
        "--strict-spec", default="",
        help="path to a JSON spec for build_strict_service_round_prompt() "
             "-- see parallel_country_sweep.py --strict-spec",
    )
    ap.add_argument(
        "--global-spec", default="",
        help="path to a JSON spec ({market, market_definition, "
             "qualifying_services, search_terms, excluded_categories}) for "
             "build_global_strict_round_prompt() -- the operator's own "
             "global mega-prompt template, batched. Takes precedence over "
             "--strict-spec if both are given.",
    )
    ap.add_argument("--out-dir", default="")
    args = ap.parse_args()

    profile = ROOT / "data" / f"ai_mode_batch_{args.slot:02d}"
    os.environ["GOOGLE_AI_MODE_PROFILE_DIR"] = str(profile)
    os.environ["GOOGLE_AI_MODE_BROWSER"] = "chromium"
    os.environ["GOOGLE_AI_MODE_ENABLED"] = "true"
    scope = _scope_for(args.market)
    if scope:
        os.environ["MARKET_SCOPE"] = scope

    from vendor_intel.pipeline.discovery_rounds import (
        build_global_strict_round_prompt,
        build_round_prompt,
        build_strict_service_round_prompt,
    )
    from vendor_intel.pipeline.web_expand import default_output_dir
    from vendor_intel.scraping.google_ai_mode import ask as ai_ask
    from vendor_intel.scraping.google_ai_mode import parse_json_answer

    strict_spec = (
        json.loads(Path(args.strict_spec).read_text(encoding="utf-8"))
        if args.strict_spec else None
    )
    global_spec = (
        json.loads(Path(args.global_spec).read_text(encoding="utf-8"))
        if args.global_spec else None
    )

    out_dir = Path(args.out_dir) if args.out_dir else Path(default_output_dir(args.market, args.country))
    ckpt_path = out_dir / "chatgpt_checkpoint_batch_all.json"
    if not ckpt_path.exists():
        print(f"ERROR: no checkpoint at {ckpt_path}", file=sys.stderr)
        return 2

    side_path = out_dir / f"broad_sweep_shard{args.shard}.json"
    found: list[dict] = []
    if side_path.exists():
        try:
            found = json.loads(side_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            found = []

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
        tmp.write_text(json.dumps(found, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, side_path)

    def _current_exclusions() -> list[str]:
        # Re-read the checkpoint before EVERY round: several shards are
        # discovering in parallel, and a shard that only knew its own
        # names would re-find what another shard already has. The
        # checkpoint itself is not updated until merge_broad_sweep.py runs,
        # so this also folds in this shard's own sidecar so it never
        # re-asks for a name it already found this run.
        state = json.loads(ckpt_path.read_text(encoding="utf-8"))
        existing = (state.get("data") or {}).get("recalled") or []
        names = [str(r.get("Company") or r.get("name") or "") for r in existing]
        names += [str(r.get("company") or r.get("brand") or "") for r in found]
        return [n for n in names if n]

    started = time.monotonic()
    empty_streak = 0
    for i in range(1, args.rounds + 1):
        excluded = _current_exclusions()
        if global_spec:
            system, user = build_global_strict_round_prompt(
                global_spec["market"], global_spec["market_definition"],
                global_spec["qualifying_services"], global_spec["search_terms"],
                global_spec["excluded_categories"],
                excluded_names=excluded, batch=args.batch,
            )
        elif strict_spec:
            system, user = build_strict_service_round_prompt(
                strict_spec["market"], strict_spec["market_definition"],
                strict_spec["qualifying_services"], strict_spec["excluded_categories"],
                excluded_names=excluded, batch=args.batch,
            )
        else:
            system, user = build_round_prompt(
                args.market, args.player_type,
                excluded_names=excluded, batch=args.batch, scope=scope,
            )
        answer = _ask_retry(f"{system}\n\n{user}")
        new_rows: list[dict] = []
        if answer:
            try:
                data = parse_json_answer(answer, require_key="companies")
                new_rows = (data or {}).get("companies") or []
            except Exception:  # noqa: BLE001
                new_rows = []
        found.extend(new_rows)
        _write_sidecar()
        mins = (time.monotonic() - started) / 60
        print(f"  [{i}/{args.rounds}] round {i}: +{len(new_rows)} "
              f"(shard total {len(found)}, {mins:.1f}m elapsed)", flush=True)
        empty_streak = empty_streak + 1 if not new_rows else 0
        if empty_streak >= args.empty_stop:
            print(f"  stopping: {empty_streak} consecutive empty rounds",
                  flush=True)
            break

    print(f"\ndone: {len(found)} candidate rows from this shard "
          f"(duplicates against other shards not yet removed)")
    print(f"sidecar: {side_path}")
    print("run merge_broad_sweep.py once every shard has finished")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
