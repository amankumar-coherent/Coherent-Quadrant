#!/usr/bin/env python3
"""Re-apply ROW-LEVEL proportional-floor-65 normalization to an already-scored
market.

Supersedes this script's original population-based behaviour, which min-max
normalized X and Y across the whole market. That was wrong: it made one
company's score depend on every other company's, so adding a low-scoring
company shifted everyone. The current rule
(matrix_rollup.normalize_row_score_floor) transforms each row independently:

  * both X and Y >= 65        -> unchanged
  * both below 65             -> scale both by 65/min(x, y), cap at 100
                                 (preserves their relative relationship)
  * exactly one below 65      -> raise that one to 65, leave the other alone

Overall is then recomputed from the normalized X/Y with the existing formula
(never `max(original_overall, 65)`), and quadrants are reassigned.

IMPORTANT — reads the ORIGINAL raw scores from the xy audit file, not the
checkpoint. The checkpoint's X/Y have already been population-normalized, so
re-normalizing those would compound the distortion. The audit's `x`/`y` are
the true pre-normalization values.

Pure post-processing: no re-crawling and no LLM re-scoring. Only run it after
the market's run_chatgpt_expand.py process has exited — it edits the
checkpoint in place.

  .\\.venv\\Scripts\\python.exe scripts\\apply_score_normalization.py --market "Global Animal Healthcare Market"
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))


def _key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name or "").lower())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market", "-q", required=True)
    parser.add_argument("--country", "-c", default="global")
    parser.add_argument("--batch", "-b", default="all")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without writing any file.",
    )
    args = parser.parse_args()

    from vendor_intel.pipeline.expand_quadrant_score import (
        export_expand_quadrant_outputs,
        to_company_detail_rows,
    )
    from vendor_intel.pipeline.web_expand import (
        default_output_dir,
        resolve_final_path,
        write_final_xlsx,
    )
    from vendor_intel.quadrant.matrix_rollup import normalize_row_score_floor
    from vendor_intel.quadrant.rating_map import (
        assign_quadrants_absolute_median,
        compute_overall,
    )

    out_dir = default_output_dir(args.market, args.country)
    ckpt_path = out_dir / f"chatgpt_checkpoint_batch_{args.batch.lower()}.json"
    xy_audit_path = out_dir / f"chatgpt_xy_scores_batch_{args.batch.lower()}.json"
    top_audit_path = out_dir / f"chatgpt_expand_batch_{args.batch.lower()}_audit.json"

    if not ckpt_path.exists():
        print(f"ERROR: checkpoint not found: {ckpt_path}", file=sys.stderr)
        return 1
    if not xy_audit_path.exists():
        print(f"ERROR: xy audit not found: {xy_audit_path}", file=sys.stderr)
        return 1

    state = json.loads(ckpt_path.read_text(encoding="utf-8"))
    xy_rows = state.get("data", {}).get("xy_rows") or []
    if not xy_rows:
        print(f"ERROR: no data.xy_rows in checkpoint: {ckpt_path}", file=sys.stderr)
        return 1

    xy_audit = json.loads(xy_audit_path.read_text(encoding="utf-8"))
    audit_rows = xy_audit.get("rows") or []
    # The audit carries each company's TRUE pre-normalization X/Y.
    raw_by_key = {
        _key(a.get("company")): a
        for a in audit_rows
        if a.get("x") is not None and a.get("y") is not None
    }
    if not raw_by_key:
        print(
            "ERROR: xy audit has no original x/y values — cannot recover the "
            "pre-normalization scores. A full re-score is required instead.",
            file=sys.stderr,
        )
        return 1

    norm_x: list[int] = []
    norm_y: list[int] = []
    missing = 0
    for row in xy_rows:
        src = raw_by_key.get(_key(row.get("Company")))
        if src is None:
            # No audit entry: fall back to the row's current values so an
            # unmatched company is left alone rather than silently zeroed.
            missing += 1
            cx = float(row.get("X Score") or 0)
            cy = float(row.get("Y Score") or 0)
        else:
            cx = float(src.get("x") or 0)
            cy = float(src.get("y") or 0)
        nx, ny = normalize_row_score_floor(cx, cy)
        norm_x.append(int(round(nx)))
        norm_y.append(int(round(ny)))

    quads, mid_x, mid_y = assign_quadrants_absolute_median(norm_x, norm_y)

    changed = 0
    for row, nx, ny, quad in zip(xy_rows, norm_x, norm_y, quads):
        src = raw_by_key.get(_key(row.get("Company"))) or {}
        ox = src.get("x")
        oy = src.get("y")
        if str(row.get("X Score")) != str(nx) or str(row.get("Y Score")) != str(ny):
            changed += 1
        if args.dry_run:
            continue
        row["X Score"] = str(nx)
        row["Y Score"] = str(ny)
        row["Overall Score"] = str(compute_overall(nx, ny))
        row["Quadrant"] = quad
        # Audit fields stay internal — never rendered in the HTML.
        if ox is not None:
            row["x_original"] = str(ox)
            row["y_original"] = str(oy)
            row["normalization_applied"] = str(
                bool(int(round(float(ox))) != nx or int(round(float(oy))) != ny)
            ).lower()
            row["normalization_method"] = "proportional_floor_65"

    print(f"Rows: {len(xy_rows)} | changed: {changed} | unmatched in audit: {missing}")
    print(f"After: X range {min(norm_x)}-{max(norm_x)}, Y range {min(norm_y)}-{max(norm_y)}")
    if min(norm_x) < 65 or min(norm_y) < 65:
        print("WARNING: a normalized score is still below 65 — investigate.")

    if args.dry_run:
        print("(dry run — nothing written)")
        return 0

    xy_audit["quadrant_mid_x"] = mid_x
    xy_audit["quadrant_mid_y"] = mid_y
    xy_audit["normalization_method"] = "proportional_floor_65"
    xy_audit_path.write_text(
        json.dumps(xy_audit, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    detail_rows = to_company_detail_rows(xy_rows, args.market, xy_audit)
    state["data"]["xy_rows"] = xy_rows
    state["data"]["detail_rows"] = detail_rows
    ckpt_path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")

    extras = export_expand_quadrant_outputs(
        out_dir, detail_rows, args.market, country=args.country, audit=xy_audit, chart_n=20
    )

    if top_audit_path.exists():
        top_audit = json.loads(top_audit_path.read_text(encoding="utf-8"))
    else:
        top_audit = {"query": args.market, "country": args.country}
    top_audit["xy_scoring"] = {k: v for k, v in xy_audit.items() if k != "rows"}
    xlsx = resolve_final_path(args.market, args.country, out_dir, None)
    write_final_xlsx(xlsx, xy_rows, "Companies", top_audit, detail_rows=detail_rows)
    top_audit_path.write_text(
        json.dumps(top_audit, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"Updated {len(xy_rows)} rows -> {xlsx}")
    print(f"Regenerated report -> {extras['html']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
