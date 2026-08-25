"""Per-market gap-fill orchestrator with checkpoint/resume."""
from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

from vendor_intel.config import Settings
from vendor_intel.enrichment.gap_fill.gaps import (
    company_key,
    missing_contact_fields,
    missing_fields,
    row_has_gaps,
    uses_contact_sources,
)
from vendor_intel.enrichment.gap_fill.sources import (
    DEFAULT_SOURCES,
    fill_from_contact_page,
    fill_from_crunchbase,
    fill_from_google_ai_scraper,
    fill_from_leadership,
    fill_from_linkedin,
    fill_from_locations_search,
    fill_from_openai_residual,
    fill_from_owler,
    fill_from_search_backfill,
    fill_from_sec_edgar,
    fill_from_wikidata,
    fill_from_wikipedia,
    parse_sources,
)


def _cache_path(output_dir: Path, sources: tuple[str, ...] = ()) -> Path:
    if sources and set(sources).issubset({"contact_page", "leadership"}):
        return output_dir / "contact_fill_cache.json"
    return output_dir / "gap_fill_cache.json"


def load_cache(output_dir: Path, sources: tuple[str, ...] = ()) -> dict[str, Any]:
    path = _cache_path(output_dir, sources)
    if not path.is_file():
        return {"companies": {}, "market_completed": False}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data.setdefault("companies", {})
            return data
    except Exception:
        pass
    return {"companies": {}, "market_completed": False}


def save_cache(output_dir: Path, cache: dict[str, Any], sources: tuple[str, ...] = ()) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    _cache_path(output_dir, sources).write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")


def _source_timeout_sec(source_name: str = "") -> float:
    """Per-source wait budget.

    Google AI runs up to ~22 column asks + DeepSeek clean each, so the old
    default 90s aborted mid-company (looks "stuck", then sources applied: none).
    """
    env_key = "GAP_FILL_SOURCE_TIMEOUT_SEC"
    default = "90"
    if source_name == "google_ai":
        env_key = "GAP_FILL_GOOGLE_AI_TIMEOUT_SEC"
        # ~22 queries × ~25–40s (scrape + DeepSeek) under light load
        default = "900"
    try:
        return max(15.0, float(os.getenv(env_key) or os.getenv("GAP_FILL_SOURCE_TIMEOUT_SEC") or default))
    except ValueError:
        return float(default)


