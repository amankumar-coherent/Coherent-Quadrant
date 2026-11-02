#!/usr/bin/env python3
"""Keep an unattended market run healthy: disk, Google blocks, stuck browsers.

    .venv/Scripts/python.exe logs/_overnight_watchdog.py <slug> <first-slot> <last-slot>

profood/supervise_market.py already restarts a run that crashes or stalls. This covers the
two things it cannot: the disk filling with archived browser profiles, and Google flagging
the session so every query comes back as a sign-in wall or CAPTCHA (owner 2026-10-30, left
running overnight). Checks every CHECK_EVERY seconds and writes what it did to
logs/overnight_watchdog.log. Nothing market-specific: the slug and slots are arguments.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECK_EVERY = int(os.getenv("CHECK_EVERY") or "600")      # 10 minutes
DISK_FLOOR_GB = float(os.getenv("DISK_FLOOR_GB") or "6")  # clean below this
DISK_TARGET_GB = float(os.getenv("DISK_TARGET_GB") or "20")
BLOCK_LIMIT = int(os.getenv("BLOCK_LIMIT") or "25")       # walls in one window -> fresh cookies
ARCHIVED = re.compile(r"_(stall|quota|noanswer|verify|captchas|reset|ratelimit|signin)_")
BLOCK_LINE = re.compile(r"Sign in to verify|Verifying your request|unusual traffic", re.I)


def log(msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with (ROOT / "logs" / "overnight_watchdog.log").open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def ps(command: str, timeout: float = 180.0) -> str | None:
    """PowerShell, or None when it fails. A watchdog must never die of its own checks:
    under 20 browsers a CIM query can take minutes, and an unhandled TimeoutExpired
    killed this guard 10 minutes into an overnight run (owner 2026-10-30)."""
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", command],
                           capture_output=True, text=True, timeout=timeout)
        return (r.stdout or "").strip()
    except Exception:  # noqa: BLE001 -- timeout, busy machine, anything
        return None


def free_gb() -> float:
    return shutil.disk_usage(str(ROOT)).free / (1024 ** 3)


def clean_archived_profiles() -> int:
    """Delete archived browser profiles (never a live one) until the target is met."""
    data = ROOT / "data"
    gone = 0
    live = re.compile(r"^ai_mode_batch_\d+(_chromium)?$")
    try:
        dirs = sorted((d for d in data.iterdir()
                       if d.is_dir() and ARCHIVED.search(d.name) and not live.match(d.name)),
                      key=lambda d: d.stat().st_mtime)
    except OSError:
        return 0
    for d in dirs:
        if free_gb() >= DISK_TARGET_GB:
            break
        try:
            shutil.rmtree(d, ignore_errors=True)
            gone += 1
        except OSError:
            pass
    return gone


def blocks_since(path: Path, offset: int) -> tuple[int, int]:
    """(block lines added since offset, new offset)."""
    try:
        size = path.stat().st_size
    except OSError:
        return 0, offset
    if size < offset:          # log rotated
        offset = 0
    n = 0
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            fh.seek(offset)
            for line in fh:
                if BLOCK_LINE.search(line):
                    n += 1
            offset = fh.tell()
    except OSError:
        pass
    return n, offset


def archive_live_profiles(first: int, last: int) -> int:
    """Give every slot fresh cookies: the run reopens on a clean profile by itself."""
    stamp = time.strftime("%H%M%S")
    moved = 0
    for slot in range(first, last + 1):
        for suffix in ("", "_chromium"):
            p = ROOT / "data" / f"ai_mode_batch_{slot}{suffix}"
            if p.exists():
                try:
                    p.rename(ROOT / "data" / f"ai_mode_batch_{slot}{suffix}_signin_{stamp}")
                    moved += 1
                except OSError:
                    pass      # in use: the run's own reset will deal with it
    return moved


def kill_slot_browsers(first: int, last: int) -> None:
    """Close the slot browsers so they reopen on the fresh profiles."""
    ps("Get-CimInstance Win32_Process | Where-Object { $_.Name -match 'chrome|chromium' -and "
       "$_.CommandLine -match 'ai_mode_batch_' } | ForEach-Object "
       "{ Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }")


def main() -> int:
    slug, first, last = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    plog = ROOT / "logs" / "parallel" / f"{slug}.log"
    offset = plog.stat().st_size if plog.exists() else 0
    log(f"watching {slug} (slots {first}-{last}); disk floor {DISK_FLOOR_GB} GB, "
        f"block limit {BLOCK_LIMIT} per {CHECK_EVERY}s")
    gone = 0          # consecutive checks that found no supervisor
    while True:
        time.sleep(CHECK_EVERY)
        try:
            # 1. the run finished or was stopped -> nothing left to guard. A failed or slow
            #    check is NOT evidence of that, so only a confirmed count of 0, three times
            #    in a row, ends the watch.
            count = ps("(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                       "Where-Object { $_.CommandLine -match 'supervise_market' } | "
                       "Measure-Object).Count")
            gone = gone + 1 if count == "0" else 0
            if gone >= 3:
                log("no supervisor for three checks running -- watchdog stopping")
                return 0
            # 2. disk
            if free_gb() < DISK_FLOOR_GB:
                n = clean_archived_profiles()
                log(f"disk was low: deleted {n} archived profiles, now {free_gb():.1f} GB free")
            # 3. Google blocks
            n, offset = blocks_since(plog, offset)
            if n >= BLOCK_LIMIT:
                moved = archive_live_profiles(first, last)
                kill_slot_browsers(first, last)
                log(f"{n} block pages in the last window: archived {moved} profiles and closed "
                    "the browsers so the run reopens with fresh cookies")
            elif n:
                log(f"{n} block page(s) in the last window (under the limit, leaving it alone)")
        except Exception as err:  # noqa: BLE001 -- nothing may kill the guard
            log(f"check failed ({type(err).__name__}: {str(err)[:90]}) -- carrying on")


if __name__ == "__main__":
    raise SystemExit(main())
