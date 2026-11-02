#!/usr/bin/env python3
"""Run ONE big market (logs/run_market.py: many-browser discovery + the full pipeline) unattended.

    .venv\\Scripts\\python.exe profood\\supervise_market.py "Global X Market" --country global ^
        --keep 250 --discover-to 300 --browsers 20 --wait-for run_sequential

* --wait-for NAME: first waits until no python process has NAME in its command line
  (another run still holds the same browser slots).
* Runs logs/run_market.py; it is resumable (markers + saved work), so every restart
  continues where the market stopped.
* Finished = the market's log ends with a VERIFY block of PASS lines and "report:"
  (profood/watchdog.py's `status`).
* Not finished when the run ends (crash, AI Mode refusals, VERIFY failure) -> restarted.
* No saved progress for --stall minutes (a JSON, log or browser-copy file written) ->
  the run is stopped, its browsers closed and their profiles archived (new cookies, new
  browser), and it is restarted; up to --max-restarts times.
Nothing market-specific: the market, its brief and the numbers come from the arguments.
State: logs/supervise_<slug>.json, log: logs/supervise_<slug>.log.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "profood"))
import watchdog as wd  # noqa: E402  (status, progress_time, reset_browser, processes, kill, PY)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("market")
    ap.add_argument("--country", default="global")
    ap.add_argument("--keep", type=int, default=250)
    ap.add_argument("--discover-to", type=int, default=300)
    ap.add_argument("--browsers", type=int, default=20)
    ap.add_argument("--slot-start", type=int, default=41)
    ap.add_argument("--wait-for", default="", help="wait until no python process has this in its command line")
    ap.add_argument("--stall", type=float, default=60, help="minutes without saved progress before a restart")
    ap.add_argument("--max-restarts", type=int, default=12)
    ap.add_argument("--no-global-focus", action="store_true")
    ap.add_argument("--pipeline-browsers", type=int, default=0,
                    help="browsers for the steps after discovery (default: same as --browsers)")
    ap.add_argument("--city-wise", action="store_true",
                    help="single-country run: discover area by area with each area's cities named")
    ap.add_argument("--force-run", action="store_true",
                    help="run again although the log already ends in a passed VERIFY block (a finished "
                         "market whose saved checks were cleared); finished = that run exits 0")
    args = ap.parse_args()

    from vendor_intel.pipeline.web_expand import default_output_dir

    out = Path(default_output_dir(args.market, args.country))
    slug = out.name
    plog = ROOT / "logs" / "parallel" / f"{slug}.log"
    LOG = ROOT / "logs" / f"supervise_{slug}.log"
    STATE = ROOT / "logs" / f"supervise_{slug}.json"

    def log(msg: str) -> None:
        line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
        print(line, flush=True)
        with LOG.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    def progress() -> float:
        """Newest saved progress: the watchdog's (JSON files, pipeline steps, the browser
        copies of a many-browser discovery) and the discovery browsers' own logs."""
        t = wd.progress_time(out, plog)
        for pat in (f"topup_{slug}_*.log", f"countries_{slug}_*.log", f"supervise_{slug}_run.log"):
            for f in (ROOT / "logs").glob(pat):
                try:
                    t = max(t, f.stat().st_mtime)
                except OSError:
                    pass
        return t

    slots = range(args.slot_start, args.slot_start + args.browsers)
    if args.wait_for:
        log(f"waiting for '{args.wait_for}' to end before starting {args.market}")
        # not this supervisor itself: its own command line holds the same words
        while any(args.wait_for in p["cmd"] for p in wd.processes()
                  if "python" in p["cmd"].lower() and "supervise_market" not in p["cmd"]):
            time.sleep(60)
        log(f"'{args.wait_for}' has ended")
    st = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {"restarts": 0}
    procs = wd.processes()
    for s in slots:
        wd.reset_browser(s, procs)  # fresh profiles: a forced stop leaves locks and stale cookies
    forced = args.force_run
    while True:
        if not forced and wd.status(plog) == "done":
            log(f"DONE: {args.market}")
            return 0
        if st["restarts"] > args.max_restarts:
            log(f"GAVE UP: {args.market} after {st['restarts']} restarts")
            return 1
        cmd = [wd.PY, str(ROOT / "logs" / "run_market.py"), args.market, "--country", args.country,
               "--keep", str(args.keep), "--discover-to", str(args.discover_to), "--browsers", str(args.browsers),
               "--slot-start", str(args.slot_start)] + ([] if args.no_global_focus else ["--global-focus"]) \
            + (["--city-wise"] if args.city_wise else []) \
            + (["--pipeline-browsers", str(args.pipeline_browsers)] if args.pipeline_browsers else [])
        run_log = (ROOT / "logs" / f"supervise_{slug}_run.log").open("a", encoding="utf-8")
        run_log.write(f"\n=== run {st['restarts']} at {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        run_log.flush()
        proc = subprocess.Popen(cmd, cwd=str(ROOT), stdout=run_log, stderr=subprocess.STDOUT,
                                env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONPATH": str(ROOT / "src")},
                                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        started = time.time()
        log(f"RUN {args.market}: attempt {st['restarts'] + 1}, {args.browsers} browsers (slots {slots[0]}-{slots[-1]})")
        why = "run ended"
        while proc.poll() is None:
            time.sleep(60)
            silent = (time.time() - max(progress(), started)) / 60
            if silent >= args.stall:
                why = f"no progress for {silent:.0f} min"
                wd.kill([proc.pid])
                break
        run_log.close()
        if forced and proc.returncode == 0:
            forced = False  # the forced run finished; the log now ends in its own VERIFY block
            continue
        if not forced and wd.status(plog) == "done":
            continue
        st["restarts"] += 1
        STATE.write_text(json.dumps(st, indent=1), encoding="utf-8")
        # Everything this market started goes (its browser copies and the pipeline).
        wd.kill([p["pid"] for p in wd.processes() if args.market in p["cmd"] and "python" in p["cmd"].lower()
                 and "supervise_market" not in p["cmd"]])
        time.sleep(5)
        procs = wd.processes()
        for s in slots:
            wd.reset_browser(s, procs)
        log(f"not finished ({why}); browsers reset, restart #{st['restarts']}")


if __name__ == "__main__":
    raise SystemExit(main())
