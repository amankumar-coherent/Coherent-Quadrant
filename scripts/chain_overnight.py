#!/usr/bin/env python3
"""Wait for the in-flight market run to finish, then run the overnight queue.

Kept separate from run_overnight.py so the currently running Silicon Carbide
job is not disturbed: this only watches, then hands over.

"Finished" is judged by our own processes disappearing, not by a timer — a
market that takes four hours and one that takes forty minutes both end when
the pipeline exits.

    .\\.venv\\Scripts\\python.exe scripts\\chain_overnight.py --markets-file queries\\overnight_5.txt
"""
from __future__ import annotations

import argparse
import datetime
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLL_SECONDS = 60
# A fresh run needs a moment to appear in the process list; without this the
# watcher can see "nothing running" in the gap and hand over far too early.
SETTLE_CHECKS = 3


def _log(msg: str) -> None:
    stamp = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[chain {stamp}] {msg}", flush=True)


def pipeline_running() -> bool:
    """True while a run_chatgpt_expand subprocess is alive."""
    try:
        out = subprocess.run(
            [
                "powershell", "-NoProfile", "-NonInteractive", "-Command",
                "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                "Where-Object { $_.CommandLine -like '*run_chatgpt_expand*' } | "
                "Measure-Object | Select-Object -ExpandProperty Count",
            ],
            capture_output=True, text=True, timeout=30,
        )
        return int((out.stdout or "0").strip() or 0) > 0
    except Exception:  # noqa: BLE001 - assume still running rather than
        return True   # handing over on top of a live job


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--markets-file", required=True)
    ap.add_argument("--target", type=int, default=300)
    ap.add_argument("--max-wait-hours", type=float, default=8.0)
    args = ap.parse_args()

    _log("waiting for the current market run to finish")
    deadline = time.monotonic() + args.max_wait_hours * 3600
    idle = 0
    while time.monotonic() < deadline:
        if pipeline_running():
            idle = 0
        else:
            idle += 1
            # Require several consecutive idle polls: a market boundary or a
            # browser restart briefly shows no process.
            if idle >= SETTLE_CHECKS:
                break
        time.sleep(POLL_SECONDS)

    _log("current run finished — starting the overnight queue")
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = ROOT / "logs" / f"overnight_{stamp}.log"
    (ROOT / "logs" / ".current_overnight_log").write_text(
        str(log_path.relative_to(ROOT)).replace("\\", "/"), encoding="utf-8"
    )
    with log_path.open("w", encoding="utf-8") as fh:
        proc = subprocess.run(
            [
                sys.executable, str(ROOT / "scripts" / "run_overnight.py"),
                "--markets-file", args.markets_file,
                "--target", str(args.target),
            ],
            cwd=str(ROOT), stdout=fh, stderr=subprocess.STDOUT,
        )
    _log(f"overnight queue exited with {proc.returncode}")
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
