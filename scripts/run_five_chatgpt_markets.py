#!/usr/bin/env python3
"""Run ChatGPT expand for 5 markets from Coherent-Quadrant (scraper :15561).

This is NOT scripts/run_markets_batch.py (quadrant crawl). Output:

  D:\\Coherent-Quadrant\\output\\chatgpt_expand\\<slug>\\*_FINAL.xlsx

Chrome Profile 2 extension Server URL must be http://localhost:15561
(other project keeps :15551).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[1]
MARKETS = [
    "Global Flexible Packaging Market",
    "Global Wearable Medical Devices Market",
    "Global Semiconductor Market",
    "Global Liquefied Natural Gas Market",
    "Global GLP-1 Receptor Agonist Market",
]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run 5 ChatGPT expand markets one after another (target 700)."
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Ignore checkpoints/FINAL and start each market from scratch",
    )
    parser.add_argument("--target", type=int, default=700)
    args = parser.parse_args()

    os.chdir(ROOT)
    py = ROOT / ".venv" / "Scripts" / "python.exe"
    if not py.exists():
        py = Path(sys.executable)

    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["GOOGLE_AI_SCRAPER_ENABLED"] = "true"
    env["GOOGLE_AI_SCRAPER_BASE_URL"] = "http://127.0.0.1:15561"
    env["GOOGLE_AI_SCRAPER_URL"] = "http://127.0.0.1:15561"
    env["GOOGLE_AI_SCRAPER_LLM_CLEAN"] = "true"
    env["GOOGLE_AI_SCRAPER_LLM_CLEAN_ONLY_WHEN_MISSING"] = "false"
    env["GOOGLE_AI_SCRAPER_DISCOVERY"] = "true"
    env["GOOGLE_AI_SCRAPER_GAP_FILL"] = "true"
    env["EXPAND_LANDSCAPE_MODE"] = "vendors"
    env["CHANNEL_PURITY_FILTER"] = "false"
    env["EXPAND_OUTPUT_FOLDER"] = "chatgpt_expand"
    env["SEARCH_STACK_SOURCES"] = "google_ai"
    # Company Details: Brand|Company|Role|Quadrant|X|Y|Overall|Found in
    # Google asks only HQ (Found in) + website — not employees/turnover/contacts
    env["GOOGLE_AI_GAP_FILL_FIELDS"] = "headquarters,website"
    env["GOOGLE_AI_GAP_FILL_MAX_QUERIES"] = "4"
    env["SEARCH_STACK_RESIDUAL_COLUMNS"] = "Headquarters,Website"
    env["FOUND_IN_CITY_COUNTRY"] = "1"
    env["FOUND_IN_WIKI_RESOLVE"] = "1"
    env["EXPAND_MARKET_GATE"] = "1"

    health_py = (
        "import sys; sys.path.insert(0, r'" + str(ROOT / "src") + "')\n"
        "import httpx\n"
        "from vendor_intel.clients.google_ai_scraper import google_ai_base_url\n"
        "url = google_ai_base_url().rstrip('/') + '/health'\n"
        "try:\n"
        "    r = httpx.get(url, timeout=5.0)\n"
        "    data = r.json() if r.status_code == 200 else {}\n"
        "except Exception as e:\n"
        "    print('HEALTH FAIL', e); raise SystemExit(1)\n"
        "print(url, data)\n"
        "if not data.get('extension_connected'):\n"
        "    print('Extension not connected on 15561. Set Server URL to http://localhost:15561 and refresh.')\n"
        "    raise SystemExit(1)\n"
    )
    chk = subprocess.run([str(py), "-c", health_py], cwd=str(ROOT), env=env)
    if chk.returncode != 0:
        print(
            "Start scraper on 15561 (scripts/start_scraper_profile2.ps1) "
            "and point THIS Chrome extension to http://localhost:15561",
            flush=True,
        )
        return 1

    target = str(max(1, int(args.target)))
    if args.fresh:
        print(f"FRESH start: target={target} (checkpoints ignored for all 5 markets)", flush=True)

    failed: list[str] = []
    runner = ROOT / "scripts" / "run_chatgpt_expand.py"
    for i, market in enumerate(MARKETS, 1):
        print(f"\n=== [{i}/{len(MARKETS)}] ChatGPT expand: {market} ===\n", flush=True)
        cmd = [
            str(py),
            str(runner),
            "--query",
            market,
            "--country",
            "global",
            "--batch",
            "all",
            "--target",
            target,
            "--max-fill",
            target,
            "--max-queries",
            "220",
            "--fill-existing",
            "--scraper-url",
            "http://127.0.0.1:15561",
        ]
        if args.fresh:
            cmd.append("--fresh")
        rc = subprocess.run(cmd, cwd=str(ROOT), env=env).returncode
        if rc != 0:
            print(f"FAILED: {market} (exit {rc})", flush=True)
            failed.append(market)
        else:
            print(f"DONE: {market}", flush=True)

    print(f"\nBatch complete: {len(MARKETS) - len(failed)}/{len(MARKETS)} ok", flush=True)
    if failed:
        print("Failed: " + "; ".join(failed), flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
