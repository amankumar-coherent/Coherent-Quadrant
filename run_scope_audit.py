#!/usr/bin/env python3
"""Audit an exported landscape against cached Google AI Overview evidence.

    python run_scope_audit.py --market "Rupture Disc Market" \
        --json output/region/north_america/rupture_disc_market_north_america.json [--apply]

Reads only the local cache — never drives a browser. Writes a review report next
to the input; --apply also rewrites the export without the confident rejects.
"""
import argparse, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
from dotenv import load_dotenv; load_dotenv(ROOT / ".env", override=True)

from vendor_intel.config import Settings
from vendor_intel.pipeline.scope_audit import apply_audit, audit_rows


def main() -> None:
    p = argparse.ArgumentParser(description="Scope audit from AI Overview evidence")
    p.add_argument("--market", required=True)
    p.add_argument("--json", required=True, help="Pipeline/region result JSON")
    p.add_argument("--min-confidence", type=float, default=0.7)
    p.add_argument("--apply", action="store_true", help="Rewrite the export without rejects")
    args = p.parse_args()

    src = Path(args.json)
    data = json.loads(src.read_text(encoding="utf-8"))
    rows = data.get("relevant_companies") or []
    print(f"auditing {len(rows)} companies against cached AI Overview evidence…", flush=True)

    verdicts, out = audit_rows(rows, args.market, settings=Settings.load(),
                               min_confidence=args.min_confidence)
    tally = {}
    for v in verdicts:
        tally[v.verdict] = tally.get(v.verdict, 0) + 1
    print(f"\nscreened candidates: {len(verdicts)}   {tally}")
    print(f"confident out-of-scope (>= {args.min_confidence}): {len(out)}\n")
    for v in sorted(out, key=lambda v: -v.confidence):
        print(f"  {v.brand[:34]:36s} {v.confidence:.2f}  {v.reason[:70]}")

    report = src.with_name(src.stem + "_scope_audit.json")
    report.write_text(json.dumps([v.to_dict() for v in verdicts], ensure_ascii=False, indent=2),
                      encoding="utf-8")
    print(f"\nreport: {report}")

    if args.apply and out:
        kept, dropped = apply_audit(rows, out)
        data["relevant_companies"] = kept
        data.setdefault("scope_audit_rejected", []).extend(dropped)
        src.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(f"applied: {len(rows)} -> {len(kept)} companies")


if __name__ == "__main__":
    main()
