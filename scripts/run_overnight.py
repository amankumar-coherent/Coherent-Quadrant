#!/usr/bin/env python3
"""Run every market to completion unattended, recovering from AI Mode blocks.

Written for an overnight run: nobody is watching, so anything that would
normally stop and wait for a human has to be handled here instead.

What it recovers from, and why each needs different treatment:

* "AI response request limit" (quota) — per IP, and a soured profile makes it
  worse. Archive the profile, wait, resume from the checkpoint.
* CAPTCHA wall — the extension clears single CAPTCHAs; a sustained run of them
  means the profile is burnt. Same treatment.
* "An AI response wasn't generated" / browser crash — usually transient.
  Retry from the checkpoint without touching the profile.
* An orphaned browser holding the profile lock, which silently took a whole
  market to 0 companies in an earlier run. Killed before every attempt.

Progress is never lost: each market resumes from its own checkpoint, so a
retry continues rather than restarting.

    .\\.venv\\Scripts\\python.exe scripts\\run_overnight.py --markets-file queries\\batch_2026_09_11.txt
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

# A market gets this many attempts before the queue moves on. Three is enough
# to ride out a quota window without letting one market eat the whole night.
MAX_ATTEMPTS = 4
COOL_OFF_AFTER_BLOCK = 900  # 15 min — quota is per IP and needs real time
COOL_OFF_BETWEEN_MARKETS = 120

# Log fingerprints of the blocks worth reacting to.
_QUOTA = re.compile(
    r"request limit for ai responses|only waiting helps|quota", re.I
)
_CAPTCHA = re.compile(r"CAPTCHA \((\d+) this run\)", re.I)
_SOFT = re.compile(
    r"an ai response wasn't generated|something went wrong|"
    r"no answer generated|browser ready.*failed",
    re.I,
)


def _log(msg: str) -> None:
    stamp = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[overnight {stamp}] {msg}", flush=True)


def kill_browsers() -> None:
    """Kill any browser still holding our profile.

    A crashed or force-killed run leaves Chromium on the profile lock, and the
    next launch then fails with "Opening in existing browser session" — which
    took an entire market to 0 companies before this existed.
    """
    try:
        out = subprocess.run(
            [
                "powershell", "-NoProfile", "-NonInteractive", "-Command",
                "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
                "Where-Object { $_.CommandLine -like '*ai_mode_chrome_profile*' } | "
                "Select-Object -ExpandProperty ProcessId",
            ],
            capture_output=True, text=True, timeout=30,
        )
        pids = [p for p in (out.stdout or "").split() if p.strip().isdigit()]
        for pid in pids:
            subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True, timeout=15)
        if pids:
            _log(f"killed {len(pids)} orphaned browser process(es)")
            time.sleep(3)
    except Exception as err:  # noqa: BLE001 - never block the queue
        _log(f"browser cleanup skipped: {type(err).__name__}")


def reset_profile() -> None:
    """Archive the AI Mode profile so the next launch starts clean.

    Renamed, not deleted: a soured profile is worth keeping for diagnosis, and
    deleting user data unprompted is not something an unattended script should
    do.
    """
    kill_browsers()
    try:
        from vendor_intel.scraping.google_ai_mode import profile_dir_for, resolve_channel

        exts_root = ROOT / "data" / "ai_mode_chrome_profile_extensions"
        exts = [str(p) for p in exts_root.iterdir()] if exts_root.exists() else []
        target = Path(profile_dir_for(resolve_channel(exts)))
        if not target.is_absolute():
            target = ROOT / target
        if target.exists():
            stamp = time.strftime("%Y%m%d_%H%M%S")
            target.rename(target.with_name(f"{target.name}_auto_{stamp}"))
            _log(f"profile archived -> {target.name}_auto_{stamp}")
    except Exception as err:  # noqa: BLE001
        _log(f"profile reset failed ({type(err).__name__}) — continuing anyway")


def classify(log_path: Path, tail_bytes: int = 200_000) -> str:
    """What stopped this attempt: 'quota', 'captcha', 'soft' or 'other'."""
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")[-tail_bytes:]
    except Exception:  # noqa: BLE001
        return "other"
    if _QUOTA.search(text):
        return "quota"
    hits = _CAPTCHA.findall(text)
    if hits and int(hits[-1]) >= 5:
        return "captcha"
    if _SOFT.search(text):
        return "soft"
    return "other"


def market_done(market: str, country: str) -> tuple[bool, int, int]:
    """(finished, rows, scored) from the market's own checkpoint."""
    try:
        from vendor_intel.pipeline.web_expand import default_output_dir

        ckpt = Path(default_output_dir(market, country)) / "chatgpt_checkpoint_batch_all.json"
        if not ckpt.exists():
            return False, 0, 0
        state = json.loads(ckpt.read_text(encoding="utf-8"))
        rows = (state.get("data") or {}).get("detail_rows") or []
        scored = sum(1 for r in rows if str(r.get("X") or "").strip())
        # "Done" means SCORED, not merely finished: a quota block used to wipe
        # the scoring step and still mark the market complete.
        return bool(rows) and scored == len(rows) and state.get("status") == "done", len(rows), scored
    except Exception:  # noqa: BLE001
        return False, 0, 0


