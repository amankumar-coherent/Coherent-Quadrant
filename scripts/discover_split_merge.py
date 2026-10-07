#!/usr/bin/env python3
"""Discover ONE market with 2 (or more) browsers working at once, by running
N independent discovery halves in parallel and merging the results.

Discovery is a sequential conversation with Google AI Mode -- each round's
exclusion list depends on every prior round, so it cannot be split mid-flow
without touching discover_in_rounds()'s internals (region/state escalation,
exhaustion detection) -- too risky to patch under time pressure for a market
that needs to run correctly. Splitting BETWEEN independent runs instead needs
no internals touched at all:

  1. Each half runs the real run_chatgpt_expand.py discovery on the SAME,
     UNCHANGED market name -- not a modified one. An earlier version of this
     script appended "(Half 1)"/"(Half 2)" to the market name to get each
     half its own output folder, but that changes the exact string Step 0c
     sends to Google AI Mode for the B2B/B2C + player-type read, risking a
     different classification per half and a broken, inconsistent merge.
     Caught before this ever ran live. Each half instead gets its own
     folder via EXPAND_OUTPUT_FOLDER (output/<folder>/<slug>/, independent
     of the market name string), so Step 0c's query is byte-identical
     across both halves.
  2. Each half is a genuinely independent process on its own browser slot,
     so N halves = N real, concurrently-working browsers.
  3. Once every half finishes (or is stopped), their verified companies are
     merged (deduped by domain/name) into the REAL market's checkpoint
     (output/chatgpt_expand/, the default folder), and the half folders are
     left in place (not deleted) for inspection.
  4. run_quadrant_pipeline.py is then run normally on the real market name --
     it sees the merged verified list already there and skips straight to
     axes/dedupe/scoring, exactly as when it resumes any other market.

    .\\.venv\\Scripts\\python.exe scripts\\discover_split_merge.py ^
        --market "Electrical Fire Safety Industry Analysis" --country india ^
        --keep 120 --halves 2 --slot-start 41
"""
from __future__ import annotations

