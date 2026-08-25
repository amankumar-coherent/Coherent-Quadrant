"""Phase 3 — parallel smart_crawl enrichment + domain fix + scrape fallback."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Awaitable, Callable

# Project root: vendor_intel/enrichment → src → project
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_cache: dict[str, dict[str, Any]] = {}
_smart_crawl: Callable[..., Awaitable[dict[str, Any]]] | None = None


def _sync_llm_env() -> None:
    """One key in .env: OPENCODE_API_KEY also powers smart_crawl via OpenAI-compatible API."""
    from backend.config import sync_opencode_to_openai_env

    sync_opencode_to_openai_env()


def _load_smart_crawl() -> Callable[..., Awaitable[dict[str, Any]]]:
    global _smart_crawl
    if _smart_crawl is not None:
        return _smart_crawl
    _sync_llm_env()
    try:
        from crawler.smart_crawl import smart_crawl as fn

        _smart_crawl = fn
        return fn
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            f"{exc}. Install pipeline crawl deps: "
            ".venv\\Scripts\\python.exe -m pip install openai scrapling"
        ) from exc


def clear_enrichment_cache() -> None:
    _cache.clear()


def _crawl_has_content(result: dict[str, Any] | None) -> bool:
    if not result or result.get("error"):
        return False
    data = result.get("data")
    if isinstance(data, dict) and data:
        return len(str(data)) > 80
    pages = result.get("pages") or []
    return bool(pages)


def _summary_len(result: dict[str, Any] | None) -> int:
    if not result:
        return 0
    pages = result.get("pages") or []
    if pages and isinstance(pages[0], dict):
        return len(str(pages[0].get("text") or ""))
    data = result.get("data") or {}
    if isinstance(data, dict):
        intel = data.get("intel") or {}
        if isinstance(intel, dict) and intel.get("summary"):
            return len(str(intel["summary"]))
        return len(json.dumps(data))
    return 0


async def supplement_crawl(
    domain: str,
    existing: dict[str, Any] | None = None,
    *,
    crawl_mode: str | None = None,
    max_pages: int = 0,
) -> dict[str, Any]:
    """Extra web scrape for weak classify rows — ddgs extract then smart_crawl retry."""
    dom = (domain or "").strip().lower().removeprefix("www.")
    if not dom:
        return existing or {"error": "no_domain", "data": {}}
    if existing and _crawl_has_content(existing) and _summary_len(existing) >= 400:
        return existing

    print(f"  [enrich] supplement crawl: {dom}", flush=True)
    fb = await _ddgs_fallback(dom)
    if fb and _summary_len(fb) >= 120:
        return fb

    try:
        from vendor_intel.config import Settings as _Settings

        settings = _Settings.load()
        mode = (crawl_mode or getattr(settings, "quadrant_crawl_mode", None) or "business").strip()
        pages = int(max_pages or getattr(settings, "quadrant_crawl_max_pages", 0) or 0)
        smart_crawl = _load_smart_crawl()
        result = await smart_crawl(dom, mode=mode, max_pages=pages)
        if _crawl_has_content(result) and _summary_len(result) >= 120:
            print(f"  [enrich] supplement ok (smart_crawl/{mode}): {dom}", flush=True)
            return result
    except Exception as exc:
        print(f"  [enrich] supplement smart_crawl failed: {dom} — {exc}", flush=True)

    return fb or existing or {"error": "thin_content", "data": {}, "domain": dom}


async def _ddgs_fallback(domain: str) -> dict[str, Any] | None:
    """When local DNS/HTTP crawl fails, ddgs.extract often still returns markdown."""
    try:
        from vendor_intel.scraping.ddgs_extract import fetch_page_via_ddgs_extract

        url = f"https://{domain}/"
        page = await asyncio.to_thread(fetch_page_via_ddgs_extract, url)
        if not page.alive or len((page.text or "").strip()) < 80:
            return None
        text = (page.text or "")[:12000]
        print(f"  [enrich] ddgs.extract fallback OK: {domain} ({len(text)} chars)", flush=True)
        return {
            "domain": domain,
            "data": {
                "company": {"name": domain},
                "business": {"products": [], "services": []},
                "intel": {"summary": text[:4000]},
                "source": "ddgs_extract_fallback",
            },
            "pages": [{"url": url, "text": text}],
        }
    except Exception as exc:
        print(f"  [enrich] ddgs fallback failed: {domain} — {exc}", flush=True)
        return None


async def _ssc_only(dom: str) -> dict[str, Any] | None:
    from vendor_intel.enrichment.ssc_fetch import fetch_server_side_content

    result = await fetch_server_side_content(dom)
    if result.get("error") and not result.get("pages"):
        return None
    print(
        f"  [enrich] SSC OK: {dom} via {result.get('source', 'ssc')} "
        f"({len(str((result.get('pages') or [{}])[0].get('text', '')))} chars)",
        flush=True,
    )
    return result


async def _crawl_one(
    name: str,
    domain: str,
    *,
    country: str = "",
    use_ssc: bool = False,
    crawl_mode: str = "business",
    max_pages: int = 0,
) -> tuple[str, dict[str, Any] | None, str | None]:
    from vendor_intel.utils.domain_corrections import fix_company_domain

    from vendor_intel.config import Settings as _Settings

    _recall = bool(getattr(_Settings.load(), "pipeline_recall_mode", False))
    fixed = fix_company_domain(
        {"name": name, "domain": domain}, country=country, recall_mode=_recall
    )
    from vendor_intel.utils.domain_corrections import crawl_host_for_domain

    dom = crawl_host_for_domain((fixed.get("domain") or "").strip().lower())
    if not dom:
        print(f"  [enrich] skip (no domain): {name[:50]}", flush=True)
        return name, None, "no_domain"

    try:
        from vendor_intel.discovery.entity_extract import is_blocked_domain
        from vendor_intel.discovery.candidate_quality import (
            is_junk_candidate_name,
            is_junk_media_domain,
        )

        force = (os.getenv("EXPAND_XY_FORCE_CRAWL") or "").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        if not force and (
            is_blocked_domain(dom)
            or is_junk_media_domain(dom)
            or is_junk_candidate_name(name, dom)
        ):
            print(f"  [enrich] skip junk: {name[:40]} ({dom})", flush=True)
            return name, None, "junk_domain"
        if force and (
            is_blocked_domain(dom)
            or is_junk_media_domain(dom)
            or is_junk_candidate_name(name, dom)
        ):
            print(f"  [enrich] force-crawl despite junk heuristic: {name[:40]} ({dom})", flush=True)
    except Exception:
        pass

    if dom in _cache:
        print(f"  [enrich] cache hit: {dom}", flush=True)
        return name, _cache[dom], None

    mode = (crawl_mode or "business").strip() or "business"
    print(f"  [enrich] crawl start: {name[:40]} ({dom}) mode={mode}", flush=True)
    if use_ssc:
        result = await _ssc_only(dom)
        if result:
            _cache[dom] = result
            return name, result, None
        fb = await _ddgs_fallback(dom)
        if fb:
            _cache[dom] = fb
            return name, fb, None
        return name, None, "ssc_failed"

    try:
        smart_crawl = _load_smart_crawl()
        result = await smart_crawl(dom, mode=mode, max_pages=int(max_pages or 0))
        if not _crawl_has_content(result):
            fb = await _ddgs_fallback(dom)
            if fb:
                result = fb
        _cache[dom] = result
        print(f"  [enrich] crawl ok: {dom}", flush=True)
        return name, result, None
    except Exception as exc:
        err = f"{type(exc).__name__}: {exc}"[:200]
        fb = await _ddgs_fallback(dom)
        if fb:
            _cache[dom] = fb
            print(f"  [enrich] crawl ok (fallback): {dom}", flush=True)
            return name, fb, None
        print(f"  [enrich] crawl failed: {dom} — {err}", flush=True)
        return name, None, err


async def enrich_companies(
    companies: list[dict[str, str]],
    limit: int = 80,
    *,
    max_concurrent: int = 4,
    country: str = "",
    use_ssc: bool | None = None,
    crawl_mode: str | None = None,
    max_pages: int | None = None,
) -> dict[str, Any]:
    """
    Run smart_crawl in parallel for up to `limit` companies.

    Input: [{"name": str, "domain": str}, ...]
    Returns: {company_name: smart_crawl_output}
    """
    from vendor_intel.config import Settings

    settings = Settings.load()
    if use_ssc is None:
        use_ssc = bool(getattr(settings, "pipeline_use_ssc", True))
    mode = (
        crawl_mode
        if crawl_mode is not None
        else str(getattr(settings, "quadrant_crawl_mode", None) or "business")
    ).strip() or "business"
    pages = int(
        max_pages
        if max_pages is not None
        else (getattr(settings, "quadrant_crawl_max_pages", 0) or 0)
    )
    if not use_ssc:
        _load_smart_crawl()
    else:
        print("  [enrich] mode=SSC (server-side content, fast)", flush=True)
    batch = list(companies or [])[: max(0, limit)]
    if not batch:
        print("  [enrich] no companies to enrich", flush=True)
        return {}

    print(
        f"  [enrich] enriching {len(batch)} companies (limit={limit}, "
        f"concurrent={max_concurrent}, crawl={mode}, max_pages={pages or 'mode-default'})",
        flush=True,
    )
    sem = asyncio.Semaphore(max(1, max_concurrent))

    async def _run_one(c: dict[str, str]) -> tuple[str, dict[str, Any] | None, str | None]:
        async with sem:
            return await _crawl_one(
                str(c.get("name") or "").strip(),
                str(c.get("domain") or "").strip(),
                country=country,
                use_ssc=use_ssc,
                crawl_mode=mode,
                max_pages=pages,
            )

    results = await asyncio.gather(*[_run_one(c) for c in batch])

    out: dict[str, Any] = {}
    for name, data, err in results:
        key = name or "unknown"
        if data is not None:
            out[key] = data
        elif err:
            out[key] = {"error": err, "domain": "", "data": {}}

    print(f"  [enrich] done: {len(out)} entries", flush=True)
    return out
