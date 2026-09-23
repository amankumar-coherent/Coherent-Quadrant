#!/usr/bin/env python3
"""Sweep countries for a market on 3 browsers at once, one country per ask.

discover_in_rounds() already escalates broad -> region -> country, but it is
one long-running loop on one browser: a shard can't safely interrupt its
internal region_queue/country_queue state. This is the standalone
equivalent for when the broad rounds have thinned out and what is left is
"ask every one of the 64 countries individually" -- a job that is
naturally parallel, since each country's answer depends on none of the
others (only the shared exclusion list, which we merge after each round).

Each instance owns a disjoint SLICE of the 64 countries (fixed by position,
not a hash), asks each once, and appends new companies straight to the
checkpoint's `recalled` list. Running 3 of these searches ~3x the countries
per minute of wall-clock.

    .\\.venv\\Scripts\\python.exe scripts\\parallel_country_sweep.py ^
        --market "Advanced Seismic Data Processing Solutions Market" ^
        --country global --slot 13 --shard 0 --shards 3
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
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--shards", type=int, default=1)
    ap.add_argument("--batch", type=int, default=10)
    ap.add_argument(
        "--player-type", default="Solution Provider",
        help="the ALLOWED_PLAYER_TYPES label discovery should search for "
             "(e.g. 'Service Provider'), matching whatever the checkpoint's "
             "market_analysis.primary_participant was forced to",
    )
    ap.add_argument(
        "--out-dir", default="",
        help="explicit output directory, overriding the market/country slug "
             "-- use this when the run was started with run_chatgpt_expand.py "
             "--out-dir so the checkpoint lives somewhere non-default",
    )
    ap.add_argument(
        "--strict-spec", default="",
        help="path to a JSON spec ({market, market_definition, "
             "qualifying_services, excluded_categories}) with an "
             "OPERATOR-AUTHORED strict query -- uses "
             "build_strict_service_round_prompt() instead of the generic "
             "build_round_prompt(), for markets whose exclusion list needs "
             "to be more specific than the generic one (e.g. also "
             "rejecting standalone software vendors and multi-client data "
             "libraries by name).",
    )
    args = ap.parse_args()

    profile = ROOT / "data" / f"ai_mode_batch_{args.slot:02d}"
    os.environ["GOOGLE_AI_MODE_PROFILE_DIR"] = str(profile)
    os.environ["GOOGLE_AI_MODE_BROWSER"] = "chromium"
    os.environ["GOOGLE_AI_MODE_ENABLED"] = "true"
    scope = _scope_for(args.market)
    if scope:
        os.environ["MARKET_SCOPE"] = scope

    from vendor_intel.pipeline.discovery_rounds import (
        build_round_prompt,
        build_strict_service_round_prompt,
    )
    from vendor_intel.pipeline.geo_rotation import COUNTRIES_BY_REGION
    from vendor_intel.pipeline.web_expand import default_output_dir
    from vendor_intel.scraping.google_ai_mode import ask as ai_ask
    from vendor_intel.scraping.google_ai_mode import parse_json_answer

    strict_spec = (
        json.loads(Path(args.strict_spec).read_text(encoding="utf-8"))
        if args.strict_spec else None
    )

    out_dir = Path(args.out_dir) if args.out_dir else Path(default_output_dir(args.market, args.country))
    ckpt_path = out_dir / "chatgpt_checkpoint_batch_all.json"
    if not ckpt_path.exists():
        print(f"ERROR: no checkpoint at {ckpt_path}", file=sys.stderr)
        return 2

    all_countries: list[str] = []
    for region, countries in COUNTRIES_BY_REGION.items():
        all_countries.extend(countries)

    my_countries = all_countries[args.shard::args.shards]
    print(f"shard {args.shard}/{args.shards}: {len(my_countries)} countries "
          f"of {len(all_countries)} total")

    # Sidecar per shard: several processes appending to the SAME checkpoint
    # with a non-atomic read-modify-write would drop each other's rows. Each
    # shard writes only its own new-companies file; nothing else touches the
    # checkpoint until merge_country_sweep.py runs after every shard is done.
    side_path = out_dir / f"country_sweep_shard{args.shard}.json"
    found: list[dict] = []
    if side_path.exists():
        try:
            found = json.loads(side_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            found = []
    done_countries = {row.get("_swept_country") for row in found}

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

    # Exclusion list from what the checkpoint already has, refreshed once at
    # the start. A live-shared exclusion list across 3 processes would need
    # its own coordination; the discovery/verify dedupe pass downstream
    # already removes any cross-shard duplicates, so skipping that here is
    # a real but acceptable trade for running unattended.
    state = json.loads(ckpt_path.read_text(encoding="utf-8"))
    existing = (state.get("data") or {}).get("recalled") or []
    excluded = [str(r.get("Company") or r.get("name") or "") for r in existing]
    print(f"  excluding {len(excluded)} already-known companies")

    started = time.monotonic()
    for i, country in enumerate(my_countries, 1):
        if country in done_countries:
            continue
        if strict_spec:
            system, user = build_strict_service_round_prompt(
                strict_spec["market"], strict_spec["market_definition"],
                strict_spec["qualifying_services"], strict_spec["excluded_categories"],
                excluded_names=excluded, batch=args.batch, focus_region=country,
            )
        else:
            system, user = build_round_prompt(
                args.market, args.player_type,
                excluded_names=excluded, batch=args.batch, scope=scope,
                focus_region=country, country=args.country if args.country != "global" else "",
            )
        answer = _ask_retry(f"{system}\n\n{user}")
        new_rows: list[dict] = []
        if answer:
            try:
                data = parse_json_answer(answer, require_key="companies")
                new_rows = (data or {}).get("companies") or []
            except Exception:  # noqa: BLE001
                new_rows = []
        for row in new_rows:
            row["_swept_country"] = country
            found.append(row)
            name = str(row.get("company") or row.get("brand") or "")
            if name:
                excluded.append(name)
        # A round with 0 companies still records the country as swept, or a
        # resume would re-ask a country that genuinely has none.
        if not new_rows:
            found.append({"_swept_country": country, "_empty": True})
        _write_sidecar()
        mins = (time.monotonic() - started) / 60
        print(f"  [{i}/{len(my_countries)}] {country}: +{len(new_rows)} "
              f"({mins:.1f}m elapsed)", flush=True)

    total_new = sum(1 for r in found if not r.get("_empty"))
    print(f"\ndone: {total_new} new companies from {len(my_countries)} countries")
    print(f"sidecar: {side_path}")
    print("run merge_country_sweep.py once every shard has finished")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
