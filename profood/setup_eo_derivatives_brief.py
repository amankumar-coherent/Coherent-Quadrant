#!/usr/bin/env python3
r"""Market brief (data) for the Global Ethylene Oxide Derivatives Market, from the client's pivot
("Pivot_Global Ethylene Oxide Derivatives Market _Coherent Market Insights.xlsx": product types, functions,
end-use industries, feedstock, channels) and the client's vendor list (Section 6 real-time insights).

    .venv\Scripts\python.exe profood\setup_eo_derivatives_brief.py [--force]

Writes ``<market>/_pipeline/market_brief.json`` and Step 0c in the market's checkpoint. Nothing here is
pipeline logic; the client's named vendors are in queries/seeds/global_ethylene_oxide_derivatives_market_global.txt.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

MARKET = "Global Ethylene Oxide Derivatives Market"
COUNTRY = "global"

DEFINITION = (
    "The Global Ethylene Oxide Derivatives Market covers the production and sale of chemicals made from ethylene "
    "oxide: ethoxylates (alcohol, fatty acid, fatty amine, alkylphenol and other ethoxylates), ethylene glycols "
    "(MEG, DEG, TEG), polyethylene glycols, polyether polyols, ethylene oxide sterilants (pure or blended with CO2 "
    "or nitrogen), polyethylene oxide, ethylene carbonate and other EO derivatives, from ethylene-based and "
    "bio-ethylene feedstock.")
SEGMENTATION = (
    "By Product Type: Ethoxylates (Alcohol, Fatty Acid, Fatty Amine, Alkylphenol, Other), Ethylene Glycols, "
    "Polyethylene Glycols, Polyether Polyols, Ethylene Oxide Sterilants, Polyethylene Oxide, Ethylene Carbonate, "
    "Other EO Derivatives. By Function: Surfactants, Solvents, Chemical Intermediates, Humectants, Emulsifiers, "
    "Dispersants, Wetting Agents, Defoamers, Plasticizers, Corrosion Inhibitors, Gas Treatment Chemicals, "
    "Antifreeze & Coolants, Sterilizing Agents. By End-use Industry: Home Care, Personal Care & Cosmetics, "
    "Pharmaceuticals & Healthcare, Agrochemicals, Paints Coatings & Inks, Oil & Gas, Textile & Leather, Automotive, "
    "Construction, Chemical Manufacturing, Packaging, Food & Beverage Processing, Electronics, Pulp & Paper, Water "
    "Treatment. By Feedstock: Ethylene-Based, Bio-Ethylene Based. By Sales Channel: Direct, Indirect.")
EXCLUSIONS = [
    "Distributors, traders and resellers that produce no EO derivative themselves",
    "Formulators that only blend bought-in EO derivatives into finished goods",
    "Buyers and end users of EO derivatives",
    "Sterilization service providers that only run EO sterilization of devices without supplying the sterilant",
    "Ethylene and ethylene oxide producers that sell no derivative",
]
PRODUCT = ("ethylene oxide derivatives (ethoxylates, ethylene glycols, polyethylene glycols, polyether polyols, EO "
           "sterilant gas, polyethylene oxide, ethylene carbonate or other EO derivatives)")


def build() -> dict:
    scope = (f"ONLY companies that produce one or more {PRODUCT} in their own or joint-venture plants and sell them "
             "under their own name. A diversified chemicals, petrochemicals or industrial-gas group qualifies when "
             "an EO derivative is one of its own product lines. NOT in this market: " + "; ".join(EXCLUSIONS) + ".")
    assert len(scope) <= 900, len(scope)
    core = (f"A core player produces one or more {PRODUCT} in its own or joint-venture plants and sells them under "
            "its own name; a diversified chemicals or industrial-gas group qualifies when an EO derivative is one "
            "of its own product lines.")
    return {
        "source": "Client pivot (Pivot_Global Ethylene Oxide Derivatives Market _Coherent Market Insights.xlsx) and "
                  "the client's Section 6 vendor list, 2026-11-15; written by profood/setup_eo_derivatives_brief.py",
        "player_type": "Manufacturer",
        "market_type": "B2B",
        "market_definition": f"{DEFINITION} Segmentation: {SEGMENTATION} Exclusions: " + "; ".join(EXCLUSIONS) + ".",
        "report_definition": DEFINITION,
        "player_type_reason": ("Manufacturers: the landscape compares the companies that produce ethylene oxide "
                               "derivatives and sell them under their own name."),
        "core_scope": core,
        "adjacent_segments": EXCLUSIONS,
        "scope": scope,
        "scope_test": "own_product_line",
        # No "adjacent_policy": "exclude": the client's vendor list names laboratory suppliers and gas
        # companies, so a company the scope check calls adjacent stays in Other Noticeable Players
        # (never on the chart) instead of disappearing from the report.
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
        "market_type_reason": "B2B: detergent, personal care, pharmaceutical, polyurethane, polyester, agrochemical "
                              "and healthcare manufacturers buy EO derivatives. Set by the client's pivot.",
        "market_definition": brief["market_definition"], "core_scope": brief["core_scope"],
        "adjacent_segments": brief["adjacent_segments"],
        "market_participants": [{"type": "Manufacturer", "definition": brief["core_scope"],
                                 "why_relevant": "They make the products this market is measured on."}],
        "primary_participant": "Manufacturer",
        "primary_reason": "Defined by the scope of this report.",
        "report_definition": brief["report_definition"],
        "player_type_reason": brief["player_type_reason"],
    }
    ck = (ExpandCheckpoint.load(ExpandCheckpoint.path_for(out, "all"))
          or ExpandCheckpoint.create(out, query=MARKET, country=COUNTRY, batch="all", target=400))
    if args.force or not (ck.state.get("data") or {}).get("market_analysis"):
        ck.bump("0_start", "0c_market", market_analysis=analysis, note="market brief (client pivot)")
    print(f"brief written: {path} (definition {len(brief['market_definition'])} chars, scope {len(brief['scope'])})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
