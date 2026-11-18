"""Change the machine's public IP when Google blocks it.

Google's "unusual traffic / Try again later" block follows the IP, so every browser on the
machine is blocked together and only waiting (the shared pause in ``google_ai_mode``) used to
help -- for hours at a time. With a VPN, a fresh IP clears it at once. This module switches to
the next VPN server the moment a block starts the shared pause, checks that the public IP
really changed, and then lets the browsers go back to work after a short wait.

The idea of cycling through a list of server configs and checking the new exit IP comes from
VPN rotators such as bradsec/pfsense-vpn-rotator and rotating-ovpn; the code is our own and
switches on a BLOCK rather than on a fixed timer, so a working IP is never dropped mid-search.

Two backends, both off unless configured:

* ``GOOGLE_AI_MODE_WIREGUARD_CONFIGS=<folder>`` -- a folder of WireGuard ``*.conf`` files (for
  example Proton VPN's downloaded WireGuard configs, one per server). The switcher removes the
  tunnel it installed last and installs the next one with ``wireguard.exe``
  (``GOOGLE_AI_MODE_WIREGUARD_EXE``, default the standard install path). Installing a tunnel
  service needs an Administrator terminal on Windows.
  Without Administrator rights the switch is handed to a scheduled task that runs with
  them (``GOOGLE_AI_MODE_WIREGUARD_TASK``, default ``CoherentQuadrant_VPN_Switch``; register it
  once with ``scripts/setup_vpn_switch.ps1`` from an Administrator PowerShell), so the
  pipeline itself never needs an elevated terminal.
* ``GOOGLE_AI_MODE_ROTATE_CMD=<command>`` -- any command that changes the IP (a VPN CLI, a
  router script, a mobile-hotspot toggle). Run through the shell; exit code 0 = done.

Machine-wide: ten browsers in ten processes share one IP, so one lock file makes sure only one
of them switches at a time, and ``GOOGLE_AI_MODE_ROTATE_MIN_GAP`` (default 90 s) stops a burst
of blocks from switching servers again before the new IP has even been tried.

CLI: ``python -m vendor_intel.scraping.ip_rotate status | ip | rotate | wg-next``
(``wg-next`` = the elevated half: move WireGuard to the next config, run by the task)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_WG = r"C:\Program Files\WireGuard\wireguard.exe"
_LOCK_STALE = 300.0       # a lock older than this belongs to a process that died mid-switch
_IP_URLS = ("https://api.ipify.org", "https://ifconfig.me/ip", "https://icanhazip.com")


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _float_env(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return default


def state_path() -> Path:
    override = _env("GOOGLE_AI_MODE_ROTATE_STATE")
    return Path(override) if override else _ROOT / "data" / "ip_rotate_state.json"


def _wg_state_path() -> Path:
    """Which tunnel is up: written only by the process that switches WireGuard (possibly the
    elevated task), so it never races the caller's own state file."""
    return state_path().with_name("ip_rotate_wireguard.json")


def _task_name() -> str:
    return _env("GOOGLE_AI_MODE_WIREGUARD_TASK", "CoherentQuadrant_VPN_Switch")


def configs() -> list[Path]:
    folder = _env("GOOGLE_AI_MODE_WIREGUARD_CONFIGS")
    if not folder:
        return []
    return sorted(Path(folder).glob("*.conf"))


def backend() -> str:
    """"cmd", "wireguard" or "" (switching off)."""
    if _env("GOOGLE_AI_MODE_ROTATE_CMD"):
        return "cmd"
    if configs():
        return "wireguard"
    return ""


def enabled() -> bool:
    return bool(backend())


