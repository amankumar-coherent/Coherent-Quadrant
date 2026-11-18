#!/usr/bin/env python3
"""Watch Google blocks across ALL pipeline browsers and switch the Proton VPN
server when they pile up (user 2026-11-16). One guard for the whole PC, so
20 browsers never fight over the VPN.

Every google_ai_mode worker appends one line per block to data/vpn/blocks.log
("<epoch> <pid> <kind>", kinds: signin, verify, captcha, no_answer). Every
CHECK_SEC the guard scores the last WINDOW_MIN minutes:

    signin 3, verify 2, no_answer 1, captcha 0.5  (solved CAPTCHAs are routine)

and when the score reaches SCORE_LIMIT -- and the last switch was at least
COOLDOWN_MIN minutes ago -- runs vpn_switch.switch(): pause the pipeline
(browsers close), Disconnect, connect the next country, verify the new IP,
resume. Blocks recorded before a switch never count after it.

On start it connects the VPN if it is not connected (the run is meant to go
through the VPN).

Env: VPN_SCORE_LIMIT (default 30), VPN_WINDOW_MIN (10), VPN_COOLDOWN_MIN (15),
VPN_CHECK_SEC (30). Log: logs/vpn_switch.log.

Usage: python scripts/vpn_guard.py
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import vpn_switch as V  # noqa: E402

WEIGHT = {"signin": 3.0, "verify": 2.0, "no_answer": 1.0, "captcha": 0.5}
SCORE_LIMIT = float(os.environ.get("VPN_SCORE_LIMIT") or 30)
WINDOW_MIN = float(os.environ.get("VPN_WINDOW_MIN") or 10)
COOLDOWN_MIN = float(os.environ.get("VPN_COOLDOWN_MIN") or 15)
CHECK_SEC = float(os.environ.get("VPN_CHECK_SEC") or 30)
# User 2026-11-16 17:2x: "if block or not happen, automatically switch after
# 20 minutes" -> a scheduled switch every ROTATE_MIN minutes on top of the
# block-triggered ones (0 = off).
ROTATE_MIN = float(os.environ.get("VPN_ROTATE_MIN") or 20)
BLOCKS = V.VPN_DIR / "blocks.log"
# owner 2026-11-18: a "Sign in" or "Verifying your request" wall means Google flagged this IP; when it
# hits WALL_BROWSERS browsers within WALL_WINDOW_MIN, switch to an unused server at once (the browsers
# reset cookies + profile after the switch), without waiting for the score cooldown.
WALL_BROWSERS = int(os.environ.get("VPN_WALL_BROWSERS") or 2)
WALL_WINDOW_MIN = float(os.environ.get("VPN_WALL_WINDOW_MIN") or 3)
WALL_MIN_GAP_MIN = float(os.environ.get("VPN_WALL_MIN_GAP_MIN") or 3)


def wall_browsers(since: float) -> int:
    """Distinct browser processes that hit a sign-in or verify wall since `since`."""
    pids = set()
    try:
        lines = BLOCKS.read_text(encoding="utf-8", errors="replace").splitlines()[-2000:]
    except FileNotFoundError:
        return 0
    for line in lines:
        parts = line.split()
        if len(parts) >= 3 and parts[2] in ("signin", "verify"):
            try:
                if float(parts[0]) >= since:
                    pids.add(parts[1])
            except ValueError:
                pass
    return len(pids)


def score(since: float) -> tuple[float, dict]:
    counts: dict[str, int] = {}
    total = 0.0
    try:
        lines = BLOCKS.read_text(encoding="utf-8", errors="replace").splitlines()[-5000:]
    except FileNotFoundError:
        return 0.0, counts
    for line in lines:
        parts = line.split()
        if len(parts) < 3:
            continue
        try:
            t = float(parts[0])
        except ValueError:
            continue
        if t < since:
            continue
        counts[parts[2]] = counts.get(parts[2], 0) + 1
        total += WEIGHT.get(parts[2], 1.0)
    return total, counts


def trim() -> None:
    try:
        lines = BLOCKS.read_text(encoding="utf-8", errors="replace").splitlines()
        if len(lines) > 20000:
            BLOCKS.write_text("\n".join(lines[-5000:]) + "\n", encoding="utf-8")
    except FileNotFoundError:
        pass


def _other_guard_running() -> bool:
    """One guard per PC (the VPN is machine-wide): another project's guard, e.g.
    distributor-intelligence's, already decides the switches. Itself and its
    venv launcher (the parent python) do not count."""
    import subprocess
    mine = {os.getpid(), os.getppid()}
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
          "Where-Object { $_.CommandLine -match 'vpn_guard' } | ForEach-Object { $_.ProcessId }")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True,
                             text=True, timeout=60).stdout.split()
        return any(int(x) not in mine for x in out if x.strip().isdigit())
    except Exception:  # noqa: BLE001 -- a failed check must not block the run
        return False


def main() -> None:
    if _other_guard_running():
        V.log("another vpn_guard is already running on this PC -- it switches the VPN; this one exits")
        return
    V.log(f"vpn_guard started: switch when block score >= {SCORE_LIMIT} in {WINDOW_MIN} min "
          f"(cooldown {COOLDOWN_MIN} min) and every {ROTATE_MIN:.0f} min regardless")
    if V.PAUSE_FILE.exists():  # a crashed earlier switch must not freeze the pipeline
        V.resume()
    try:
        if not V.status()["connected"]:
            V.log("VPN not connected - connecting before the run continues")
            V.switch("guard start: VPN was not connected")
    except Exception as exc:  # noqa: BLE001
        V.log(f"start check failed: {type(exc).__name__}: {exc}")
    last_switch = time.time()
    last_note = 0.0
    while True:
        time.sleep(CHECK_SEC)
        now = time.time()
        since = max(now - WINDOW_MIN * 60, last_switch)
        s, counts = score(since)
        if now - last_note > 600:
            V.log(f"guard: block score {s:.1f} in last {WINDOW_MIN:.0f} min {counts}")
            last_note = now
            trim()
        if ROTATE_MIN and now - last_switch >= ROTATE_MIN * 60:
            V.log(f"scheduled switch: {ROTATE_MIN:.0f} min on this server (block score {s:.1f} {counts})")
            try:
                V.switch(f"scheduled every {ROTATE_MIN:.0f} min")
            except Exception as exc:  # noqa: BLE001
                V.log(f"switch failed: {type(exc).__name__}: {exc}")
                if V.PAUSE_FILE.exists():
                    V.resume()
            last_switch = time.time()
            continue
        n_wall = wall_browsers(max(now - WALL_WINDOW_MIN * 60, last_switch + 30))
        if n_wall >= WALL_BROWSERS and now - last_switch >= WALL_MIN_GAP_MIN * 60:
            V.log(f"sign-in / verify wall on {n_wall} browsers in {WALL_WINDOW_MIN:.0f} min - switching to an unused server now")
            try:
                V.switch(f"walls on {n_wall} browsers")
            except Exception as exc:  # noqa: BLE001
                V.log(f"switch failed: {type(exc).__name__}: {exc}")
                if V.PAUSE_FILE.exists():
                    V.resume()
            last_switch = time.time()
            continue
        if s >= SCORE_LIMIT and now - last_switch >= COOLDOWN_MIN * 60:
            V.log(f"block score {s:.1f} >= {SCORE_LIMIT} {counts} - switching VPN server")
            try:
                V.switch(f"Google blocks: score {s:.1f} {counts}")
            except Exception as exc:  # noqa: BLE001
                V.log(f"switch failed: {type(exc).__name__}: {exc}")
                if V.PAUSE_FILE.exists():
                    V.resume()
            last_switch = time.time()


if __name__ == "__main__":
    main()
