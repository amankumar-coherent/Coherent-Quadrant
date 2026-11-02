#!/usr/bin/env python3
"""Keep a list of markets running unattended until every one has its report.

    .venv\\Scripts\\python.exe profood\\watchdog.py profood\\fmt_india_markets.json [--every 10] [--stall 45]

Every --every minutes, for each market in the markets file:
  * finished (its log ends with the VERIFY block and "exit=0") -> left alone;
  * not running and not finished (crashed: AI Mode refusals, browser crash,
    VERIFY failure) -> restarted from its saved work on a free browser slot
    (--slots-from .. 99), up to --max-restarts times;
  * running but silent for --stall minutes (no log or state file written) ->
    its processes are stopped and it is restarted the same way.
Nothing market-specific here: the markets come from the file, every restart is
the normal one-command pipeline (run_quadrant_pipeline.py), which resumes from
saved work. State: logs/profood_watchdog.json, log: logs/profood_watchdog.log.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
PY = str(ROOT / ".venv" / "Scripts" / "python.exe")
LOG = ROOT / "logs" / "profood_watchdog.log"
STATE = ROOT / "logs" / "profood_watchdog.json"


def log(msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def processes() -> list[dict]:
    """[{pid, cmd}] of every python / chrome process (PowerShell, no psutil)."""
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe' OR Name='chrome.exe'\" | "
          "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress")
    try:
        out = subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps], capture_output=True,
                             text=True, timeout=300).stdout
        data = json.loads(out or "[]")
    except Exception:  # noqa: BLE001 -- a failed listing just skips this cycle
        return []
    data = data if isinstance(data, list) else [data]
    return [{"pid": d.get("ProcessId"), "cmd": d.get("CommandLine") or ""} for d in data]


def kill(pids: list[int]) -> None:
    for p in pids:
        subprocess.run(["taskkill", "/PID", str(p), "/T", "/F"], capture_output=True)


def newest_write(paths: list[Path]) -> float:
    t = 0.0
    for p in paths:
        try:
            if p.is_dir():
                for f in p.rglob("*"):
                    if f.is_file():
                        t = max(t, f.stat().st_mtime)
            elif p.exists():
                t = max(t, p.stat().st_mtime)
        except OSError:
            continue
    return t


def progress_time(out: Path, plog: Path) -> float:
    """When the market last made REAL progress: a saved JSON state file (companies,
    scores, evidence, answers) or a pipeline step line. Logs and the pipeline's
    once-a-minute "still running" lines do not count -- they kept a market that
    sat 3 hours in its fact-check looking alive (owner 2026-10-26)."""
    t = 0.0
    dirs = [out] + list(ROOT.glob(f"output/chatgpt_expand_top*/{out.name}"))
    for d in dirs:
        try:
            for f in d.rglob("*.json"):
                t = max(t, f.stat().st_mtime)
        except OSError:
            continue
    try:
        text = plog.read_text(encoding="utf-8", errors="replace")[-20000:]
        steps = [l for l in text.splitlines() if l.startswith("[pipeline ") and "still running" not in l]
        if steps and plog.exists():
            # the last step line's clock time, today (or yesterday if that is in the future)
            hh, mm, ss = map(int, re.match(r"\[pipeline (\d+):(\d+):(\d+)\]", steps[-1]).groups())
            lt = time.localtime()
            ts = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, hh, mm, ss, 0, 0, -1))
            if ts > time.time() + 60:
                ts -= 86400
            t = max(t, ts)
    except (OSError, AttributeError, ValueError):
        pass
    return t


def reset_browser(slot: int, procs: list[dict]) -> str:
    """Close the slot's browser and archive its profile: the restart opens a new
    browser on a fresh profile (new cookies, no flagged session)."""
    kill([p["pid"] for p in procs if f"ai_mode_batch_{slot:02d}" in p["cmd"]])
    time.sleep(3)
    moved = []
    for d in (ROOT / "data").glob(f"ai_mode_batch_{slot:02d}*"):
        if d.is_dir() and re.fullmatch(rf"ai_mode_batch_{slot:02d}(_chromium)?", d.name):
            dest = d.with_name(f"{d.name}_stall_{time.strftime('%Y%m%d_%H%M%S')}")
            try:
                d.rename(dest)
                moved.append(dest.name)
            except OSError:
                pass
    return ", ".join(moved) or "no profile to archive"


def browser_shares(open_markets: list[tuple[str, Path]], total: int) -> dict[str, int]:
    """How many browsers each unfinished market gets when --total-browsers is
    above the market count. Discovery uses one browser; the steps after it
    (status, scores, evidence, fact-check) split over every --slots browser, so
    the spare browsers go first to markets past discovery (axes written), then
    to the larger ones (more saved candidates = more to score), at most 3 each."""
    share = {name: 1 for name, _ in open_markets}
    spare = total - len(open_markets)
    def weight(item):
        _, out = item
        ck = out / "chatgpt_checkpoint_batch_all.json"
        return ((out / "_pipeline" / "axes_spec.json").exists(), ck.stat().st_size if ck.exists() else 0)
    order = sorted(open_markets, key=weight, reverse=True)
    while spare > 0 and order:
        given = False
        for name, _ in order:
            if spare <= 0:
                break
            if share[name] < 3:
                share[name] += 1
                spare -= 1
                given = True
        if not given:
            break
    return share


def status(log_path: Path) -> str:
    try:
        tail = log_path.read_text(encoding="utf-8", errors="replace")[-8000:]
    except OSError:
        return "none"
    # The pipeline itself prints no "exit=" line (only the old launchers did): a
    # finished run is a last VERIFY block that ends in "report:" with no FAIL.
    block = tail[tail.rfind("VERIFY"):] if "VERIFY" in tail else ""
    if block and "report:" in block and "[PASS]" in block and "[FAIL]" not in block:
        return "done"
    if "VERIFY" in tail and re.search(r"^exit=0\s*$", tail, re.M):
        return "done"
    if re.search(r"^exit=\d+\s*$", tail, re.M) or "discovery produced no verified" in tail:
        return "stopped"
    return "open"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("markets_file")
    ap.add_argument("--every", type=float, default=10, help="minutes between checks")
    ap.add_argument("--stall", type=float, default=45, help="minutes of silence before a restart")
    ap.add_argument("--max-restarts", type=int, default=6)
    ap.add_argument("--slots-from", type=int, default=80)
    ap.add_argument("--keep", type=int, default=120)
    ap.add_argument("--total-browsers", type=int, default=0,
                    help="browsers for all unfinished markets together (0 = one per market); "
                         "spare ones give a market 2-3 browsers")
    args = ap.parse_args()

    from vendor_intel.pipeline.web_expand import default_output_dir

    markets = json.loads(Path(args.markets_file).read_text(encoding="utf-8"))["markets"]
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    log(f"watchdog start: {len(markets)} markets, check every {args.every:g} min, stall {args.stall:g} min")
    outs = {m["market"]: Path(default_output_dir(m["market"], str(m.get("country") or "global").lower()))
            for m in markets}
    unfinished = [(m["market"], outs[m["market"]]) for m in markets
                  if status(ROOT / "logs" / "parallel" / f"{outs[m['market']].name}.log") != "done"
                  and state.get(m["market"], {}).get("restarts", 0) < args.max_restarts]
    shares = browser_shares(unfinished, args.total_browsers) if args.total_browsers else {}
    if shares:
        log("browsers per market: " + ", ".join(f"{n.replace('India ', '')[:30]}={k}" for n, k in shares.items()))
    while True:
        procs = processes()
        used = {int(m) for p in procs for m in re.findall(r"ai_mode_batch_(\d{2})", p["cmd"])}
        for s in state.values():
            if s.get("status") not in ("done", "gave up"):
                used |= {int(x) for x in (s.get("slots") or ([s["slot"]] if s.get("slot") else []))}
        done = gave_up = 0
        for m in markets:
            name, country = m["market"], str(m.get("country") or "global").lower()
            out = Path(default_output_dir(name, country))
            plog = ROOT / "logs" / "parallel" / f"{out.name}.log"
            st = state.setdefault(name, {"restarts": 0})
            # The market's own pipeline processes; a launcher (run_markets_parallel)
            # may name several markets, so killing it would stop the others too.
            mine = [p for p in procs if name in p["cmd"] and "python" in p["cmd"].lower()
                    and "run_markets_parallel" not in p["cmd"]]
            stt = status(plog)
            if stt == "done":
                done += 1
                st["status"] = "done"
                continue
            if st["restarts"] >= args.max_restarts:
                gave_up += 1
                st["status"] = "gave up"
                continue
            # A market restarted less than --stall minutes ago gets that long to show progress.
            silent = (time.time() - max(progress_time(out, plog), st.get("restarted_at", 0))) / 60
            if mine and silent < args.stall:
                st["status"] = "running"
                continue
            why = "no progress for %.0f min" % silent if mine else f"not running ({stt})"
            old_slots = {int(x) for p in mine for v in re.findall(r"--slots\"?\s+\"?([\d,-]+)", p["cmd"])
                         for x in re.findall(r"\d{2}", v)}
            if mine:
                kill([p["pid"] for p in mine])
            want = shares.get(name, 1)
            mine_before = set(st.get("slots") or ([st["slot"]] if st.get("slot") else []))
            used -= mine_before  # this market's own slots are free for its restart
            slots = [s for s in sorted(mine_before) if s not in used][:want]
            for s in range(args.slots_from, 100):
                if len(slots) >= want:
                    break
                if s not in used and s not in slots:
                    slots.append(s)
            used |= set(slots)
            slot = slots[0]
            slot_arg = ",".join(str(s) for s in slots)
            # A stuck or crashed market gets a NEW browser: the old one closed and its
            # profile archived, so cookies and a flagged Google session start fresh.
            for s in old_slots | set(slots):
                log(f"  browser reset slot {s}: {reset_browser(s, procs)}")
            st.update(slot=slot, slots=slots, restarts=st["restarts"] + 1, status="restarted", last=time.strftime("%H:%M"),
                      restarted_at=time.time())
            with plog.open("a", encoding="utf-8") as fh:
                fh.write(f"\n=== watchdog restart {st['restarts']} ({why}) on slots {slot_arg} at "
                         f"{time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            fh = plog.open("a", encoding="utf-8")
            subprocess.Popen([PY, str(ROOT / "scripts" / "run_quadrant_pipeline.py"), "--market", name,
                              "--country", country, "--slots", slot_arg, "--top-n", "20", "--keep", str(args.keep)],
                             cwd=str(ROOT), stdout=fh, stderr=subprocess.STDOUT,
                             env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8",
                                  "PYTHONPATH": str(ROOT / "src")},
                             creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
            log(f"RESTART {name}: {why}; slots {slot_arg}, restart #{st['restarts']}")
            time.sleep(20)  # stagger browser launches
        STATE.write_text(json.dumps(state, indent=1), encoding="utf-8")
        running = sum(1 for s in state.values() if s.get("status") in ("running", "restarted"))
        log(f"check: {done} done, {running} running, {gave_up} gave up, of {len(markets)}")
        if done + gave_up >= len(markets):
            log("watchdog end: every market finished or gave up")
            return 0
        time.sleep(args.every * 60)


if __name__ == "__main__":
    raise SystemExit(main())
