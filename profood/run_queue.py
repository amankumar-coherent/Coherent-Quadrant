#!/usr/bin/env python3
"""ProFood India -- 75 Coherent Quadrant markets, one after another, unattended.

    .venv\\Scripts\\python.exe profood\\run_queue.py            # run / resume the queue
    .venv\\Scripts\\python.exe profood\\run_queue.py --status   # where it is

Per market (logs\\run_market.py, unchanged pipeline):
  * 5 browsers at a time (slots 41-45, one profile each);
  * India only, state by state (--state-wise), cap 120 verified;
  * discovery stops at 120 verified, or earlier when a pass over the states adds
    fewer than 5 (every state searched, market exhausted) -- then the full
    pipeline runs on what was found and the queue moves to the next market.

Unattended recovery:
  * CAPTCHA / quota / "verifying your request" pages are handled inside the
    pipeline: cookies cleared, browser relaunched, profile reset, no waiting;
  * a market whose logs stay silent for --stall minutes (hung browser) is
    stopped, its 5 browser profiles are archived (fresh cookies) and the market
    is restarted from its saved work; after --max-restarts it is marked
    "stalled" and the queue moves on;
  * the queue itself is resumable: finished markets are skipped
    (profood\\state.json), every market resumes from its saved work.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

STATE = HERE / "state.json"
LOGS = ROOT / "logs" / "profood"
PY = str(ROOT / ".venv" / "Scripts" / "python.exe") if os.name == "nt" else sys.executable


def log(msg: str) -> None:
    LOGS.mkdir(parents=True, exist_ok=True)
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with (LOGS / "queue.log").open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, STATE)


def out_dir(market: str, country: str) -> Path:
    from vendor_intel.pipeline.web_expand import default_output_dir

    return Path(default_output_dir(market, country))


def newest_activity(market: str, country: str, own_log: Path) -> float:
    """Latest write to any log of this market (pipeline steps, discovery
    browsers, the market's own log)."""
    out = out_dir(market, country)
    files = [own_log, ROOT / "logs" / "parallel" / f"{out.name}.log"]
    files += list((out / "_pipeline" / "logs").glob("*.log"))
    files += list((ROOT / "logs").glob(f"topup_{out.name}_*.log"))
    files += list((ROOT / "logs").glob(f"countries_{out.name}_*.log"))
    return max((f.stat().st_mtime for f in files if f.exists()), default=time.time())


def kill_market(proc: subprocess.Popen, slots: range) -> None:
    """Stop the market's process tree and every browser on its slots."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
        pat = "|".join(f"ai_mode_batch_{s}" for s in slots)
        subprocess.run(["powershell", "-NoProfile", "-Command",
                        "Get-CimInstance Win32_Process -Filter \"name='chrome.exe'\" | "
                        f"Where-Object {{ $_.CommandLine -match '{pat}' }} | "
                        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"],
                       capture_output=True)
    else:
        proc.kill()
    time.sleep(5)


def reset_profiles(slots: range) -> None:
    """Fresh cookies: archive the slots' browser profiles (renamed, not deleted;
    data/_archived_profiles_* is never committed)."""
    archive = ROOT / "data" / "_archived_profiles_profood"
    archive.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    for s in slots:
        for p in (ROOT / "data").glob(f"ai_mode_batch_{s}*"):
            if p.is_dir() and "_archived" not in p.name:
                try:
                    p.rename(archive / f"{p.name}_{stamp}")
                except OSError:
                    pass


def prepare_resume(market: str, country: str) -> None:
    """Before a market continues after a stop, crash or stall: nothing found is lost.

    Every pipeline step already saves per company (status, ownership, scope, HQ,
    scores, evidence, estimates, fact-check), so those continue from the last
    company. The one gap is a discovery pass cut off mid-way: each browser keeps
    its finds in its own copy (output/chatgpt_expand_top<N>/). So: (1) merge every
    company those copies already verified into the market, and (2) clear the
    "verify_only_done" marker, so the market's first step verifies every company
    that was found but not yet checked, before searching for more."""
    out = out_dir(market, country)
    if not (out / "chatgpt_checkpoint_batch_all.json").exists():
        return
    r = subprocess.run([PY, str(ROOT / "scripts" / "parallel_topup.py"), "--market", market, "--country", country,
                        "--keep", "100000", "--browsers", "1", "--merge-only"],
                       cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    merged = [ln for ln in (r.stdout or "").splitlines() if "merged:" in ln]
    (out / "_pipeline" / "verify_only_done").unlink(missing_ok=True)
    log(f"RESUME {market}: saved finds merged ({merged[-1].split('merged:')[1].split('->')[0].strip() if merged else 'nothing to merge'}); "
        "unchecked companies are verified first")


def run_market(m: dict, args, state: dict) -> str:
    market, country = m["market"], str(m.get("country") or "india").lower()
    slots = range(args.slot_start, args.slot_start + args.browsers)
    own_log = LOGS / f"{out_dir(market, country).name}.log"
    cmd = [PY, str(ROOT / "logs" / "run_market.py"), market, "--country", country,
           "--keep", str(args.cap), "--browsers", str(args.browsers), "--slot-start", str(args.slot_start),
           "--global-focus", "--discover-to", str(args.cap)]
    if country != "global":
        cmd.append("--state-wise")
    rec = state.setdefault(market, {"id": m.get("id", ""), "restarts": 0})
    if rec.get("status") in ("running", "stalled", "failed"):
        # Interrupted last time (machine off, stop.ps1, crash): pick up every find.
        prepare_resume(market, country)
    while True:
        rec.update(status="running", started=time.strftime("%Y-%m-%d %H:%M:%S"))
        save_state(state)
        log(f"START {m.get('id', '')} {market} ({args.browsers} browsers, cap {args.cap}, "
            f"restart {rec['restarts']})")
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        stalled = False
        with own_log.open("a", encoding="utf-8") as fh:
            proc = subprocess.Popen(cmd, cwd=str(ROOT), stdout=fh, stderr=subprocess.STDOUT, env=env)
            while proc.poll() is None:
                time.sleep(60)
                idle = (time.time() - newest_activity(market, country, own_log)) / 60
                if idle >= args.stall:
                    log(f"STALL {market}: no log activity for {idle:.0f} min -- stopping, fresh browser "
                        "profiles, restarting from saved work")
                    kill_market(proc, slots)
                    reset_profiles(slots)
                    stalled = True
                    break
        if stalled:
            rec["restarts"] += 1
            if rec["restarts"] > args.max_restarts:
                rec["status"] = "stalled"
                save_state(state)
                log(f"GIVE UP {market} after {args.max_restarts} restarts -- moving to the next market")
                return "stalled"
            prepare_resume(market, country)
            continue
        rec["exit"] = proc.returncode
        rec["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
        # exit 0 = report built and every VERIFY line passed; 1 = report built with a VERIFY
        # line to review (see logs\parallel\<market>.log); anything else = it stopped early.
        rec["status"] = {0: "done", 1: "done_check_verify"}.get(proc.returncode, "failed")
        save_state(state)
        log(f"END   {market}: {rec['status']} (exit {proc.returncode})")
        return rec["status"]


def status(markets: list[dict]) -> None:
    from collections import Counter

    state = load_state()
    c = Counter(state.get(m["market"], {}).get("status", "pending") for m in markets)
    print(f"{len(markets)} markets: " + ", ".join(f"{k} {v}" for k, v in sorted(c.items())))
    for m in markets:
        r = state.get(m["market"])
        if r and r.get("status") != "pending":
            print(f"  {m.get('id', ''):7} {r.get('status', ''):18} {m['market']}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--markets", default=str(HERE / "markets.json"))
    ap.add_argument("--browsers", type=int, default=5, help="browsers per market (default 5)")
    ap.add_argument("--slot-start", type=int, default=41, help="first browser slot (default 41 -> 41-45)")
    ap.add_argument("--cap", type=int, default=120, help="verified companies per market (default 120)")
    ap.add_argument("--stall", type=int, default=25, help="minutes without log activity = stuck (default 25)")
    ap.add_argument("--max-restarts", type=int, default=3)
    ap.add_argument("--only", default="", help="comma-separated market ids, e.g. FP-01,FI-03")
    ap.add_argument("--retry-failed", action="store_true", help="run stalled / failed markets again")
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args()

    markets = json.loads(Path(args.markets).read_text(encoding="utf-8"))["markets"]
    if args.only:
        ids = {i.strip() for i in args.only.split(",")}
        markets = [m for m in markets if m.get("id") in ids]
    if args.status:
        status(markets)
        return 0

    # Briefs first (idempotent: existing briefs and found companies are kept).
    subprocess.run([PY, str(HERE / "setup_briefs.py"), args.markets], cwd=str(ROOT))
    state = load_state()
    skip = {"done", "done_check_verify"} | (set() if args.retry_failed else {"stalled", "failed"})
    todo = [m for m in markets if state.get(m["market"], {}).get("status") not in skip]
    log(f"QUEUE {len(todo)} of {len(markets)} markets to run ({args.browsers} browsers each, cap {args.cap})")
    for m in todo:
        state = load_state()
        if args.retry_failed and state.get(m["market"], {}).get("status") in ("stalled", "failed"):
            state[m["market"]]["restarts"] = 0
        run_market(m, args, state)
    log("ALL DONE")
    status(markets)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
