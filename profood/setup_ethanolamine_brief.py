#!/usr/bin/env python3
r"""Market brief (data) for the Global Ethanolamine Market, from the client's pivot
("Pivot_Global Ethanolamine Market _Coherent Market Insights.xlsx": product types, grades, functions,
applications, end-user industries, channels).

    .venv\Scripts\python.exe profood\setup_ethanolamine_brief.py [--force]

Writes ``<market>/_pipeline/market_brief.json`` and Step 0c in the market's checkpoint, so discovery asks
for the right company type (ethanolamine producers) from the first round. Nothing here is pipeline logic.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

MARKET = "Global Ethanolamine Market"
COUNTRY = "global"

DEFINITION = (
    "The Global Ethanolamine Market covers the production and sale of ethanolamines -- monoethanolamine (MEA), "
    "diethanolamine (DEA), triethanolamine (TEA) and methyldiethanolamine (MDEA) -- made mainly by reacting "
    "ethylene oxide with ammonia, in industrial, pharmaceutical, cosmetic and electronic grades. They are used as "
    "chemical intermediates, pH control agents, gas treatment agents, surfactant intermediates, corrosion "
    "inhibitors and emulsifying agents.")
SEGMENTATION = (
    "By Product Type: MEA, DEA, TEA, MDEA. By Grade: Industrial, Pharmaceutical, Cosmetic, Electronic. "
    "By Function: Chemical Intermediate, pH Control Agent, Gas Treatment Agent, Surfactant Intermediate, Corrosion "
    "Inhibitor, Emulsifying Agent. By Application: Gas Sweetening, Surfactants & Detergents, Personal Care & "
    "Cosmetics, Herbicides & Agrochemicals, Cement Grinding Aids, Metalworking Fluids, Textile Chemicals, "
    "Pharmaceuticals, Water Treatment, Chemical Processing. By End-user Industry: Oil & Gas, Home & Personal Care, "
    "Agriculture, Construction, Chemical Manufacturing, Pharmaceuticals, Textile, Water & Wastewater Treatment. "
    "By Distribution Channel: Direct Sales, Indirect Sales.")
EXCLUSIONS = [
    "Distributors, traders and resellers of ethanolamines that produce none themselves",
    "Formulators that only blend ethanolamines into gas-treating solvents, detergents, cosmetics, cement additives or metalworking fluids",
    "Producers of other amines only (methylamines, ethyleneamines, isopropanolamines, fatty amines) with no ethanolamine production",
    "Ethylene oxide and ammonia suppliers that do not make ethanolamines",
    "Buyers and end users of ethanolamines (gas processors, detergent, personal care, agrochemical and cement companies)",
]
PRODUCT = "ethanolamines (MEA, DEA, TEA or MDEA)"


def build() -> dict:
    scope = (f"ONLY chemical companies that produce {PRODUCT} in their own plants (own or joint-venture capacity) "
             "and sell them under their own name. A diversified chemicals or petrochemicals group qualifies when "
             "ethanolamines are one of its own product lines, however small a share of its revenue. NOT in this "
             "market: " + "; ".join(EXCLUSIONS) + ".")
    assert len(scope) <= 900, len(scope)
    core = (f"A core player produces {PRODUCT} in its own or joint-venture plants and sells them under its own "
            "name; a diversified chemicals group qualifies when ethanolamines are one of its own product lines.")
    return {
        "source": "Client pivot (Pivot_Global Ethanolamine Market _Coherent Market Insights.xlsx), 2026-11-14; "
                  "written by profood/setup_ethanolamine_brief.py",
        "player_type": "Manufacturer",
        "market_type": "B2B",
        "market_definition": f"{DEFINITION} Segmentation: {SEGMENTATION} Exclusions: " + "; ".join(EXCLUSIONS) + ".",
        "report_definition": DEFINITION,
        "player_type_reason": ("Manufacturers: the landscape compares the companies that produce ethanolamines "
                               "(MEA, DEA, TEA, MDEA) and sell them under their own name."),
        "core_scope": core,
        "adjacent_segments": EXCLUSIONS,
        "scope": scope,
        "scope_test": "own_product_line",
        "adjacent_policy": "exclude",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    from vendor_intel.pipeline.openai_expand_checkpoint import ExpandCheckpoint
    from vendor_intel.pipeline.web_expand import default_output_dir

    out = Path(default_output_dir(MARKET, COUNTRY))
    path = out / "_pipeline" / "market_brief.json"
    if path.exists() and not args.force:
        print(f"brief kept (already there): {path}")
        return 0
    brief = build()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(brief, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    analysis = {
        "market_type": "B2B",
        "market_type_reason": "B2B: industrial, gas-processing, detergent, agrochemical and cement customers buy "
                              "ethanolamines. Set by the client's pivot for this report.",
        "market_definition": brief["market_definition"], "core_scope": brief["core_scope"],
        "adjacent_segments": brief["adjacent_segments"],
        "market_participants": [{"type": "Manufacturer", "definition": brief["core_scope"],
                                 "why_relevant": "They make the product this market is measured on."}],
        "primary_participant": "Manufacturer",
        "primary_reason": "Defined by the scope of this report.",
        "report_definition": brief["report_definition"],
        "player_type_reason": brief["player_type_reason"],
    }
    ck = (ExpandCheckpoint.load(ExpandCheckpoint.path_for(out, "all"))
          or ExpandCheckpoint.create(out, query=MARKET, country=COUNTRY, batch="all", target=300))
    if args.force or not (ck.state.get("data") or {}).get("market_analysis"):
        ck.bump("0_start", "0c_market", market_analysis=analysis, note="market brief (client pivot)")
    print(f"brief written: {path} (definition {len(brief['market_definition'])} chars, scope {len(brief['scope'])})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
