"""Batch-level gap-fill runner (any --batch-id, any market count)."""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from vendor_intel.batch import db
from vendor_intel.config import _project_root
from vendor_intel.enrichment.gap_fill.orchestrator import gap_fill_market_from_slug, load_cache


def _done_markets(batch_id: str) -> list[Any]:
    return [m for m in db.list_markets(batch_id) if m["status"] == "done"]


def gap_fill_status(batch_id: str) -> dict[str, Any]:
    """Summary of gap-fill progress for a batch."""
    markets = _done_markets(batch_id)
    completed = 0
    pending = 0
    no_json = 0
    rows: list[dict[str, Any]] = []
    for m in markets:
        slug = m["market_slug"]
        output_dir = _project_root() / "output" / slug
        cache = load_cache(output_dir)
        if cache.get("market_completed"):
            completed += 1
            st = cache.get("stats") or {}
            rows.append(
                {
                    "slug": slug,
                    "query": m["query"],
                    "status": "done",
                    "updated": st.get("updated", 0),
                    "still_missing": st.get("still_missing_gaps", 0),
                }
            )
        elif (output_dir / f"{slug}.json").is_file() or list(output_dir.glob("*.json")):
            pending += 1
            rows.append({"slug": slug, "query": m["query"], "status": "pending"})
        else:
            no_json += 1
            rows.append({"slug": slug, "query": m["query"], "status": "no_json"})
    return {
        "batch_id": batch_id,
        "done_markets": len(markets),
        "gap_fill_completed": completed,
        "gap_fill_pending": pending,
        "no_json": no_json,
        "markets": rows,
    }


async def gap_fill_batch_async(
    batch_id: str,
    *,
    max_concurrent: int = 3,
    gap_concurrent: int = 4,
    sources: str | None = None,
    force: bool = False,
    fmcg_xlsx: bool = True,
    also_csv: bool = True,
    limit: int | None = None,
    push_neon: bool = True,
) -> dict[str, Any]:
    markets = _done_markets(batch_id)
    if not markets:
        print(f"  [gap_fill] No done markets in batch '{batch_id}'", flush=True)
        return {"done_markets": 0}

    todo_slugs: list[str] = []
    for m in markets:
        slug = m["market_slug"]
        output_dir = _project_root() / "output" / slug
        cache = load_cache(output_dir)
        if cache.get("market_completed") and not force:
            continue
        if not (output_dir / f"{slug}.json").is_file() and not list(output_dir.glob("*.json")):
            print(f"  [gap_fill] SKIP {slug} — no JSON export", flush=True)
            continue
        todo_slugs.append(slug)

    if limit is not None:
        todo_slugs = todo_slugs[: max(0, limit)]

    print(
        f"  [gap_fill] Batch {batch_id}: {len(todo_slugs)} market(s) to process "
        f"(of {len(markets)} done, concurrency={max_concurrent})",
        flush=True,
    )
    if not todo_slugs:
        summary = gap_fill_status(batch_id)
        print(f"  [gap_fill] Nothing pending — all done markets already gap-filled.", flush=True)
        return summary

    sem = asyncio.Semaphore(max(1, max_concurrent))
    results: list[dict[str, Any]] = []
    t0 = time.perf_counter()

    async def _one(slug: str) -> None:
        async with sem:
            print(f"\n  [gap_fill] === {slug} ===", flush=True)
            try:
                stats = await gap_fill_market_from_slug(
                    slug,
                    fmcg_xlsx=fmcg_xlsx,
                    concurrent=gap_concurrent,
                    sources=sources,
                    force=force,
                    also_csv=also_csv,
                    push_neon=push_neon,
                )
                results.append({"slug": slug, **stats})
            except Exception as exc:
                print(f"  [gap_fill] ERROR {slug}: {exc}", flush=True)
                results.append({"slug": slug, "error": str(exc)})

    await asyncio.gather(*[_one(s) for s in todo_slugs])

    summary = gap_fill_status(batch_id)
    summary["processed"] = results
    summary["elapsed_minutes"] = round((time.perf_counter() - t0) / 60.0, 2)

    out_path = _project_root() / "output" / f"gap_fill_summary_{batch_id}.json"
    out_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n  [gap_fill] Summary written: {out_path}", flush=True)
    return summary


def gap_fill_batch(
    batch_id: str,
    *,
    max_concurrent: int = 3,
    gap_concurrent: int = 4,
    sources: str | None = None,
    force: bool = False,
    fmcg_xlsx: bool = True,
    also_csv: bool = True,
    limit: int | None = None,
    push_neon: bool = True,
) -> dict[str, Any]:
    return asyncio.run(
        gap_fill_batch_async(
            batch_id,
            max_concurrent=max_concurrent,
            gap_concurrent=gap_concurrent,
            sources=sources,
            force=force,
            fmcg_xlsx=fmcg_xlsx,
            also_csv=also_csv,
            limit=limit,
            push_neon=push_neon,
        )
    )