def run_market(market: str, country: str, target: int, logs: Path) -> tuple[str, int, int]:
    for attempt in range(1, MAX_ATTEMPTS + 1):
        done, rows, scored = market_done(market, country)
        if done:
            _log(f"{market}: already complete ({scored}/{rows} scored)")
            return "ok", rows, scored

        kill_browsers()
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = logs / f"{_slug(market)}_{stamp}.log"
        _log(f"{market}: attempt {attempt}/{MAX_ATTEMPTS} -> {log_path.name}")

        env = dict(os.environ)
        env["PYTHONPATH"] = str(ROOT / "src")
        with log_path.open("w", encoding="utf-8") as fh:
            proc = subprocess.run(
                [
                    sys.executable, str(ROOT / "scripts" / "run_chatgpt_expand.py"),
                    "--query", market, "--country", country, "--target", str(target),
                ],
                cwd=str(ROOT), stdout=fh, stderr=subprocess.STDOUT, env=env,
            )

        done, rows, scored = market_done(market, country)
        if done:
            _log(f"{market}: DONE ({scored}/{rows} scored)")
            return "ok", rows, scored

        reason = classify(log_path)
        _log(
            f"{market}: incomplete ({scored}/{rows} scored, exit {proc.returncode}, "
            f"reason={reason})"
        )
        if attempt >= MAX_ATTEMPTS:
            break
        if reason in ("quota", "captcha"):
            # Both mean the profile is burnt and the IP needs a rest. The
            # checkpoint holds the progress, so the retry continues.
            reset_profile()
            _log(f"cooling off {COOL_OFF_AFTER_BLOCK}s before retrying")
            time.sleep(COOL_OFF_AFTER_BLOCK)
        else:
            kill_browsers()
            time.sleep(60)

    done, rows, scored = market_done(market, country)
    return ("ok" if done else "incomplete"), rows, scored


def _slug(market: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", market.lower()).strip("_")[:48]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--markets-file")
    ap.add_argument("--query", "-q", action="append", default=[])
    ap.add_argument("--country", "-c", default="global")
    ap.add_argument("--target", "-t", type=int, default=300)
    args = ap.parse_args()

    markets: list[str] = list(args.query)
    if args.markets_file:
        for line in Path(args.markets_file).read_text(encoding="utf-8").splitlines():
            name = line.split("#", 1)[0].strip()
            if name:
                markets.append(name)
    markets = list(dict.fromkeys(markets))
    if not markets:
        ap.print_help()
        return 2

    logs = ROOT / "logs"
    logs.mkdir(exist_ok=True)
    _log(f"{len(markets)} market(s) queued, target={args.target}")
    for i, m in enumerate(markets, 1):
        _log(f"  {i}. {m}")

    results: list[tuple[str, str, int, int, float]] = []
    for i, market in enumerate(markets, 1):
        _log("")
        _log(f"=== [{i}/{len(markets)}] {market} ===")
        started = time.monotonic()
        status, rows, scored = run_market(market, args.country, args.target, logs)
        results.append((market, status, rows, scored, (time.monotonic() - started) / 60))
        if i < len(markets):
            _log(f"cooling off {COOL_OFF_BETWEEN_MARKETS}s before the next market")
            time.sleep(COOL_OFF_BETWEEN_MARKETS)

    _log("")
    _log("=== SUMMARY ===")
    for market, status, rows, scored, mins in results:
        _log(f"  {status:11} {scored:4}/{rows:<4} scored  {mins:5.0f} min  {market}")
    ok = sum(1 for r in results if r[1] == "ok")
    _log(f"{ok}/{len(results)} markets completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
