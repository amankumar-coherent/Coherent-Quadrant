#!/usr/bin/env python3
"""Run several markets at once, each with 2+ browsers ACTIVE from the very
first query -- not just reserved for later scoring.

run_markets_parallel.py's --slots-per-market gives each market a BLOCK of
browsers, but discovery (Step 1/1b) only ever uses the first slot in that
block regardless of size -- the extra browsers sit idle until the market
reaches scoring. This script instead runs discover_split_merge.py for every
market FIRST (N halves = N real concurrently-working browsers per market,
all markets at once), waits for every market's split-discovery to finish and
merge, THEN hands each market to run_quadrant_pipeline.py for axes/dedupe/
scoring -- which reuses the SAME slot block for real parallel scoring, same
as run_markets_parallel.py already does.

    .\\.venv\\Scripts\\python.exe scripts\\run_markets_split_discovery.py ^
        --markets-file queries\\my_markets.txt --slots-per-market 2 ^
        --keep 120 --slot-start 41
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_PRINT = threading.Lock()


def log(msg: str) -> None:
    with _PRINT:
        print(f"[splitrun {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:60]


def read_markets(path: Path, default_country: str) -> list[tuple[str, str]]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        market, _, ctry = line.replace("\t", "|").partition("|")
        market, ctry = market.strip(), (ctry.strip() or default_country).lower()
        if market:
            out.append((market, ctry))
    return out


def verify_counts(log_path: Path) -> tuple[int, int]:
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0, 0
    block = text[text.rfind("VERIFY"):] if "VERIFY" in text else ""
    return block.count("[PASS]"), block.count("[FAIL]")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--markets-file", required=True)
    ap.add_argument("--country", default="global")
    ap.add_argument("--slots-per-market", type=int, default=2)
    ap.add_argument("--slot-start", type=int, default=41)
    ap.add_argument("--keep", type=int, required=True)
    ap.add_argument("--top-n", type=int, default=20)
    ap.add_argument("--discovery-timeout-minutes", type=float, default=35.0)
    ap.add_argument("--stagger", type=int, default=15,
                    help="seconds between starting each market's split-discovery")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    markets = read_markets(Path(args.markets_file), args.country)
    spm = max(1, args.slots_per_market)
    n = len(markets)
    total_slots = n * spm
    all_slots = list(range(args.slot_start, args.slot_start + total_slots))
    if all_slots[0] < 1 or all_slots[-1] > 99:
        ap.error("slots must stay within 1..99 (2-digit profile names)")
    blocks = [all_slots[i:i + spm] for i in range(0, total_slots, spm)]

    log(f"{n} market(s), {spm} browser(s) each ({total_slots} total), "
        f"slots {all_slots[0]}..{all_slots[-1]}")
    for (market, country), block in zip(markets, blocks):
        log(f"  {market} ({country}) -> slots {block}")

    if args.dry_run:
        return 0

    log_dir = ROOT / "logs" / "parallel"
    log_dir.mkdir(parents=True, exist_ok=True)

    # --- Phase 1: split-discovery, ALL markets at once, every browser busy.
    log("=== Phase 1: split discovery for every market at once ===")
    split_procs = []
    for i, ((market, country), block) in enumerate(zip(markets, blocks)):
        cmd = [sys.executable, str(ROOT / "scripts" / "discover_split_merge.py"),
               "--market", market, "--country", country, "--keep", str(args.keep),
               "--halves", str(spm), "--slot-start", str(block[0]),
               "--timeout-minutes", str(args.discovery_timeout_minutes)]
        log_path = log_dir / f"split_{slug(market)}_{slug(country)}.log"
        fh = log_path.open("w", encoding="utf-8")
        proc = subprocess.Popen(cmd, cwd=str(ROOT), stdout=fh, stderr=subprocess.STDOUT,
                                env={**os.environ, "PYTHONIOENCODING": "utf-8",
                                     "PYTHONPATH": str(ROOT / "src")})
        split_procs.append((proc, fh, market, country, log_path))
        log(f"split-discovery START: {market} ({country}) -> {log_path.name}")
        time.sleep(args.stagger)

    while any(p.poll() is None for p, *_ in split_procs):
        alive = sum(1 for p, *_ in split_procs if p.poll() is None)
        log(f"{alive}/{len(split_procs)} market(s) still in split discovery")
        time.sleep(30)
    for _, fh, *_ in split_procs:
        fh.close()
    for p, _, market, country, log_path in split_procs:
        status = "OK" if p.returncode == 0 else "CHECK"
        log(f"split-discovery {status}: {market} ({country}) exit={p.returncode} "
            f"-> {log_path.name}")

    # --- Phase 2: axes/dedupe/scoring/report, same slot blocks, real parallel scoring.
    log("=== Phase 2: axes, scoring, report for every market ===")
    results: list[dict] = []
    scoring_procs = []
    for (market, country), block in zip(markets, blocks):
        slots_arg = str(block[0]) if len(block) == 1 else f"{block[0]}-{block[-1]}"
        cmd = [sys.executable, str(ROOT / "scripts" / "run_quadrant_pipeline.py"),
               "--market", market, "--country", country, "--slots", slots_arg,
               "--top-n", str(args.top_n), "--keep", str(args.keep)]
        log_path = log_dir / f"{slug(market)}_{slug(country)}.log"
        t0 = time.time()
        fh = log_path.open("w", encoding="utf-8")
        proc = subprocess.Popen(cmd, cwd=str(ROOT), stdout=fh, stderr=subprocess.STDOUT,
                                env={**os.environ, "PYTHONIOENCODING": "utf-8",
                                     "PYTHONPATH": str(ROOT / "src")})
        scoring_procs.append((proc, fh, market, country, log_path, t0))
        log(f"scoring START: {market} ({country}) on slots {block} -> {log_path.name}")
        time.sleep(3)  # stagger just enough to avoid a launch burst

    while any(p.poll() is None for p, *_ in scoring_procs):
        alive = sum(1 for p, *_ in scoring_procs if p.poll() is None)
        log(f"{alive}/{len(scoring_procs)} market(s) still scoring")
        time.sleep(60)
    for _, fh, *_ in scoring_procs:
        fh.close()

    for p, _, market, country, log_path, t0 in scoring_procs:
        passed, failed = verify_counts(log_path)
        mins = (time.time() - t0) / 60
        status = "OK" if p.returncode == 0 and failed == 0 and passed else "CHECK"
        log(f"slots done: {status} {market} ({country}) exit={p.returncode} "
            f"VERIFY {passed} pass / {failed} fail, {mins:.0f} min")
        results.append({"market": market, "country": country, "exit": p.returncode,
                        "verify_pass": passed, "verify_fail": failed,
                        "minutes": round(mins, 1), "log": str(log_path)})

    (log_dir / "split_summary.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    ok = [r for r in results if r["exit"] == 0 and r["verify_fail"] == 0 and r["verify_pass"]]
    log(f"done: {len(ok)}/{len(results)} market(s) passed every VERIFY check "
        f"-> {log_dir / 'split_summary.json'}")
    return 0 if len(ok) == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