def _read_state() -> dict:
    try:
        data = json.loads(state_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 -- missing or half-written: start fresh
        return {}


def _write_state(data: dict) -> None:
    path = state_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        os.replace(tmp, path)
    except Exception:  # noqa: BLE001
        pass


def public_ip(timeout: float = 6.0) -> str:
    """The machine's current public IP, or "" when no lookup answers (network down)."""
    for url in _IP_URLS:
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 -- fixed URLs
                ip = resp.read().decode("ascii", "ignore").strip()
            if ip and len(ip) <= 45 and " " not in ip:
                return ip
        except Exception:  # noqa: BLE001 -- try the next service
            continue
    return ""


def _take_lock() -> Path | None:
    lock = state_path().with_suffix(".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        if lock.exists() and time.time() - lock.stat().st_mtime > _LOCK_STALE:
            lock.unlink()
    except OSError:
        pass
    try:
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return None
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)
    return lock


def _is_admin() -> bool:
    if os.name != "nt":
        return os.geteuid() == 0 if hasattr(os, "geteuid") else False
    try:
        import ctypes  # noqa: PLC0415
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        return False


def _run(cmd: list[str] | str, *, shell: bool = False, timeout: float = 90.0) -> int:
    try:
        return subprocess.run(cmd, shell=shell, timeout=timeout, capture_output=True,  # noqa: S603
                              check=False).returncode
    except Exception as err:  # noqa: BLE001
        print(f"  [ip-rotate] command failed: {err}", flush=True)
        return -1


def _switch_wireguard(state: dict) -> str:
    """Remove the tunnel we installed last, install the next config. Returns its name or ""."""
    confs = configs()
    if not confs:
        return ""
    if not _is_admin():
        # Installing a tunnel service needs elevation: hand it to the elevated task.
        if os.getenv("IP_ROTATE_IN_TASK"):
            return ""                      # the task itself is not elevated: stop, no loop
        if _run(["schtasks", "/query", "/tn", _task_name()], timeout=20.0) == 0 and                 _run(["schtasks", "/run", "/tn", _task_name()], timeout=20.0) == 0:
            return f"task {_task_name()}"
        print("  [ip-rotate] WireGuard switching needs Administrator rights: run "
              "scripts/setup_vpn_switch.ps1 once from an Administrator PowerShell", flush=True)
        return ""
    exe = _env("GOOGLE_AI_MODE_WIREGUARD_EXE", _DEFAULT_WG)
    current = str(state.get("tunnel") or "")
    if current:
        _run([exe, "/uninstalltunnelservice", current])
        time.sleep(2)
    names = [c.stem for c in confs]
    start = (names.index(current) + 1) if current in names else int(state.get("index") or 0)
    # Try each config once, starting after the current one: a server that will not come up
    # is skipped instead of ending the switch.
    for step in range(len(confs)):
        conf = confs[(start + step) % len(confs)]
        if _run([exe, "/installtunnelservice", str(conf)]) == 0:
            state["index"] = (start + step + 1) % len(confs)
            return conf.stem
        print(f"  [ip-rotate] tunnel {conf.stem} did not install -- trying the next", flush=True)
    return ""


def _wg_next() -> str:
    """Switch WireGuard to the next config, remembering the tunnel in its own file."""
    wg: dict = {}
    try:
        wg = json.loads(_wg_state_path().read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        pass
    name = _switch_wireguard(wg)
    if name and not name.startswith("task "):   # the task saves its own
        wg["tunnel"] = name
        try:
            _wg_state_path().parent.mkdir(parents=True, exist_ok=True)
            _wg_state_path().write_text(json.dumps(wg), encoding="utf-8")
        except OSError:
            pass
    return name


def rotate(*, reason: str = "Google block", wait_for_new_ip: float = 60.0) -> bool:
    """Switch to a new IP now. True only when the public IP actually changed.

    False (and nothing changed) when switching is off, another process is already switching,
    the last switch was less than GOOGLE_AI_MODE_ROTATE_MIN_GAP ago, or the new IP never
    appeared -- then the caller's normal pause simply goes on."""
    kind = backend()
    if not kind:
        return False
    state = _read_state()
    gap = _float_env("GOOGLE_AI_MODE_ROTATE_MIN_GAP", 90.0)
    if time.time() - float(state.get("last_at") or 0) < gap:
        return False
    lock = _take_lock()
    if lock is None:
        return False                      # another browser is switching right now
    try:
        state = _read_state()             # re-read under the lock
        if time.time() - float(state.get("last_at") or 0) < gap:
            return False
        old_ip = public_ip() or str(state.get("ip") or "")
        print(f"  [ip-rotate] {reason}: switching IP (was {old_ip or 'unknown'}, {kind})",
              flush=True)
        state["last_at"] = time.time()    # also on failure: no retry storm
        if kind == "cmd":
            ok = _run(_env("GOOGLE_AI_MODE_ROTATE_CMD"), shell=True, timeout=180.0) == 0
            tunnel = ""
        else:
            tunnel = _wg_next()
            ok = bool(tunnel)
        new_ip = ""
        if ok:
            deadline = time.time() + wait_for_new_ip
            while time.time() < deadline:
                new_ip = public_ip()
                if new_ip and new_ip != old_ip:
                    break
                time.sleep(3)
        changed = bool(new_ip) and new_ip != old_ip
        state.update({"ip": new_ip or old_ip, "switches": int(state.get("switches") or 0)
                      + (1 if changed else 0), "last_ok": changed})
        _write_state(state)
        print(f"  [ip-rotate] {'new IP ' + new_ip if changed else 'IP did NOT change'}"
              f"{' via ' + tunnel if tunnel else ''}", flush=True)
        return changed
    finally:
        try:
            lock.unlink()
        except OSError:
            pass


def _cli(argv: list[str]) -> int:
    cmd = argv[0] if argv else "status"
    if cmd == "ip":
        print(public_ip() or "no answer")
        return 0
    if cmd == "wg-next":
        # The elevated half (scheduled task): switch WireGuard, the caller checks the IP.
        name = _wg_next()
        print(f"tunnel: {name or 'none'}")
        return 0 if name else 1
    if cmd == "rotate":
        os.environ["GOOGLE_AI_MODE_ROTATE_MIN_GAP"] = "0"
        return 0 if rotate(reason="manual") else 1
    print(f"backend: {backend() or 'off (set GOOGLE_AI_MODE_WIREGUARD_CONFIGS or ..._ROTATE_CMD)'}")
    print(f"configs: {len(configs())}  admin: {_is_admin()}")
    print(f"state:   {json.dumps(_read_state())}")
    print(f"ip now:  {public_ip() or 'no answer'}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
