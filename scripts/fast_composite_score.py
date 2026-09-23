#!/usr/bin/env python3
"""Fast pass: composite X/Y for every verified company, 10 per query.

Two-phase scoring for a market under a deadline:
  1. THIS script — one number per axis per company, ~10/query. No evidence,
     no per-parameter breakdown. Enough to plot every company and split
     Top 20 from the rest.
  2. scripts/prescore_verified.py — full per-parameter evidence, but only
     for the Top 20 that land on the chart. Nobody reads the evidence
     behind an "Other Noticeable Player" row, so it is not worth the
     ~2 queries/company those rows would otherwise cost.

This is the SAME query shape expand_quadrant_score.py already uses for its
batch-scoring pass (build_batch_score_query / score_companies) — just run
standalone, on its own browser profile, against the verified pool.

    .\\.venv\\Scripts\\python.exe scripts\\fast_composite_score.py ^
        --market "Advanced Seismic Data Processing Solutions Market" ^
        --country global --slot 9 --batch 10
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
    ap.add_argument("--slot", type=int, default=9)
    ap.add_argument("--batch", type=int, default=10)
    ap.add_argument(
        "--shard", type=int, default=0,
        help="this instance's shard index (0-based), for splitting the "
             "verified pool across several browsers",
    )
    ap.add_argument(
        "--shards", type=int, default=1,
        help="total number of shards. Each shard's slice is fixed by "
             "position, so shards can run concurrently and never overlap.",
    )
    args = ap.parse_args()

    profile = ROOT / "data" / f"ai_mode_batch_{args.slot:02d}"
    os.environ["GOOGLE_AI_MODE_PROFILE_DIR"] = str(profile)
    os.environ["GOOGLE_AI_MODE_BROWSER"] = "chromium"
    os.environ["GOOGLE_AI_MODE_ENABLED"] = "true"
    scope = _scope_for(args.market)
    if scope:
        os.environ["MARKET_SCOPE"] = scope

    from vendor_intel.config import Settings
    from vendor_intel.pipeline.web_expand import default_output_dir
    from vendor_intel.quadrant import ai_mode_scorer as S
    from vendor_intel.quadrant.axis_define import define_market_axes
    from vendor_intel.quadrant.industry_select import select_industry

    out_dir = Path(default_output_dir(args.market, args.country))
    ckpt_path = out_dir / "chatgpt_checkpoint_batch_all.json"
    if not ckpt_path.exists():
        print(f"ERROR: no checkpoint at {ckpt_path}", file=sys.stderr)
        return 2

    state = json.loads(ckpt_path.read_text(encoding="utf-8"))
    data = state.get("data") or {}
    verified = data.get("verified") or []
    if not verified:
        print("nothing verified yet")
        return 1

    names = [str(r.get("Company") or r.get("name") or "").strip() for r in verified]
    names = [n for n in names if n]
    if args.shards > 1:
        # Fixed slice by position, not a hash: every shard's boundaries are
        # deterministic from the SAME verified list, so two shards can never
        # both claim a company even if launched slightly out of sync.
        names = names[args.shard::args.shards]
        print(f"shard {args.shard}/{args.shards}: {len(names)} of this "
              f"market's companies")

    settings = Settings.load()
    industry = select_industry(args.market, geography=args.country, settings=settings)
    industry = define_market_axes(
        args.market, industry, geography=args.country, settings=settings
    )
    x_feats = list(industry.get("x") or [])
    y_feats = list(industry.get("y") or [])
    if not x_feats or not y_feats:
        print("ERROR: could not resolve axis parameters", file=sys.stderr)
        return 2

    print(f"fast composite scoring {len(names)} companies, batch={args.batch}")
    print(f"  X: {', '.join(x_feats)}")
    print(f"  Y: {', '.join(y_feats)}")

    # One sidecar per shard, not one shared file: three processes doing a
    # non-atomic read-modify-write on the same JSON would silently drop
    # whichever write lost the race. Each shard owns its own slice of
    # companies, so there is nothing to merge until all shards are done.
    suffix = f"_shard{args.shard}" if args.shards > 1 else ""
    side_path = out_dir / f"composite_scores_fast{suffix}.json"
    scores: dict[str, tuple] = {}
    if side_path.exists():
        try:
            raw = json.loads(side_path.read_text(encoding="utf-8"))
            scores = {k: tuple(v) for k, v in raw.items()}
        except Exception:  # noqa: BLE001
            scores = {}
    remaining = [n for n in names if n not in scores]
    print(f"  already scored: {len(scores)}  |  remaining: {len(remaining)}")

    started = time.monotonic()

    def _write_sidecar() -> None:
        tmp = side_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(scores, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, side_path)

    def _on_batch(start: int, chunk: list[str], out: dict) -> None:
        for n in chunk:
            if n in out:
                scores[n] = out[n]
        _write_sidecar()
        mins = (time.monotonic() - started) / 60
        got = sum(1 for v in scores.values() if v[0] is not None and v[1] is not None)
        print(f"  batch [{start + 1}-{start + len(chunk)}]: "
              f"{got}/{len(scores)} scored so far ({mins:.1f}m)", flush=True)

    if remaining:
        S.score_companies(
            remaining,
            x_parameters=x_feats,
            y_parameters=y_feats,
            market=args.market,
            batch=args.batch,
            on_batch=_on_batch,
        )

    got = sum(1 for v in scores.values() if v[0] is not None and v[1] is not None)
    elapsed = (time.monotonic() - started) / 60
    label = f" (shard {args.shard}/{args.shards})" if args.shards > 1 else ""
    print(f"\ndone{label}: {got}/{len(names)} companies have both X and Y")
    print(f"elapsed {elapsed:.1f} min")
    print(f"sidecar: {side_path}")
    if args.shards > 1:
        print("run merge_composite_shards.py once every shard has finished")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