async def gap_fill_row(
    row: dict[str, Any],
    *,
    router: Any,
    owler_client: Any,
    owler_model: str,
    sources: tuple[str, ...],
    idx: int = 0,
    total: int = 0,
) -> dict[str, Any]:
    """Run configured sources for ANY market: Google AI → DDGS/SearXNG → … → OpenAI residual."""
    name = str(row.get("company") or row.get("brand") or "")[:60]
    applied: list[str] = []
    has_gaps = row_has_gaps(row, sources=sources)

    # Skip whole row only when nothing to do and Google AI / LinkedIn verify not requested.
    if not has_gaps:
        from vendor_intel.integrations.linkedin_mcp import linkedin_mcp_available

        want_google = "google_ai" in sources
        want_li = "linkedin" in sources and linkedin_mcp_available()
        want_openai = "openai_residual" in sources
        if not want_google and not want_li and not want_openai:
            return {"company": name, "skipped": True, "sources": [], "remaining": []}

    if idx and total:
        print(f"  [gap_fill] starting [{idx}/{total}] {name}", flush=True)

    # Fixed order for every market (batch-safe, not hardcoded to one market):
    # 1) Google AI  2) DDGS/SearXNG backfill  3) other free sources  4) OpenAI residual last
    runners: list[tuple[str, Any]] = []
    if "google_ai" in sources:
        runners.append(("google_ai", lambda: fill_from_google_ai_scraper(row)))
    if "backfill" in sources:
        runners.append(("backfill", lambda: fill_from_search_backfill(row, router)))
    if "wikipedia" in sources:
        runners.append(("wikipedia", lambda: fill_from_wikipedia(row)))
    if "wikidata" in sources:
        runners.append(("wikidata", lambda: fill_from_wikidata(row)))
    if "owler" in sources:
        runners.append(
            ("owler", lambda: fill_from_owler(row, client=owler_client, router=router, model=owler_model))
        )
    if "linkedin" in sources:
        runners.append(("linkedin", lambda: fill_from_linkedin(row, idx=idx, total=total)))
    if "crunchbase" in sources:
        runners.append(("crunchbase", lambda: fill_from_crunchbase(row, router)))
    if "sec" in sources:
        runners.append(("sec", lambda: fill_from_sec_edgar(row)))
    if "locations" in sources:
        runners.append(("locations", lambda: fill_from_locations_search(row, router)))
    if "contact_page" in sources:
        runners.append(("contact_page", lambda: fill_from_contact_page(row)))
    if "leadership" in sources:
        runners.append(("leadership", lambda: fill_from_leadership(row, router)))
    if "openai_residual" in sources:
        runners.append(("openai_residual", lambda: fill_from_openai_residual(row, router)))

    # Always attempt primary + residual even if mid-stack looks complete.
    always_run = frozenset({"google_ai", "linkedin", "openai_residual"})
    for source_name, fn in runners:
        if source_name not in always_run and not row_has_gaps(row, sources=sources):
            continue
        # Residual only when gaps remain after free/search sources
        if source_name == "openai_residual" and not row_has_gaps(row, sources=sources):
            continue
        timeout_sec = _source_timeout_sec(source_name)
        try:
            if source_name == "google_ai":
                print(f"  [gap_fill] Google AI scraper first — {name}", flush=True)
            elif source_name == "backfill":
                print(f"  [gap_fill] DDGS/SearXNG backfill — {name}", flush=True)
            elif source_name == "openai_residual":
                print(f"  [gap_fill] OpenAI residual (leftover gaps) — {name}", flush=True)
            got = await asyncio.wait_for(fn(), timeout=timeout_sec)
            if got:
                applied.extend(got)
                print(
                    f"  [gap_fill] {source_name} filled {got} for {name}",
                    flush=True,
                )
        except asyncio.TimeoutError:
            print(
                f"  [gap_fill] {source_name} timed out after {timeout_sec:.0f}s for {name}",
                flush=True,
            )
        except Exception as exc:
            print(f"  [gap_fill] {source_name} failed for {name}: {exc}", flush=True)

    # Promote Founded/HQ/Employees when 2+ low-trust sources agreed
    try:
        from vendor_intel.enrichment.gap_fill.gaps import finalize_pending_facts

        promoted = finalize_pending_facts(row)
        if promoted:
            applied.append("consensus")
            print(
                f"  [gap_fill] consensus promoted {promoted} for {name}",
                flush=True,
            )
    except Exception as exc:  # noqa: BLE001
        print(f"  [gap_fill] consensus finalize skip for {name}: {exc}", flush=True)

    remaining = list(missing_fields(row))
    if uses_contact_sources(sources):
        for field in missing_contact_fields(row):
            if field not in remaining:
                remaining.append(field)
    return {"company": name, "skipped": False, "sources": applied, "remaining": remaining}


def _gap_fill_concurrent(explicit: int) -> int:
    try:
        cap = int(os.getenv("GAP_FILL_CONCURRENT", os.getenv("SEARCH_MAX_WORKERS", "2")) or "2")
    except ValueError:
        cap = 2
    return max(1, min(explicit, cap, 3))


def _gap_fill_batch_size() -> int:
    try:
        return max(10, int(os.getenv("GAP_FILL_BATCH_SIZE", "100")))
    except ValueError:
        return 100


def _gap_fill_batch_pause_sec() -> int:
    try:
        return max(0, int(os.getenv("GAP_FILL_BATCH_PAUSE_SEC", "300")))
    except ValueError:
        return 300


