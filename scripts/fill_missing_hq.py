#!/usr/bin/env python3
"""Fill a missing Headquarters value for specific verified companies via AI Mode.

The VERIFY check "Every company has an HQ" occasionally fails for a
handful of Top-20 companies whose discovery row never carried a
Headquarters value (found through a query angle that returned the company
without its city/country). Rather than re-run discovery or hand-edit the
checkpoint, this asks AI Mode directly for just "City, Country" per named
company and writes the answer onto that company's own row (every
Company/company/name key spelling) in the checkpoint's verified list.
Leaves a company untouched if AI Mode has no confident answer -- never
invents a location.

    .\\.venv\\Scripts\\python.exe scripts\\fill_missing_hq.py ^
        --market "Drone Propulsion Industry Analysis" --country india ^
        --slot 61 --company "VTOL Aviation India Private Limited"
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _row_name(r: dict) -> str:
    return str(r.get("Company") or r.get("company") or r.get("name") or "").strip()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--market", required=True)
    ap.add_argument("--country", default="global")
    ap.add_argument("--slot", type=int, required=True)
    ap.add_argument("--company", action="append", required=True,
                    help="repeatable; exact company name as it appears in the checkpoint")
    args = ap.parse_args()

    profile = ROOT / "data" / f"ai_mode_batch_{args.slot:02d}"
    os.environ["GOOGLE_AI_MODE_PROFILE_DIR"] = str(profile)
    os.environ["GOOGLE_AI_MODE_BROWSER"] = "chromium"
    os.environ["GOOGLE_AI_MODE_ENABLED"] = "true"

    from vendor_intel.pipeline.web_expand import default_output_dir
    from vendor_intel.scraping.google_ai_mode import ask as ai_ask

    out_dir = Path(default_output_dir(args.market, args.country))
    ckpt_path = out_dir / "chatgpt_checkpoint_batch_all.json"
    state = json.loads(ckpt_path.read_text(encoding="utf-8"))
    data = state.setdefault("data", {})
    verified = data.get("verified") or []

    wanted = set(args.company)
    found_names = {_row_name(r) for r in verified if _row_name(r) in wanted}
    missing = wanted - found_names
    if missing:
        print(f"WARNING: not found in verified list, skipping: {sorted(missing)}",
              file=sys.stderr)

    filled = 0
    for name in sorted(found_names):
        prompt = (
            f'What city and country is the headquarters of the company "{name}"? '
            'Answer with ONLY compact JSON: {"headquarters":"City, Country"}. '
            'If you cannot find a confident, specific answer, answer '
            '{"headquarters":""}.'
        )
        try:
            raw = ai_ask(prompt)
        except Exception as err:  # noqa: BLE001
            print(f"  {name}: query failed ({type(err).__name__}: {err})")
            continue
        # The page echoes the prompt (which itself contains two example JSON
        # snippets) before the real answer, so a greedy first-brace-to-
        # last-brace match spans the echoed template too and parses as
        # garbage. Take the LAST {...} on the page instead -- that is
        # always the model's own answer, never the echoed prompt.
        hq = ""
        for m in re.finditer(r'\{[^{}]*\}', str(raw)):
            try:
                candidate = json.loads(m.group(0))
            except Exception:  # noqa: BLE001
                continue
            if "headquarters" in candidate:
                hq = str(candidate.get("headquarters") or "").strip()
        if not hq:
            print(f"  {name}: no confident HQ found, left blank")
            continue
        for r in verified:
            if _row_name(r) == name:
                r["Headquarters"] = hq
        print(f"  {name}: {hq}")
        filled += 1

    ckpt_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    print(f"\nfilled {filled}/{len(found_names)} companies -> {ckpt_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
