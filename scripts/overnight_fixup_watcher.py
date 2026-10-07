#!/usr/bin/env python3
"""Overnight unattended watcher for the 10-market drone batch.

Polls every market's report file. Once a market produces a report (or
already has one from the main run_markets_parallel.py batch), re-runs
run_quadrant_pipeline.py for it ONE more time on a dedicated slot, with
NO --reselect, so it picks up:
  - the seed_from_full_evidence.py fix (full-evidence long-tail lookup,
    fixes reports coming up short of --keep)
  - the rewrite_assessed_on_tone.py fix (mid-sentence hedge phrase
    without "but")
without disturbing the already-selected, already-scored Top 20.

Re-running is cheap once a market is done: every step is checkpointed, so
this only rebuilds steps 6-9 (composite -> tone -> report -> verify),
not discovery or scoring.

Idempotent: a market already fixed (report has exactly --keep companies
and 0 VERIFY failures) is skipped on the next poll.

Logs to logs/overnight_fixup_watcher.log. Runs until every market is
confirmed fixed, or until --max-hours elapses.

    .\\.venv\\Scripts\\python.exe scripts\\overnight_fixup_watcher.py ^
        --markets-file queries\\drone_10_india.txt --keep 120 --poll-seconds 120
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
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def log(msg: str) -> None:
    print(f"[watcher {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:60]


def read_markets(path: Path, default_country: str) -> list[tuple[str, str]]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        market, _, ctry = line.replace("\t", "|").partition("|")
        market, ctry = market.strip(), (ctry.strip() or default_country).lower()
        if market:
            out.append((market, ctry))
    return out


def market_still_running(market: str) -> bool:
    """True if ANY python.exe process (the main batch or an earlier fix
    attempt) currently has this market name on its command line.

    Critical safety check: a stale leftover report (from before this batch
    ever started) must never trigger a fix re-run while the main batch is
    still actively writing that same market's files -- two processes
    writing the same checkpoint/evidence files at once can corrupt them.
    Uses PowerShell's CIM query (same approach used to inspect these
    processes manually all session) rather than adding a psutil dependency.

    A wildcard -like match on the quoted "--market <name>" form -- not a
    regex -- since [regex]::Escape() through -Command's own argv assembly
    proved unreliable in testing (it matched process command lines that did
    not contain the search string at all).
    """
    try:
        needle = f'--market "{market}"'.replace("'", "''")
        script = (
            "$procs = Get-CimInstance Win32_Process -Filter \"Name='python.exe'\";"
            f"$n = 0; foreach ($p in $procs) {{ if ($p.CommandLine -and "
            f"$p.CommandLine.Contains('{needle}')) {{ $n++ }} }}; $n"
        )
        out = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", script],
            capture_output=True, text=True, timeout=20,
        )
        return int((out.stdout or "0").strip() or "0") > 0
    except Exception:  # noqa: BLE001
        # Cannot confirm either way -- fail SAFE (assume still running) so a
        # transient PowerShell hiccup never races a live write.
        return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--markets-file", required=True)
    ap.add_argument("--country", default="global")
    ap.add_argument("--keep", type=int, required=True)
    ap.add_argument("--poll-seconds", type=int, default=120)
    ap.add_argument("--max-hours", type=float, default=10.0)
    ap.add_argument("--fix-slot-start", type=int, default=71,
                    help="dedicated slots for fix re-runs, separate from the "
                         "main batch's 41-50 so the two never collide")
    args = ap.parse_args()

    from vendor_intel.pipeline.web_expand import default_output_dir

    markets = read_markets(Path(args.markets_file), args.country)
    log(f"watching {len(markets)} market(s), keep={args.keep}, "
        f"poll every {args.poll_seconds}s, max {args.max_hours}h")

    fixed: set[str] = set()
    attempted_this_state: dict[str, int] = {}  # slug -> company count already tried
    deadline = time.time() + args.max_hours * 3600
    next_slot = args.fix_slot_start

    while time.time() < deadline and len(fixed) < len(markets):
        for market, country in markets:
            out_dir = Path(default_output_dir(market, country))
            slug_name = out_dir.name
            if slug_name in fixed:
                continue

            q_path = out_dir / f"{slug_name}_quadrant.json"
            ckpt_path = out_dir / "chatgpt_checkpoint_batch_all.json"
            if not ckpt_path.exists():
                continue

            if not q_path.exists():
                continue  # market hasn't produced any report yet

            try:
                mtime = q_path.stat().st_mtime
            except OSError:
                continue

            # Already fixed and correct? A previous watcher pass, or the
            # main batch itself, may have already produced a clean report.
            try:
                data = json.loads(q_path.read_text(encoding="utf-8"))
                count = len(data.get("brands") or [])
            except Exception:  # noqa: BLE001
                continue

            if count == args.keep:
                # Company count is right; confirm no hedge phrase leaked in
                # (the other symptom the two fixes address).
                html_path = out_dir / f"{slug_name}_report.html"
                hedge = False
                if html_path.exists():
                    try:
                        text = html_path.read_text(encoding="utf-8", errors="replace")
                        hedge = "could not verify" in text.lower()
                    except OSError:
                        pass
                if not hedge:
                    fixed.add(slug_name)
                    log(f"{market}: OK -- {count}/{args.keep} companies, no hedge text. DONE")
                    continue

            # Needs a fix re-run. Skip if we already tried at this exact
            # company count (nothing changed since the last attempt, so
            # retrying now would waste a slot without progress) unless the
            # report has grown/changed (mtime moved forward is caught by the
            # count check above already; this is a belt-and-suspenders guard).
            if attempted_this_state.get(slug_name) == count:
                continue

            # NEVER fix-run a market the main batch (or an earlier fix
            # attempt) is still actively writing to -- e.g. a stale report
            # left over from before this run even started (count != keep)
            # while Step 5 is still gathering evidence right now. Two
            # processes writing the same checkpoint/_pipeline files at once
            # can corrupt them.
            if market_still_running(market):
                log(f"{market}: report is {count}/{args.keep} but the market is "
                    f"still actively running elsewhere -- waiting, not fixing yet")
                continue

            log(f"{market}: report has {count}/{args.keep} companies (or hedge text) -- "
                f"re-running with the fix on slot {next_slot}")
            cmd = [sys.executable, str(ROOT / "scripts" / "run_quadrant_pipeline.py"),
                   "--market", market, "--country", country,
                   "--keep", str(args.keep), "--slots", str(next_slot)]
            log_path = ROOT / "logs" / f"overnight_fix_{slug_name}.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("w", encoding="utf-8") as fh:
                rc = subprocess.call(cmd, cwd=str(ROOT), stdout=fh, stderr=subprocess.STDOUT)
            attempted_this_state[slug_name] = count
            next_slot += 1
            if next_slot > 90:
                next_slot = args.fix_slot_start

            # Re-check immediately after the fix run.
            try:
                data = json.loads(q_path.read_text(encoding="utf-8"))
                new_count = len(data.get("brands") or [])
            except Exception:  # noqa: BLE001
                new_count = -1
            html_path = out_dir / f"{slug_name}_report.html"
            hedge = False
            if html_path.exists():
                try:
                    hedge = "could not verify" in html_path.read_text(
                        encoding="utf-8", errors="replace"
                    ).lower()
                except OSError:
                    pass
            if rc == 0 and new_count == args.keep and not hedge:
                fixed.add(slug_name)
                log(f"{market}: FIXED -- now {new_count}/{args.keep}, no hedge text. DONE")
            else:
                log(f"{market}: fix run exit={rc}, now {new_count}/{args.keep}, "
                    f"hedge={hedge} -- will retry next poll (see {log_path.name})")

        if len(fixed) < len(markets):
            time.sleep(args.poll_seconds)

    log(f"stopped: {len(fixed)}/{len(markets)} markets confirmed done")
    for market, country in markets:
        out_dir = Path(default_output_dir(market, country))
        status = "DONE" if out_dir.name in fixed else "NOT DONE"
        log(f"  {status}: {market} ({country})")
    return 0 if len(fixed) == len(markets) else 1


if __name__ == "__main__":
    raise SystemExit(main())
