#!/usr/bin/env python3
"""Proton VPN server switching by driving the Proton VPN app's own window
(user 2026-11-16: Proton VPN Plus, no admin rights -> no WireGuard CLI, so
the app is controlled through Windows UI Automation).

When Google blocks the pipeline's IP, switch() does, in this order (user:
"when you click Disconnect, first stop all browsers, then after connect
resume"):
  1. pause: create data/vpn/PAUSE. google_ai_mode.ask() sees it before its
     next query, CLOSES its browser and waits;
  2. wait until every pipeline browser has closed (max PAUSE_WAIT_SEC, then
     the leftovers are closed);
  3. click Disconnect in Proton VPN and wait for "Unprotected";
  4. connect to the next country in the rotation (search box + that
     country's Connect button), wait for the protected state;
  5. check the new public IP really changed and the internet works;
  6. resume: delete PAUSE -> every worker opens a fresh browser and goes on.

Automation ids (Proton VPN 5.1.9): ConnectionCardConnectButton (when off),
ConnectionCardDisconnectButton (when on), ProtectionTitle ("Protected" /
"Unprotected"), SearchTextBox, Connect_to_<code> (UK, not GB).

Usage:
    python scripts/vpn_switch.py --status
    python scripts/vpn_switch.py --switch [--country US]
    python scripts/vpn_switch.py --connect        # connect if not connected
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
try:  # VPN_DIR / VPN_BROWSER_PATTERN may be set in this project's .env
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:  # noqa: BLE001
    pass
# One VPN per PC: projects that run at the same time share ONE folder (VPN_DIR in .env, e.g. the
# distributor-intelligence data/vpn), so a switch pauses every project's browsers and gives each a
# fresh profile, and only one guard decides. Default: this project's own data/vpn.
VPN_DIR = Path(os.environ.get("VPN_DIR") or (ROOT / "data" / "vpn"))
PAUSE_FILE = VPN_DIR / "PAUSE"
STATE_FILE = VPN_DIR / "state.json"
LOG_FILE = ROOT / "logs" / "vpn_switch.log"
LAUNCHER = r"C:\Program Files\Proton\VPN\ProtonVPN.Launcher.exe"

# Rotation: countries with many Proton servers and normal Google service.
ROTATION: tuple[tuple[str, str], ...] = (
    ("US", "United States"), ("NL", "Netherlands"), ("DE", "Germany"),
    ("UK", "United Kingdom"), ("CA", "Canada"), ("SE", "Sweden"),
    ("CH", "Switzerland"), ("FR", "France"), ("SG", "Singapore"),
    ("JP", "Japan"), ("AU", "Australia"), ("ES", "Spain"),
    ("IT", "Italy"), ("BE", "Belgium"), ("AT", "Austria"),
    ("DK", "Denmark"), ("NO", "Norway"), ("PL", "Poland"),
)
PAUSE_WAIT_SEC = int(os.environ.get("VPN_PAUSE_WAIT_SEC") or 180)
# Browser profiles of the pipeline (closed during a switch). Never the
# user's own Chrome (VPN_BROWSER_PATTERN overrides).
BROWSER_PATTERN = os.environ.get("VPN_BROWSER_PATTERN") or r"ai_mode_batch_\d+_|ai_mode_chrome_profile"


def log(msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    LOG_FILE.parent.mkdir(exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def public_ip(timeout: float = 10.0) -> str:
    for url in ("https://api.ipify.org", "https://ifconfig.me/ip"):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                return r.read().decode().strip()
        except Exception:
            continue
    return ""


def _window():
    from pywinauto import Desktop
    desk = Desktop(backend="uia")
    try:
        w = desk.window(title="Proton VPN")
        w.wait("exists", timeout=5)
        return w
    except Exception:
        subprocess.Popen([LAUNCHER])
        w = desk.window(title="Proton VPN")
        w.wait("exists", timeout=60)
        return w


def _by_id(w, aid: str):
    return w.child_window(auto_id=aid)


def status() -> dict:
    """Proton 5.1.9: connected screen = ProtectionTitle "Protected" and a
    ConnectionCardDisconnectButton; disconnected = "Unprotected" and
    ConnectionCardConnectButton; anything else (Connecting...) = not yet."""
    w = _window()
    try:
        title = _by_id(w, "ProtectionTitle").window_text().strip()
    except Exception:
        title = ""
    return {"protection": title, "connected": title.lower() == "protected"}


def _wait(cond, timeout: float, what: str) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            if cond():
                return True
        except Exception:
            pass
        time.sleep(2)
    log(f"timeout waiting for: {what}")
    return False


def disconnect() -> bool:
    w = _window()
    if status()["protection"].lower() == "unprotected":
        return True
    btn = _by_id(w, "ConnectionCardDisconnectButton")
    log("clicking Disconnect")
    btn.invoke()
    return _wait(lambda: status()["protection"].lower() == "unprotected", 60, "Unprotected")


def connect(iso: str, name: str) -> bool:
    w = _window()
    box = _by_id(w, "SearchTextBox")
    box.set_focus()
    box.set_edit_text(name)
    time.sleep(2)
    btn = _by_id(w, f"Connect_to_{iso}")
    if not _wait(lambda: btn.exists(), 15, f"Connect_to_{iso}"):
        return False
    log(f"connecting to {name} ({iso})")
    btn.invoke()
    ok = _wait(lambda: status()["connected"], 120, f"connected to {name}")
    try:
        box.set_edit_text("")
    except Exception:
        pass
    return ok


RECENT_IP_HOURS = float(os.environ.get("VPN_RECENT_IP_HOURS") or 24)


def _recent_ips(st: dict) -> set[str]:
    return {h[0] for h in st.get("ips", []) if time.time() - h[1] < RECENT_IP_HOURS * 3600}


def _unused_country(st: dict, tried: set[str]) -> tuple[str, str]:
    """The rotation country used least recently (never used first), skipping ones tried in this switch
    and the one we are on now."""
    used = st.get("used", {})
    cur = st.get("country", "")
    pool = [c for c in ROTATION if c[0] not in tried and c[1] != cur] or list(ROTATION)
    return min(pool, key=lambda c: used.get(c[0], 0.0))


def _load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"next": 0, "switches": 0}


def _save_state(st: dict) -> None:
    VPN_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=1), encoding="utf-8")
    os.replace(tmp, STATE_FILE)


def _pipeline_browsers() -> int:
    ps = ("(Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | Where-Object { "
          f"$_.CommandLine -match '{BROWSER_PATTERN}' "
          "}).Count")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True,
                             text=True, timeout=60).stdout.strip()
        return int(out or 0)
    except Exception:
        return -1


def _close_pipeline_browsers() -> None:
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | Where-Object { "
          f"$_.CommandLine -match '{BROWSER_PATTERN}' "
          "} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, timeout=120)


def pause(reason: str) -> None:
    VPN_DIR.mkdir(parents=True, exist_ok=True)
    PAUSE_FILE.write_text(f"{time.strftime('%H:%M:%S')} {reason}", encoding="utf-8")
    log(f"PAUSE set ({reason}) - waiting for pipeline browsers to close")
    end = time.time() + PAUSE_WAIT_SEC
    while time.time() < end:
        n = _pipeline_browsers()
        if n == 0:
            log("all pipeline browsers closed")
            return
        time.sleep(5)
    log(f"{_pipeline_browsers()} browser(s) still open after {PAUSE_WAIT_SEC}s - closing them")
    _close_pipeline_browsers()
    time.sleep(5)


def resume() -> None:
    try:
        PAUSE_FILE.unlink()
    except FileNotFoundError:
        pass
    log("PAUSE removed - browsers reopen and the pipeline resumes")


def switch(reason: str = "manual", country: str | None = None) -> bool:
    """Pause -> disconnect -> connect next country -> verify IP -> resume.
    The pause is ALWAYS lifted at the end, even if the switch failed, so a
    UI hiccup can never freeze the pipeline."""
    st = _load_state()
    old_ip = public_ip()
    pause(reason)
    ok = False
    tried: set[str] = set()
    if st.get("ip"):  # the server being left counts as used
        st.setdefault("ips", []).append([st["ip"], time.time()])
    try:
        if not disconnect():
            log("disconnect did not complete")
        for attempt in range(3):
            if country:
                iso, name = next(((i, n) for i, n in ROTATION if i == country.upper()),
                                 (country.upper(), country))
            else:
                iso, name = _unused_country(st, tried)
            tried.add(iso)
            if connect(iso, name):
                new_ip = ""
                end = time.time() + 60   # the tunnel needs a moment to carry traffic
                while time.time() < end:
                    new_ip = public_ip(timeout=8)
                    if new_ip and new_ip != old_ip:
                        break
                    time.sleep(4)
                if new_ip and new_ip in _recent_ips(st) and attempt < 2:
                    # owner 2026-11-18: always a server that was not used -- Google remembers a flagged IP
                    log(f"{name} gave {new_ip}, an IP used in the last {RECENT_IP_HOURS:.0f} h - trying another country")
                    disconnect()
                    country = None
                    continue
                if new_ip and new_ip != old_ip:
                    st["switches"] = st.get("switches", 0) + 1
                    st["last_switch"] = time.time()
                    st["country"] = name
                    st["ip"] = new_ip
                    st.setdefault("used", {})[iso] = time.time()
                    hist = [h for h in st.get("ips", []) if time.time() - h[1] < RECENT_IP_HOURS * 3600]
                    st["ips"] = hist + [[new_ip, time.time()]]
                    log(f"SWITCHED: {old_ip or '?'} -> {new_ip} ({name}), switch #{st['switches']}")
                    ok = True
                    break
                log(f"connected to {name} but IP check failed (old {old_ip}, new {new_ip or 'none'})")
            country = None
        _save_state(st)
    except Exception as exc:  # noqa: BLE001
        log(f"switch error: {type(exc).__name__}: {exc}")
    finally:
        resume()
    return ok


def ensure_connected() -> bool:
    if status()["connected"]:
        return True
    st = _load_state()
    iso, name = ROTATION[st["next"] % len(ROTATION)]
    st["next"] = (st["next"] + 1) % len(ROTATION)
    _save_state(st)
    return connect(iso, name)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--switch", action="store_true")
    ap.add_argument("--connect", action="store_true")
    ap.add_argument("--country", default=None)
    args = ap.parse_args()
    if args.status:
        print(status(), "ip:", public_ip())
    elif args.switch:
        print("ok" if switch("manual", args.country) else "FAILED")
    elif args.connect:
        print("ok" if ensure_connected() else "FAILED", public_ip())


if __name__ == "__main__":
    main()
