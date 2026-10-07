#!/usr/bin/env python3
"""Run several markets at the same time, each in its OWN Chromium browser(s).

Every market runs the full one-command pipeline (run_quadrant_pipeline.py:
discovery -> verify rounds -> quick scores -> Top 20 -> evidence -> report ->
VERIFY) as a separate process pinned to a BLOCK of browser slots. A slot is a
Chromium profile folder, data/ai_mode_batch_<slot>, and every browser loads
the bundled CAPTCHA Raptor extension from extensions/ automatically.
With --workers 10 --slots-per-market 2, 5 markets run at once, 2 browsers
each (10 browsers total). run_quadrant_pipeline.py's own --slots range
fans a market's SCORING queries (Step 4 quick scores, Step 5 deep evidence)
across every browser in its block at once. Discovery and the --keep top-up
rounds (Step 1/1b) still run on a single browser regardless of the block
size -- that stage is one sequential conversation with Google AI Mode, not
parallelizable per company the way scoring is. Default --slots-per-market 1
keeps the original one-browser-per-market behaviour.

Isolation:
  * browser  -- one slot per market; Chromium locks its profile, so two
                markets never share one. Slots are 2-digit (<= 99) so
                killing slot 41's orphans cannot touch slot 4 or 410.
  * output   -- every market has its own output/chatgpt_expand/<slug>/.
  * caches   -- the shared HQ cache is merged + written atomically.

When a market finishes, the next one in the file takes its browser slot, so
the 10 browsers stay busy until the queue is empty. Every market is
resumable: re-running this command skips work that is already saved.

Markets file: one market per line, optional "| country" (default --country);
blank lines and # comments ignored.

    Global Smart Ring Market
    Smart Ring Market | india
    Global Hearing Aids Market | global

    .\\.venv\\Scripts\\python.exe scripts\\run_markets_parallel.py ^
        --markets-file queries\\my_markets.txt --workers 10 --keep 120

Per-market logs: logs/parallel/<market>_<country>.log (the full pipeline
output, VERIFY block at the end). Summary: logs/parallel/summary.json.
Anything after "--" is passed to every run_quadrant_pipeline.py call.
"""
from __future__ import annotations

