#!/usr/bin/env python3
"""Seed composite_scores_fast.json into the checkpoint, then resume the real
pipeline so it does quadrant assignment, 5-per-quadrant Top 20 selection, and
export -- using the pipeline's OWN tested logic rather than a re-implementation.

score_expand_rows() reads ckpt.data("xy_partial") at the top of its run and
copies X/Y/Overall/Quadrant onto any row it matches by lowercased Company
name, skipping the AI Mode call for rows that already have both scores. This
writes that cache from our composite pass, so resuming the pipeline scores
NOTHING it doesn't have to -- it goes straight to select_chart_rows_by_quadrant
_country (5 per quadrant), Top 20 vs Other, and the HTML/xlsx export.

    .\\.venv\\Scripts\\python.exe scripts\\seed_composite_and_resume.py ^
        --market "Advanced Seismic Data Processing Solutions Market" ^
        --country global
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))


def _overall(x: int, y: int) -> int:
    return round((x + y) / 2)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--market", required=True)
    ap.add_argument("--country", default="global")
    args = ap.parse_args()

    from vendor_intel.pipeline.web_expand import default_output_dir
    from vendor_intel.quadrant.matrix_rollup import normalize_row_score_floor
    from vendor_intel.quadrant.rating_map import assign_quadrants_absolute_median

    out_dir = Path(default_output_dir(args.market, args.country))
    ckpt_path = out_dir / "chatgpt_checkpoint_batch_all.json"
    scores_path = out_dir / "composite_scores_fast.json"

    if not ckpt_path.exists() or not scores_path.exists():
        print("ERROR: checkpoint or composite scores missing", file=sys.stderr)
        return 2

    state = json.loads(ckpt_path.read_text(encoding="utf-8"))
    scores = json.loads(scores_path.read_text(encoding="utf-8"))
    data = state.setdefault("data", {})
    verified = data.get("verified") or []

    # One row per unique company name (verified holds one row per brand,
    # which can repeat a company several times under different products).
    by_company: dict[str, dict] = {}
    for r in verified:
        name = str(r.get("Company") or r.get("name") or "").strip()
        if name and name not in by_company:
            by_company[name] = r

    scored_names = [n for n in by_company if n in scores and
                    scores[n][0] is not None and scores[n][1] is not None]
    print(f"verified unique companies: {len(by_company)}")
    print(f"with a composite score   : {len(scored_names)}")

    # Row-level proportional floor normalization -- the SAME rule
    # expand_quadrant_score.py applies to every AI-Mode-scored row. Without
    # it, a market where the model's own scores run low across the board
    # (measured here: 87 of 115 companies under 65 on X or Y) ships raw
    # scores that read as failing grades on a chart whose floor is meant to
    # be 65. Quadrant assignment and Overall are both computed from the
    # NORMALIZED pair, matching the real pipeline's order of operations.
    normalized: dict[str, tuple[int, int]] = {}
    for n in scored_names:
        x_raw, y_raw = scores[n]
        x_f, y_f = normalize_row_score_floor(x_raw, y_raw)
        normalized[n] = (int(round(x_f)), int(round(y_f)))

    xs = [normalized[n][0] for n in scored_names]
    ys = [normalized[n][1] for n in scored_names]
    quads, _midx, _midy = assign_quadrants_absolute_median(xs, ys)

    xy_partial = []
    for name, quad in zip(scored_names, quads):
        x, y = normalized[name]
        x_raw, y_raw = scores[name]
        row = by_company[name]
        xy_partial.append({
            "Company": name,
            "Brand": str(row.get("brand_name") or row.get("Market Offering") or name),
            "X Score": str(x),
            "Y Score": str(y),
            "Overall Score": str(_overall(x, y)),
            "Quadrant": quad,
            "Industry Category": "",
            "X Score Raw": str(x_raw),
            "Y Score Raw": str(y_raw),
        })

    data["xy_partial"] = xy_partial
    ckpt_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

    from collections import Counter
    print(f"\nseeded xy_partial: {len(xy_partial)} rows")
    print("quadrant split:", dict(Counter(quads)))
    print(f"\nwrote {ckpt_path}")
    print("next: resume run_chatgpt_expand.py for this market to let the "
          "pipeline pick the Top 20 (5/quadrant) and export the report")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