async def gap_fill_market(
    result: dict[str, Any],
    *,
    json_path: Path,
    output_dir: Path,
    market_type: str = "general",
    fmcg_xlsx: bool = True,
    concurrent: int = 4,
    sources: str | None = None,
    force: bool = False,
    also_csv: bool = True,
    push_neon: bool = True,
) -> dict[str, Any]:
    """Gap-fill all companies in a market JSON; re-export CSV/XLSX."""
    from backend.config import get_settings, sync_opencode_to_openai_env
    from openai import AsyncOpenAI

    from vendor_intel.clients.search_router import FreeSearchRouter
    from vendor_intel.enrichment.post_export_enrich import re_export_market
    from vendor_intel.utils.scrape_logging import log, log_section

    sync_opencode_to_openai_env()
    cfg = get_settings()
    settings = Settings.load()
    router = FreeSearchRouter(settings)
    source_tuple = parse_sources(sources)

    cache = load_cache(output_dir, source_tuple)
    if cache.get("market_completed") and not force:
        log(f"Gap-fill already completed for {output_dir.name} (use --force to redo)")
        return cache.get("stats") or {"skipped": True}

    rows = [r for r in (result.get("relevant_companies") or []) if r.get("is_relevant", True)]
    todo = [r for r in rows if row_has_gaps(r, sources=source_tuple)]
    if force:
        todo = rows

    company_cache: dict[str, Any] = dict(cache.get("companies") or {})
    if not force:
        todo = [r for r in todo if company_key(r) not in company_cache]

    log_section(f"GAP-FILL: {output_dir.name}")
    log(f"Sources: {','.join(source_tuple)} | queue={len(todo)} (of {len(rows)} companies)")

    owler_client = None
    owler_model = ""
    if cfg.openai_api_key and "owler" in source_tuple:
        owler_client = AsyncOpenAI(api_key=cfg.openai_api_key)
        owler_model = (os.getenv("OPENAI_MODEL") or cfg.model_extract or "gpt-4o-mini").strip()

    sem = asyncio.Semaphore(max(1, _gap_fill_concurrent(concurrent)))
    updated = 0
    still_missing = 0
    t0 = time.perf_counter()
    total = len(todo)

    async def _one(row: dict[str, Any], idx: int) -> None:
        nonlocal updated, still_missing
        async with sem:
            stats = await gap_fill_row(
                row,
                router=router,
                owler_client=owler_client,
                owler_model=owler_model,
                sources=source_tuple,
                idx=idx,
                total=total,
            )
            key = company_key(row)
            company_cache[key] = stats
            if stats.get("sources"):
                updated += 1
                print(
                    f"  [gap_fill] [{idx}/{total}] {stats['company']} +{stats['sources']}",
                    flush=True,
                )
            if stats.get("remaining"):
                still_missing += 1
            save_cache(output_dir, {"companies": company_cache, "market_completed": False}, source_tuple)
            json_path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")

    if todo:
        batch_size = _gap_fill_batch_size()
        pause_sec = _gap_fill_batch_pause_sec()
        for batch_start in range(0, len(todo), batch_size):
            batch = todo[batch_start : batch_start + batch_size]
            await asyncio.gather(
                *[_one(r, batch_start + i) for i, r in enumerate(batch, 1)]
            )
            done = batch_start + len(batch)
            if done < len(todo) and pause_sec > 0:
                print(
                    f"  [gap_fill] batch pause {pause_sec}s after {done}/{len(todo)} companies",
                    flush=True,
                )
                await asyncio.sleep(pause_sec)

    paths = re_export_market(result, json_path, market_type=market_type, fmcg_xlsx=fmcg_xlsx)
    result.update(paths)
    if also_csv:
        from vendor_intel.pipeline.orchestrator import save_pipeline_csv

        csv_path = json_path.with_suffix(".csv")
        save_pipeline_csv(result, str(csv_path))
        result["_csv_path"] = str(csv_path)

    elapsed_min = (time.perf_counter() - t0) / 60.0
    stats = {
        "total_companies": len(rows),
        "queued": len(todo),
        "updated": updated,
        "still_missing_gaps": still_missing,
        "sources": list(source_tuple),
        "elapsed_minutes": round(elapsed_min, 2),
        "gap_fill_cache_path": str(_cache_path(output_dir, source_tuple)),
    }
    result["gap_fill"] = stats
    if set(source_tuple).issubset({"contact_page", "leadership"}):
        result["contact_fill"] = stats
        result["contact_fill_completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    else:
        result["gap_fill_completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    json_path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")

    save_cache(output_dir, {"companies": company_cache, "market_completed": True, "stats": stats}, source_tuple)
    log(f"Gap-fill done: {updated} updated, {still_missing} still have gaps, {elapsed_min:.1f} min")

    if push_neon and updated > 0:
        try:
            from vendor_intel.neon_push import push_json_after_gap_fill

            neon_stats = push_json_after_gap_fill(json_path)
            if neon_stats:
                stats["neon_push"] = neon_stats
        except Exception as exc:
            log(f"Neon push failed (gap-fill JSON saved locally): {exc}")
            stats["neon_push_error"] = str(exc)

    return stats


async def gap_fill_market_from_slug(
    slug: str,
    *,
    market_type: str = "general",
    fmcg_xlsx: bool = True,
    concurrent: int = 4,
    sources: str | None = None,
    force: bool = False,
    also_csv: bool = True,
    push_neon: bool = True,
) -> dict[str, Any]:
    from vendor_intel.config import _project_root

    output_dir = _project_root() / "output" / slug
    json_path = output_dir / f"{slug}.json"
    if not json_path.is_file():
        candidates = sorted(output_dir.glob("*.json"))
        json_path = candidates[0] if candidates else json_path
    if not json_path.is_file():
        return {"error": f"no JSON in {output_dir}", "skipped": True}

    result = json.loads(json_path.read_text(encoding="utf-8"))
    mt = result.get("market_type") or market_type
    return await gap_fill_market(
        result,
        json_path=json_path,
        output_dir=output_dir,
        market_type=mt,
        fmcg_xlsx=fmcg_xlsx,
        concurrent=concurrent,
        sources=sources,
        force=force,
        also_csv=also_csv,
        push_neon=push_neon,
    )
