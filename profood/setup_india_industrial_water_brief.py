#!/usr/bin/env python3
"""Market brief (data) for the India Industrial Water & Wastewater Market.

    .venv/Scripts/python.exe profood/setup_india_industrial_water_brief.py [--force]

Writes <market>/_pipeline/market_brief.json and Step 0c in the market's checkpoint, so
discovery asks for the right company type from the first round. Every word of the definition,
the inclusions and the exclusions is the client's (owner 2026-11-02). Nothing here is pipeline
logic: the exclusions become adjacent_segments, and adjacent_policy "exclude" keeps a company
of an excluded type out of the report entirely rather than in Other Noticeable Players.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

MARKET = "Industrial Water and Wastewater Market"
COUNTRY = "india"

DEFINITION = (
    "The India Industrial Water & Wastewater Market comprises revenue generated through the design, "
    "engineering, supply, installation, modernization, operation, maintenance and lifecycle management "
    "of water and wastewater treatment systems serving industrial facilities in India. It covers "
    "industrial process water, high-purity water, boiler feedwater, cooling water, effluent treatment, "
    "water reuse and recycling, desalination, zero liquid discharge (ZLD), brine management, sludge "
    "treatment and other specialized industrial water treatment applications.")

INCLUSIONS = [
    "Greenfield industrial water and wastewater treatment projects",
    "Brownfield expansion, modernization and retrofit projects",
    "Industrial water and wastewater treatment equipment and technology supply",
    "Raw water, process water and high-purity water treatment",
    "Industrial effluent and wastewater treatment",
    "Water reuse, recycling and desalination",
    "Zero liquid discharge (ZLD), brine and sludge management",
    "Cooling water and boiler water treatment",
    "Operations and maintenance (O&M) services",
    "Aftermarket spare parts, consumables, repair and refurbishment",
    "Process optimization, digital monitoring and lifecycle services",
    "Common Effluent Treatment Plants (CETPs) and shared industrial water infrastructure",
    "EPC, EPCM, DBO, BOO and other relevant project and service contracts",
]

# The client's exclusions, their words.
EXCLUSIONS = [
    "Municipal and urban water or wastewater treatment unrelated to industrial facilities",
    "Residential and domestic water treatment",
    "Agricultural irrigation and rural water infrastructure",
    "Water treatment for commercial buildings, offices and hospitality facilities",
    "Bottled-water sales and packaged drinking water distribution unrelated to industrial treatment",
    "Bulk water trading, tanker supply and raw water distribution without treatment",
    "General industrial plant construction and infrastructure not directly attributable to water or "
    "wastewater treatment",
    "Standalone chemical sales and consumables unrelated to treatment operations or services",
    "Regulatory penalties and environmental fines",
    "Duplicate counting of integrated project, equipment and recurring O&M revenues",
]

SEGMENTATION = (
    "By Industrial Sector: Chemicals and Specialty Chemicals; Pharmaceuticals and Biotechnology; Oil "
    "Refining and Petrochemicals; Power Generation; Iron, Steel and Other Metals; Textiles and Apparel "
    "Processing; Food and Beverage Processing; Pulp and Paper; Automotive and Auto Components; "
    "Electronics and Semiconductor Manufacturing; Cement and Building Materials; Mining and Mineral "
    "Processing; Other Industrial Sectors. By Treatment Solution: Raw Water and Process Water Treatment; "
    "Demineralized and High-Purity Water Treatment; Industrial Wastewater and Effluent Treatment; "
    "Industrial Water Reuse and Recycling; Industrial Desalination; Zero Liquid Discharge and Brine "
    "Management; Sludge Treatment and Residuals Management; Cooling Water Treatment and Boiler Water "
    "Conditioning. By Revenue Stream: New Installation and Greenfield Projects; Brownfield Expansion, "
    "Modernization and Retrofit; Standalone Equipment and Technology Sales; Operations and Maintenance "
    "Services; Aftermarket Spare Parts and Consumables; Repair, Refurbishment and Lifecycle Technical "
    "Services; Digital Monitoring and Optimization Services. By Treatment Plant Capacity: below 1 MLD; "
    "1 to below 10 MLD; 10 to below 50 MLD; 50 MLD and above. By Geographic Coverage: North, South, "
    "East, West, Central and Northeast India.")

SOLUTIONS = ("industrial water and wastewater treatment systems -- process water, high-purity and "
             "demineralized water, boiler feedwater, cooling water, effluent treatment, water reuse and "
             "recycling, desalination, zero liquid discharge, brine and sludge management -- which it "
             "designs, engineers, supplies, installs, modernizes, operates or maintains for industrial "
             "facilities in India")
NOT_IN = ("municipal or urban water and sewage treatment unrelated to industrial facilities; residential "
          "and domestic water treatment; agricultural irrigation and rural water; water treatment for "
          "commercial buildings, offices and hospitality; bottled and packaged drinking water; bulk water "
          "trading, tanker supply and untreated raw water distribution; general plant construction not "
          "attributable to water treatment; standalone chemical or consumable sales unrelated to treatment "
          "operations; pure consultancies and design-only advisers; distributors and resellers; and the "
          "industrial facilities that BUY treatment rather than provide it")


# The same inclusions and exclusions, as short phrases, for the definition every query carries.
INCLUSIONS_SHORT = (
    "greenfield and brownfield treatment projects; equipment and technology supply; raw, process and "
    "high-purity water; effluent treatment; reuse, recycling and desalination; ZLD, brine and sludge "
    "management; cooling and boiler water; O&M services; aftermarket parts, repair and refurbishment; "
    "digital monitoring and lifecycle services; CETPs and shared industrial water infrastructure; "
    "EPC, EPCM, DBO and BOO contracts.")
EXCLUSIONS_SHORT = (
    "municipal and urban water unrelated to industry; residential and domestic treatment; agricultural "
    "irrigation and rural water; commercial buildings, offices and hospitality; bottled and packaged "
    "drinking water; bulk water trading and tanker supply without treatment; general plant construction "
    "not attributable to water treatment; standalone chemical and consumable sales unrelated to "
    "treatment; regulatory penalties and fines; duplicate counting of project, equipment and O&M "
    "revenue.")

# The verify criteria go into an AI Mode search URL, so `scope` has its own, shorter wording;
# `core_scope` below carries the full test for the scope check.
SCOPE_SHORT = ("industrial water and wastewater treatment systems (process, high-purity, boiler and "
               "cooling water, effluent treatment, reuse and recycling, desalination, zero liquid "
               "discharge, brine and sludge management) that it designs, supplies, installs, operates "
               "or maintains for industrial facilities in India")
NOT_IN_SHORT = ("municipal, residential, agricultural, commercial-building or packaged drinking water; "
                "bulk water trading and tanker supply; general plant construction; standalone chemical "
                "sales; pure consultancies; distributors and resellers; and the industrial facilities "
                "that BUY treatment rather than provide it")


def build() -> dict:
    scope = (f"ONLY companies that provide, under their own name, {SCOPE_SHORT}. Diversified engineering "
             f"groups qualify when this is one of their own business lines. NOT in this market: "
             f"{NOT_IN_SHORT}.")
    assert len(scope) <= 900, len(scope)
    core = (f"A core player provides, under its own name, {SOLUTIONS}; diversified engineering groups "
            "qualify when industrial water and wastewater treatment is one of their own business lines.")
    return {
        "source": "Client brief (owner 2026-11-02): market definition, key inclusions, key exclusions and "
                  "the 12 segmentation parameters, pasted in chat; written by "
                  "profood/setup_india_industrial_water_brief.py",
        # ONE player type for this market (owner's rule). The market is measured on the design,
        # supply, installation AND operation of treatment systems, so the single role is the company
        # that delivers the system, not a separate equipment / EPC / O&M split.
        "player_type": "Solution Provider",
        "market_type": "B2B",
        # The definition is pasted into EVERY AI Mode query (status, scope, ownership, evidence),
        # and the query is sent as a search URL. At 3,400 characters -- the client's inclusions and
        # all 12 segmentation parameters in full -- the URL grew past what Google answers reliably
        # with 20 browsers running and Page.goto timed out, killing step 3b (owner 2026-11-03).
        # Finished markets sit at 1,700-2,400, so the inclusions and exclusions go in as short
        # phrases and the full segmentation stays in `segmentation` below, which no query reads.
        "market_definition": f"{DEFINITION} Inclusions: {INCLUSIONS_SHORT} Exclusions: {EXCLUSIONS_SHORT}",
        "segmentation": SEGMENTATION,
        "report_definition": (
            "The India Industrial Water & Wastewater Market covers the design, engineering, supply, "
            "installation, modernization, operation and lifecycle management of water and wastewater "
            "treatment systems for industrial facilities in India. It spans process, high-purity, boiler "
            "and cooling water, effluent treatment, reuse and recycling, desalination, zero liquid "
            "discharge, and brine and sludge management."),
        "player_type_reason": (
            "Solution Providers: the landscape compares the companies that design, engineer, supply, "
            "install and operate industrial water and wastewater treatment systems in India under their "
            "own name, including their equipment, O&M and lifecycle services."),
        "core_scope": core,
        "adjacent_segments": EXCLUSIONS + [
            "Pure consultancies, design-only advisers and project management firms that build nothing",
            "Distributors, traders and resellers of other companies' treatment equipment",
            "Industrial facilities that buy or operate treatment only for their own plants",
        ],
        "scope": scope,
        "scope_test": "own_product_line",
        # The owner asked that no company of an excluded type appear at all, so an adjacent
        # company is left out of the report rather than kept in Other Noticeable Players.
        "adjacent_policy": "exclude",
        "focus_areas": ["Maharashtra", "Gujarat", "Tamil Nadu", "Karnataka", "Uttar Pradesh", "Telangana",
                        "Andhra Pradesh", "Haryana", "Delhi NCR", "West Bengal", "Rajasthan", "Punjab",
                        "Madhya Pradesh", "Odisha", "Kerala", "Chhattisgarh", "Jharkhand", "Bihar",
                        "Uttarakhand", "Himachal Pradesh", "Assam", "Goa"],
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
        "market_type": brief["market_type"],
        "market_type_reason": "B2B: industrial facilities, public sector enterprises and industrial estate "
                              "operators buy these systems and services. Set by the client brief.",
        "market_definition": brief["market_definition"], "core_scope": brief["core_scope"],
        "adjacent_segments": brief["adjacent_segments"],
        "market_participants": [{"type": brief["player_type"], "definition": brief["core_scope"],
                                 "why_relevant": "They provide the treatment systems and services this "
                                                 "market is measured on."}],
        "primary_participant": brief["player_type"],
        "primary_reason": "Defined by the scope of this report.",
        "report_definition": brief["report_definition"],
        "player_type_reason": brief["player_type_reason"],
    }
    ck = (ExpandCheckpoint.load(ExpandCheckpoint.path_for(out, "all"))
          or ExpandCheckpoint.create(out, query=MARKET, country=COUNTRY, batch="all", target=400))
    if args.force or not (ck.state.get("data") or {}).get("market_analysis"):
        ck.bump("0_start", "0c_market", market_analysis=analysis, note="market brief (client brief)")
    print(f"brief written: {path} (scope {len(brief['scope'])} chars, {len(EXCLUSIONS)} exclusions, "
          f"{len(INCLUSIONS)} inclusions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
