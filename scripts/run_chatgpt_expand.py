#!/usr/bin/env python3
"""ChatGPT expand from Coherent-Quadrant (not the quadrant crawl).

Uses DeepSeek via OPENAI_* mapping, Google AI scraper on :15561, and writes
FINAL Excel under output/chatgpt_expand/<slug>/.

Examples (from D:\\Coherent-Quadrant):

  .\\.venv\\Scripts\\python.exe scripts\\run_chatgpt_expand.py --query "Global Semiconductor Market"

  .\\.venv\\Scripts\\python.exe scripts\\run_five_chatgpt_markets.py
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _prepare_env() -> None:
    from vendor_intel.pipeline.chatgpt_env import apply_chatgpt_expand_env

    apply_chatgpt_expand_env(root=ROOT)
    os.environ.setdefault("GOOGLE_AI_SCRAPER_ENABLED", "true")
    os.environ.setdefault("GOOGLE_AI_SCRAPER_BASE_URL", "http://127.0.0.1:15561")
    os.environ.setdefault("GOOGLE_AI_SCRAPER_URL", "http://127.0.0.1:15561")
    os.environ.setdefault("GOOGLE_AI_SCRAPER_LLM_CLEAN", "true")
    os.environ.setdefault("GOOGLE_AI_SCRAPER_LLM_CLEAN_ONLY_WHEN_MISSING", "false")
    os.environ.setdefault("GOOGLE_AI_SCRAPER_DISCOVERY", "true")
    os.environ.setdefault("GOOGLE_AI_SCRAPER_GAP_FILL", "true")
    os.environ.setdefault("EXPAND_LANDSCAPE_MODE", "vendors")
    os.environ.setdefault("CHANNEL_PURITY_FILTER", "false")
    os.environ.setdefault("EXPAND_OUTPUT_FOLDER", "chatgpt_expand")
    os.environ.setdefault("SEARCH_STACK_SOURCES", "google_ai")
    # Company Details columns only — Found in (HQ) + website; no employee/turnover asks
    os.environ.setdefault("GOOGLE_AI_GAP_FILL_FIELDS", "headquarters,website")
    os.environ.setdefault("GOOGLE_AI_GAP_FILL_MAX_QUERIES", "4")
    os.environ.setdefault("SEARCH_STACK_RESIDUAL_COLUMNS", "Headquarters,Website")
    os.environ.setdefault("FOUND_IN_CITY_COUNTRY", "1")
    os.environ.setdefault("FOUND_IN_WIKI_RESOLVE", "1")
    os.environ.setdefault("EXPAND_MARKET_GATE", "1")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="ChatGPT/DeepSeek market expand (landscape players, not quadrant crawl)"
    )
    parser.add_argument("--query", "-q", required=True)
    parser.add_argument("--country", "-c", default="global")
    parser.add_argument("--batch", "-b", choices=("a", "b", "all"), default="all")
    parser.add_argument("--target", "-t", type=int, default=1000)
    parser.add_argument("--final", default=None)
    parser.add_argument("--max-fill", type=int, default=1000)
    parser.add_argument("--fill-existing", action="store_true")
    parser.add_argument("--max-queries", type=int, default=300)
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--no-merge", action="store_true")
    parser.add_argument("--seeds-only", action="store_true")
    parser.add_argument("--seeds", default=None)
    parser.add_argument("--skip-recall", action="store_true")
    parser.add_argument("--no-web-fill", action="store_true")
    parser.add_argument("--no-openai-discover", action="store_true")
    parser.add_argument("--ddgs-harvest", action="store_true")
    parser.add_argument("--fresh", action="store_true")
    parser.add_argument("--no-linkedin-enrich", action="store_true")
    parser.add_argument("--no-apollo", action="store_true")
    parser.add_argument(
        "--fill-backend",
        choices=("search", "openai"),
        default="search",
    )
    parser.add_argument("--scraper-url", default="http://127.0.0.1:15561")
    args = parser.parse_args()

    os.chdir(ROOT)
    _prepare_env()
    if args.scraper_url:
        os.environ["GOOGLE_AI_SCRAPER_URL"] = args.scraper_url.rstrip("/")
        os.environ["GOOGLE_AI_SCRAPER_BASE_URL"] = args.scraper_url.rstrip("/")

    openai_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if not openai_key:
        print(
            "ERROR: No LLM key. Set DEEPSEEK_API_KEY (or OPENAI_API_KEY) in .env",
            file=sys.stderr,
        )
        return 1

    from vendor_intel.pipeline.chatgpt_expand import (
        _is_deepseek,
        _llm_label,
        player_label,
        run_chatgpt_expand,
    )

    provider = _llm_label()
    print(f"=== Coherent-Quadrant {provider} expand (not quadrant crawl) ===", flush=True)
    print(f"  query  : {args.query}", flush=True)
    print(f"  target : {args.target}", flush=True)
    print(f"  model  : {os.environ.get('OPENAI_MODEL')}", flush=True)
    print(f"  base   : {os.environ.get('OPENAI_BASE_URL')}", flush=True)
    print(f"  scraper: {os.environ.get('GOOGLE_AI_SCRAPER_URL')}", flush=True)
    print(
        f"  players: {player_label(args.query)} "
        "(tech=Solution Provider, other=Brand/Marketer)",
        flush=True,
    )
    print("  graph  : top 20 from table | table target ~1000 after filter", flush=True)
    if _is_deepseek():
        print(
            "  fill   : Google AI scraper → DeepSeek residual for leftover gaps",
            flush=True,
        )

    try:
        audit = asyncio.run(
            run_chatgpt_expand(
                args.query,
                country=args.country,
                target=args.target,
                batch=args.batch,
                max_queries=args.max_queries,
                merge_existing=not args.no_merge,
                final_path=args.final,
                out_dir=args.out_dir,
                fill_existing=args.fill_existing,
                max_fill=args.max_fill,
                seeds_only=bool(args.seeds_only),
                seeds_path=args.seeds,
                skip_recall=bool(args.skip_recall),
                web_fill=not bool(args.no_web_fill),
                openai_discover=not bool(args.no_openai_discover),
                ddgs_harvest=bool(args.ddgs_harvest),
                resume=not bool(args.fresh),
                use_linkedin_enrich=not bool(args.no_linkedin_enrich),
                use_apollo=not bool(args.no_apollo),
                fill_backend=str(args.fill_backend or "search"),
                force=bool(args.fresh),
            )
        )
    except Exception as err:  # noqa: BLE001
        print(f"ERROR: chatgpt expand failed: {type(err).__name__}: {err}", file=sys.stderr)
        return 1

    print(json.dumps(audit, indent=2), flush=True)
    total = int(audit.get("total_after") or 0)
    print(f"\n  rows: {total}  (target {args.target})", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
