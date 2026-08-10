#!/usr/bin/env python3
"""Country-level runs merged into one region dataset.

Running a region as a single query ("North America") gives the search and the
LLM a vague target: results skew to whichever country dominates the index, and
the smaller market is under-covered. Running each country on its own and merging
afterwards keeps every country's discovery budget intact — a Canadian
manufacturer competes only against other Canadian results, not against the whole
US long tail.

    python run_region.py --region "North America" --countries USA Canada \
        --industry "Rupture Disc Market" --live

Each country run writes its own full outputs, then the merge writes:

    output/region/<region-slug>/<market>_<region>.csv / .xlsx / .docx / .json

Companies found in more than one country collapse to a single row carrying
``countries`` (e.g. "Canada; USA") and ``found_in_country_count``, so a
multi-country presence is visible rather than deduped away.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

# Region -> member countries. Extend freely; --countries always overrides.
REGION_PRESETS: dict[str, list[str]] = {
    "north america": ["USA", "Canada", "Mexico"],
    "europe": ["Germany", "France", "United Kingdom", "Italy", "Spain", "Netherlands"],
    "asia pacific": ["China", "Japan", "India", "South Korea", "Australia"],
    "latin america": ["Brazil", "Mexico", "Argentina", "Chile"],
    "middle east": ["Saudi Arabia", "United Arab Emirates", "Israel", "Turkey"],
}


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (s or "").strip().lower()).strip("_")[:80] or "region"


def _norm_domain(row: dict[str, Any]) -> str:
    d = str(row.get("domain") or row.get("website") or "").strip().lower()
    d = d.removeprefix("http://").removeprefix("https://").removeprefix("www.")
    return d.split("/")[0]


def _name_key(row: dict[str, Any]) -> str:
    return re.sub(r"[^a-z0-9]", "", str(row.get("company") or row.get("brand") or "").lower())


def _row_score(row: dict[str, Any]) -> float:
    """Which duplicate to keep: the better-evidenced one."""
    return float(row.get("quality_score") or 0) + float(row.get("confidence") or 0)


def merge_country_rows(
    per_country: list[tuple[str, list[dict[str, Any]]]]
) -> list[dict[str, Any]]:
    """Collapse country result sets into one, tracking where each company appeared.

    Identity is the domain when there is one — two countries returning the same
    company under slightly different names ("Fike Corp" / "Fike Corporation")
    must not become two rows. Name is only a fallback for domain-less rows.
    """
    merged: dict[str, dict[str, Any]] = {}
    for country, rows in per_country:
        for row in rows:
            key = _norm_domain(row) or f"name:{_name_key(row)}"
            if not key or key == "name:":
                continue
            existing = merged.get(key)
            if existing is None:
                merged[key] = {**row, "_countries": {country}}
                continue
            existing["_countries"].add(country)
            # Keep the better-evidenced body, but never lose the country set.
            if _row_score(row) > _row_score(existing):
                countries = existing["_countries"]
                merged[key] = {**row, "_countries": countries}

    out: list[dict[str, Any]] = []
    for row in merged.values():
        countries = sorted(row.pop("_countries"))
        row["countries"] = "; ".join(countries)
        row["found_in_country_count"] = len(countries)
        out.append(row)
    out.sort(key=lambda r: str(r.get("company") or "").lower())
    return out


def build_region_result(
    region: str,
    industry: str,
    country_results: list[tuple[str, dict[str, Any]]],
    settings: Any = None,
) -> dict[str, Any]:
    """Assemble a merged result dict the existing exporters accept unchanged."""
    relevant = merge_country_rows(
        [(c, (r.get("relevant_companies") or [])) for c, r in country_results]
    )
    # Re-run the cross-row passes on the merged set: a doorway network can be
    # split across countries (each country contributing a few of its domains),
    # so it only becomes visible once the countries are pooled. The merge also
    # keys on domain alone, which lets "Parker Hannifin" and "Parker Hannifin
    # Corporation" both through when two countries recorded different domains.
    from vendor_intel.pipeline.doorway_filter import dedupe_name_variants, filter_doorways

    relevant, _doorways = filter_doorways(relevant)
    relevant, _variants = dedupe_name_variants(relevant)
    if _doorways:
        print(f"  [region] doorway networks collapsed: {len(_doorways)} row(s)", flush=True)
    if _variants:
        print(f"  [region] name-variant duplicates: {len(_variants)} row(s)", flush=True)

    # Scope audit: the only check that asks whether the WIDER WEB places this
    # company in this market. Every earlier gate reads the company's own
    # material, which is why a brake-disc brand clears them all.
    try:
        from vendor_intel.pipeline.scope_audit import apply_audit, audit_rows

        _verdicts, _out = audit_rows(relevant, industry, settings=settings)
        if _out:
            relevant, _rejected = apply_audit(relevant, _out)
            print(f"  [region] scope audit: {len(_out)} company(ies) ruled out of market", flush=True)
            for v in _out[:8]:
                print(f"      - {v.brand}: {v.reason[:70]}", flush=True)
    except Exception as exc:
        print(f"  [region] scope audit skipped: {exc}", flush=True)

    # Canonical roles, then the per-industry role scope. Normalisation must run
    # first — the industry filter matches on canonical names, and the classifier
    # emits 'distributor' / 'Distributor' / 'reseller' for one role.
    try:
        from vendor_intel.pipeline.role_rules import (
            canonicalize_sections,
            filter_by_industry,
            normalize_rows,
            profile_for,
        )

        _secs = canonicalize_sections(relevant)
        if _secs:
            print(f"  [region] section names canonicalised: {_secs} row(s)", flush=True)
        _changed = normalize_rows(relevant)
        if _changed:
            print(f"  [region] roles normalised: {_changed} row(s)", flush=True)
        relevant, _off_role = filter_by_industry(relevant, industry)
        if _off_role:
            prof = profile_for(industry).get("name", "?")
            print(f"  [region] role scope '{prof}': {len(_off_role)} row(s) out of scope", flush=True)
    except Exception as exc:
        print(f"  [region] role rules skipped: {exc}", flush=True)

    # Ownership: annotate names the evidence says changed hands —
    # "Oseco" -> "Oseco (acquired by Halma plc)".
    try:
        from vendor_intel.pipeline.ownership import annotate, detect

        _owners = detect(relevant, industry, settings=settings)
        if _owners:
            _n = annotate(relevant, _owners)
            print(f"  [region] ownership: {_n} company name(s) annotated", flush=True)
            for o in _owners[:8]:
                print(f"      - {o.brand} {o.suffix}", flush=True)
    except Exception as exc:
        print(f"  [region] ownership detection skipped: {exc}", flush=True)
    unverified = merge_country_rows(
        [(c, (r.get("unverified_companies") or [])) for c, r in country_results]
    )
    # A company confirmed in any country outranks its unverified status elsewhere.
    confirmed = {_norm_domain(r) or f"name:{_name_key(r)}" for r in relevant}
    unverified = [
        r for r in unverified if (_norm_domain(r) or f"name:{_name_key(r)}") not in confirmed
    ]

    first_scope = next((r.get("scope") for _, r in country_results if r.get("scope")), {}) or {}
    scope = {**first_scope, "geography": region, "geographies": [c for c, _ in country_results]}

    return {
        "query": f"{industry} in {region}",
        "query_context": {"industry": industry, "country": region, "functions": []},
        "scope": scope,
        "region": region,
        "countries": [c for c, _ in country_results],
        "relevant_companies": relevant,
        "unverified_companies": unverified,
        "all_classified": [r for _, res in country_results for r in (res.get("all_classified") or [])],
        "per_country": {
            c: {
                "relevant": len(res.get("relevant_companies") or []),
                "unverified": len(res.get("unverified_companies") or []),
                "elapsed_minutes": res.get("elapsed_minutes"),
                "error": res.get("error"),
            }
            for c, res in country_results
        },
        "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def main() -> None:
    p = argparse.ArgumentParser(description="Run a market per country, then merge into a region")
    p.add_argument("--industry", required=True, help="Market / industry name")
    p.add_argument("--region", required=True, help='Region label, e.g. "North America"')
    p.add_argument(
        "--countries",
        nargs="*",
        default=[],
        help="Countries to run. Defaults to the region preset when omitted.",
    )
    p.add_argument("--functions", nargs="*", default=[], help="Optional role hints")
    p.add_argument("--live", action="store_true")
    p.add_argument("--mock", action="store_true")
    p.add_argument("--profile", choices=("quality", "balanced", "recall", "deep"), default=None)
    p.add_argument("--quadrant", action="store_true", help="Score the merged region set")
    p.add_argument("--out-dir", default="", help="Override output directory")
    args = p.parse_args()

    countries = args.countries or REGION_PRESETS.get(args.region.strip().lower(), [])
    if not countries:
        p.error(
            f"No countries for region {args.region!r}. Pass --countries, or add a preset. "
            f"Known: {', '.join(sorted(REGION_PRESETS))}"
        )

    import os

    if args.live:
        os.environ["USE_MOCK_DATA"] = "false"
    if args.mock:
        os.environ["USE_MOCK_DATA"] = "true"
    if args.profile:
        os.environ["PIPELINE_PROFILE"] = args.profile
    # The region merge is the only place allowed to cap; per-country runs stay uncapped.
    os.environ.setdefault("PYTHONUTF8", "1")

    from vendor_intel.config import Settings
    from vendor_intel.live_checks import print_run_banner, validate_live_settings
    from vendor_intel.pipeline.orchestrator import (
        run_pipeline_sync,
        save_pipeline_csv,
        save_pipeline_docx,
        save_pipeline_xlsx,
    )

    settings = Settings.load()
    print_run_banner(settings, validate_live_settings(settings))

    out_dir = Path(args.out_dir) if args.out_dir else ROOT / "output" / "region" / _slug(args.region)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n=== Region run: {args.industry} — {args.region} ===")
    print(f"  Countries ({len(countries)}): {', '.join(countries)}")
    print(f"  Output: {out_dir}\n")

    country_results: list[tuple[str, dict[str, Any]]] = []
    for i, country in enumerate(countries, 1):
        print(f"\n{'=' * 64}\n[{i}/{len(countries)}] {args.industry} — {country}\n{'=' * 64}", flush=True)
        ctx = {"industry": args.industry, "country": country, "functions": list(args.functions)}
        try:
            result = run_pipeline_sync(ctx, settings)
        except Exception as exc:
            # One dead country must not lose the countries already collected.
            print(f"  [region] {country} FAILED: {exc}", flush=True)
            country_results.append((country, {"error": str(exc)}))
            continue

        stem = out_dir / f"{_slug(args.industry)}_{_slug(country)}"
        try:
            save_pipeline_csv(result, str(stem) + ".csv")
        except Exception as exc:
            print(f"  [region] {country} CSV save failed: {exc}", flush=True)
        country_results.append((country, result))
        print(f"  [region] {country}: {len(result.get('relevant_companies') or [])} companies", flush=True)

    merged = build_region_result(args.region, args.industry, country_results, settings)
    rows = merged["relevant_companies"]

    stem = out_dir / f"{_slug(args.industry)}_{_slug(args.region)}"
    Path(str(stem) + ".json").write_text(
        json.dumps(merged, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    for saver, ext in ((save_pipeline_csv, ".csv"), (save_pipeline_xlsx, ".xlsx"), (save_pipeline_docx, ".docx")):
        try:
            saver(merged, str(stem) + ext)
        except Exception as exc:
            print(f"  [region] {ext} save failed: {exc}", flush=True)

    print(f"\n{'=' * 64}\n=== Region merge complete ===")
    for country, stats in merged["per_country"].items():
        note = f" ERROR: {stats['error']}" if stats.get("error") else ""
        print(f"  {country:20s} {stats['relevant'] or 0:>4} companies{note}")
    overlap = [r for r in rows if r.get("found_in_country_count", 1) > 1]
    print(f"  {'-' * 40}")
    print(f"  {'MERGED REGION':20s} {len(rows):>4} unique companies")
    print(f"  {'multi-country':20s} {len(overlap):>4} present in more than one country")
    print(f"  Output: {stem}.csv / .xlsx / .docx / .json")

    if args.quadrant and rows:
        import asyncio

        from vendor_intel.quadrant import synthesize_quadrant

        print("\n  [region] scoring merged region set with the Coherent Quadrant…", flush=True)
        q = asyncio.run(
            synthesize_quadrant(
                rows,
                query_context=merged["query_context"],
                scope=merged["scope"],
                settings=settings,
            )
        )
        if q.get("output_path"):
            print(f"  [region] quadrant: {q['output_path']}")


if __name__ == "__main__":
    main()
