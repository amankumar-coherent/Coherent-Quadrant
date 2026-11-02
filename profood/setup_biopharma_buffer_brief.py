#!/usr/bin/env python3
"""Market brief (data) for the Global Biopharma Buffer Market, from the client's brief.

    .venv\\Scripts\\python.exe profood\\setup_biopharma_buffer_brief.py [--force]

Writes ``<market>/_pipeline/market_brief.json`` (definition, scope, the client's
exclusions, player type) and Step 0c in the market's checkpoint, so discovery asks
for the right company type from the first round. The wording comes from
queries/global_biopharma_buffer_market_brief.md; nothing here is pipeline logic.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

MARKET = "Global Biopharma Buffer Market"
COUNTRY = "global"

DEFINITION = (
    "The Global Biopharma Buffer Market encompasses the commercial production, supply, and sale of specialized "
    "buffering agents, buffer salts, pre-formulated buffer mixtures, buffer concentrates, and ready-to-use buffer "
    "solutions used in the development and manufacturing of biopharmaceutical products. These buffers are designed "
    "to maintain controlled pH conditions, support protein stability, and regulate critical physicochemical "
    "parameters during upstream processing, downstream purification, and biopharmaceutical formulation. They are "
    "used across manufacturing processes involving monoclonal antibodies, recombinant proteins, vaccines, "
    "antibody-drug conjugates, cell and gene therapies, and other biological therapeutics.")
SEGMENTATION = (
    "By Product Type: Customized / Application-Specific Buffers, Ready-to-Use (RTU) Buffers, Buffer Concentrates; "
    "By Buffer Type: Phosphate Buffers, Tris Buffers, Acetate Buffers, HEPES Buffers, Others (Citrate Buffers, "
    "MES Buffers, etc.). Further segmentation (client's report sample, same products): By Application: Upstream "
    "Processing, Downstream Processing, Final Formulation; By pH Range: Acidic, Neutral, Alkaline Buffers; By "
    "Biologic Type: Monoclonal Antibodies, Vaccines, Gene Therapy / Viral Vectors, Other Recombinant Proteins "
    "(Enzymes, etc.); By Delivery Format: Powder buffers, Liquid buffers; By End User: Large Biopharma Companies, "
    "CDMOs, Biotech Startups, Academic & Research Institutes.")

# The client's exclusions: title + what it covers (their words, shortened to the list of items).
EXCLUSIONS = [
    "Cell Culture Media & Feeds: basal media, chemically defined media, serum-free media, nutrient feeds, complete culture media, including those containing buffering ingredients",
    "Water for Injection & Purified Water: standalone WFI, purified water, sterile water and other water products used for buffer preparation or biopharmaceutical manufacturing",
    "Standalone pH-Adjustment Chemicals: hydrochloric acid, sodium hydroxide, potassium hydroxide and other acids or bases used exclusively for pH adjustment rather than buffering",
    "Non-Buffer Process Salts & Chemicals: sodium chloride, potassium chloride and other chemicals used solely for ionic strength adjustment, conductivity control or unrelated processing functions",
    "Cleaning & Sanitization Chemicals: CIP and COP chemicals, detergents, sanitizers, caustic cleaning agents, sterilization chemicals",
    "Chromatography Resins & Columns: Protein A resins, ion-exchange resins, chromatography membranes, prepacked columns and chromatography equipment",
    "Filtration & Separation Consumables: ultrafiltration and diafiltration membranes, depth filters, sterilizing filters, filtration cartridges and associated consumables",
    "Buffer Preparation & Management Equipment: mixing tanks, buffer preparation skids, inline dilution systems, automated buffer blending systems, buffer management equipment",
    "Single-Use Equipment & Empty Containers: empty single-use bags, mixing bags, tubing assemblies, connectors, bottles and fluid-transfer systems sold separately from buffer formulations",
    "Analytical & Calibration Buffers: pH calibration standards, reference buffer solutions, analytical chromatography mobile phases, buffers used exclusively for instrument calibration or analytical testing",
    "Molecular Biology & Diagnostic Reagents: PCR buffers, ELISA assay buffers, electrophoresis buffers, diagnostic-kit buffers and other laboratory reagents unrelated to biopharmaceutical manufacturing",
    "Non-Buffer Formulation Excipients: sugars, surfactants, antioxidants, preservatives, bulking agents and stabilizers sold separately without a buffering function",
    "Finished Biopharmaceutical Products: monoclonal antibodies, vaccines, recombinant proteins, antibody-drug conjugates, cell therapies, gene therapies and other finished biological medicines",
    "Non-Biopharmaceutical Buffer Applications: buffers used in food processing, cosmetics, agriculture, environmental testing, conventional chemical manufacturing and other non-biopharmaceutical industries",
    "Standalone Buffer-Related Services: buffer-development consulting, equipment installation, maintenance, qualification and preparation-only services without the commercial sale of eligible buffer products",
    "Internal Buffer Preparation & Intermediate Transactions: internally generated buffer preparation value and intermediate sales of buffering ingredients later incorporated into finished buffer products (double counting)",
]
# Short names for the scope text (the checker reads at most 900 characters).
NOT_IN = ("cell culture media / feeds; water (WFI, purified); pH-adjustment acids and bases; non-buffer process "
          "salts; cleaning / sanitization chemicals; chromatography resins and columns; filters and filtration "
          "consumables; buffer preparation equipment; empty single-use bags, tubing, containers; analytical / "
          "calibration buffers; molecular biology and diagnostic reagents; non-buffer excipients; finished "
          "biologics; non-biopharma buffers; buffer services only; distributors, traders, resellers; buyers of buffers")
PRODUCTS = ("customized / application-specific buffers, ready-to-use (RTU) buffers, buffer concentrates, buffer "
            "salts and pre-formulated buffer mixtures (phosphate, Tris, acetate, HEPES, citrate, MES, other) for "
            "biopharmaceutical manufacturing")


def build() -> dict:
    scope = (f"ONLY companies that make and sell under their own name {PRODUCTS}. Diversified groups qualify when "
             f"this is one of their own product lines. NOT in this market: {NOT_IN}.")
    assert len(scope) <= 900, len(scope)
    core = (f"A core player makes and sells under its own name {PRODUCTS}; diversified groups qualify when this is "
            "one of their own product or business lines.")
    return {
        "source": "Client brief + report sample (owner 2026-10-28): queries/global_biopharma_buffer_market_brief.md; "
                  "written by profood/setup_biopharma_buffer_brief.py",
        "player_type": "Manufacturer",
        "market_type": "B2B",
        "market_definition": f"{DEFINITION} Segmentation: {SEGMENTATION} Exclusions: "
                             + "; ".join(e.split(":")[0] for e in EXCLUSIONS) + ".",
        "core_scope": core,
        "adjacent_segments": EXCLUSIONS + ["Distributors, traders and resellers", "Buyers / users of these products"],
        "scope": scope,
        "scope_test": "own_product_line",
        "adjacent_policy": "exclude",
        "chart_selection": "top_overall",
        "focus_areas": ["United States", "Germany", "United Kingdom", "Switzerland", "France", "China", "India",
                        "Japan", "South Korea", "Singapore", "Ireland", "Belgium", "Netherlands"],
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
        "market_type_reason": "B2B: set by the client brief for this report.",
        "market_definition": brief["market_definition"], "core_scope": brief["core_scope"],
        "adjacent_segments": brief["adjacent_segments"],
        "market_participants": [{"type": "Manufacturer", "definition": brief["core_scope"],
                                 "why_relevant": "They supply what this market is measured on."}],
        "primary_participant": "Manufacturer",
        "primary_reason": "Defined by the scope of this report.",
    }
    ck = (ExpandCheckpoint.load(ExpandCheckpoint.path_for(out, "all"))
          or ExpandCheckpoint.create(out, query=MARKET, country=COUNTRY, batch="all", target=300))
    if args.force or not (ck.state.get("data") or {}).get("market_analysis"):
        ck.bump("0_start", "0c_market", market_analysis=analysis, note="market brief (client brief)")
    print(f"brief written: {path} (scope {len(brief['scope'])} chars, {len(EXCLUSIONS)} exclusions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
