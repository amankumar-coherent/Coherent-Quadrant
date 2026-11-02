#!/usr/bin/env python3
"""Market brief (data) for the Global Electrosurgical and Allied Surgical Medical Devices Market.

    .venv/Scripts/python.exe profood/setup_electrosurgical_brief.py [--force]

Writes <market>/_pipeline/market_brief.json and Step 0c in the market's checkpoint, so discovery
asks for the right company type (device makers) from the first round. The wording comes from the
client's brief and the sample report (Research Definition and Scope; Competitive Landscape
pp.64-67). Nothing here is pipeline logic.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

MARKET = "Global Electrosurgical and Allied Surgical Medical Devices Market"
COUNTRY = "global"

DEFINITION = (
    "The Global Electrosurgical and Allied Surgical Medical Devices Market encompasses the commercial "
    "production, supply, and sale of electrosurgical units, disposable and reusable electrosurgical "
    "instruments and accessories, CO2 insufflators, and surgical smoke evacuation systems and "
    "accessories used in human and veterinary surgical procedures. Electrosurgical products use "
    "high-frequency electrical energy for tissue cutting, coagulation, and related surgical functions. "
    "Allied surgical devices support procedures by delivering controlled CO2 insufflation to establish "
    "and maintain the operative working space and by capturing and removing surgical smoke. The market "
    "includes standalone equipment, integrated systems, and associated accessories and consumables "
    "used across open and minimally invasive surgical procedures.")
SEGMENTATION = (
    "By Product Type: Electrosurgical Units (ESUs) and Accessories -- Monopolar, Bipolar, and Combined "
    "Monopolar and Bipolar Generators; Disposable and Reusable Electrosurgical Instruments and "
    "Accessories; CO2 Insufflators -- Conventional, Advanced, and Integrated CO2 Insufflation and Smoke "
    "Evacuation Systems; Surgical Smoke Evacuation Systems and Accessories -- Standalone Systems, "
    "Integrated Modules, and Disposable and Reusable Accessories. By Surgical Application: General and "
    "Abdominal Surgery, Gynecological Surgery, Gastrointestinal and Colorectal Surgery, Urological "
    "Surgery, Cardiovascular and Thoracic Surgery, Orthopedic Surgery, Neurosurgery, ENT Surgery, "
    "Plastic and Reconstructive Surgery, and Other Surgical Applications (Dermatology, Ophthalmology, "
    "and Other Specialties).")

# The client's exclusions: title + what it covers (their words, shortened to the items).
EXCLUSIONS = [
    "Non-Electrosurgical Surgical Instruments: conventional scalpels, scissors, forceps, clamps, retractors and other manual instruments without an electrosurgical function",
    "Alternative Surgical Energy Devices: standalone ultrasonic surgical systems, laser surgical systems, cryosurgical devices and microwave systems, including their dedicated instruments and accessories",
    "Standalone Thermal Cautery Devices: battery-operated or electrically heated cautery instruments that act through a heated tip rather than high-frequency current through tissue",
    "Dedicated Ablation Systems: cardiac electrophysiology, tumor ablation and pain-management systems and their specialized catheters or probes",
    "Endoscopy and Surgical Visualization Equipment: endoscopes, laparoscopes, cameras, light sources, monitors, video processors and visualization towers sold separately",
    "Robotic Surgical Platforms: robotic consoles, patient-side carts, robotic arms and general robotic instruments (separately sold electrosurgical instruments in scope remain included)",
    "General Laparoscopic Access Devices: trocars, access ports, cannulas, Veress needles, specimen retrieval bags and other access instruments without an electrosurgical or smoke evacuation function",
    "Medical CO2 and Gas Supply Infrastructure: medical-grade CO2, gas cylinders, bulk gas supply, central gas pipelines and standalone gas storage or distribution equipment",
    "Other Insufflation and Distension Equipment: non-CO2 insufflation systems, liquid distension pumps, irrigation systems and fluid-management equipment",
    "General Suction and Air Filtration Equipment: general surgical suction pumps, wall suction infrastructure, room air purifiers, HVAC and filtration equipment not designed for surgical smoke evacuation",
    "Surgical Closure and Hemostatic Products: sutures, staples, staplers, clips, tissue adhesives, sealants and topical hemostatic agents without an electrosurgical function",
    "General Operating Room Equipment: operating tables, surgical lights, anesthesia machines, patient monitors, ventilators and other equipment outside the listed categories",
    "General Surgical Consumables and Protective Products: surgical gloves, gowns, drapes, masks, dressings, syringes and other consumables unrelated to eligible devices",
    "Cleaning and Sterilization Products: instrument detergents, disinfectants, sterilization chemicals, autoclaves, washer-disinfectors and other reprocessing equipment",
    "Non-Surgical Electrical Therapy Devices: TENS units, electrical muscle stimulators, physiotherapy equipment and non-surgical aesthetic devices",
    "Standalone Device-Related Services: installation, maintenance, repair, training, consulting and reprocessing services without the commercial sale of eligible devices or accessories",
    "Surgical Procedure and Healthcare Service Revenue: surgeon fees, hospital charges, operating room fees and other procedure-related payments",
    "Intermediate Transactions and Duplicate System Revenues: component sales later incorporated into finished devices, and repeated manufacturer-distributor-end-user transactions for the same product",
]
NOT_IN = ("manual instruments with no electrosurgical function; ultrasonic, laser, cryo and microwave "
          "systems; heated-tip cautery; ablation systems; endoscopes and visualization towers; robotic "
          "platforms; trocars and access devices; medical gas supply; non-CO2 insufflation and fluid "
          "management; general suction and air filtration; sutures, staplers and hemostats; general "
          "operating-room equipment and consumables; cleaning and sterilization products; TENS and "
          "aesthetic devices; service-only businesses; distributors and resellers")
PRODUCTS = ("electrosurgical units (monopolar, bipolar or combined generators), disposable or reusable "
            "electrosurgical instruments and accessories, CO2 insufflators, or surgical smoke "
            "evacuation systems and their accessories")


def build() -> dict:
    scope = (f"ONLY companies that make and sell under their own name {PRODUCTS}. Diversified medical "
             f"device groups qualify when this is one of their own product lines. NOT in this market: "
             f"{NOT_IN}.")
    assert len(scope) <= 900, len(scope)
    core = (f"A core player makes and sells under its own name {PRODUCTS}; diversified medical device "
            "groups qualify when this is one of their own product or business lines.")
    return {
        "source": "Client brief + sample report (owner 2026-10-30): Report_Sample_Global_Electrosurgical "
                  "And Allied Surgical Medical Devices Market_Coherent_Market_Insights.pdf, Competitive "
                  "Landscape pp.64-67; written by profood/setup_electrosurgical_brief.py",
        "player_type": "Manufacturer",
        "market_type": "B2B",
        "market_definition": f"{DEFINITION} Segmentation: {SEGMENTATION} Exclusions: "
                             + "; ".join(e.split(":")[0] for e in EXCLUSIONS) + ".",
        "report_definition": (
            "The Global Electrosurgical and Allied Surgical Medical Devices Market covers the production "
            "and sale of electrosurgical units and their instruments and accessories, CO2 insufflators, "
            "and surgical smoke evacuation systems used in human and veterinary surgery. It spans "
            "standalone equipment, integrated systems and the consumables used with them across open and "
            "minimally invasive procedures."),
        "player_type_reason": (
            "Manufacturers: the landscape compares the companies that make and sell electrosurgical "
            "generators, instruments and accessories, CO2 insufflators and smoke evacuation systems "
            "under their own name."),
        "core_scope": core,
        "adjacent_segments": EXCLUSIONS + ["Distributors, traders and resellers that make nothing of their own",
                                           "Buyers and users of these devices (hospitals, clinics, surgery centres)"],
        "scope": scope,
        "scope_test": "own_product_line",
        "adjacent_policy": "exclude",
        "chart_selection": "top_overall",
        "focus_areas": ["United States", "Germany", "Japan", "China", "India", "Italy", "Turkey",
                        "Brazil", "United Kingdom", "France", "Switzerland", "South Korea", "Poland"],
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
        "market_type_reason": "B2B: hospitals, surgery centres and veterinary practices buy these devices. "
                              "Set by the client brief.",
        "market_definition": brief["market_definition"], "core_scope": brief["core_scope"],
        "adjacent_segments": brief["adjacent_segments"],
        # ONE player type for this market (owner's rule): every company is found and verified
        # as this single role, never a mix of categories.
        "market_participants": [{"type": brief["player_type"], "definition": brief["core_scope"],
                                 "why_relevant": "They make the devices this market is measured on."}],
        "primary_participant": brief["player_type"],
        "primary_reason": "Defined by the scope of this report.",
        "report_definition": brief["report_definition"],
        "player_type_reason": brief["player_type_reason"],
    }
    ck = (ExpandCheckpoint.load(ExpandCheckpoint.path_for(out, "all"))
          or ExpandCheckpoint.create(out, query=MARKET, country=COUNTRY, batch="all", target=400))
    if args.force or not (ck.state.get("data") or {}).get("market_analysis"):
        ck.bump("0_start", "0c_market", market_analysis=analysis, note="market brief (client brief)")
    print(f"brief written: {path} (scope {len(brief['scope'])} chars, {len(EXCLUSIONS)} exclusions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
