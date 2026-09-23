#!/usr/bin/env python3
"""Run a queue of markets N-at-a-time, in waves, unattended.

run_overnight.py runs markets one after another. This runs a whole wave
concurrently and only starts the next wave once every market in the current
one has finished, which is what a 25-market queue in batches of 5 needs.

Isolation is the whole design problem here, and there are three separate
collisions to avoid:

* Browser profiles. Chromium locks its profile directory, so five workers
  sharing one would fight over the lock and take markets to zero companies.
  Each slot gets its own GOOGLE_AI_MODE_PROFILE_DIR, and therefore its own
  extension staging root (staging_root() derives from the profile path).
* Unrelated browsers. run_overnight.kill_browsers() kills anything whose
  command line mentions "ai_mode_chrome_profile", which would take out a
  browser the operator is running themselves. Every kill here is scoped to
  the slot's OWN profile directory, so nothing else on the machine is
  touched -- including the operator's separate Chromium run.
* Output files. Already safe: default_output_dir() is per-market.

Markets are read from a file, one per line. An optional TAB-separated second
column is the market's scope (what the market covers), passed through as
MARKET_SCOPE so markets sharing a name stem are not analysed into the same
cohort.

    .\\.venv\\Scripts\\python.exe scripts\\run_parallel_batches.py ^
        --markets-file queries\\drone_25.tsv --wave-size 5 --target 300
"""
from __future__ import annotations

import argparse
import datetime
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

# Same recovery budget as the sequential runner: enough attempts to ride out
# a quota window without letting one market hold up its whole wave.
MAX_ATTEMPTS = 4
COOL_OFF_AFTER_BLOCK = 900
STAGGER_SECONDS = 0

_PRINT_LOCK = threading.Lock()


def _log(slot: str, msg: str) -> None:
    stamp = datetime.datetime.now().strftime("%H:%M:%S")
    with _PRINT_LOCK:
        print(f"[{stamp}] [{slot}] {msg}", flush=True)


