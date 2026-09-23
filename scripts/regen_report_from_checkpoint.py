#!/usr/bin/env python3
"""Regenerate a market's HTML/CSV/JSON report in place from already-saved
checkpoint + audit data, without re-running the crawl/score pipeline.

Use this after an html_report.py / expand_quadrant_score.py change (e.g. a
new report section, a scoring fix) that should apply to a market's existing
output without redoing discovery, crawling, or scoring.

Example (from Coherent-Quadrant):

  .\\.venv\\Scripts\\python.exe scripts\\regen_report_from_checkpoint.py --market "Global Animal Healthcare Market"
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
    parser.add_argument("--market", "-q", required=True)
    parser.add_argument("--country", "-c", default="global")
    parser.add_argument("--batch", "-b", default="all")
    args = parser.parse_args()

    from vendor_intel.pipeline.expand_quadrant_score import export_expand_quadrant_outputs
    from vendor_intel.pipeline.web_expand import default_output_dir

    out_dir = default_output_dir(args.market, args.country)
    ckpt_path = out_dir / f"chatgpt_checkpoint_batch_{args.batch.lower()}.json"
    audit_path = out_dir / f"chatgpt_xy_scores_batch_{args.batch.lower()}.json"

    if not ckpt_path.exists():
        print(f"ERROR: checkpoint not found: {ckpt_path}", file=sys.stderr)
        return 1
    if not audit_path.exists():
        print(f"ERROR: audit not found: {audit_path}", file=sys.stderr)
        return 1

    state = json.loads(ckpt_path.read_text(encoding="utf-8"))
    detail_rows = state.get("data", {}).get("detail_rows") or []
    if not detail_rows:
        print(f"ERROR: no data.detail_rows in checkpoint: {ckpt_path}", file=sys.stderr)
        return 1
    audit = json.loads(audit_path.read_text(encoding="utf-8"))

    extras = export_expand_quadrant_outputs(
        out_dir, detail_rows, args.market, country=args.country, audit=audit, chart_n=20
    )
    print(f"Regenerated {len(detail_rows)} rows -> {extras['html']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
