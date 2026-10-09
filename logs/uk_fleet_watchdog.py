"""Overnight watchdog for the UK Connected Fleet pipeline run.

Every 5 minutes:
  - pipeline finished with exit=0           -> stop watching
  - pipeline not running and not finished   -> restart it (resumable; max 4)
  - pipeline running but no log has changed
    for 40 minutes (a hung step)            -> stop it and its browsers, restart
Browser-level problems (CAPTCHA, "Verifying your request", quota, crashes) are
handled inside google_ai_mode.py; this only guards the run as a whole.
"""
import subprocess
import time
from pathlib import Path

ROOT = Path(r"C:\Users\aman.kumar\Downloads\Coherent-Quadrant")
RUN_LOG = ROOT / "logs" / "uk_connected_fleet_run.log"
WLOG = ROOT / "logs" / "uk_fleet_watchdog.log"
OUT = ROOT / "output" / "chatgpt_expand" / "connected_fleet_mobility_solutions_market_united_kingdom"
CMD = ROOT / "logs" / "run_uk_fleet.cmd"
STALL_MIN, CHECK_SEC, MAX_RESTARTS = 40, 300, 4


def log(msg):
    with WLOG.open("a", encoding="utf-8") as f:
        f.write(f"[watchdog {time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")


def ps(script):
    return subprocess.run(["powershell", "-NoProfile", "-Command", script],
                          capture_output=True, text=True, timeout=120).stdout.strip()


def pipeline_running():
    out = ps("(Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' -and "
             "$_.CommandLine -like '*run_quadrant_pipeline*Connected Fleet*' }).Count")
    return out not in ("", "0")


def last_exit():
    try:
        lines = RUN_LOG.read_text(encoding="utf-8", errors="replace").strip().splitlines()
    except OSError:
        return None
    for ln in reversed(lines[-5:]):
        if ln.startswith("exit="):
            return ln.split("=", 1)[1].strip()
    return None


def newest_change():
    files = [RUN_LOG] + list((OUT / "_pipeline" / "logs").glob("*.log")) + list(OUT.glob("*.json"))
    return max((f.stat().st_mtime for f in files if f.exists()), default=time.time())


def stop_all():
    ps("Get-CimInstance Win32_Process | Where-Object { ($_.Name -in 'python.exe','cmd.exe' -and "
       "($_.CommandLine -like '*Connected Fleet*' -or $_.CommandLine -like '*run_uk_fleet.cmd*')) -or "
       "($_.Name -eq 'chrome.exe' -and $_.CommandLine -match 'ai_mode_batch_(4[1-9]|50)') } | "
       "ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch {} }")


def start():
    ps(f"Start-Process -FilePath 'cmd.exe' -ArgumentList '/c','{CMD}' -WindowStyle Minimized")


restarts = 0
log("started")
while True:
    time.sleep(CHECK_SEC)
    try:
        running = pipeline_running()
        code = last_exit()
        if not running and code == "0":
            log("pipeline finished (exit=0) -- watchdog done")
            break
        idle_min = (time.time() - newest_change()) / 60
        if running and idle_min < STALL_MIN:
            continue
        if restarts >= MAX_RESTARTS:
            log(f"giving up after {restarts} restarts (running={running}, exit={code}, idle={idle_min:.0f} min)")
            break
        restarts += 1
        why = (f"no progress for {idle_min:.0f} min" if running
               else f"pipeline not running (last exit={code})")
        log(f"restart #{restarts}: {why}")
        stop_all()
        time.sleep(10)
        start()
    except Exception as err:  # noqa: BLE001 -- the watchdog itself must never die
        log(f"check failed: {err}")
