#!/usr/bin/env python3
"""Seed a market's checkpoint from an EXISTING quadrant.json report, so the
one-command pipeline can top it up to --keep instead of starting from zero.

For a market that has a report (built by some earlier run, possibly on a
different machine or an older pipeline version) but never reached the target
company count, this pulls every company's name + HQ + role out of the report
and writes them into chatgpt_checkpoint_batch_all.json as pre-verified rows.
run_quadrant_pipeline.py --keep N then sees "N-ish verified already" and runs
its normal discover -> verify TOP-UP rounds for the shortfall, then scores
everyone through the current pipeline -- nothing about scoring or evidence is
carried over from the old report; only the company list and B2B/B2C read are
reused, so results are fresh and consistent with every other market.

Skips any company whose location data is corrupted in the source report
(a literal "Country" placeholder instead of a real country name) rather than
seed bad data forward.

    .\\.venv\\Scripts\\python.exe scripts\\seed_checkpoint_from_report.py ^
        --market "Drone Propulsion Industry Analysis" --country india ^
        --report-json "C:\\path\\to\\drone_propulsion_..._quadrant.json"
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
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--market", required=True)
    ap.add_argument("--country", default="india")
    ap.add_argument("--report-json", required=True, help="path to the existing *_quadrant.json")
    args = ap.parse_args()

    from vendor_intel.pipeline.web_expand import default_output_dir

    report = json.loads(Path(args.report_json).read_text(encoding="utf-8"))
    brands = report.get("brands") or []
    relevance = (report.get("criteria") or {}).get("relevance") or {}

    out_dir = Path(default_output_dir(args.market, args.country))
    out_dir.mkdir(parents=True, exist_ok=True)
    ckpt_path = out_dir / "chatgpt_checkpoint_batch_all.json"
    if ckpt_path.exists():
        print(f"REFUSING to overwrite an existing checkpoint at {ckpt_path}. "
              "Delete it first if you really want to reseed from scratch.")
        return 2

    verified: list[dict] = []
    skipped: list[str] = []
    seen: set[str] = set()
    for b in brands:
        # company_key is the plain name; "company" may carry a display label
        # such as "Name (acquired by Owner)" in newer reports.
        name = str(b.get("company_key") or b.get("company") or b.get("display_name") or "").strip()
        hq = str(b.get("hq_location") or b.get("founded_location") or "").strip()
        role = str(b.get("commercial_role") or "").strip()
        # A literal "Country" (or similarly bare/placeholder) value means the
        # source report's location data is corrupted for this row -- do not
        # carry it forward as if it were real.
        if not name or name.lower() in seen:
            continue
        if not hq or hq.strip().lower() == "country" or hq.strip().endswith(", Country"):
            # Kept with no HQ (not dropped): the company is real data from
            # the report; scripts/fill_missing_hq.py asks AI Mode for its
            # "City, Country", and the checks then treat it like the rest.
            skipped.append(name)
            hq = ""
        seen.add(name.lower())
        verified.append({
            "name": name,
            "Company": name,
            "Market Offering": str(b.get("display_name") or name),
            "brand_name": str(b.get("brand") or b.get("display_name") or name),
            "Headquarters": hq,
            "Ownership": "Independent",
            "ownership_confidence": "medium",
            "Summary": "",
            "verify_reason": "Seeded from an existing report; will be re-verified "
                             "if the pipeline re-checks it.",
            "verify_confidence": "80",
            "commercial_role": role,
            "Distribution Type": role,
            "source_query": "seeded_from_report",
            "discovery_source": "seeded_from_report",
        })

    market_analysis = {}
    if relevance:
        market_analysis = {
            "market_type": relevance.get("market_type") or "B2B",
            "market_type_reason": relevance.get("market_type_reason") or "",
            "market_definition": relevance.get("market_definition") or "",
            "market_participants": [],  # rebuilt properly if the pipeline re-runs Step 0c
            "primary_participant": (relevance.get("keep_roles") or [""])[0],
            "primary_reason": relevance.get("player_type_reason") or "",
        }

    state = {"data": {"verified": verified, "rejected_mid": [],
                      "market_analysis": market_analysis}}
    ckpt_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

    print(f"seeded {len(verified)} companies from {len(brands)} report rows "
          f"({len(skipped)} kept with no HQ -- placeholder in the report; fill with fill_missing_hq.py) -> {ckpt_path}")
    if skipped:
        print(f"  skipped: {skipped}")
    if market_analysis:
        print(f"  market_type: {market_analysis['market_type']}, "
              f"primary_participant: {market_analysis['primary_participant']!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
