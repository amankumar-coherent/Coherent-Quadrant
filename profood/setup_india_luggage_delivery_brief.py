#!/usr/bin/env python3
"""Market brief (data) for the India Luggage Delivery Service Market.

    .venv/Scripts/python.exe profood/setup_india_luggage_delivery_brief.py [--force]

Writes <market>/_pipeline/market_brief.json and Step 0c in the market's checkpoint, so
discovery asks for the right company type from the first round. Every word of the definition,
the inclusions and the exclusions is the client's (owner 2026-11-05). Nothing here is pipeline
logic: the exclusions become adjacent_segments, and adjacent_policy "exclude" keeps a company
of an excluded type out of the report entirely rather than in Other Noticeable Players.

The definition every AI Mode query carries is kept near 1,500 characters: at 3,400 the search
URL overflowed and the queries were truncated, which cost a whole run (owner 2026-11-03).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

MARKET = "Luggage Delivery Service Market"
COUNTRY = "india"

DEFINITION = (
    "The India Luggage Delivery Service Market comprises paid logistics services that collect, "
    "transport and deliver travellers' personal luggage, suitcases, excess baggage, sports equipment, "
    "student belongings and business travel baggage between specified locations within India or "
    "between India and international destinations. It covers luggage delivery through road, air, rail "
    "and multimodal transport, including doorstep pickup, airport transfers, railway station transfers "
    "and customised delivery arrangements.")

INCLUSIONS = [
    "Paid door-to-door luggage pickup and delivery services",
    "Airport-to-home, airport-to-hotel and hotel-to-airport luggage transfers",
    "Railway station-related luggage collection and delivery",
    "Domestic and international luggage shipping involving India",
    "Student, corporate, sports and excess baggage delivery",
    "Road, air, rail and multimodal luggage transportation",
    "Standard and customised luggage delivery services",
    "Online and offline luggage delivery bookings",
]
EXCLUSIONS = [
    "Regular airline checked baggage included in passenger tickets",
    "Standard airline excess baggage fees without a separate delivery service",
    "Personal luggage carried directly by passengers without a separate delivery service",
    "International luggage deliveries with no Indian pickup or delivery point",
    "Commercial freight, bulk industrial cargo and regular e-commerce parcel deliveries",
    "Passenger transportation, airline tickets and railway tickets",
    "Standalone luggage storage, packaging and insurance services",
    "Household relocation services covering furniture, appliances and complete household moves",
]

# Short phrases for the definition every query carries (the full lists stay in the brief).
INCLUSIONS_SHORT = (
    "door-to-door luggage pickup and delivery; airport-to-home, airport-to-hotel and hotel-to-airport "
    "transfers; railway station luggage collection and delivery; domestic and international luggage "
    "shipping involving India; student, corporate, sports and excess baggage delivery; road, air, rail "
    "and multimodal luggage transport; standard and customised services; online and offline bookings.")
EXCLUSIONS_SHORT = (
    "airline checked baggage included in a ticket; airline excess baggage fees without a separate "
    "delivery service; luggage a passenger carries themselves; international deliveries with no Indian "
    "pickup or delivery point; commercial freight, bulk cargo and ordinary e-commerce parcel delivery; "
    "passenger transport and ticket sales; standalone luggage storage, packaging or insurance; and "
    "household relocation of furniture, appliances and complete household moves.")

SERVICE = ("a paid luggage delivery service -- collecting, transporting and delivering travellers' "
           "luggage, suitcases, excess baggage, sports equipment or student belongings door to door, "
           "to or from airports and railway stations, within India or between India and abroad")
NOT_IN = ("airlines and their baggage allowances; passenger transport and ticket agents; commercial "
          "freight, bulk cargo and ordinary e-commerce parcel delivery; luggage storage, packaging or "
          "insurance on their own; household relocation of furniture and appliances; booking "
          "aggregators that carry nothing themselves; and companies with no Indian pickup or "
          "delivery point")


def build() -> dict:
    scope = (f"ONLY companies that themselves provide, under their own name, {SERVICE}. A broader "
             f"logistics or courier company qualifies when this is one of its own named services. "
             f"NOT in this market: {NOT_IN}.")
    assert len(scope) <= 900, len(scope)
    core = (f"A core player itself provides, under its own name, {SERVICE}; a courier, express or "
            "logistics company qualifies when luggage or excess-baggage delivery is one of its own "
            "named services, however small a share of its revenue that line is.")
    definition = f"{DEFINITION} Inclusions: {INCLUSIONS_SHORT} Exclusions: {EXCLUSIONS_SHORT}"
    assert len(definition) <= 2400, len(definition)
    return {
        "source": "Client brief (owner 2026-11-05): market definition, inclusions and exclusions, plus "
                  "9 mandatory companies, pasted in chat; written by "
                  "profood/setup_india_luggage_delivery_brief.py",
        # ONE player type for this market (owner's rule). The market is measured on a SERVICE
        # performed for a traveller, so the single role is the company that performs it.
        "player_type": "Service Provider",
        "market_type": "B2C",
        "market_definition": definition,
        "report_definition": (
            "The India Luggage Delivery Service Market covers paid services that collect, transport and "
            "deliver travellers' luggage, excess baggage, sports equipment and student belongings "
            "door to door, to and from airports and railway stations. It spans road, air, rail and "
            "multimodal delivery within India and between India and international destinations."),
        "player_type_reason": (
            "Service Providers: the landscape compares the companies that themselves collect, transport "
            "and deliver travellers' luggage under their own name, including the courier and express "
            "operators that run luggage and excess-baggage services."),
        "core_scope": core,
        "adjacent_segments": EXCLUSIONS + [
            "Airlines, railways and bus operators carrying a passenger's own baggage",
            "Booking aggregators and comparison sites that arrange but do not carry",
            "Luggage manufacturers and retailers",
        ],
        "scope": scope,
        "scope_test": "own_product_line",
        # The owner asked that no company of an excluded type appear at all.
        "adjacent_policy": "exclude",
        "focus_areas": ["Delhi NCR", "Maharashtra", "Karnataka", "Tamil Nadu", "Telangana", "Gujarat",
                        "West Bengal", "Uttar Pradesh", "Rajasthan", "Kerala", "Punjab", "Haryana",
                        "Madhya Pradesh", "Andhra Pradesh", "Goa", "Odisha", "Bihar", "Assam",
                        "Uttarakhand", "Himachal Pradesh", "Jammu and Kashmir", "Chandigarh"],
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
        "market_type_reason": "B2C: travellers, students and holidaymakers buy the service themselves; "
                              "corporate travel is a secondary buyer. Set by the client brief.",
        "market_definition": brief["market_definition"], "core_scope": brief["core_scope"],
        "adjacent_segments": brief["adjacent_segments"],
        "market_participants": [{"type": brief["player_type"], "definition": brief["core_scope"],
                                 "why_relevant": "They perform the service this market is measured on."}],
        "primary_participant": brief["player_type"],
        "primary_reason": "Defined by the scope of this report.",
        "report_definition": brief["report_definition"],
        "player_type_reason": brief["player_type_reason"],
    }
    ck = (ExpandCheckpoint.load(ExpandCheckpoint.path_for(out, "all"))
          or ExpandCheckpoint.create(out, query=MARKET, country=COUNTRY, batch="all", target=400))
    if args.force or not (ck.state.get("data") or {}).get("market_analysis"):
        ck.bump("0_start", "0c_market", market_analysis=analysis, note="market brief (client brief)")
    print(f"brief written: {path}")
    print(f"  definition {len(brief['market_definition'])} chars, scope {len(brief['scope'])} chars, "
          f"{len(INCLUSIONS)} inclusions, {len(EXCLUSIONS)} exclusions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
