#!/usr/bin/env python3
"""Market brief (data) for the Mozambique Fire Insurance Market, from the client's brief + report sample.

    .venv\\Scripts\\python.exe profood\\setup_mozambique_fire_brief.py [--force]

Writes ``<market>/_pipeline/market_brief.json`` and Step 0c in the market's checkpoint, so discovery asks
for the right company type (insurers) from the first round. Nothing here is pipeline logic.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

MARKET = "Fire Insurance Market"
COUNTRY = "mozambique"

DEFINITION = (
    "The Mozambique Fire Insurance Market encompasses insurance policies designed to provide financial protection "
    "against physical loss or damage to buildings, properties, machinery, equipment, inventories, and other insured "
    "assets caused by fire and associated risks, including lightning and explosions. The market covers basic "
    "standalone fire insurance, extended standalone fire insurance, and property multi-risk insurance policies "
    "incorporating fire coverage, for residential, commercial, industrial, agricultural, institutional, "
    "infrastructure and mixed-use properties insured by individuals, businesses, government entities and other "
    "organizations across Mozambique.")
SEGMENTATION = (
    "By Policy Type: Basic Standalone Fire Insurance, Extended Standalone Fire Insurance, Property Multi-Risk "
    "Insurance Including Fire; By Policyholder Type: individuals and households, private businesses (micro, small, "
    "medium, large), state-owned enterprises, government and public institutions, non-profit organizations; By "
    "Distribution Channel: direct, brokers, agents, bancassurance, affinity and institutional partnerships.")

EXCLUSIONS = [
    "Non-Fire Property Insurance: standalone policies exclusively covering theft, burglary, flooding, earthquakes, storms or other risks without fire coverage",
    "Other Insurance Categories: life, health, motor, marine, aviation, personal accident, workers' compensation and standalone liability insurance",
    "Motor and Cargo Fire Coverage: fire protection provided exclusively under motor vehicle, marine cargo or goods-in-transit policies",
    "Standalone Business Interruption Insurance: business interruption and loss-of-profit cover unrelated to an insured fire event or not attached to an eligible property policy",
    "Specialized Agricultural and Engineering Insurance: crop, livestock, construction all-risk and machinery breakdown policies outside the fire / property scope",
    "Reinsurance and Ancillary Services: reinsurance, fire prevention equipment, firefighting services, insurance consulting and other non-insurance activities",
    "Insurance Outside Mozambique: policies covering properties and assets situated outside Mozambique",
]
NOT_IN = ("life, health, motor, marine, aviation, personal accident, workers' compensation or liability-only insurers; "
          "reinsurers; insurance brokers, agents and bancassurance distributors; fire protection equipment and "
          "firefighting services; insurance consultants; insurers with no property / fire cover in Mozambique")
PRODUCTS = ("fire insurance policies in Mozambique (standalone basic or extended fire, or property multi-risk "
            "including fire) for residential, commercial, industrial and other properties")


def build() -> dict:
    scope = (f"ONLY licensed insurers that underwrite and sell under their own name {PRODUCTS}. Composite insurers "
             f"qualify when fire / property cover is one of their own lines. NOT in this market: {NOT_IN}.")
    assert len(scope) <= 900, len(scope)
    core = (f"A core player is an insurer that underwrites and sells {PRODUCTS} under its own name; composite "
            "insurers qualify when fire / property cover is one of their own business lines.")
    return {
        "source": "Client brief + report sample (owner 2026-10-28); written by profood/setup_mozambique_fire_brief.py",
        "player_type": "Service Provider",
        "market_type": "B2B",
        "market_definition": f"{DEFINITION} Segmentation: {SEGMENTATION} Exclusions: "
                             + "; ".join(e.split(":")[0] for e in EXCLUSIONS) + ".",
        "core_scope": core,
        "adjacent_segments": EXCLUSIONS + ["Insurance brokers, agents and bancassurance distributors",
                                           "Buyers / policyholders of these policies"],
        "scope": scope,
        "scope_test": "own_product_line",
        "adjacent_policy": "exclude",
        "chart_selection": "top_overall",
        "focus_areas": ["Maputo", "Beira", "Nampula", "Matola", "Tete"],
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
        "market_participants": [{"type": "Service Provider", "definition": brief["core_scope"],
                                 "why_relevant": "They underwrite the policies this market is measured on."}],
        "primary_participant": "Service Provider",
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
