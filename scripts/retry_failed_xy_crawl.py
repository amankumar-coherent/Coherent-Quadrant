#!/usr/bin/env python3
"""Retry Step 6c crawl+score for only the companies whose website crawl
failed in a completed chatgpt_expand run — leaves already-scored companies
untouched so the next run only redoes the failed subset.

How it works: chatgpt_expand.py rebuilds the row list entering Step 6c from
checkpoint["data"]["purity_rows"] every run. Row dicts are mutated in place
during scoring, so once a run has completed once, purity_rows already has
X/Y/Overall/Quadrant baked in for EVERY company (not just the successfully
crawled ones) — meaning a fresh process will see every row as already scored
and skip scoring/crawling entirely, no matter what checkpoint["completed"]
flags say. So this script must strip the score columns back out of
purity_rows for just the failed companies — clearing xy_partial alone is
NOT enough (that only matters for a same-process resume after a kill, where
purity_rows genuinely has no scores yet).

This script identifies the failed-crawl companies from
chatgpt_xy_scores_batch_<batch>.json (the "crawled" flag per company),
strips SCORE_COLUMNS from just those companies' entries in purity_rows,
rebuilds xy_partial from the authoritative full xy_rows snapshot minus the
same companies, and un-marks the 6c_xy / 6d_details checkpoint steps so the
next run re-crawls and re-scores only them.

Note: a company with crawled=false and resumed=true was NOT a crawl failure
— it means that pass reused an already-good score and skipped crawling it
entirely. Only crawled=false WITHOUT resumed=true is a real failure. Treating
resumed rows as failures would wrongly re-queue already-good companies.

Only run this AFTER the target market's run_chatgpt_expand.py process has
exited (finished, or you stopped it) — editing the checkpoint while that
process is still writing to it can race with its own save.

Example (from Coherent-Quadrant):

  .\\.venv\\Scripts\\python.exe scripts\\retry_failed_xy_crawl.py --market "Global Animal Healthcare Market"

Then re-run the original command to retry only the failed companies:

  .\\.venv\\Scripts\\python.exe scripts\\run_chatgpt_expand.py --query "Global Animal Healthcare Market" --scraper-url http://127.0.0.1:15551
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market", "-q", required=True, help="Exact --query used for the original run")
    parser.add_argument("--country", "-c", default="global")
    parser.add_argument("--batch", "-b", default="all")
    args = parser.parse_args()

    from vendor_intel.pipeline.web_expand import default_output_dir

    out_dir = default_output_dir(args.market, args.country)
    ckpt_path = out_dir / f"chatgpt_checkpoint_batch_{args.batch.lower()}.json"
    audit_path = out_dir / f"chatgpt_xy_scores_batch_{args.batch.lower()}.json"

    if not ckpt_path.exists():
        print(f"ERROR: checkpoint not found: {ckpt_path}", file=sys.stderr)
        return 1
    if not audit_path.exists():
        print(
            f"ERROR: {audit_path.name} not found — Step 6c hasn't finished writing "
            "its audit yet. Wait for the run to reach Step 6d before retrying.",
            file=sys.stderr,
        )
        return 1

    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    meta_rows = audit.get("rows") or []
    failed = {
        str(r.get("company") or "").strip().lower()
        for r in meta_rows
        if isinstance(r, dict)
        and not r.get("crawled")
        and not r.get("resumed")
        and str(r.get("company") or "").strip()
    }
    if not failed:
        print("No failed-crawl companies found in the audit — nothing to retry.")
        return 0

    state = json.loads(ckpt_path.read_text(encoding="utf-8"))
    data = state.setdefault("data", {})

    SCORE_COLUMNS = ("X Score", "Y Score", "Overall Score", "Quadrant", "Industry Category")

    purity_rows = data.get("purity_rows") or []
    if not purity_rows:
        print(f"ERROR: no data.purity_rows in checkpoint — nothing to reset from: {ckpt_path}", file=sys.stderr)
        return 1
    stripped = 0
    for r in purity_rows:
        if str(r.get("Company") or "").strip().lower() in failed:
            for col in SCORE_COLUMNS:
                r.pop(col, None)
            stripped += 1
    data["purity_rows"] = purity_rows

    # xy_rows is the authoritative full post-run snapshot (all companies,
    # written once 6c_xy completes) — rebuild xy_partial from it rather than
    # filtering the existing xy_partial, so this script is self-correcting
    # even if a prior run left xy_partial in a bad state. Only matters for a
    # same-process resume after a kill; harmless to keep in sync regardless.
    xy_rows = data.get("xy_rows") or []
    kept = [
        r
        for r in xy_rows
        if str(r.get("Company") or "").strip().lower() not in failed
    ]
    if xy_rows:
        data["xy_partial"] = kept

    completed = state.setdefault("completed", {})
    completed["6c_xy"] = False
    completed["6d_details"] = False

    # run_chatgpt_expand() short-circuits the ENTIRE market with
    # {"skipped": True, "reason": "already_done"} whenever ckpt.is_done()
    # (state["status"] == "done"), before it ever looks at individual step
    # flags above. Must also clear this or the retry never runs.
    state["status"] = "running"

    ckpt_path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Failed-crawl companies found: {len(failed)}")
    print(f"Stripped scores from {stripped} of them in purity_rows (kept {len(purity_rows) - stripped} untouched).")
    print(f"Checkpoint updated: {ckpt_path}")
    print("Re-run the original run_chatgpt_expand.py command to retry only those companies.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
