#!/usr/bin/env python3
"""Write a market brief for every market in a CMI dashboard-topics Excel, by row number.

    .venv\\Scripts\\python.exe profood\\setup_briefs_from_excel.py ^
        --excel "C:\\...\\CMI Dashboard Topics.xlsx" --from 21 --to 40 [--country global] [--force]

The sheet "Market Definitions" holds one row per market: S. No. | Market Name | Market
Definition | Segmentation | Exclusion. Each row becomes <market>/_pipeline/market_brief.json
plus Step 0c in that market's checkpoint, so discovery asks for the right company type from
the first round.

Nothing market-specific is coded here: the definition, the segmentation and the exclusions are
read from the sheet, and every market in the range gets the same treatment. The player type is
a flag (--player-type), because one sheet is one kind of market -- these dashboards list
product markets measured on "sales of finished <product>", which is a Manufacturer landscape.

The definition every AI Mode query carries is kept short: an oversized one overflows the search
URL, the query is truncated and the answers come back unusable (owner 2026-11-03).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

SHEET = "Market Definitions"
MAX_DEFINITION = 2400          # what fits a query URL beside the rest of the prompt
MAX_SCOPE = 900                # verify criteria budget


def clean(text: object) -> str:
    """Sheet text as one tidy line: bullets, vertical tabs and stray spaces gone."""
    s = str(text or "")
    s = s.replace("\x0b", "\n")                       # Excel soft line break
    s = re.sub(r"[\u2022\uf0a7\uf0b7\ufffd\u25aa\u25cf]", "", s)   # bullet glyphs
    s = re.sub(r"\s*\n\s*", "; ", s)
    s = re.sub(r"\s{2,}", " ", s)
    return s.strip(" ;")


def segmentation_line(text: object) -> str:
    """"By X: a; b; c. By Y: ..." from the sheet's bulleted block, Region dropped
    (every one of these markets is global, so the region split says nothing about
    which companies belong in it)."""
    s = clean(text)
    s = re.sub(r"(?:^|;\s*)By Region:?.*$", "", s, flags=re.I)
    s = re.sub(r";\s*(By [A-Z])", r". \1", s)
    s = re.sub(r"(By [A-Za-z /&-]+?);", r"\1:", s)
    return s.strip(" ;.") + "."


def exclusions(text: object) -> list[str]:
    return [x.strip(" .;") for x in re.split(r"[;\n]", clean(text)) if x.strip(" .;")]


def build(name: str, definition: str, segmentation: str, excl: list[str],
          player_type: str, market_type: str) -> dict:
    product = re.sub(r"^Global\s+|\s+Market$", "", name).strip()
    not_in = "; ".join(excl)
    scope = (f"ONLY companies that make and sell {product} under their own name. A diversified "
             f"adhesives, chemicals or materials group qualifies when this is one of its own "
             f"product lines, however small a share of its revenue. NOT in this market: {not_in}.")
    if len(scope) > MAX_SCOPE:                       # trim the exclusion tail, never the KEEP rule
        room = MAX_SCOPE - (len(scope) - len(not_in)) - 4
        scope = scope.replace(not_in, not_in[:max(room, 0)].rsplit(";", 1)[0] + " …")
    core = (f"A core player makes and sells {product} under its own name; a diversified adhesives, "
            "chemicals or materials group qualifies when this is one of its own product lines, "
            "however small a share of its revenue that line is.")
    full = f"{definition} Segmentation: {segmentation} Exclusions: {not_in}."
    if len(full) > MAX_DEFINITION:
        full = full[:MAX_DEFINITION].rsplit(". ", 1)[0] + "."
    return {
        "source": f"CMI dashboard-topics Excel, sheet '{SHEET}': definition, segmentation and "
                  f"exclusions as written there; built by profood/setup_briefs_from_excel.py",
        # ONE player type per market (owner's rule): the sheet measures sales of the finished
        # product, so the single role is the company that makes and sells it.
        "player_type": player_type,
        "market_type": market_type,
        "market_definition": full,
        "report_definition": definition,
        "player_type_reason": (
            f"Manufacturers: the landscape compares the companies that make and sell {product} "
            "under their own name."),
        "core_scope": core,
        "adjacent_segments": excl + [
            "Distributors, traders and resellers that make nothing of their own",
            "Buyers and users of these products rather than their makers",
            "Raw-material and monomer suppliers that do not sell the finished adhesive",
        ],
        "scope": scope,
        "scope_test": "own_product_line",
        # The owner asked that no company of an excluded type appear at all.
        "adjacent_policy": "exclude",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--excel", required=True)
    ap.add_argument("--from", dest="first", type=int, required=True)
    ap.add_argument("--to", dest="last", type=int, required=True)
    ap.add_argument("--country", default="global")
    ap.add_argument("--player-type", default="Manufacturer")
    ap.add_argument("--market-type", default="B2B")
    ap.add_argument("--markets-file", help="also write the list for run_markets_parallel.py")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    from openpyxl import load_workbook

    from vendor_intel.pipeline.openai_expand_checkpoint import ExpandCheckpoint
    from vendor_intel.pipeline.web_expand import default_output_dir

    ws = load_workbook(args.excel, data_only=True, read_only=True)[SHEET]
    written, names = 0, []
    for row in ws.iter_rows(min_row=2, values_only=True):
        try:
            sn = int(row[0])
        except (TypeError, ValueError):
            continue
        if not (args.first <= sn <= args.last):
            continue
        name = str(row[1] or "").strip()
        if not name:
            continue
        brief = build(name, clean(row[2]), segmentation_line(row[3]), exclusions(row[4]),
                      args.player_type, args.market_type)
        if args.country.strip().lower() not in ("global", "worldwide", "world", ""):
            # The sheet names every market "Global ..."; a regional / country run is named
            # for its own geography ("Europe Spray Adhesives Market"), never "Global".
            name = re.sub(r"^\s*global\s+", "", name, flags=re.I)
            name = f"{args.country.strip().title()} {name}"
        out = Path(default_output_dir(name, args.country))
        path = out / "_pipeline" / "market_brief.json"
        names.append(name)
        if path.exists() and not args.force:
            print(f"{sn:>3}  kept (already there)  {name[:52]}")
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(brief, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        analysis = {
            "market_type": brief["market_type"],
            "market_type_reason": f"{brief['market_type']}: industrial and converter customers buy "
                                  "these products. Set by the client's market sheet.",
            "market_definition": brief["market_definition"], "core_scope": brief["core_scope"],
            "adjacent_segments": brief["adjacent_segments"],
            "market_participants": [{"type": brief["player_type"], "definition": brief["core_scope"],
                                     "why_relevant": "They make the product this market is measured on."}],
            "primary_participant": brief["player_type"],
            "primary_reason": "Defined by the scope of this report.",
            "report_definition": brief["report_definition"],
            "player_type_reason": brief["player_type_reason"],
        }
        ck = (ExpandCheckpoint.load(ExpandCheckpoint.path_for(out, "all"))
              or ExpandCheckpoint.create(out, query=name, country=args.country, batch="all", target=400))
        if args.force or not (ck.state.get("data") or {}).get("market_analysis"):
            ck.bump("0_start", "0c_market", market_analysis=analysis, note="market brief (client Excel)")
        written += 1
        print(f"{sn:>3}  def {len(brief['market_definition']):>4}  scope {len(brief['scope']):>3}  "
              f"excl {len(brief['adjacent_segments']):>2}  {name[:52]}")
    if args.markets_file:
        Path(args.markets_file).write_text(
            "\n".join(f"{n} | {args.country}" for n in names) + "\n", encoding="utf-8")
        print(f"\nmarkets file: {args.markets_file} ({len(names)} markets)")
    print(f"briefs written: {written} of {len(names)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