import argparse
import json
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
    print(f"[split {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--market", required=True)
    ap.add_argument("--country", default="global")
    ap.add_argument("--keep", type=int, required=True)
    ap.add_argument("--halves", type=int, default=2)
    ap.add_argument("--slot-start", type=int, required=True,
                    help="first of --halves consecutive browser slots for the split")
    ap.add_argument("--timeout-minutes", type=float, default=30.0,
                    help="give up waiting on a half after this long (checkpoint is "
                         "still merged with whatever it found)")
    args = ap.parse_args()

    import os

    from vendor_intel.pipeline.web_expand import default_output_dir, slugify
    from vendor_intel.pipeline.quadrant_pipeline import dedupe_companies

    def half_output_dir(folder: str) -> Path:
        # Mirrors default_output_dir()'s own logic, but for an ARBITRARY
        # folder name rather than the current process's environment -- each
        # half runs as its own subprocess with its own EXPAND_OUTPUT_FOLDER,
        # so this process (the merger) needs to compute that child's path
        # without touching its own environment.
        slug = slugify(args.market, args.country)
        return ROOT / "output" / folder / slug

    per_half_target = max(50, (args.keep * 2) // args.halves)  # headroom for verify loss
    half_folders = [f"chatgpt_expand_half{i + 1}" for i in range(args.halves)]

    log(f"discovering {args.market!r} in {args.halves} halves (SAME market name, "
        f"different output folders), ~{per_half_target} companies each, "
        f"slots {args.slot_start}..{args.slot_start + args.halves - 1}")

    procs = []
    for i, folder in enumerate(half_folders):
        slot = args.slot_start + i
        cmd = [sys.executable, str(ROOT / "scripts" / "run_chatgpt_expand.py"),
               "--query", args.market, "--country", args.country,
               "--target", str(per_half_target)]
        log_path = ROOT / "logs" / f"split_half{i + 1}_{slot}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        env = {
            "GOOGLE_AI_MODE_PROFILE_DIR": str(ROOT / "data" / f"ai_mode_batch_{slot:02d}"),
            "GOOGLE_AI_MODE_BROWSER": "chromium",
            "GOOGLE_AI_MODE_ENABLED": "true",
            "EXPAND_OUTPUT_FOLDER": folder,
            # Discovery only: run_quadrant_pipeline.py scores after the merge.
            "EXPAND_DISCOVERY_XY": "0",
        }
        fh = log_path.open("w", encoding="utf-8")
        proc = subprocess.Popen(cmd, cwd=str(ROOT), stdout=fh, stderr=subprocess.STDOUT,
                                env={**os.environ, "PYTHONIOENCODING": "utf-8", **env})
        procs.append((proc, fh, folder, slot, log_path))
        log(f"half {i + 1}: START on slot {slot}, folder {folder} -> {log_path.name}")
        time.sleep(3)

    deadline = time.time() + args.timeout_minutes * 60
    while time.time() < deadline:
        alive = [p for p, *_ in procs if p.poll() is None]
        if not alive:
            break
        log(f"{len(alive)}/{len(procs)} half(es) still discovering")
        time.sleep(30)
    else:
        log(f"timeout after {args.timeout_minutes} min -- stopping any half still running")
        for p, *_ in procs:
            if p.poll() is None:
                p.terminate()

    for _, fh, *_ in procs:
        fh.close()

    # Merge every half's verified companies into the real market's checkpoint.
    real_out = Path(default_output_dir(args.market, args.country))
    real_out.mkdir(parents=True, exist_ok=True)
    real_ckpt_path = real_out / "chatgpt_checkpoint_batch_all.json"
    real_ckpt = json.loads(real_ckpt_path.read_text(encoding="utf-8")) if real_ckpt_path.exists() else {}
    real_data = real_ckpt.setdefault("data", {})
    combined_verified = list(real_data.get("verified") or [])
    combined_rejected = list(real_data.get("rejected_mid") or [])

    def key(row: dict) -> str:
        name = str(row.get("name") or row.get("Company") or "").strip().lower()
        return name

    seen = {key(r) for r in combined_verified}
    half_market_analyses = []
    for i, folder in enumerate(half_folders):
        half_out = half_output_dir(folder)
        half_ckpt_path = half_out / "chatgpt_checkpoint_batch_all.json"
        if not half_ckpt_path.exists():
            log(f"half {i + 1}: no checkpoint produced -- skipping merge for this half")
            continue
        try:
            half_data = json.loads(half_ckpt_path.read_text(encoding="utf-8")).get("data", {})
        except Exception as err:  # noqa: BLE001
            log(f"half {i + 1}: checkpoint unreadable ({err}) -- skipping")
            continue
        half_verified = half_data.get("verified") or []
        new = [r for r in half_verified if key(r) and key(r) not in seen]
        for r in new:
            seen.add(key(r))
        combined_verified.extend(new)
        combined_rejected.extend(half_data.get("rejected_mid") or [])
        if half_data.get("market_analysis"):
            half_market_analyses.append(half_data["market_analysis"])
        log(f"half {i + 1}: {len(half_verified)} verified, {len(new)} new after dedupe")

    real_data["verified"] = combined_verified
    real_data["rejected_mid"] = combined_rejected
    # market_analysis (B2B/B2C read): both halves asked Google the SAME
    # market-name query (not a modified one), so their Step 0c reads should
    # already agree; take the first one found. A later run of
    # run_quadrant_pipeline.py re-reads/re-asks Step 0c on the real market
    # anyway if this is empty, so this is a head start, not the only source.
    if not real_data.get("market_analysis") and half_market_analyses:
        real_data["market_analysis"] = half_market_analyses[0]
        types = {json.dumps(ma.get("market_type")) for ma in half_market_analyses}
        if len(types) > 1:
            log("WARNING: the two halves disagreed on market_type (B2B/B2C) -- "
                "this should not happen since both asked the identical query; "
                "using the first half's read, but check the market's own "
                "Step 0c result once run_quadrant_pipeline.py runs on it")
    real_ckpt_path.write_text(json.dumps(real_ckpt, ensure_ascii=False), encoding="utf-8")

    have = len(dedupe_companies(combined_verified)[0])
    log(f"merged: {len(combined_verified)} verified rows -> {have} companies after dedupe "
        f"-> {real_ckpt_path}")
    return 0 if have > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