def _slug(market: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", market.lower()).strip("_")[:48]


def read_queue(path: Path) -> list[tuple[str, str]]:
    """[(market, scope)] from a file; blank lines and # comments skipped."""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        market, _, scope = line.partition("\t")
        market, scope = market.strip(), scope.strip()
        if market and market.lower() not in seen:
            seen.add(market.lower())
            out.append((market, scope))
    return out


# --- per-slot browser isolation -------------------------------------------


def profile_for(slot: int) -> Path:
    """This slot's own profile directory.

    Distinct from the default "ai_mode_chrome_profile" so a batch run never
    adopts (or burns) the profile an interactive run is using.

    Zero-padded because the name is matched as a wildcard when killing this
    slot's browsers: bare "ai_mode_batch_1" would also match slot 10.
    """
    return ROOT / "data" / f"ai_mode_batch_{slot:02d}"


def kill_slot_browsers(slot: int) -> None:
    """Kill browsers holding THIS slot's profile, and nothing else.

    The match is on the slot's own profile directory name, which appears in
    the browser's --user-data-dir argument. Other slots, and any browser the
    operator is running, do not match and are left alone.
    """
    name = profile_for(slot).name
    try:
        out = subprocess.run(
            [
                "powershell", "-NoProfile", "-NonInteractive", "-Command",
                "Get-CimInstance Win32_Process -Filter "
                "\"Name='chrome.exe' OR Name='chromium.exe'\" | "
                f"Where-Object {{ $_.CommandLine -like '*{name}*' }} | "
                "Select-Object -ExpandProperty ProcessId",
            ],
            capture_output=True, text=True, timeout=30,
        )
        pids = [p for p in (out.stdout or "").split() if p.strip().isdigit()]
        for pid in pids:
            subprocess.run(
                ["taskkill", "/F", "/PID", pid], capture_output=True, timeout=15
            )
        if pids:
            _log(f"slot{slot}", f"killed {len(pids)} browser(s) on {name}")
            time.sleep(2)
    except Exception as err:  # noqa: BLE001 - never block the queue
        _log(f"slot{slot}", f"browser cleanup skipped: {type(err).__name__}")


def reset_slot_profile(slot: int) -> None:
    """Archive this slot's profile so its next attempt starts clean."""
    kill_slot_browsers(slot)
    target = profile_for(slot)
    try:
        if target.exists():
            stamp = time.strftime("%Y%m%d_%H%M%S")
            target.rename(target.with_name(f"{target.name}_auto_{stamp}"))
            _log(f"slot{slot}", f"profile archived -> {target.name}_auto_{stamp}")
    except Exception as err:  # noqa: BLE001
        _log(f"slot{slot}", f"profile reset failed ({type(err).__name__})")


def seed_extensions(slot: int) -> None:
    """Give this slot its own copy of the staged CAPTCHA extensions.

    staging_root() is derived from the profile path, so each slot needs its
    own copy; without this only the default profile would have the extension.
    """
    import shutil

    try:
        from vendor_intel.scraping.google_ai_mode import installed_extensions, staging_root

        src = staging_root(str(ROOT / "data" / "ai_mode_chrome_profile"))
        dst = staging_root(str(profile_for(slot)))
        if src.exists() and not dst.exists():
            shutil.copytree(src, dst)
            _log(f"slot{slot}", f"extensions staged -> {dst.name}")
        # Say so loudly rather than running a whole market without CAPTCHA
        # solving and only finding out from the block rate hours later.
        # Counts the repo's bundled extensions/ too (what a fresh clone has).
        found = [Path(p).parent.name if Path(p).name == "extension" else Path(p).name
                 for p in installed_extensions(str(profile_for(slot)))]
        if found:
            _log(f"slot{slot}", f"extensions: {', '.join(found)}")
        else:
            _log(f"slot{slot}", f"WARNING no CAPTCHA extension in {dst.name}")
    except Exception as err:  # noqa: BLE001
        _log(f"slot{slot}", f"extension staging skipped: {type(err).__name__}")


# --- running one market ----------------------------------------------------


def market_done(market: str, country: str) -> tuple[bool, int, int]:
    """(finished, rows, scored) from the market's own checkpoint."""
    import json

    try:
        from vendor_intel.pipeline.web_expand import default_output_dir

        ckpt = (
            Path(default_output_dir(market, country))
            / "chatgpt_checkpoint_batch_all.json"
        )
        if not ckpt.exists():
            return False, 0, 0
        state = json.loads(ckpt.read_text(encoding="utf-8"))
        rows = (state.get("data") or {}).get("detail_rows") or []
        scored = sum(1 for r in rows if str(r.get("X") or "").strip())
        # "Done" means SCORED, not merely finished: a quota block used to
        # wipe the scoring step and still mark the market complete.
        done = bool(rows) and scored == len(rows) and state.get("status") == "done"
        return done, len(rows), scored
    except Exception:  # noqa: BLE001
        return False, 0, 0


_QUOTA = re.compile(r"request limit for ai responses|only waiting helps|quota", re.I)
_CAPTCHA = re.compile(r"CAPTCHA \((\d+) this run\)", re.I)


def classify(log_path: Path, tail_bytes: int = 200_000) -> str:
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")[-tail_bytes:]
    except Exception:  # noqa: BLE001
        return "other"
    if _QUOTA.search(text):
        return "quota"
    hits = _CAPTCHA.findall(text)
    if hits and int(hits[-1]) >= 5:
        return "captcha"
    return "other"


def run_market(
    slot: int, market: str, scope: str, country: str, target: int, logs: Path
) -> tuple[str, int, int]:
    tag = f"slot{slot}"
    for attempt in range(1, MAX_ATTEMPTS + 1):
        done, rows, scored = market_done(market, country)
        if done:
            _log(tag, f"{market}: already complete ({scored}/{rows})")
            return "ok", rows, scored

        kill_slot_browsers(slot)
        seed_extensions(slot)
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = logs / f"{_slug(market)}_{stamp}.log"
        _log(tag, f"{market}: attempt {attempt}/{MAX_ATTEMPTS} -> {log_path.name}")

        env = dict(os.environ)
        env["PYTHONPATH"] = str(ROOT / "src")
        # The isolation that keeps five concurrent browsers apart.
        env["GOOGLE_AI_MODE_PROFILE_DIR"] = str(profile_for(slot))
        # Chromium, not Chrome: managed Chrome silently ignores
        # --load-extension, so captcha-raptor would never load and every
        # CAPTCHA would stall the slot. seed_extensions() puts the extension
        # where installed_extensions() looks.
        env["GOOGLE_AI_MODE_BROWSER"] = "chromium"
        env["GOOGLE_AI_MODE_ENABLED"] = "true"
        # Companies per parameter-detail query. 5 measured at 100% evidence
        # coverage against live AI Mode once the batch prompt was rewritten
        # to carry the worked example and per-company HQ/description; that
        # takes a 250-company market from ~500 scoring queries to ~100. A
        # batch that comes back short falls back to per-company asks, so a
        # CAPTCHA costs one company rather than five.
        env.setdefault("AI_MODE_PARAM_BATCH", os.getenv("AI_MODE_PARAM_BATCH", "5"))
        # Discovery speed. Each round costs the same paced query whether it
        # asks for 10 names or 20, so a run that is query-bound rather than
        # market-bound finishes sooner at 20. Escalating to the region and
        # country sweep after ONE empty round (rather than three) reaches the
        # tier that actually finds the long tail.
        env.setdefault("DISCOVER_BATCH", os.getenv("DISCOVER_BATCH", "20"))
        env.setdefault(
            "DISCOVER_EMPTY_BEFORE_ESCALATE",
            os.getenv("DISCOVER_EMPTY_BEFORE_ESCALATE", "1"),
        )
        if scope:
            env["MARKET_SCOPE"] = scope

        with log_path.open("w", encoding="utf-8") as fh:
            proc = subprocess.run(
                [
                    sys.executable, str(ROOT / "scripts" / "run_chatgpt_expand.py"),
                    "--query", market, "--country", country,
                    "--target", str(target),
                ],
                cwd=str(ROOT), stdout=fh, stderr=subprocess.STDOUT, env=env,
            )

        done, rows, scored = market_done(market, country)
        if done:
            _log(tag, f"{market}: DONE ({scored}/{rows})")
            return "ok", rows, scored

        reason = classify(log_path)
        _log(
            tag,
            f"{market}: incomplete ({scored}/{rows}, exit {proc.returncode}, "
            f"reason={reason})",
        )
        if attempt >= MAX_ATTEMPTS:
            break
        if reason in ("quota", "captcha"):
            reset_slot_profile(slot)
            _log(tag, f"cooling off {COOL_OFF_AFTER_BLOCK}s")
            time.sleep(COOL_OFF_AFTER_BLOCK)
        else:
            kill_slot_browsers(slot)
            time.sleep(60)

    done, rows, scored = market_done(market, country)
    return ("ok" if done else "incomplete"), rows, scored


# --- waves -----------------------------------------------------------------


def effective_target(default: int) -> int:
    """Target for the wave about to start.

    Read fresh at every wave boundary from logs/.target_override so the
    number can be changed DURING a long unattended run: restarting the
    orchestrator to change one integer would re-pay the CAPTCHA cost of
    every in-flight market. Falls back to the launch value when the file is
    absent or unreadable, which is the safe direction.
    """
    override = ROOT / "logs" / ".target_override"
    try:
        value = int(override.read_text(encoding="utf-8").strip())
    except Exception:  # noqa: BLE001 - absent or malformed = use the default
        return default
    return value if 10 <= value <= 5000 else default


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--markets-file", required=True)
    ap.add_argument("--wave-size", type=int, default=5)
    ap.add_argument("--country", "-c", default="global")
    ap.add_argument("--target", "-t", type=int, default=300)
    ap.add_argument(
        "--stagger", type=int, default=STAGGER_SECONDS,
        help="seconds between starts within a wave (0 = all at once)",
    )
    ap.add_argument(
        "--slot-offset", type=int, default=0,
        help=(
            "shift this run's browser profiles by N slots. A second "
            "orchestrator running CONCURRENTLY must not reuse slots 1-5, or "
            "the two would fight over the same profile locks and each would "
            "kill the other's browsers."
        ),
    )
    args = ap.parse_args()

    queue = read_queue(Path(args.markets_file))
    if not queue:
        print("no markets found", file=sys.stderr)
        return 2

    logs = ROOT / "logs"
    logs.mkdir(exist_ok=True)
    waves = [
        queue[i : i + args.wave_size]
        for i in range(0, len(queue), args.wave_size)
    ]
    _log("main", f"{len(queue)} markets in {len(waves)} wave(s) of {args.wave_size}")
    if args.slot_offset:
        _log(
            "main",
            f"slot offset {args.slot_offset}: using profiles "
            f"{profile_for(1 + args.slot_offset).name}.."
            f"{profile_for(args.slot_offset + args.wave_size).name}",
        )
    for i, (m, _s) in enumerate(queue, 1):
        _log("main", f"  {i:2}. {m}")

    results: dict[str, tuple[str, int, int]] = {}
    started_all = time.monotonic()

    for wi, wave in enumerate(waves, 1):
        _log("main", "")
        _log("main", f"=== wave {wi}/{len(waves)} ({len(wave)} markets) ===")
        wave_started = time.monotonic()
        wave_target = effective_target(args.target)
        if wave_target != args.target:
            _log("main", f"target override in effect: {wave_target}")
        threads: list[threading.Thread] = []

        def worker(slot: int, market: str, scope: str) -> None:
            began = time.monotonic()
            try:
                status, rows, scored = run_market(
                    slot, market, scope, args.country, wave_target, logs
                )
            except Exception as err:  # noqa: BLE001 - one market must not
                _log(f"slot{slot}", f"{market}: crashed {err!r}")  # kill the wave
                status, rows, scored = "error", 0, 0
            finally:
                kill_slot_browsers(slot)
            mins = (time.monotonic() - began) / 60
            results[market] = (status, rows, scored)
            _log(f"slot{slot}", f"{market}: {status} ({scored}/{rows}) in {mins:.0f}m")

        for slot, (market, scope) in enumerate(wave, 1 + args.slot_offset):
            t = threading.Thread(
                target=worker, args=(slot, market, scope), daemon=False
            )
            t.start()
            threads.append(t)
            if args.stagger and slot < len(wave):
                time.sleep(args.stagger)

        # The next wave starts only when every market in this one is finished.
        for t in threads:
            t.join()
        _log(
            "main",
            f"=== wave {wi} finished in {(time.monotonic() - wave_started) / 60:.0f}m ===",
        )

    _log("main", "")
    _log("main", f"ALL DONE in {(time.monotonic() - started_all) / 60:.0f}m")
    ok = 0
    for market, _scope in queue:
        status, rows, scored = results.get(market, ("not run", 0, 0))
        ok += status == "ok"
        _log("main", f"  {status:10} {scored:4}/{rows:<4} {market}")
    _log("main", f"{ok}/{len(queue)} complete")
    return 0 if ok == len(queue) else 1


if __name__ == "__main__":
    raise SystemExit(main())
