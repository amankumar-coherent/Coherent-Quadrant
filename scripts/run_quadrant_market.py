#!/usr/bin/env python3
"""Fast Coherent Quadrant market run — discover, deep-crawl brands, score, export.

Default path:
  1) Google AI Overview seeds + landscape discovery (wide list for table)
  2) Deep-crawl + score (all table rows when QUADRANT_SCORE_ALL_TABLE=true)
  3) Company Details **table** targets ~500 pre-filter (~300 after relevance);
     graph still shows top 15–20 by overall

Examples:
  $env:PYTHONPATH = "src"
  .venv\\Scripts\\python.exe scripts\\run_quadrant_market.py --industry "Avocado Oil Market" --country global
  .venv\\Scripts\\python.exe scripts\\run_quadrant_market.py --industry "Avocado Oil Market" --max-companies 18 --table-companies 500
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def _print_table(brands: list[dict[str, Any]]) -> None:
    headers = ("Brand", "Company", "Quadrant", "X", "Y", "Overall", "Founded in")
    rows: list[tuple[str, ...]] = []
    for b in brands:
        founded = str(
            b.get("founded_location") or b.get("founded_in") or b.get("hq_location") or ""
        )
        rows.append(
            (
                str(b.get("display_name") or b.get("brand") or "")[:48],
                str(b.get("company") or "")[:28],
                str(b.get("quadrant") or ""),
                str(b.get("execution") if b.get("execution") is not None else ""),
                str(b.get("innovation") if b.get("innovation") is not None else ""),
                str(b.get("overall") if b.get("overall") is not None else ""),
                founded[:28],
            )
        )
    widths = [len(h) for h in headers]
    for r in rows:
        for i, cell in enumerate(r):
            widths[i] = max(widths[i], len(cell))
    fmt = "  ".join(f"{{:{w}}}" for w in widths)
    print("\n" + fmt.format(*headers), flush=True)
    print(fmt.format(*("-" * w for w in widths)), flush=True)
    for r in rows:
        print(fmt.format(*r), flush=True)


async def _deep_crawl_cohort(
    companies: list[dict[str, Any]],
    *,
    country: str,
    settings: Any,
) -> list[dict[str, Any]]:
    """Full smart_crawl only for the selected quadrant brands; refresh evidence_snapshot."""
    from vendor_intel.enrichment.smart_enrichment import clear_enrichment_cache, enrich_companies
    from vendor_intel.quadrant.snapshot import build_evidence_snapshot

    batch: list[dict[str, str]] = []
    for c in companies:
        name = str(c.get("company_raw") or c.get("company") or c.get("brand") or "").strip()
        # Strip acquisition suffix for crawl key matching
        from vendor_intel.quadrant.brand_meta import plain_brand_name

        name = plain_brand_name(c)
        dom = str(c.get("domain") or c.get("website") or "").strip()
        if name:
            batch.append({"name": name, "domain": dom})

    if not batch:
        return companies

    clear_enrichment_cache()
    crawl_mode = str(getattr(settings, "quadrant_crawl_mode", None) or "business").strip() or "business"
    max_pages = int(getattr(settings, "quadrant_crawl_max_pages", 0) or 0)
    print(
        f"  [quadrant-market] deep-crawling {len(batch)} cohort brands "
        f"(smart_crawl mode={crawl_mode}, max_pages={max_pages or 'default'})…",
        flush=True,
    )
    concurrent = int(getattr(settings, "pipeline_enrich_concurrent", 8) or 8)
    # Full-table crawl can be large — allow a higher but still safe concurrency
    score_all = bool(getattr(settings, "quadrant_score_all_table", True))
    conc_cap = 12 if score_all and len(batch) > 40 else 8
    enriched = await enrich_companies(
        batch,
        limit=len(batch),
        max_concurrent=max(1, min(concurrent, conc_cap)),
        country=country,
        use_ssc=False,
        crawl_mode=crawl_mode,
        max_pages=max_pages,
    )

    for c in companies:
        name = plain_brand_name(c)
        dom = str(c.get("domain") or c.get("website") or "").strip()
        smart = enriched.get(name) or enriched.get(dom)
        if not isinstance(smart, dict) or smart.get("error"):
            continue
        c["evidence_snapshot"] = build_evidence_snapshot(smart, c, c)
        # Surface founded_year onto the row when INTEL has it
        data = smart.get("data") if isinstance(smart.get("data"), dict) else {}
        company_block = data.get("company") if isinstance(data.get("company"), dict) else {}
        fy = company_block.get("founded_year") or company_block.get("founded")
        if fy and not c.get("founded_year"):
            c["founded_year"] = fy
    return companies


async def _ownership_pass(companies: list[dict[str, Any]], market: str, settings: Any) -> None:
    try:
        from vendor_intel.pipeline.ownership import annotate, detect

        owners = detect(companies, market, settings=settings)
        if owners:
            n = annotate(companies, owners)
            print(f"  [quadrant-market] ownership: {n} company name(s) annotated", flush=True)
    except Exception as exc:
        print(f"  [quadrant-market] ownership skipped: {exc}", flush=True)


async def _synthesize(
    companies: list[dict[str, Any]],
    *,
    industry: str,
    country: str,
    settings: Any,
    query_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from vendor_intel.quadrant import synthesize_quadrant

    qc = dict(query_context or {})
    qc.setdefault("industry", industry)
    qc.setdefault("country", country)
    scope = {"market": industry, "geography": country}
    return await synthesize_quadrant(
        companies,
        query_context=qc,
        scope=scope,
        settings=settings,
        write_output=True,
    )


async def _from_pipeline_json(args: argparse.Namespace, settings: Any) -> dict[str, Any]:
    path = Path(args.from_pipeline_json)
    if not path.is_file():
        path = ROOT / args.from_pipeline_json
    if not path.is_file():
        raise SystemExit(f"Pipeline JSON not found: {args.from_pipeline_json}")

    payload = json.loads(path.read_text(encoding="utf-8"))
    companies = list(payload.get("relevant_companies") or [])
    if not companies:
        raise SystemExit("No relevant_companies in pipeline JSON")

    qc = dict(payload.get("query_context") or {})
    industry = args.industry or qc.get("industry") or "market"
    country = args.country or qc.get("country") or "global"
    qc["industry"] = industry
    qc["country"] = country

    from vendor_intel.quadrant.synthesize import _pick_companies

    picked = _pick_companies(companies, int(args.max_companies))
    if not args.skip_deep_crawl:
        await _deep_crawl_cohort(picked, country=country, settings=settings)
    try:
        from vendor_intel.pipeline.fact_enrich import enrich_brand_facts

        print("  [quadrant-market] dual fact enrich (scraper + LLM)…", flush=True)
        enrich_brand_facts(picked, industry, settings=settings)
    except Exception as exc:
        print(f"  [quadrant-market] fact enrich skipped: {exc}", flush=True)
    await _ownership_pass(picked, industry, settings)
    return await _synthesize(
        picked,
        industry=industry,
        country=country,
        settings=settings,
        query_context=qc,
    )


async def _full_landscape(args: argparse.Namespace, settings: Any) -> dict[str, Any]:
    from vendor_intel.pipeline.orchestrator import run_pipeline

    query_context = {
        "industry": args.industry,
        "country": args.country or "global",
        "functions": list(args.functions or []),
    }
    # Full path: pipeline runs SSC/full-crawl and synthesizes at the end
    settings = settings.model_copy(
        update={
            "quadrant_enabled": True,
            "quadrant_max_companies": int(args.max_companies),
            "pipeline_use_ssc": not bool(args.full_crawl),
        }
    )
    result = await run_pipeline(query_context, settings)
    return result.get("coherent_quadrant") or {}


async def _fast_market(args: argparse.Namespace, settings: Any) -> dict[str, Any]:
    """Wide table (200+) + top 15-20 scored on the graph."""
    import re

    from vendor_intel.evidence.google_ai_scraper import health, scraper_enabled
    from vendor_intel.pipeline.ai_brand_discovery import (
        discover_brands_from_google_ai,
        discover_landscape_from_google_ai,
        resolve_domains_for_brands,
    )
    from vendor_intel.pipeline.orchestrator import run_pipeline
    from vendor_intel.quadrant.synthesize import _pick_companies

    def _nk(s: str) -> str:
        return re.sub(r"[^a-z0-9]", "", str(s or "").lower())

    chart_n = max(1, min(int(getattr(args, "max_companies", 20) or 20), 20))
    table_n = max(chart_n, min(int(getattr(args, "table_companies", 300) or 300), 800))

    query_context = {
        "industry": args.industry,
        "country": args.country or "global",
        "functions": list(args.functions or []),
    }
    companies: list[dict[str, Any]] = []
    industry_meta: dict[str, Any] = {}

    use_ai = (
        scraper_enabled()
        and bool(health().get("ok"))
        and not bool(getattr(args, "legacy_landscape", False))
    )
    if use_ai:
        print(
            "  [quadrant-market] Phase A — Google AI Overview brands (chart seeds)…",
            flush=True,
        )
        ai_rows, industry_meta = discover_brands_from_google_ai(
            str(args.industry),
            country=str(args.country or "global"),
            settings=settings,
            max_brands=min(40, table_n),
            max_queries=4,
        )
        if ai_rows:
            ai_rows = resolve_domains_for_brands(
                ai_rows, settings=settings, market=str(args.industry)
            )
            companies.extend(ai_rows)
            query_context["industry_group"] = industry_meta.get("industry_group")
            query_context["industry_category"] = industry_meta.get("industry_category")
            query_context["discovery_path"] = "google_ai_overview"

        # Wide table: country-wise queries (avocado oil India, avocado oil New Zealand, …)
        if bool(getattr(settings, "quadrant_geo_discovery", True)):
            print(
                "  [quadrant-market] Phase A2 — country-wise Google AI landscape (table)…",
                flush=True,
            )
            geo_rows = discover_landscape_from_google_ai(
                str(args.industry),
                country=str(args.country or "global"),
                settings=settings,
                industry=industry_meta or None,
                max_brands=table_n,
                max_countries=int(getattr(settings, "quadrant_geo_max_countries", 16) or 16),
                queries_per_country=int(
                    getattr(settings, "quadrant_geo_queries_per_country", 2) or 2
                ),
                countries_override=str(getattr(settings, "quadrant_geo_countries", "") or ""),
            )
            seen_geo = {_nk(str(c.get("company") or c.get("brand") or "")) for c in companies}
            added = 0
            for row in geo_rows:
                key = _nk(str(row.get("company") or row.get("brand") or ""))
                if not key or key in seen_geo:
                    continue
                seen_geo.add(key)
                companies.append(row)
                added += 1
                if len(companies) >= table_n:
                    break
            print(
                f"  [quadrant-market] geo landscape added {added} brands "
                f"(table pool={len(companies)})",
                flush=True,
            )
            # Resolve domains for geo brands ahead of full-table crawl
            need_dom = [
                c
                for c in companies
                if not c.get("domain")
                and c.get("discovery_source") in ("google_ai_geo", "google_ai_overview")
            ][:table_n]
            if need_dom:
                print(
                    f"  [quadrant-market] resolving domains for {len(need_dom)} AI brands…",
                    flush=True,
                )
                resolve_domains_for_brands(
                    need_dom, settings=settings, market=str(args.industry)
                )

    print(
        f"  [quadrant-market] Phase A3 — SSC landscape fill (target {table_n})…",
        flush=True,
    )
    run_settings = settings.model_copy(
        update={
            "quadrant_enabled": False,
            "quadrant_max_companies": chart_n,
            "quadrant_chart_companies": chart_n,
            "quadrant_table_companies": table_n,
            "pipeline_use_ssc": True,
            "pipeline_profile": settings.pipeline_profile or "quality",
        }
    )
    result = await run_pipeline(query_context, run_settings)
    landscape = list(result.get("relevant_companies") or [])
    seen = {_nk(str(c.get("company") or c.get("brand") or "")) for c in companies}
    for row in landscape:
        key = _nk(str(row.get("company") or row.get("brand") or ""))
        if not key or key in seen:
            continue
        seen.add(key)
        companies.append(row)
        if len(companies) >= table_n:
            break

    if not companies:
        raise SystemExit("No brands discovered (Google AI Overview + landscape empty)")

    # Drop geo query artifacts like "Avocado Oil India" before crawl/score
    from vendor_intel.pipeline.ai_brand_discovery import is_market_geo_artifact
    from vendor_intel.quadrant.market_relevance import verify_market_companies

    market_s = str(args.industry)
    companies = [
        c
        for c in companies
        if not is_market_geo_artifact(
            str(c.get("company") or c.get("brand") or ""), market_s
        )
    ]
    try:
        companies, _rel = verify_market_companies(
            companies,
            market_s,
            settings=settings,
            industry_group=str(query_context.get("industry_group") or ""),
            industry_category=str(query_context.get("industry_category") or ""),
        )
    except Exception as exc:
        print(f"  [quadrant-market] relevance verify skipped: {exc}", flush=True)

    score_all = bool(getattr(settings, "quadrant_score_all_table", True))

    table_cohort = _pick_companies(companies, table_n, market=market_s)
    # Prefer real seed brands first in the list for domain resolve / crawl priority
    ai_seed = [c for c in table_cohort if c.get("discovery_source") == "google_ai_overview"]
    ai_geo = [c for c in table_cohort if c.get("discovery_source") == "google_ai_geo"]
    rest = [
        c
        for c in table_cohort
        if c.get("discovery_source") not in ("google_ai_overview", "google_ai_geo")
    ]
    ordered: list[dict[str, Any]] = []
    seen_o: set[str] = set()
    for src in (ai_seed, ai_geo, rest):
        for c in src:
            k = _nk(str(c.get("company") or c.get("brand") or ""))
            if not k or k in seen_o:
                continue
            seen_o.add(k)
            ordered.append(c)
    table_cohort = ordered[:table_n]

    print(
        f"  [quadrant-market] Phase B — full crawl+score ALL {len(table_cohort)} table brands"
        if score_all
        else f"  [quadrant-market] Phase B — chart crawl only (top {chart_n})",
        flush=True,
    )
    crawl_targets = table_cohort if score_all else table_cohort[:chart_n]
    if not args.skip_deep_crawl:
        await _deep_crawl_cohort(
            crawl_targets,
            country=str(query_context.get("country") or "global"),
            settings=settings,
        )

    try:
        from vendor_intel.pipeline.fact_enrich import enrich_brand_facts

        print(
            f"  [quadrant-market] Phase B2 — fact enrich ({len(crawl_targets)} brands)…",
            flush=True,
        )
        enrich_brand_facts(crawl_targets, str(args.industry), settings=settings)
    except Exception as exc:
        print(f"  [quadrant-market] fact enrich skipped: {exc}", flush=True)

    await _ownership_pass(crawl_targets, str(args.industry), settings)

    # Merge crawl/fact fields back onto table rows
    by_key = {_nk(str(c.get("company") or c.get("brand") or "")): c for c in crawl_targets}
    merged_table: list[dict[str, Any]] = []
    for c in table_cohort:
        k = _nk(str(c.get("company") or c.get("brand") or ""))
        merged_table.append(by_key.get(k) or c)

    score_settings = settings.model_copy(
        update={
            "quadrant_enabled": True,
            "quadrant_max_companies": chart_n,
            "quadrant_chart_companies": chart_n,
            "quadrant_table_companies": table_n,
            "quadrant_score_all_table": score_all,
        }
    )
    print(
        f"  [quadrant-market] Phase C — score {len(merged_table)} brands "
        f"(graph still top {chart_n} by overall)…",
        flush=True,
    )
    return await _synthesize(
        merged_table,
        industry=str(args.industry),
        country=str(args.country or "global"),
        settings=score_settings,
        query_context=query_context,
    )


async def _amain(args: argparse.Namespace) -> int:
    from vendor_intel.config import Settings
    from vendor_intel.live_checks import print_run_banner, validate_live_settings
    from vendor_intel.placeholders.load_keys import apply_env_overrides

    apply_env_overrides()
    settings = Settings.load()
    if args.live:
        settings = settings.model_copy(update={"use_mock_data": False, "mock_mode": False})
    if args.mock:
        settings = settings.model_copy(update={"mock_mode": True, "use_mock_data": True})

    # Chart = top 15–20; table = wide list (200+)
    chart_n = max(1, min(int(args.max_companies), 20))
    table_n = max(chart_n, min(int(getattr(args, "table_companies", 300) or 300), 800))
    args.max_companies = chart_n
    args.table_companies = table_n
    settings = settings.model_copy(
        update={
            "quadrant_enabled": True,
            "quadrant_max_companies": chart_n,
            "quadrant_chart_companies": chart_n,
            "quadrant_table_companies": table_n,
        }
    )
    print(
        f"  [quadrant-market] chart cap: {chart_n} · table cap: {table_n}",
        flush=True,
    )

    warnings = validate_live_settings(settings)
    print_run_banner(settings, warnings)

    try:
        if args.from_pipeline_json:
            coherent = await _from_pipeline_json(args, settings)
        elif args.full_landscape:
            if not args.industry:
                raise SystemExit("--industry is required with --full-landscape")
            coherent = await _full_landscape(args, settings)
        else:
            if not args.industry:
                raise SystemExit("--industry is required (or use --from-pipeline-json)")
            coherent = await _fast_market(args, settings)
    finally:
        try:
            from vendor_intel.clients.ddg_worker_pool import shutdown_ddg_pool

            shutdown_ddg_pool(wait=True)
        except Exception:
            pass

    brands = list(coherent.get("brands") or [])
    scored = [
        b
        for b in brands
        if int(b.get("execution") or 0) or int(b.get("innovation") or 0) or int(b.get("overall") or 0)
    ]
    on_chart = [b for b in brands if b.get("on_chart")]
    print("\n=== Quadrant market complete ===", flush=True)
    print(
        f"  Scored (X/Y): {len(scored)}/{len(brands)} · "
        f"Chart dots: {len(on_chart)} · Table rows: {len(brands)}",
        flush=True,
    )
    out = coherent.get("output_path") or ""
    csv_path = coherent.get("companies_csv_path") or ""
    html_path = coherent.get("html_report_path") or ""
    if out:
        print(f"  JSON: {out}", flush=True)
    if csv_path:
        print(f"  CSV:  {csv_path}", flush=True)

    # Ensure HTML report exists (also regenerates if synthesize skipped HTML)
    if brands and not html_path and out:
        try:
            from vendor_intel.quadrant.html_report import write_report_from_json

            html_path = write_report_from_json(out, open_browser=False)
            coherent["html_report_path"] = html_path
        except Exception as exc:
            print(f"  [quadrant-market] HTML report failed: {exc}", flush=True)

    if html_path:
        print(f"  UI:   {html_path}", flush=True)

    _print_table(on_chart[:20] if on_chart else brands[:20])

    open_ui = bool(getattr(args, "open_ui", True)) and not bool(getattr(args, "no_open", False))
    if open_ui and html_path:
        try:
            from vendor_intel.quadrant.html_report import open_quadrant_report

            open_quadrant_report(html_path)
            print("\n  Opened quadrant UI in your browser.", flush=True)
        except Exception as exc:
            print(f"\n  Could not auto-open browser: {exc}", flush=True)
            print(f"  Open manually: {html_path}", flush=True)
    elif html_path:
        print(f"\n  Open the UI file in a browser:\n    {html_path}", flush=True)
    else:
        print(
            "\n  No HTML report generated. Re-run scoring or open Streamlit at http://localhost:8501",
            flush=True,
        )
    return 0 if brands or coherent.get("error") is None else 1


def main() -> None:
    p = argparse.ArgumentParser(
        description="Coherent Quadrant — market CLI (15–20 brands, chart-ready export)"
    )
    p.add_argument("--industry", default="", help="Market / industry name")
    p.add_argument("--country", default="global", help="Geography (default: global)")
    p.add_argument("--functions", nargs="*", default=[], help="Optional role hints")
    p.add_argument(
        "--max-companies",
        type=int,
        default=20,
        help="Brands plotted on the quadrant graph (default 20)",
    )
    p.add_argument(
        "--table-companies",
        type=int,
        default=300,
        help="Company Details table size after filter (default 300; discover 700 first)",
    )
    p.add_argument(
        "--from-pipeline-json",
        default=None,
        help="Rescore from an existing pipeline JSON (skip discovery)",
    )
    p.add_argument(
        "--full-landscape",
        action="store_true",
        help="Run full landscape pipeline + quadrant (slower)",
    )
    p.add_argument(
        "--legacy-landscape",
        action="store_true",
        help="Skip Google AI Overview discovery; use classic SSC landscape only",
    )
    p.add_argument(
        "--full-crawl",
        action="store_true",
        help="With --full-landscape: use smart_crawl for all companies",
    )
    p.add_argument(
        "--skip-deep-crawl",
        action="store_true",
        help="Skip cohort deep-crawl (use existing evidence_snapshot only)",
    )
    p.add_argument(
        "--open-ui",
        dest="open_ui",
        action="store_true",
        default=True,
        help="Open the HTML quadrant UI in the browser after the run (default)",
    )
    p.add_argument(
        "--no-open",
        action="store_true",
        help="Do not auto-open the browser UI",
    )
    p.add_argument("--live", action="store_true", help="Force live mode")
    p.add_argument("--mock", action="store_true", help="Mock mode")
    args = p.parse_args()
    raise SystemExit(asyncio.run(_amain(args)))


if __name__ == "__main__":
    main()
