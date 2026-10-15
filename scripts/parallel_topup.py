#!/usr/bin/env python3
"""Top up a market's verified companies with N browsers at once.

run_quadrant_pipeline.py's own top-up (step 1b) uses one browser. Here each of
N browsers runs discover_verify_rounds.py on its OWN copy of the market's
checkpoint (every name already found is excluded from its prompts and only
new companies are verified), with GEO_AREA_SHARD=k/N so each browser sweeps
a different share of the regions / states instead of repeating the others.
The new verified companies are then merged back into the market's real
checkpoint. Run the pipeline afterwards with --max-discover-rounds 0.

    .venv\\Scripts\\python.exe scripts\\parallel_topup.py --market "X Market" --country global ^
        --keep 250 --browsers 10 --slot-start 41 --max-rounds 6
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def log(msg: str) -> None:
    print(f"[topup {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def key(row: dict) -> str:
    return str(row.get("name") or row.get("Company") or row.get("company") or "").strip().lower()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--market", required=True)
    ap.add_argument("--country", default="global")
    ap.add_argument("--keep", type=int, required=True)
    ap.add_argument("--browsers", type=int, default=10)
    ap.add_argument("--slot-start", type=int, default=41)
    ap.add_argument("--max-rounds", type=int, default=6, help="top-up rounds per browser")
    ap.add_argument("--timeout-minutes", type=float, default=90.0)
    ap.add_argument("--countries", action="store_true",
                    help="start at the country-by-country tier, each browser on its own slice of countries")
    ap.add_argument("--verify-only", action="store_true",
                    help="no discovery: verify the companies an earlier (stopped) run's browsers already "
                         "found, each company on one browser only, then merge")
    ap.add_argument("--merge-only", action="store_true",
                    help="launch nothing: merge what the browser copies of a stopped run already verified "
                         "(their work would be lost when the next run recreates the copies)")
    args = ap.parse_args()

    from vendor_intel.pipeline.quadrant_pipeline import dedupe_companies
    from vendor_intel.pipeline.web_expand import default_output_dir

    real_dir = Path(default_output_dir(args.market, args.country))
    real = real_dir / "chatgpt_checkpoint_batch_all.json"
    state = json.loads(real.read_text(encoding="utf-8"))
    before = len(dedupe_companies(state["data"].get("verified") or [])[0])
    log(f"start: {before} verified companies; {args.browsers} browsers, target {args.keep}"
        + (" -- country by country" if args.countries else ""))
    if before >= args.keep and not args.merge_only:
        log("already at target -- nothing to do")
        return 0
    if args.merge_only:
        dirs = sorted((ROOT / "output").glob(f"chatgpt_expand_top*/{real_dir.name}"))
        return merge(real, dirs, before, dedupe_companies)

    shards: list[list[dict]] = [[] for _ in range(args.browsers)]
    if args.verify_only:
        from vendor_intel.pipeline.chatgpt_expand import _dedupe_key
        known = {_dedupe_key(key(r)) for k in ("verified", "rejected_mid") for r in state["data"].get(k) or []}
        pending: dict[str, dict] = {}
        # The market's own checkpoint too: a one-browser discovery stopped
        # between finding and verifying leaves its candidates there.
        for ck in [real, *sorted((ROOT / "output").glob(f"chatgpt_expand_top*/{real_dir.name}/{real.name}"))]:
            try:
                found = json.loads(ck.read_text(encoding="utf-8")).get("data") or {}
            except Exception as err:  # noqa: BLE001
                log(f"{ck}: unreadable ({err})")
                continue
            for r in found.get("recalled") or []:
                k = _dedupe_key(key(r))
                if k and k not in known:
                    pending.setdefault(k, r)
        for n, r in enumerate(pending.values()):
            shards[n % args.browsers].append(r)
        log(f"verify only: {len(pending)} unchecked companies over {args.browsers} browsers")
        if not pending:
            return 0

    procs = []
    for i in range(args.browsers):
        folder = f"chatgpt_expand_top{i + 1}"
        d = ROOT / "output" / folder / real_dir.name
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True)
        shutil.copy(real, d / real.name)
        if args.verify_only:
            if not shards[i]:
                continue
            copy = json.loads((d / real.name).read_text(encoding="utf-8"))
            copy["data"]["recalled"] = shards[i]
            (d / real.name).write_text(json.dumps(copy, ensure_ascii=False), encoding="utf-8")
        slot = args.slot_start + i
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "EXPAND_OUTPUT_FOLDER": folder,
               "GEO_AREA_SHARD": f"{i + 1}/{args.browsers}",
               **({"DISCOVER_START_TIER": "country"} if args.countries else {}),
               "GOOGLE_AI_MODE_PROFILE_DIR": str(ROOT / "data" / f"ai_mode_batch_{slot:02d}"),
               "GOOGLE_AI_MODE_BROWSER": "chromium", "GOOGLE_AI_MODE_ENABLED": "true"}
        tag = "countries" if args.countries else "topup"
        fh = (ROOT / "logs" / f"{tag}_{real_dir.name}_{i + 1}.log").open("w", encoding="utf-8")
        p = subprocess.Popen([sys.executable, str(ROOT / "scripts" / "discover_verify_rounds.py"),
                              "--market", args.market, "--country", args.country, "--keep", str(args.keep),
                              "--slot", str(slot), "--max-rounds", str(args.max_rounds)]
                             + (["--verify-only"] if args.verify_only else []),
                             cwd=str(ROOT), stdout=fh, stderr=subprocess.STDOUT, env=env)
        procs.append((p, fh, d))
        log(f"browser {i + 1}: start on slot {slot}")
        time.sleep(4)

    deadline = time.time() + args.timeout_minutes * 60
    # One slow browser (a CAPTCHA loop, unusable AI Mode replies) must not leave the
    # others idle: once 80% have finished, the rest get STRAGGLER_GRACE_MIN minutes,
    # then are stopped; merge() keeps whatever they already saved.
    grace_min = float(os.getenv("STRAGGLER_GRACE_MIN", "5"))
    grace_at: float | None = None
    while time.time() < deadline and any(p.poll() is None for p, _, _ in procs):
        time.sleep(30)
        done = sum(p.poll() is not None for p, _, _ in procs)
        if grace_at is None and len(procs) >= 5 and done >= 0.8 * len(procs):
            grace_at = time.time() + grace_min * 60
        if grace_at is not None and time.time() >= grace_at:
            log(f"{len(procs) - done} slow browser(s) stopped after {grace_min:g} min grace; their saved finds are merged")
            break
    for p, fh, _ in procs:
        if p.poll() is None:
            p.terminate()
        fh.close()

    return merge(real, [d for _, _, d in procs], before, dedupe_companies)


def merge(real: Path, dirs: list[Path], before: int, dedupe_companies) -> int:
    """Fold every browser copy's verified / rejected companies into the market."""
    state = json.loads(real.read_text(encoding="utf-8"))
    verified = list(state["data"].get("verified") or [])
    rejected = list(state["data"].get("rejected_mid") or [])
    seen = {key(r) for r in verified}
    for i, d in enumerate(dirs, 1):
        try:
            data = json.loads((d / real.name).read_text(encoding="utf-8")).get("data") or {}
        except Exception as err:  # noqa: BLE001 -- one bad copy must not lose the others
            log(f"browser {i}: unreadable checkpoint ({err})")
            continue
        new = [r for r in data.get("verified") or [] if key(r) and key(r) not in seen]
        seen |= {key(r) for r in new}
        verified += new
        rejected += [r for r in data.get("rejected_mid") or [] if r not in rejected]
        log(f"browser {i}: {len(new)} new verified")
    state["data"]["verified"], state["data"]["rejected_mid"] = verified, rejected
    real.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    after = len(dedupe_companies(verified)[0])
    log(f"merged: {before} -> {after} verified companies after dedupe -> {real}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
