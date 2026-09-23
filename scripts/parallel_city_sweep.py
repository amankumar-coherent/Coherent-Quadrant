#!/usr/bin/env python3
"""Sweep CITIES (not countries) for a market on several browsers at once.

For a consolidated, specialist market a country-wide ask ("headquartered in
Norway") returns nothing once the country sweep has already picked up the
national majors -- but the industry clusters in specific CITIES the country
sweep never asks about by name (Stavanger, not "Norway"; Houston, not "the
United States"). This is parallel_country_sweep.py's same one-ask-per-focus-
region loop, pointed at a curated city list instead of the fixed 64-country
list.

    .\\.venv\\Scripts\\python.exe scripts\\parallel_city_sweep.py ^
        --market "Marine Seismic Data Processing Services Market" ^
        --country global --slot 45 --shard 0 --shards 4 ^
        --cities-file config/marine_seismic_cities.txt
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
    ap.add_argument("--player-type", default="Solution Provider")
    ap.add_argument(
        "--cities-file", required=True,
        help="path to a text file, one 'City, Country' focus region per "
             "line (blank lines and # comments skipped)",
    )
    ap.add_argument("--out-dir", default="")
    ap.add_argument(
        "--strict-spec", default="",
        help="path to a JSON spec for build_strict_service_round_prompt() "
             "-- see parallel_country_sweep.py --strict-spec",
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

    all_cities: list[str] = []
    for line in Path(args.cities_file).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            all_cities.append(line)

    my_cities = all_cities[args.shard::args.shards]
    print(f"shard {args.shard}/{args.shards}: {len(my_cities)} cities "
          f"of {len(all_cities)} total")

    # Sidecar per shard, same reasoning as parallel_country_sweep.py: several
    # processes doing a non-atomic read-modify-write on ONE file would drop
    # each other's rows.
    side_path = out_dir / f"city_sweep_shard{args.shard}.json"
    found: list[dict] = []
    if side_path.exists():
        try:
            found = json.loads(side_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            found = []
    done_cities = {row.get("_swept_city") for row in found}

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

    state = json.loads(ckpt_path.read_text(encoding="utf-8"))
    existing = (state.get("data") or {}).get("recalled") or []
    excluded = [str(r.get("Company") or r.get("name") or "") for r in existing]
    print(f"  excluding {len(excluded)} already-known companies")

    started = time.monotonic()
    for i, city in enumerate(my_cities, 1):
        if city in done_cities:
            continue
        if strict_spec:
            system, user = build_strict_service_round_prompt(
                strict_spec["market"], strict_spec["market_definition"],
                strict_spec["qualifying_services"], strict_spec["excluded_categories"],
                excluded_names=excluded, batch=args.batch, focus_region=city,
            )
        else:
            system, user = build_round_prompt(
                args.market, args.player_type,
                excluded_names=excluded, batch=args.batch, scope=scope,
                focus_region=city, country=args.country if args.country != "global" else "",
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
            row["_swept_city"] = city
            found.append(row)
            name = str(row.get("company") or row.get("brand") or "")
            if name:
                excluded.append(name)
        if not new_rows:
            found.append({"_swept_city": city, "_empty": True})
        _write_sidecar()
        mins = (time.monotonic() - started) / 60
        print(f"  [{i}/{len(my_cities)}] {city}: +{len(new_rows)} "
              f"({mins:.1f}m elapsed)", flush=True)

    total_new = sum(1 for r in found if not r.get("_empty"))
    print(f"\ndone: {total_new} new companies from {len(my_cities)} cities")
    print(f"sidecar: {side_path}")
    print("run merge_city_sweep.py once every shard has finished")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
