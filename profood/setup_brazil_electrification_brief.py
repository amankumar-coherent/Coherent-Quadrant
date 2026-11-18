#!/usr/bin/env python3
r"""Market brief (data) for the Brazil Industrial Electrification Market, from the client's market definition
and its inclusion / exclusion table by segmentation (sent by the owner 2026-11-18), the client's taxonomy and
the sample report "Report Sample_Brazil Industrial Electrification Market_2026-2033_CMI.pdf".

    .venv\Scripts\python.exe profood\setup_brazil_electrification_brief.py [--force]

Writes ``<market>/_pipeline/market_brief.json`` and Step 0c in the market's checkpoint. Nothing here is
pipeline logic; the client's named manufacturers are in
queries/seeds/brazil_industrial_electrification_market_brazil.txt.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

MARKET = "Brazil Industrial Electrification Market"
COUNTRY = "brazil"

DEFINITION = (
    "The Brazil Industrial Electrification Market encompasses hardware, software, and services used to electrify "
    "industrial processes, machinery, material handling equipment, and electrical power distribution infrastructure "
    "across Brazil. The market includes electric heating and steam generation systems, industrial motors and drives, "
    "electrified industrial machinery, electrical distribution and control equipment, energy management software, "
    "and associated engineering, installation, retrofit, and maintenance services. It covers both greenfield and "
    "brownfield industrial electrification projects across manufacturing, mining, oil and gas, chemicals, and other "
    "industrial sectors.")
REPORT_DEFINITION = (
    "The Brazil Industrial Electrification Market encompasses hardware, software, and services used to electrify "
    "industrial processes, machinery, material handling equipment, and electrical power distribution infrastructure "
    "across Brazil, in greenfield and brownfield projects.")
INCLUSION = (
    "Hardware: industrial electric heating equipment (electric boilers and steam generation systems, industrial heat "
    "pumps, electric furnaces and process heating systems); electrified industrial machinery and equipment (electric "
    "excavators, wheel loaders, forklifts, mining trucks and material handling equipment); industrial electric motors "
    "and drive systems; industrial electrical devices and power distribution equipment (electric actuators, "
    "switchgear, power distribution units, transformers and substations, electrical cables and connection equipment). "
    "Software: industrial energy management and optimization software; industrial electrical monitoring and control "
    "software; other industrial electrification software. Services: industrial electrification consulting and "
    "engineering; installation, integration and retrofit; operation and maintenance; equipment leasing and rental; "
    "electrification-as-a-service and dedicated renewable electricity supply for industrial electrification. "
    "Applications: process heating and steam generation; mechanical drives and motion control; material handling and "
    "transportation; electrical power distribution and management; industrial HVAC. Deployment: greenfield and "
    "brownfield (retrofit) projects. End-use: chemicals and petrochemicals, mining, food and beverages, pulp and "
    "paper, oil and gas, automotive manufacturing, construction, logistics and warehousing, textiles, "
    "pharmaceuticals, electronics, water and wastewater. Sales channels: online and offline (direct, dealers and "
    "distributors, system integrators, EPC contractors).")
EXCLUSIONS = [
    "Makers of conventional fossil-fuel-fired boilers, furnaces and steam systems without electric heating",
    "Makers of diesel or combustion-engine excavators, loaders, forklifts and machinery only",
    "Makers of mechanical, pneumatic or hydraulic drives without electric motors or drives",
    "Makers of residential or commercial electrical, HVAC or smart-home products only",
    "General ERP, accounting, business or consumer energy software vendors",
    "General consultancies without industrial electrification work",
    "Electricity retailers, utilities and standalone renewable power generators without dedicated industrial "
    "electrification supply",
    "Distributors, dealers and resellers that make no equipment",
    "Industrial end users that only buy electrification equipment",
]
PRODUCT = ("industrial electrification hardware or software (electric heating and steam systems, industrial heat "
           "pumps, electric furnaces, electric motors and drives, electrified machinery and forklifts, switchgear, "
           "transformers, power distribution and control equipment, industrial energy management or electrical "
           "control software)")
WHERE = ("incorporated and run in Brazil (a Brazilian company owned by a foreign group qualifies; a foreign "
         "company's branch, sales office or distributor does not)")


def build() -> dict:
    # MARKET_SCOPE is cut at 900 characters (chatgpt_expand), so the scope names the exclusions briefly.
    scope = ("ONLY companies incorporated and run in Brazil (foreign-owned Brazilian companies qualify) that make "
             "industrial electrification hardware or software under their own name: electric boilers, heat pumps, "
             "furnaces and process heating; electric motors and drives; electrified machinery, forklifts and "
             "mining trucks; switchgear, transformers, power distribution and control equipment; industrial "
             "energy management or electrical control software. Diversified groups qualify when this is one of "
             "their own product lines. NOT in this market: makers of fossil-fuel, diesel, hydraulic or only "
             "residential/commercial equipment; general ERP or consumer software; general consultancies; "
             "utilities, electricity retailers and standalone power generators; distributors and resellers; end users.")
    assert len(scope) <= 900, len(scope)
    core = (f"A core player is {WHERE} and makes {PRODUCT} under its own name; a diversified electrical, "
            "industrial or machinery group qualifies when this is one of its own product lines. Engineering, "
            "installation, maintenance, leasing and electrification-as-a-service companies are part of the market "
            "but a different player type.")
    return {
        "source": "Client market definition and inclusion / exclusion table (owner 2026-11-18), client taxonomy and "
                  "sample report; written by profood/setup_brazil_electrification_brief.py",
        "player_type": "Manufacturer",
        "market_type": "B2B",
        "market_definition": (f"{DEFINITION} Inclusion: {INCLUSION} Exclusions: " + "; ".join(EXCLUSIONS)
                              + f". Geography: Brazil -- companies {WHERE}."),
        "report_definition": REPORT_DEFINITION,
        "player_type_reason": ("Manufacturers: the landscape compares the companies that make industrial "
                               "electrification equipment and software in Brazil and sell it under their own name."),
        "core_scope": core,
        "adjacent_segments": EXCLUSIONS + [
            "Industrial electrification engineering, installation, retrofit and maintenance service companies",
            "Equipment leasing and rental, electrification-as-a-service and dedicated renewable electricity "
            "supply companies"],
        "scope": scope,
        "scope_test": "own_product_line",
        # No "adjacent_policy": "exclude": the client's sample names energy-solution and service companies,
        # so a company the scope check calls adjacent stays in Other Noticeable Players (never on the chart).
        "focus_areas": [],
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
        "market_type_reason": "B2B: industrial companies in chemicals, mining, food, pulp and paper, oil and gas, "
                              "automotive and other sectors buy industrial electrification equipment. Set by the "
                              "client's definition.",
        "market_definition": brief["market_definition"], "core_scope": brief["core_scope"],
        "adjacent_segments": brief["adjacent_segments"],
        "market_participants": [{"type": "Manufacturer", "definition": brief["core_scope"],
                                 "why_relevant": "They make the equipment and software this market is measured on."}],
        "primary_participant": "Manufacturer",
        "primary_reason": "Defined by the scope of this report.",
        "report_definition": brief["report_definition"],
        "player_type_reason": brief["player_type_reason"],
    }
    ck = (ExpandCheckpoint.load(ExpandCheckpoint.path_for(out, "all"))
          or ExpandCheckpoint.create(out, query=MARKET, country=COUNTRY, batch="all", target=400))
    if args.force or not (ck.state.get("data") or {}).get("market_analysis"):
        ck.bump("0_start", "0c_market", market_analysis=analysis, note="market brief (client definition)")
    print(f"brief written: {path} (definition {len(brief['market_definition'])} chars, scope {len(brief['scope'])})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
