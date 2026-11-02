#!/usr/bin/env python3
"""Run the unfinished markets of a markets file, --parallel at a time (default 1), --browsers in total.

    .venv\\Scripts\\python.exe profood\\run_sequential.py profood\\run21_india_markets.json --browsers 20

With --parallel 1 one market runs at a time on all --browsers; with --parallel 2 the browsers are
split in two FIXED groups (a browser profile cannot be used by two markets at once: Chrome reports
"Profile error" and the pipeline kills what it takes for an orphan), so a step that needs few
browsers (5 companies = 5 browsers) leaves the other group's market working instead of idling.
For a market the whole pipeline's browser steps (company checks, scoring,
evidence, estimates, fact-check) split over all N browsers, so one market
finishes much faster than with one browser each; when it has passed VERIFY the
next market takes the same N browsers. Markets already finished are skipped;
the one furthest along (by its last pipeline step) goes first.

Unattended recovery, as in profood/watchdog.py (whose helpers it uses):
  * a market whose run ends without finishing (crash, AI Mode refusals, VERIFY
    failure) is restarted from its saved work on fresh browser profiles;
  * a market with no saved progress for --stall minutes is stopped, its browsers
    are closed and their profiles archived (new cookies), and it is restarted;
  * after --max-restarts a market is left (logged "gave up") and the next goes.
Nothing market-specific: the markets come from the file, every run is the normal
one-command pipeline (run_quadrant_pipeline.py). State: logs/profood_sequential.json,
log: logs/profood_sequential.log.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "profood"))
import watchdog as wd  # noqa: E402  (status, progress_time, reset_browser, processes, kill)

LOG = ROOT / "logs" / "profood_sequential.log"
STATE = ROOT / "logs" / "profood_sequential.json"

# Pipeline progress, earliest to latest: a market whose last step line holds a
# later key is further along and goes first.
STEP_ORDER = ["3b.", "3c.", "ownership:", "identity:", "hq:", "scope:", "overall:", "evidence_r",
              "reasoning_r", "partfill", "fillgap", "5b.", "7c.", "7b.", "8a.", "8b."]


def log(msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def progress_rank(plog: Path) -> int:
    try:
        text = plog.read_text(encoding="utf-8", errors="replace")[-20000:]
    except OSError:
        return -1
    steps = [l for l in text.splitlines() if l.startswith("[pipeline ") and "still running" not in l]
    if not steps:
        return -1
    return max((i for i, k in enumerate(STEP_ORDER) if k in steps[-1]), default=-1)


LOCK = threading.Lock()
ACTIVE: set[str] = set()


def save_state() -> None:
    with LOCK:
        STATE.write_text(json.dumps(STATE_DATA, indent=1), encoding="utf-8")


def run_market(name: str, country: str, args, st: dict, first: int, count: int) -> str:
    from vendor_intel.pipeline.web_expand import default_output_dir

    out = Path(default_output_dir(name, country))
    plog = ROOT / "logs" / "parallel" / f"{out.name}.log"
    slots = f"{first}-{first + count - 1}"
    while True:
        if wd.status(plog) == "done":
            return "done"
        if st["restarts"] > args.max_restarts:
            return "gave up"
        with plog.open("a", encoding="utf-8") as fh:
            fh.write(f"\n=== sequential run {st['restarts']} on slots {slots} at {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            proc = subprocess.Popen(
                [wd.PY, str(ROOT / "scripts" / "run_quadrant_pipeline.py"), "--market", name,
                 "--country", country, "--slots", slots, "--top-n", "20", "--keep", str(args.keep)],
                cwd=str(ROOT), stdout=fh, stderr=subprocess.STDOUT,
                env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONPATH": str(ROOT / "src")},
                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        started = time.time()
        log(f"RUN {name}: slots {slots}, attempt {st['restarts'] + 1}")
        why = "run ended"
        while proc.poll() is None:
            time.sleep(60)
            silent = (time.time() - max(wd.progress_time(out, plog), started)) / 60
            if silent >= args.stall:
                why = f"no progress for {silent:.0f} min"
                wd.kill([proc.pid])
                break
        if wd.status(plog) == "done":
            return "done"
        st["restarts"] += 1
        procs = wd.processes()
        for s in range(first, first + count):
            wd.reset_browser(s, procs)
        log(f"{name}: not finished ({why}); browsers reset, restart #{st['restarts']}")
        STATE_DATA[name] = st
        save_state()


STATE_DATA: dict = {}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("markets_file")
    ap.add_argument("--browsers", type=int, default=20, help="browsers in total")
    ap.add_argument("--parallel", type=int, default=1, help="markets at a time; the browsers are split evenly")
    ap.add_argument("--slot-start", type=int, default=41)
    ap.add_argument("--keep", type=int, default=120)
    ap.add_argument("--stall", type=float, default=45, help="minutes without saved progress before a restart")
    ap.add_argument("--max-restarts", type=int, default=8)
    ap.add_argument("--list", action="store_true", help="print the order and exit")
    args = ap.parse_args()

    from vendor_intel.pipeline.web_expand import default_output_dir

    markets = json.loads(Path(args.markets_file).read_text(encoding="utf-8"))["markets"]
    if STATE.exists():
        STATE_DATA.update(json.loads(STATE.read_text(encoding="utf-8")))

    def plog_of(m: dict) -> Path:
        country = str(m.get("country") or "global").lower()
        return ROOT / "logs" / "parallel" / f"{Path(default_output_dir(m['market'], country)).name}.log"

    def pending() -> list[dict]:
        left = [m for m in markets if wd.status(plog_of(m)) != "done"
                and STATE_DATA.get(m["market"], {}).get("status") != "gave up"
                and m["market"] not in ACTIVE]
        return sorted(left, key=lambda m: progress_rank(plog_of(m)), reverse=True)

    if args.list:
        for m in pending():
            print(f"{progress_rank(plog_of(m)):>3}  {m['market']}")
        return 0

    count = max(1, args.browsers // max(1, args.parallel))
    log(f"sequential start: {len(pending())} markets to run, {args.parallel} at a time, {count} browsers each "
        f"(slots {args.slot_start}-{args.slot_start + count * args.parallel - 1}), stall {args.stall:g} min")
    procs = wd.processes()
    for sl in range(args.slot_start, args.slot_start + count * args.parallel):
        wd.reset_browser(sl, procs)  # fresh profiles: a forced stop leaves locks and stale cookies

    def worker(first: int) -> None:
        while True:
            with LOCK:
                todo = pending()
                if not todo:
                    return
                m = todo[0]
                ACTIVE.add(m["market"])
            name, country = m["market"], str(m.get("country") or "global").lower()
            st = STATE_DATA.setdefault(name, {"restarts": 0})
            try:
                result = run_market(name, country, args, st, first, count)
            except Exception as err:  # noqa: BLE001 -- one market's failure must not stop the others
                log(f"{name}: runner error {err!r}")
                result = "error"
                st["restarts"] += 1
                if st["restarts"] > args.max_restarts:
                    result = "gave up"
            finally:
                ACTIVE.discard(name)
            if result not in ("done", "gave up"):
                st.pop("status", None)
                save_state()
                continue
            st["status"] = result
            save_state()
            log(f"{result.upper()}: {name} ({len(pending())} left to start)")

    threads = []
    for k in range(args.parallel):
        t = threading.Thread(target=worker, args=(args.slot_start + k * count,), daemon=False)
        t.start()
        threads.append(t)
        time.sleep(30)  # stagger the two groups' first browser launches
    for t in threads:
        t.join()
    log("sequential end: every market finished or gave up")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
