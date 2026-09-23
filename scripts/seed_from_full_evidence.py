#!/usr/bin/env python3
"""Seed xy_partial straight from full per-parameter evidence sidecars.

For a fixed-axes market (10 operator-authored parameters, scored with full
evidence via prescore_verified.py for EVERY verified company, not just a
Top 20) there is no separate fast-composite pass: the X/Y score for a
company starts as the mean of its 5 already-scored X (or Y) parameters, then
each axis is independently banded onto [65, 100] via normalize_cohort_to_
band(), by that company's real rank against every OTHER company's raw mean
on the SAME axis.

This replaced two earlier attempts, both live-tested and both wrong in
different ways:
  - No normalization at all: a company's raw mean could sit well under 65
    (e.g. HGS raw X 10.0), contradicting the "every score >= 65" requirement.
  - Row-level ratio-preserving scaling (normalize_row_score_floor): scales a
    company's own X and Y by one shared factor derived from its WEAKER axis,
    capped so the stronger axis never exceeds 100. This keeps each company's
    own X:Y ratio exact, but when a company's two raw axes are far apart
    (e.g. Sino Geophysical raw X 61.2 / Y 36.0) the factor needed to lift
    the weak axis is large enough to push the ALREADY-DECENT other axis all
    the way to a flat 100 -- a display value that reads as "best in the
    market" for a company whose raw 61.2 was nowhere near the top.
Per-axis cohort banding avoids both: every company's displayed X (and Y,
independently) is exactly where it truly ranks between the weakest and
strongest company in the whole 182-company market on that one axis, so 100
is reserved for the company that is actually the strongest on that axis, and
65 for the one that is actually the weakest -- nothing is inflated or
floored by an unrelated number on its OTHER axis. This reads every
param_detail_prescored*.json sidecar, averages each axis, and writes
xy_partial + quadrant assignment into the checkpoint -- the same contract
seed_composite_and_resume.py produces, so build_report_from_composite.py
works unchanged downstream.

    .\\.venv\\Scripts\\python.exe scripts\\seed_from_full_evidence.py ^
        --market "Marine Seismic Data Processing Services Market" ^
        --country global
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))


def _overall(x: int, y: int) -> int:
    return round((x + y) / 2)


def _axis_mean(record: dict, axis_key: str) -> float | None:
    stored = ((record.get(axis_key) or {}).get("parameters")) or {}
    scores = [
        float(p["score"]) for p in stored.values()
        if isinstance(p, dict) and p.get("score") is not None
    ]
    if not scores:
        return None
    return sum(scores) / len(scores)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--market", required=True)
    ap.add_argument("--country", default="global")
    ap.add_argument(
        "--force-even-quadrants", action="store_true",
        help="rank-split into exactly N/4 per quadrant (assign_quadrants_"
             "half_median) instead of the default cohort-median threshold "
             "(assign_quadrants_absolute_median). Use this when the scored "
             "pool itself IS the small Top-N set (no larger pool for a "
             "downstream chart selector to pick a balanced 5 FROM), since "
             "then the Quadrant label is the only thing that can balance "
             "the split. Leave off for a normal full-market scoring run, "
             "where the label should reflect each company's real standing "
             "against the whole cohort and a separate selector balances "
             "the CHART from that larger, naturally uneven pool.",
    )
    ap.add_argument(
        "--include-legacy-scores", action="store_true",
        help="add every company from the checkpoint's xy_rows that has an "
             "old composite X/Y/Overall score but no per-parameter evidence "
             "sidecar -- gives the report a real Other Noticeable Player "
             "long tail (Strength-bubble only, no Key Takeaways entry) "
             "instead of stopping at the small evidence-backed pool.",
    )
    ap.add_argument(
        "--evidence-file", default="",
        help="JSON list of the companies whose evidence is COMPLETE and "
             "deduped. Without it, any sidecar company with at least one "
             "parameter on each axis counts as evidence-scored.",
    )
    ap.add_argument(
        "--long-tail-file", default="",
        help="JSON list of company names allowed into the long tail "
             "(a deduped list). Without it, every xy_rows / overall_only "
             "name is eligible.",
    )
    args = ap.parse_args()

    from vendor_intel.pipeline.web_expand import default_output_dir
    from vendor_intel.quadrant.matrix_rollup import normalize_cohort_to_band
    from vendor_intel.quadrant.rating_map import (
        assign_quadrants_absolute_median,
        assign_quadrants_half_median,
    )

    out_dir = Path(default_output_dir(args.market, args.country))
    ckpt_path = out_dir / "chatgpt_checkpoint_batch_all.json"
    if not ckpt_path.exists():
        print(f"ERROR: no checkpoint at {ckpt_path}", file=sys.stderr)
        return 2

    state = json.loads(ckpt_path.read_text(encoding="utf-8"))
    data = state.setdefault("data", {})
    verified = data.get("verified") or []
    by_company: dict[str, dict] = {}
    for r in verified:
        name = str(
            r.get("Company") or r.get("company") or r.get("name") or ""
        ).strip()
        if name and name not in by_company:
            by_company[name] = r
    print(f"verified unique companies: {len(by_company)}")

    # Union each company's X/Y parameters across every sidecar rather than
    # letting the last sidecar file win wholesale: a small targeted sidecar
    # (e.g. from a straggler gap-fill run that only ever asked about 1-2
    # parameters) can hold the exact parameter a "fuller-looking" sidecar
    # from an earlier pass is still missing -- picking one sidecar per
    # company would silently drop it.
    evidence: dict[str, dict] = {}
    for side in sorted(out_dir.glob("param_detail_prescored*.json")):
        try:
            part = json.loads(side.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - a half-written sidecar is skipped
            continue
        for name, record in part.items():
            merged = evidence.setdefault(name, {"x": {"parameters": {}}, "y": {"parameters": {}}})
            for axis_key in ("x", "y"):
                dest = merged.setdefault(axis_key, {"parameters": {}})
                dest.setdefault("parameters", {})
                src_params = (record.get(axis_key) or {}).get("parameters") or {}
                for pname, pval in src_params.items():
                    dest["parameters"].setdefault(pname, pval)
    print(f"evidence sidecars merged: {len(evidence)} companies")

    raw_scores: dict[str, tuple[float, float]] = {}
    evidence_allow = (
        set(json.loads(Path(args.evidence_file).read_text(encoding="utf-8")))
        if args.evidence_file else None
    )
    for name, record in evidence.items():
        if name not in by_company:
            continue
        if evidence_allow is not None and name not in evidence_allow:
            continue
        x_mean = _axis_mean(record, "x")
        y_mean = _axis_mean(record, "y")
        if x_mean is None or y_mean is None:
            continue
        raw_scores[name] = (x_mean, y_mean)
    scored_names = list(raw_scores.keys())
    print(f"with both axes fully scored : {len(scored_names)}")

    if not scored_names:
        print("ERROR: nothing to seed -- no company has both axes scored",
              file=sys.stderr)
        return 2

    # Per-axis cohort banding: X and Y are each mapped onto [65, 100]
    # independently by that company's real rank on THIS axis against every
    # other company's raw mean on the same axis (see the module docstring
    # for why this replaced the two row-level approaches tried earlier).
    xs_raw = [raw_scores[n][0] for n in scored_names]
    ys_raw = [raw_scores[n][1] for n in scored_names]
    xs_band = normalize_cohort_to_band(xs_raw)
    ys_band = normalize_cohort_to_band(ys_raw)
    normalized: dict[str, tuple[int, int]] = {
        n: (int(round(xs_band[i])), int(round(ys_band[i])))
        for i, n in enumerate(scored_names)
    }

    xs = [normalized[n][0] for n in scored_names]
    ys = [normalized[n][1] for n in scored_names]
    assign = (
        assign_quadrants_half_median if args.force_even_quadrants
        else assign_quadrants_absolute_median
    )
    quads, _midx, _midy = assign(xs, ys)

    xy_partial = []
    for name, quad in zip(scored_names, quads):
        x, y = normalized[name]
        x_raw, y_raw = raw_scores[name]
        row = by_company[name]
        xy_partial.append({
            "Company": name,
            "Brand": str(row.get("brand_name") or row.get("Market Offering") or name),
            "X Score": str(x),
            "Y Score": str(y),
            "Overall Score": str(_overall(x, y)),
            "Quadrant": quad,
            "Industry Category": "",
            "X Score Raw": f"{x_raw:.1f}",
            "Y Score Raw": f"{y_raw:.1f}",
        })

    # Other Noticeable Player only ever shows a Strength bubble (Overall
    # score), never per-parameter evidence -- so a company that has no
    # evidence sidecar but DOES have an older legacy composite score
    # (X/Y/Overall in xy_rows, from before this market got the full
    # per-parameter evidence pipeline) is good enough for that section.
    # Adding these as extra xy_partial rows (never touching the
    # evidence-backed rows above, and never eligible for the Top 20 chart
    # since --fixed-top20 controls that separately) gives the report a
    # real long tail instead of just the 20 fully-scored companies.
    if args.include_legacy_scores:
        # Score source, best first: fresh overall_only_shard*.json sidecars
        # (scripts/score_overall_only.py), then the checkpoint's older
        # xy_rows composite. Only ever X/Y numbers -- no evidence.
        fresh: dict[str, dict] = {}
        for side in sorted(out_dir.glob("overall_only_shard*.json")):
            try:
                fresh.update(json.loads(side.read_text(encoding="utf-8")))
            except Exception:  # noqa: BLE001 - half-written sidecar skipped
                continue
        legacy: dict[str, dict] = {}
        for r in data.get("xy_rows") or []:
            name = str(r.get("Company") or r.get("company") or "").strip()
            if name and name not in legacy:
                legacy[name] = r

        # An explicit deduped allowlist (written by run_quadrant_pipeline.py)
        # keeps a subsidiary or name-variant duplicate of a Top-20 company
        # (e.g. a parent and its own diabetes-care division sharing one
        # website) out of the long tail. Without it, every xy_rows name is
        # eligible, as before.
        if args.long_tail_file:
            allow = json.loads(Path(args.long_tail_file).read_text(encoding="utf-8"))
        else:
            allow = list(dict.fromkeys(list(fresh) + list(legacy)))

        seen = {row["Company"] for row in xy_partial}
        tail: list[tuple[str, int, int, str]] = []
        for name in allow:
            if not name or name in seen:
                continue
            if name in fresh:
                x_raw, y_raw = fresh[name].get("x_score"), fresh[name].get("y_score")
            elif name in legacy:
                x_raw = legacy[name].get("X Score")
                y_raw = legacy[name].get("Y Score")
            else:
                continue
            if not (str(x_raw).strip().isdigit() and str(y_raw).strip().isdigit()):
                continue
            brand_row = by_company.get(name) or legacy.get(name) or {}
            brand = str(
                brand_row.get("brand_name") or brand_row.get("Market Offering") or name
            )
            tail.append((name, int(x_raw), int(y_raw), brand))
            seen.add(name)

        # The same 65-100 floor as the evidence-backed rows, banded across
        # the long tail's own cohort, so every exported X/Y respects the
        # floor regardless of which scoring path produced it.
        if tail:
            tx = normalize_cohort_to_band([t[1] for t in tail])
            ty = normalize_cohort_to_band([t[2] for t in tail])
            t_norm = [(int(round(a)), int(round(b))) for a, b in zip(tx, ty)]
            t_quads, _, _ = assign_quadrants_absolute_median(
                [a for a, _ in t_norm], [b for _, b in t_norm]
            )
            for (name, x_raw, y_raw, brand), (x, y), quad in zip(tail, t_norm, t_quads):
                xy_partial.append({
                    "Company": name,
                    "Brand": brand,
                    "X Score": str(x),
                    "Y Score": str(y),
                    "Overall Score": str(_overall(x, y)),
                    "Quadrant": quad,
                    "Industry Category": "",
                    "X Score Raw": str(x_raw),
                    "Y Score Raw": str(y_raw),
                })
        print(f"added {len(tail)} long-tail companies (Overall score only, "
              f"no evidence) for the Other Noticeable Player table")

    data["xy_partial"] = xy_partial
    ckpt_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

    print(f"\nseeded xy_partial: {len(xy_partial)} rows")
    print("quadrant split:", dict(Counter(quads)))
    print(f"\nwrote {ckpt_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
