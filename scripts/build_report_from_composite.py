#!/usr/bin/env python3
"""Build detail_rows from the seeded composite scores, select the Top 20
(5 per quadrant, via the pipeline's OWN selector), and export CSV+HTML+JSON.

Calls select_chart_rows_by_quadrant_country + export_expand_quadrant_outputs
directly -- the same functions the full pipeline uses -- rather than
re-implementing quadrant selection. Skips merge/purity/column-fill, which
this market's rows never needed: composite scoring, not those steps, is
what was missing.

    .\\.venv\\Scripts\\python.exe scripts\\build_report_from_composite.py ^
        --market "Advanced Seismic Data Processing Solutions Market" ^
        --country global
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--market", required=True)
    ap.add_argument("--country", default="global")
    ap.add_argument(
        "--fixed-top20", default="",
        help="path to a JSON list of exactly 20 company names to use as the "
             "chart selection, instead of re-deriving it. The automatic "
             "selector has no memory of which companies were already tried "
             "and swapped for failing evidence scoring -- left to itself it "
             "silently re-picks a different company with no evidence at "
             "all on every rebuild.",
    )
    ap.add_argument(
        "--fixed-axes", default="",
        help="path to a JSON spec ({market, axis_x, axis_y, x, y, "
             "parameter_definitions}) with OPERATOR-AUTHORED scoring "
             "parameters -- see prescore_verified.py --fixed-axes. Must be "
             "the SAME spec used to score, or the report's parameter list "
             "will not match what was actually scored.",
    )
    ap.add_argument(
        "--role", default="",
        help="the Role column value stamped on every company row. Default: "
             "this market's own classified primary participant "
             "(market_analysis.primary_participant in the checkpoint), "
             "falling back to 'Solution Provider' only if the market was "
             "never classified.",
    )
    args = ap.parse_args()

    import vendor_intel.pipeline.expand_quadrant_score as _eqs
    from vendor_intel.config import Settings
    from vendor_intel.pipeline.expand_quadrant_score import (
        export_expand_quadrant_outputs,
        select_chart_rows_by_quadrant_country,
    )
    from vendor_intel.pipeline.web_expand import default_output_dir
    from vendor_intel.quadrant.axis_define import define_market_axes
    from vendor_intel.quadrant.industry_select import select_industry

    out_dir = Path(default_output_dir(args.market, args.country))
    ckpt_path = out_dir / "chatgpt_checkpoint_batch_all.json"
    state = json.loads(ckpt_path.read_text(encoding="utf-8"))
    data = state.get("data") or {}
    xy_partial = data.get("xy_partial") or []
    verified = data.get("verified") or []
    if not xy_partial:
        print("ERROR: no xy_partial — run seed_composite_and_resume.py first",
              file=sys.stderr)
        return 2
    role = (
        args.role.strip()
        or str((data.get("market_analysis") or {}).get("primary_participant") or "").strip()
        or "Solution Provider"
    )

    # Prefer a record WITH a Headquarters value over one without, rather
    # than "first duplicate wins": the same company can appear more than
    # once in `verified` (different discovery rounds/queries finding it
    # again), and only SOME of the duplicate rows carry HQ -- keeping
    # whichever was seen first silently lost it when that first copy
    # happened to be the one without HQ (confirmed live on GoodFlip, whose
    # 3rd duplicate row had "Bengaluru, Karnataka, India" but the 1st and
    # 2nd did not, so a plain first-match lookup left HQ blank).
    by_company: dict[str, dict] = {}
    for r in verified:
        name = str(
            r.get("Company") or r.get("company") or r.get("name") or ""
        ).strip()
        if not name:
            continue
        existing = by_company.get(name)
        has_hq = bool(str(r.get("Headquarters") or r.get("headquarters") or "").strip())
        existing_has_hq = bool(
            existing and str(existing.get("Headquarters") or existing.get("headquarters") or "").strip()
        )
        if existing is None or (has_hq and not existing_has_hq):
            by_company[name] = r

    detail_rows = []
    for row in xy_partial:
        name = row["Company"]
        src = by_company.get(name, {})
        hq = str(src.get("Headquarters") or src.get("headquarters") or "")
        detail_rows.append({
            "Brand": row["Brand"],
            "Company": name,
            "Role": role,
            "Quadrant": row["Quadrant"],
            "X": row["X Score"],
            "Y": row["Y Score"],
            "Overall": row["Overall Score"],
            "Found in": hq,
            "_meta": {"hq_location": hq},
        })

    settings = Settings.load()
    # Axis names are fixed for every market (shown as Product / Business
    # Capability); a market-specific title in an axes file is ignored.
    from vendor_intel.quadrant.axis_define import AXIS_X_FIXED, AXIS_Y_FIXED

    axis_x_title, axis_y_title = AXIS_X_FIXED, AXIS_Y_FIXED
    if args.fixed_axes:
        industry = json.loads(Path(args.fixed_axes).read_text(encoding="utf-8"))
        industry["axis_x"], industry["axis_y"] = AXIS_X_FIXED, AXIS_Y_FIXED
    else:
        industry = select_industry(args.market, geography=args.country, settings=settings)
        industry = define_market_axes(
            args.market, industry, geography=args.country, settings=settings
        )

        # define_market_axes() derives fresh parameters for the market but does
        # not always attach a matching definition for every one of them (only a
        # second LLM call inside it does, and that call can come back empty).
        # The report's Parameter Definitions panel needs one per parameter, so
        # ask again here for whatever is still missing rather than shipping
        # "Definition pending" placeholders.
        x_feats = list(industry.get("x") or [])
        y_feats = list(industry.get("y") or [])
        defs = industry.get("parameter_definitions") or {}
        x_defs = dict(defs.get("x") or {}) if isinstance(defs, dict) else {}
        y_defs = dict(defs.get("y") or {}) if isinstance(defs, dict) else {}
        missing_x = [f for f in x_feats if not str(x_defs.get(f) or "").strip()]
        missing_y = [f for f in y_feats if not str(y_defs.get(f) or "").strip()]
        if missing_x or missing_y:
            from vendor_intel.quadrant.axis_define import explain_market_parameters

            print(f"fetching {len(missing_x) + len(missing_y)} missing parameter "
                  f"definitions from the LLM")
            fresh = explain_market_parameters(
                args.market, missing_x, missing_y,
                axis_x=axis_x_title, axis_y=axis_y_title,
                geography=args.country, settings=settings,
            )
            x_defs.update({k: v for k, v in (fresh.get("x") or {}).items() if v})
            y_defs.update({k: v for k, v in (fresh.get("y") or {}).items() if v})
            industry["parameter_definitions"] = {"x": x_defs, "y": y_defs}

    # Merge every prescore_verified.py sidecar. Each parallel/retry run wrote
    # its own file (param_detail_prescored[_shardN|_name].json) so several
    # browsers never raced on one file -- this is the one place they all
    # come back together, right before the report is built.
    # Union each company's X/Y parameters across every sidecar rather than
    # letting one sidecar file win wholesale for that company: a sidecar
    # written by an earlier full pass can hold 5 X parameters while a later
    # straggler/gap-fill sidecar for the same company only ever asked about
    # 3 of them -- "does this sidecar have both axes non-empty" was true for
    # both, so whichever sorted later (e.g. "shard9" after "extra1") silently
    # overwrote the fuller record and dropped 2 real, already-scored
    # parameters from the export (caught live on Mint Seismic, which lost
    # "FWI & Depth-Imaging Technical Leadership" and "Project Track Record"
    # this way despite both being fully scored in an earlier sidecar).
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
                    # Prefer the version WITH assessed_on over "first
                    # sidecar wins": a straggler/gap-fill run can score the
                    # SAME parameter again after an earlier sidecar's copy
                    # was missing its "why" reasoning (confirmed live --
                    # AI Mode drops the assessed_on line specifically on
                    # its highest-confidence answers). plain setdefault()
                    # kept whichever sidecar sorted first alphabetically,
                    # silently reintroducing the reasoning gap the fix
                    # script had already closed in a LATER sidecar.
                    existing = dest["parameters"].get(pname)
                    if existing is None:
                        dest["parameters"][pname] = pval
                    elif not existing.get("assessed_on") and pval.get("assessed_on"):
                        dest["parameters"][pname] = pval
    # Only companies actually in this report: a stray sidecar entry (a
    # deduped-away name variant, or a company a gap-fill touched by mistake)
    # must not skew the per-parameter cohort normalization below.
    report_names = {row["Company"] for row in xy_partial}
    evidence = {
        name: rec for name, rec in evidence.items()
        if name in report_names
        and rec.get("x", {}).get("parameters") and rec.get("y", {}).get("parameters")
    }
    print(f"merged evidence sidecars: {len(evidence)} companies with full "
          f"parameter detail")

    # Per-parameter floor-65 normalization: the displayed X/Y/Overall scores
    # are already cohort-banded onto [65, 100] (seed_from_full_evidence.py),
    # but the 5 individual parameter scores shown in each axis's dropdown
    # were still the raw, un-normalized values -- a company could show a
    # normalized X of 84 sitting directly above 5 parameter scores in the
    # 40s, which reads as contradictory even though the average is right.
    # This bands each of the 10 parameters the SAME way, independently: for
    # one parameter (e.g. "Turnaround Time"), rank its raw score across
    # every company that has it, map the weakest to 65 and the strongest to
    # 100. Applied per parameter, not per company, so it does not disturb
    # the ranking within any single parameter -- only rescales the numbers
    # to share the same 65-100 floor the axis rollups already use.
    from vendor_intel.quadrant.matrix_rollup import normalize_cohort_to_band

    for axis_key in ("x", "y"):
        param_names: set[str] = set()
        for rec in evidence.values():
            param_names.update((rec.get(axis_key) or {}).get("parameters", {}).keys())
        for pname in param_names:
            names_with_score = [
                name for name, rec in evidence.items()
                if pname in (rec.get(axis_key) or {}).get("parameters", {})
                and (rec[axis_key]["parameters"][pname] or {}).get("score") is not None
            ]
            if not names_with_score:
                continue
            raw = [
                float(evidence[name][axis_key]["parameters"][pname]["score"])
                for name in names_with_score
            ]
            banded = normalize_cohort_to_band(raw)
            for name, band_val in zip(names_with_score, banded):
                evidence[name][axis_key]["parameters"][pname]["score"] = int(round(band_val))

    # X/Y/Overall in detail_rows came from seed_from_full_evidence.py's OWN
    # axis-level cohort banding (ranking each company's raw X-mean against
    # every other company's raw X-mean, directly -- a different ranking than
    # normalizing each of the 5 parameters separately above). Recomputing
    # X/Y here as the average of the now-normalized parameters guarantees
    # the axis score a reader sees always matches exactly what they get
    # averaging the parameter numbers listed right below it, rather than
    # being off by a point or two from two independent rankings agreeing
    # only approximately.
    def _overall(x: int, y: int) -> int:
        return round((x + y) / 2)

    for row in detail_rows:
        rec = evidence.get(row["Company"])
        if not rec:
            continue
        x_scores = [
            v["score"] for v in (rec.get("x") or {}).get("parameters", {}).values()
            if v.get("score") is not None
        ]
        y_scores = [
            v["score"] for v in (rec.get("y") or {}).get("parameters", {}).values()
            if v.get("score") is not None
        ]
        if not x_scores or not y_scores:
            continue
        x_avg = round(sum(x_scores) / len(x_scores))
        y_avg = round(sum(y_scores) / len(y_scores))
        row["X"] = str(x_avg)
        row["Y"] = str(y_avg)
        row["Overall"] = str(_overall(x_avg, y_avg))

    # Market Classification shows WHY this market is B2B/B2C and why its
    # companies were compared as this player type -- both already decided
    # by Step 0c and sitting in the checkpoint, just never carried into this
    # standalone report builder (the normal pipeline path picks them up
    # automatically; this script bypasses that path).
    market_analysis = data.get("market_analysis") or {}
    relevance = {
        "market_type": str(market_analysis.get("market_type") or ""),
        "market_definition": str(market_analysis.get("market_definition") or ""),
        "market_type_reason": str(market_analysis.get("market_type_reason") or ""),
        "keep_roles": [role],
        "player_type_reason": str(market_analysis.get("primary_reason") or ""),
    }

    audit = {
        "axis_x": axis_x_title,
        "axis_y": axis_y_title,
        "x_features": list(industry.get("x") or []),
        "y_features": list(industry.get("y") or []),
        "parameter_definitions": industry.get("parameter_definitions") or {"x": {}, "y": {}},
        "rows": [
            {"company": name, "score_detail": record}
            for name, record in evidence.items()
        ],
        "relevance": relevance,
        "strength_fill_overrides": dict(industry.get("strength_fill_overrides") or {}),
    }

    # Companies that never produced a usable evidence answer (3 attempts,
    # every one a prose summary the parser correctly rejected) are excluded
    # from the Top 20 CANDIDATE pool. The automatic selector otherwise
    # re-picks them on raw composite score alone -- it has no way to know a
    # company was already tried and swapped for the next-best same-quadrant
    # alternate. They stay in detail_rows (and the Other Noticeable Player
    # table) with their composite score; only the chart selection excludes
    # them.
    # Companies with no usable evidence at all would need excluding from the
    # chart candidate pool here (the automatic selector has no way to know
    # a company was already tried and swapped for the next-best same-quadrant
    # alternate). Every company in this market now has full 5+5 parameter
    # evidence (confirmed via the completeness audit), so there is nothing
    # to exclude.
    chart_candidates = list(detail_rows)

    if args.fixed_top20:
        wanted = json.loads(Path(args.fixed_top20).read_text(encoding="utf-8"))
        by_name = {r["Company"]: r for r in detail_rows}
        chart_slice = [by_name[n] for n in wanted if n in by_name]
        missing = [n for n in wanted if n not in by_name]
        if missing:
            print(f"WARNING: {len(missing)} fixed-top20 names not found in "
                  f"detail_rows: {missing}", file=sys.stderr)
    else:
        chart_slice = select_chart_rows_by_quadrant_country(chart_candidates, chart_n=20)
    from collections import Counter
    print("Top 20 quadrant split:",
          dict(Counter(str(r.get("Quadrant")) for r in chart_slice)))
    print(f"Top 20 companies ({len(chart_slice)}):")
    for r in chart_slice:
        print(f"  {r['Quadrant']:16} {r['Company'][:44]:46} "
              f"X={r['X']:>3} Y={r['Y']:>3} O={r['Overall']:>3}")

    # export_expand_quadrant_outputs() calls build_expand_quadrant_payload(),
    # which calls select_chart_rows_by_quadrant_country() AGAIN internally --
    # the chart_slice computed above is only used for this script's own
    # printout. Without patching this too, a --fixed-top20 list controls
    # nothing in the actual exported report: the automatic selector still
    # decides on-chart membership, and it has already been observed picking
    # two different companies with zero evidence (Ikon Science Ltd.,
    # Forland Geophysical Services LLC) that scored higher on its
    # midline-separation metric than the intended replacements.
    if args.fixed_top20:
        chart_keys_fixed = {r["Company"] for r in chart_slice}

        def _forced_selection(rows, *, chart_n=20):  # noqa: ARG001
            return [r for r in rows if r.get("Company") in chart_keys_fixed]

        _eqs.select_chart_rows_by_quadrant_country = _forced_selection

    paths = export_expand_quadrant_outputs(
        out_dir, detail_rows, args.market, country=args.country,
        audit=audit, chart_n=20,
    )
    print(f"\nexported:")
    for k, v in paths.items():
        print(f"  {k}: {v}")

    top20_names = [r["Company"] for r in chart_slice]
    (out_dir / "top20_names.json").write_text(
        json.dumps(top20_names, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nsaved Top 20 company list -> {out_dir / 'top20_names.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