import argparse
import json
import os
import queue
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
        print(f"[parallel {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:60]


def read_markets(path: Path | None, extra: list[str], country: str) -> list[tuple[str, str]]:
    """[(market, country)], de-duplicated -- the same market twice would run
    two processes into one output folder."""
    lines = list(extra)
    if path:
        lines += path.read_text(encoding="utf-8").splitlines()
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        market, _, ctry = line.replace("\t", "|").partition("|")
        market, ctry = market.strip(), (ctry.strip() or country).lower()
        key = (market.lower(), ctry)
        if market and key not in seen:
            seen.add(key)
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
    argv = sys.argv[1:]
    passthrough: list[str] = []
    if "--" in argv:
        cut = argv.index("--")
        argv, passthrough = argv[:cut], argv[cut + 1:]

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--markets-file", help="one market per line, optional '| country'")
    ap.add_argument("--market", action="append", default=[],
                    help="a market (repeatable), same 'name | country' form")
    ap.add_argument("--country", default="global", help="default country")
    ap.add_argument("--workers", type=int, default=10,
                    help="total Chromium browsers open across all markets "
                         "(markets running at once = workers / slots-per-market)")
    ap.add_argument("--slots-per-market", type=int, default=1,
                    help="browsers dedicated to EACH running market's own "
                         "scoring shards (default 1 = original behaviour); "
                         "--workers must be a multiple of this")
    ap.add_argument("--slot-start", type=int, default=41,
                    help="first browser slot; workers use slot-start .. slot-start+workers-1")
    ap.add_argument("--keep", type=int, default=0, help="passed to every market")
    ap.add_argument("--top-n", type=int, default=20, help="passed to every market")
    ap.add_argument("--stagger", type=int, default=20,
                    help="seconds between browser launches (avoids a burst of 10 at once)")
    ap.add_argument("--dry-run", action="store_true", help="show the plan only")
    args = ap.parse_args(argv)

    markets = read_markets(Path(args.markets_file) if args.markets_file else None,
                           args.market, args.country)
    if not markets:
        ap.error("no markets: give --markets-file and/or --market")
    spm = max(1, args.slots_per_market)
    if args.workers % spm != 0:
        ap.error(f"--workers {args.workers} is not a multiple of "
                 f"--slots-per-market {spm}")
    concurrent_markets = max(1, min(args.workers // spm, len(markets)))
    total_slots = concurrent_markets * spm
    all_slots = list(range(args.slot_start, args.slot_start + total_slots))
    if all_slots[0] < 1 or all_slots[-1] > 99:
        ap.error("slots must stay within 1..99 (2-digit profile names)")
    # One BLOCK of `spm` consecutive slots per concurrently-running market,
    # e.g. spm=2 -> [[41,42], [43,44], [45,46], [47,48], [49,50]].
    slot_blocks = [all_slots[i:i + spm] for i in range(0, total_slots, spm)]

    from vendor_intel.scraping.google_ai_mode import installed_extensions

    exts = installed_extensions(str(ROOT / "data" / f"ai_mode_batch_{all_slots[0]:02d}"))
    log(f"{len(markets)} market(s), {concurrent_markets} at a time "
        f"({spm} browser(s) each), browser slots "
        f"{all_slots[0]}..{all_slots[-1]} (Chromium)")
    log("extension(s) loaded in every browser: "
        + (", ".join(Path(p).parent.name if Path(p).name == "extension" else Path(p).name
                     for p in exts) or "NONE -- CAPTCHAs will need solving by hand"))

    log_dir = ROOT / "logs" / "parallel"
    log_dir.mkdir(parents=True, exist_ok=True)

    def command(market: str, country: str, block: list[int]) -> list[str]:
        slots_arg = str(block[0]) if len(block) == 1 else f"{block[0]}-{block[-1]}"
        cmd = [sys.executable, str(ROOT / "scripts" / "run_quadrant_pipeline.py"),
               "--market", market, "--country", country, "--slots", slots_arg,
               "--top-n", str(args.top_n)]
        if args.keep:
            cmd += ["--keep", str(args.keep)]
        return cmd + passthrough

    if args.dry_run:
        for i, (m, c) in enumerate(markets):
            block = slot_blocks[i % concurrent_markets]
            log(f"would run (slots {block}): {' '.join(command(m, c, block)[1:])}")
        return 0

    todo: queue.Queue[tuple[str, str]] = queue.Queue()
    for item in markets:
        todo.put(item)
    results: list[dict] = []
    procs: dict[int, subprocess.Popen] = {}
    start_lock = threading.Lock()
    last_start = [0.0]

    def worker(block: list[int]) -> None:
        label = str(block[0]) if len(block) == 1 else f"{block[0]}-{block[-1]}"
        while True:
            try:
                market, country = todo.get_nowait()
            except queue.Empty:
                return
            with start_lock:  # stagger launches across all workers
                wait = last_start[0] + args.stagger - time.time()
                if wait > 0:
                    time.sleep(wait)
                last_start[0] = time.time()
            log_path = log_dir / f"{slug(market)}_{slug(country)}.log"
            t0 = time.time()
            log(f"slots {label}: START {market} ({country}) -> {log_path.name}")
            with log_path.open("w", encoding="utf-8") as fh:
                proc = subprocess.Popen(
                    command(market, country, block), cwd=str(ROOT), stdout=fh,
                    stderr=subprocess.STDOUT,
                    env={**os.environ, "PYTHONIOENCODING": "utf-8",
                         "PYTHONPATH": str(ROOT / "src")},
                )
                procs[block[0]] = proc
                rc = proc.wait()
            passed, failed = verify_counts(log_path)
            mins = (time.time() - t0) / 60
            status = "OK" if rc == 0 and failed == 0 and passed else "CHECK"
            log(f"slots {label}: {status} {market} ({country}) exit={rc} "
                f"VERIFY {passed} pass / {failed} fail, {mins:.0f} min")
            results.append({"market": market, "country": country, "slots": block,
                            "exit": rc, "verify_pass": passed, "verify_fail": failed,
                            "minutes": round(mins, 1), "log": str(log_path)})

    threads = [threading.Thread(target=worker, args=(b,), daemon=True) for b in slot_blocks]
    for t in threads:
        t.start()
    try:
        while any(t.is_alive() for t in threads):
            time.sleep(5)
    except KeyboardInterrupt:
        log("stopping: terminating running markets (re-run to resume them)")
        for p in procs.values():
            if p.poll() is None:
                p.terminate()
        return 130

    (log_dir / "summary.json").write_text(json.dumps(results, indent=2, ensure_ascii=False),
                                          encoding="utf-8")
    ok = [r for r in results if r["exit"] == 0 and r["verify_fail"] == 0 and r["verify_pass"]]
    log(f"done: {len(ok)}/{len(results)} market(s) passed every VERIFY check "
        f"-> {log_dir / 'summary.json'}")
    for r in results:
        if r not in ok:
            log(f"  CHECK {r['market']} ({r['country']}): exit={r['exit']} "
                f"fail={r['verify_fail']} -> {r['log']}")
    return 0 if len(ok) == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
