#!/usr/bin/env python3
"""Fabrication check: flag columns that look generated rather than researched.

A field that is overwhelmingly ONE pattern was produced by a formula, not by
research. The clearest measured example: with a "no field may be blank"
instruction in the prompt, 94% of one email column came back as
``info@<the-company's-own-domain>`` and every LinkedIn URL was built from a
person's name. All of it looked researched.

Checking a column's frequency distribution takes seconds and is the fastest
way to catch that class of failure, so run this after a market completes.

  .\\.venv\\Scripts\\python.exe scripts\\check_fabrication.py --market "Global Daily Multivitamins Market"
  .\\.venv\\Scripts\\python.exe scripts\\check_fabrication.py --all
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

# Above this share, one repeated pattern in a column means a formula.
_PATTERN_THRESHOLD = 0.60

_PLACEHOLDER = re.compile(
    r"^\s*(n/?a|na|none|null|unknown|not\s+(?:publicly\s+)?disclosed|-{1,3})\s*$", re.I
)


def _filled(values: list[str]) -> list[str]:
    return [v for v in values if v.strip() and not _PLACEHOLDER.match(v)]


def _report_email(values: list[str]) -> list[str]:
    """info@/sales@ at the company's own domain is the classic invention."""
    filled = _filled(values)
    if not filled:
        return []
    locals_ = Counter(v.split("@")[0].lower() for v in filled if "@" in v)
    if not locals_:
        return []
    top, n = locals_.most_common(1)[0]
    share = n / len(filled)
    notes = [f"    top local-parts: {locals_.most_common(4)}"]
    if share >= _PATTERN_THRESHOLD:
        notes.append(
            f"    FABRICATION LIKELY: {share:.0%} are '{top}@' — a formula, not research"
        )
    return notes


def _report_linkedin(values: list[str]) -> list[str]:
    filled = _filled(values)
    if not filled:
        return []
    person = [v for v in filled if "/in/" in v]
    notes = [f"    person profiles (/in/): {len(person)}/{len(filled)}"]
    if person and len(person) / len(filled) >= _PATTERN_THRESHOLD:
        notes.append(
            "    FABRICATION LIKELY: a specific person's profile URL is the "
            "hardest thing to know — these are usually built from a name"
        )
    return notes


def _report_generic(col: str, values: list[str]) -> list[str]:
    filled = _filled(values)
    if len(filled) < 5:
        return []
    counts = Counter(v.strip().lower() for v in filled)
    top, n = counts.most_common(1)[0]
    share = n / len(filled)
    if share >= _PATTERN_THRESHOLD and len(counts) > 1:
        return [
            f"    FABRICATION LIKELY: {share:.0%} of values are identical "
            f"({top!r}) — check whether this was researched"
        ]
    return []


_CHECKS = {
    "Email": _report_email,
    "LinkedIn": _report_linkedin,
    "Office No.": None,
    "Contact Person": None,
    "Continent / Geography": None,
    "Operational Presence": None,
    "Employees": None,
    "Headquarters": None,
    "Founded": None,
}


def check_market(market: str, country: str = "global") -> int:
    from openpyxl import load_workbook

    from vendor_intel.pipeline.web_expand import default_output_dir, resolve_final_path

    out_dir = default_output_dir(market, country)
    xlsx = resolve_final_path(market, country, out_dir, None)
    if not Path(xlsx).exists():
        print(f"  no FINAL.xlsx for {market}")
        return 0

    wb = load_workbook(xlsx, read_only=True, data_only=True)
    if "Landscape" not in wb.sheetnames:
        wb.close()
        return 0
    ws = wb["Landscape"]
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    if len(rows) < 2:
        return 0

    header = [str(h or "") for h in rows[0]]
    data = rows[1:]
    print(f"\n== {market}  ({len(data)} rows)")
    flags = 0
    for col, fn in _CHECKS.items():
        if col not in header:
            continue
        idx = header.index(col)
        values = [str(r[idx] or "") for r in data]
        filled = _filled(values)
        print(f"  {col:24} filled {len(filled):4}/{len(values)}")
        notes = (fn or (lambda v: _report_generic(col, v)))(values)
        for note in notes:
            print(note)
            if "FABRICATION LIKELY" in note:
                flags += 1
    return flags


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--market", "-q")
    ap.add_argument("--country", "-c", default="global")
    ap.add_argument("--all", action="store_true", help="every completed market")
    args = ap.parse_args()

    markets: list[str] = []
    if args.all:
        import json

        for audit in sorted((ROOT / "output" / "chatgpt_expand").glob("*/*_audit.json")):
            try:
                markets.append(json.loads(audit.read_text(encoding="utf-8"))["query"])
            except Exception:  # noqa: BLE001
                continue
    elif args.market:
        markets = [args.market]
    else:
        ap.print_help()
        return 2

    total = 0
    for market in dict.fromkeys(markets):
        total += check_market(market, args.country)
    print(
        f"\n{total} column(s) flagged as likely fabricated."
        if total
        else "\nNo fabrication patterns detected."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
