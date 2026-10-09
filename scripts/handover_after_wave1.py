#!/usr/bin/env python3
"""Hand the queue over to a fresh orchestrator once wave 1 finishes.

Wave 1 was launched with --target 300. The target for the remaining markets
is 280, but a running Python process cannot pick up an edited source file,
so the change needs a new orchestrator. Restarting immediately would abandon
five markets mid-discovery, so this waits instead.

"Wave 1 finished" is judged by the five wave-1 markets, not by a timer: each
is complete when its own checkpoint says every row is scored. The old
orchestrator is then stopped BEFORE the new one starts, so the two never run
a market concurrently on the same slot profile.

Markets already complete are skipped by the new orchestrator on sight, so
handing it the full 25-market queue re-runs nothing.

    .\\.venv\\Scripts\\python.exe scripts\\handover_after_wave1.py
"""
from __future__ import annotations

import datetime
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

POLL_SECONDS = 120
MARKETS_FILE = ROOT / "queries" / "drone_25.tsv"
COUNTRY = "India"
WAVE_SIZE = 5
# Long enough for five markets to discover, verify and score; the loop exits
# as soon as they are actually done, so this only caps a pathological stall.
MAX_WAIT_HOURS = 14.0


def _log(msg: str) -> None:
    stamp = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[handover {stamp}] {msg}", flush=True)


def wave1_markets() -> list[str]:
    from run_parallel_batches import read_queue  # noqa: PLC0415

    return [m for m, _scope in read_queue(MARKETS_FILE)[:WAVE_SIZE]]


def orchestrator_pids() -> list[int]:
    """PIDs of running run_parallel_batches ORCHESTRATORS.

    Matched on the script being executed, not on the command line containing
    the name: a helper that merely mentions "run_parallel_batches" (this
    script imports it, and any status check quoting it) would otherwise match
    and be killed.

    This process and its own parent are excluded for the same reason.
    """
    import os

    try:
        out = subprocess.run(
            [
                "powershell", "-NoProfile", "-NonInteractive", "-Command",
                "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                "Where-Object { $_.CommandLine -match "
                r"'run_parallel_batches\.py' } | "
                "Select-Object -ExpandProperty ProcessId",
            ],
            capture_output=True, text=True, timeout=30,
        )
        mine = {os.getpid(), os.getppid()}
        return [
            int(p)
            for p in (out.stdout or "").split()
            if p.strip().isdigit() and int(p) not in mine
        ]
    except Exception:  # noqa: BLE001
        return []


def main() -> int:
    sys.path.insert(0, str(ROOT / "scripts"))
    from run_parallel_batches import market_done  # noqa: PLC0415

    markets = wave1_markets()
    _log(f"waiting for wave 1: {', '.join(m.split()[0] for m in markets)}")

    deadline = time.monotonic() + MAX_WAIT_HOURS * 3600
    while time.monotonic() < deadline:
        states = [market_done(m, COUNTRY) for m in markets]
        done = sum(1 for d, _r, _s in states if d)
        if done == len(markets):
            _log("wave 1 complete")
            break
        scored = sum(s for _d, _r, s in states)
        rows = sum(r for _d, r, _s in states)
        _log(f"wave 1: {done}/{len(markets)} markets, {scored}/{rows} rows scored")
        time.sleep(POLL_SECONDS)
    else:
        _log("gave up waiting — leaving the original orchestrator alone")
        return 1

    # Stop the old orchestrator BEFORE starting the new one: two orchestrators
    # would assign the same slot profile to two different markets.
    pids = orchestrator_pids()
    for pid in pids:
        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
    if pids:
        _log(f"stopped {len(pids)} old orchestrator process(es)")
        time.sleep(5)

    target = 280
    override = ROOT / "logs" / ".target_override"
    if override.exists():
        try:
            target = int(override.read_text(encoding="utf-8").strip())
        except Exception:  # noqa: BLE001
            pass

    log_path = ROOT / "logs" / "batch_drone25_wave2plus.log"
    _log(f"starting waves 2-5 at target {target} -> {log_path.name}")
    with log_path.open("w", encoding="utf-8") as fh:
        subprocess.Popen(
            [
                sys.executable, str(ROOT / "scripts" / "run_parallel_batches.py"),
                "--markets-file", str(MARKETS_FILE),
                "--wave-size", str(WAVE_SIZE),
                "--country", COUNTRY,
                "--target", str(target),
            ],
            cwd=str(ROOT), stdout=fh, stderr=subprocess.STDOUT,
        )
    _log("handover done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
