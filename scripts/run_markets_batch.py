"""Batch-run several Coherent Quadrant markets (full table crawl + score).

Example:
  set PYTHONPATH=src
  .venv\\Scripts\\python.exe scripts\\run_markets_batch.py
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

DEFAULT_MARKETS = [
    "Global Flexible Packaging Market",
    "Global Wearable Medical Devices Market",
    "Global Semiconductor Market",
    "Global Liquefied Natural Gas Market",
    "Global GLP-1 Receptor Agonist Market",
]


def main() -> int:
    ap = argparse.ArgumentParser(description="Run quadrant markets one-by-one")
    ap.add_argument(
        "--markets",
        nargs="*",
        default=DEFAULT_MARKETS,
        help="Market names (default: the five global markets)",
    )
    ap.add_argument("--country", default="global")
    ap.add_argument("--max-companies", type=int, default=20)
    ap.add_argument("--table-companies", type=int, default=300)
    ap.add_argument("--scraper-url", default="", help="e.g. http://127.0.0.1:15561")
    ap.add_argument("--skip-deep-crawl", action="store_true")
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]
    py = root / ".venv" / "Scripts" / "python.exe"
    if not py.exists():
        py = Path(sys.executable)

    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    env["QUADRANT_SCORE_ALL_TABLE"] = "true"
    env["QUADRANT_CRAWL_MODE"] = "business"
    env["QUADRANT_CRAWL_MAX_PAGES"] = "60"
    env["QUADRANT_GEO_DISCOVERY"] = "true"
    env["AI_OVERVIEW_DEEPSEEK_CLEAN"] = "true"
    env["GOOGLE_AI_SCRAPER_ENABLED"] = "true"

    candidates: list[str] = []
    if args.scraper_url:
        candidates.append(args.scraper_url.rstrip("/"))
    env_url = (env.get("GOOGLE_AI_SCRAPER_URL") or "").rstrip("/")
    for u in (env_url, "http://127.0.0.1:15551", "http://127.0.0.1:15561"):
        if u and u not in candidates:
            candidates.append(u)

    chosen = ""
    for url in candidates:
        env["GOOGLE_AI_SCRAPER_URL"] = url
        pre = subprocess.run(
            [
                str(py),
                "-c",
                "from vendor_intel.evidence.google_ai_scraper import health, scraper_base_url; "
                "h=health(); print(scraper_base_url(), h.get('extension_connected'), h.get('status') or h.get('error')); "
                "raise SystemExit(0 if h.get('ok') and h.get('extension_connected') else 1)",
            ],
            cwd=str(root),
            env=env,
        )
        if pre.returncode == 0:
            chosen = url
            break
    if not chosen:
        print(
            "No Google AI scraper extension is connected.\n"
            "Keep Chrome open with the scraper extension enabled, then retry.\n"
            "Tried: " + ", ".join(candidates),
            flush=True,
        )
        return 1
    env["GOOGLE_AI_SCRAPER_URL"] = chosen
    print(f"Using connected scraper: {chosen}", flush=True)

    failed: list[str] = []
    markets = list(args.markets or DEFAULT_MARKETS)
    for i, market in enumerate(markets, 1):
        print(f"\n=== [{i}/{len(markets)}] {market} ===\n", flush=True)
        cmd = [
            str(py),
            str(root / "scripts" / "run_quadrant_market.py"),
            "--industry",
            market,
            "--country",
            args.country,
            "--max-companies",
            str(args.max_companies),
            "--table-companies",
            str(args.table_companies),
        ]
        if args.skip_deep_crawl:
            cmd.append("--skip-deep-crawl")
        rc = subprocess.run(cmd, cwd=str(root), env=env).returncode
        if rc != 0:
            print(f"FAILED: {market} (exit {rc})", flush=True)
            failed.append(market)
        else:
            print(f"DONE: {market}", flush=True)

    print(
        f"\nBatch complete: {len(markets) - len(failed)}/{len(markets)} ok",
        flush=True,
    )
    if failed:
        print("Failed: " + "; ".join(failed), flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
