#!/usr/bin/env python3
"""Rerun Coherent Quadrant from an existing pipeline JSON export."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


async def _amain(args: argparse.Namespace) -> int:
    from vendor_intel.config import Settings
    from vendor_intel.placeholders.load_keys import apply_env_overrides
    from vendor_intel.quadrant import synthesize_quadrant

    apply_env_overrides()
    settings = Settings.load()
    settings = settings.model_copy(
        update={
            "use_mock_data": False,
            "mock_mode": False,
            "quadrant_enabled": True,
            "quadrant_max_companies": int(args.max_companies),
        }
    )

    path = Path(args.pipeline_json)
    if not path.is_file():
        path = ROOT / args.pipeline_json
    if not path.is_file():
        raise SystemExit(f"Pipeline JSON not found: {args.pipeline_json}")

    payload = json.loads(path.read_text(encoding="utf-8"))
    companies = list(payload.get("relevant_companies") or [])
    if not companies:
        raise SystemExit("No relevant_companies in pipeline JSON")

    query_context = dict(payload.get("query_context") or {})
    if args.industry:
        query_context["industry"] = args.industry
    if args.country:
        query_context["country"] = args.country

    scope = {
        "market": args.industry
        or query_context.get("industry")
        or "market",
        "geography": args.country
        or query_context.get("country")
        or "global",
    }

    print(
        f"  [pipeline] {path.name}: {len(companies)} companies "
        f"(with evidence_snapshot="
        f"{sum(1 for c in companies if c.get('evidence_snapshot'))})",
        flush=True,
    )

    result = await synthesize_quadrant(
        companies,
        query_context=query_context,
        scope=scope,
        settings=settings,
        write_output=True,
    )
    out = result.get("output_path") or ""
    brands = result.get("brands") or []
    print("\n=== Quadrant complete ===", flush=True)
    print(f"  Brands scored: {len(brands)}", flush=True)
    print(f"  Output: {out}", flush=True)
    for b in brands:
        print(
            f"    {b.get('brand')}: X={b.get('execution')} Y={b.get('innovation')} "
            f"{b.get('quadrant')} {b.get('tier')} overall={b.get('overall')}",
            flush=True,
        )
    return 0 if out else 1


def main() -> None:
    p = argparse.ArgumentParser(description="Coherent Quadrant from pipeline JSON")
    p.add_argument("--pipeline-json", required=True)
    p.add_argument("--industry", default=None)
    p.add_argument("--country", default=None)
    p.add_argument("--max-companies", type=int, default=12)
    args = p.parse_args()
    raise SystemExit(asyncio.run(_amain(args)))


if __name__ == "__main__":
    main()
