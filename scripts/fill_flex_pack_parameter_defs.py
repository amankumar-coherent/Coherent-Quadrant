#!/usr/bin/env python3
"""Fill Parameter Definitions on Flexible Packaging quadrant HTML (end panel)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vendor_intel.placeholders.load_keys import apply_env_overrides
from vendor_intel.quadrant.axis_define import explain_market_parameters
from vendor_intel.quadrant.html_report import write_quadrant_html_report

SLUG = "global_flexible_packaging_market_global"
QUERY = "Global Flexible Packaging Market"
FOLDER = ROOT / "output" / "chatgpt_expand" / SLUG
JSON_PATH = FOLDER / f"{SLUG}_quadrant.json"
HTML_PATH = FOLDER / f"{SLUG}_report.html"

AXIS_X = "Packaging Solution Capability"
AXIS_Y = "Commercial & Growth Strategy"
# Match Packaging leaf + deep-rescore features used for this market
X_FEATS = [
    "Structure / Material Portfolio",
    "Barrier, Protection & Performance",
    "Converting & Manufacturing Excellence",
    "Sustainability & Circular Design",
    "Regulatory & Food-Contact Compliance",
]
Y_FEATS = [
    "Geographic Coverage",
    "Brand / Converter Customer Reach",
    "Financial Performance",
    "Innovation Roadmap",
    "Capacity & Business Expansion",
]

# Curated fallback if LLM unavailable — market-specific, not generic pending text
FALLBACK_DEFS = {
    "x": {
        "Structure / Material Portfolio": (
            "Breadth and depth of flexible packaging structures and substrates offered — "
            "e.g. mono-material PE/PP, PET laminates, paper-flex hybrids, tubes, pouches, "
            "bags, and specialty films — relative to CPG and industrial pack needs."
        ),
        "Barrier, Protection & Performance": (
            "Ability to deliver oxygen, moisture, light, aroma, and puncture protection "
            "(EVOH, metallized, AlOx, high-barrier laminates, medical/pharma barriers) "
            "with proven shelf-life and product-protection performance."
        ),
        "Converting & Manufacturing Excellence": (
            "Print, laminate, extrusion, bag-making, and coating capability: plant quality, "
            "throughput, process control, and consistency of finished flexible packs or films."
        ),
        "Sustainability & Circular Design": (
            "Recycle-ready / mono-material designs, PCR content, compostable options, "
            "lightweighting, and circular programs aligned to PPWR and brand ESG goals."
        ),
        "Regulatory & Food-Contact Compliance": (
            "Food-contact, pharma, and safety compliance (FDA/EU, BRC/ISO, migration limits) "
            "and documented quality systems for sensitive packaging applications."
        ),
    },
    "y": {
        "Geographic Coverage": (
            "Multi-country / multi-continent manufacturing and sales footprint for flexible "
            "packaging — plants, distribution, and ability to supply global vs regional customers."
        ),
        "Brand / Converter Customer Reach": (
            "Strength of CPG, retail, pharma, and industrial customer relationships; "
            "share of wallet, key-account depth, and go-to-market / commercial partnerships."
        ),
        "Financial Performance": (
            "Scale and resilience of packaging revenue, margins, and capital strength "
            "(listed results, PE-backed capacity, or evidenced commercial scale)."
        ),
        "Innovation Roadmap": (
            "Pipeline of new flexible structures, barrier platforms, digital print, and "
            "sustainable formats — R&D investment and time-to-market for new offerings."
        ),
        "Capacity & Business Expansion": (
            "Capacity additions, M&A, plant expansions, and new market or category entry "
            "that grow the flexible packaging franchise."
        ),
    },
}


def main() -> None:
    apply_env_overrides()
    os.environ.setdefault("LLM_PROVIDER", "deepseek")

    payload = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    crit = payload.setdefault("criteria", {})
    crit["axis_labels"] = {"x": AXIS_X, "y": AXIS_Y}
    crit["x_axis"] = list(X_FEATS)
    crit["y_axis"] = list(Y_FEATS)

    defs = None
    try:
        from vendor_intel.config import Settings
        from vendor_intel.clients.claude import ClaudeClient

        settings = Settings.load()
        client = ClaudeClient(settings)
        defs = explain_market_parameters(
            QUERY,
            X_FEATS,
            Y_FEATS,
            axis_x=AXIS_X,
            axis_y=AXIS_Y,
            geography="global",
            settings=settings,
            client=client,
        )
    except Exception as exc:
        print(f"LLM explain failed: {exc}", flush=True)
        defs = None

    # Merge: LLM wins when non-empty; else curated fallback
    out_x, out_y = {}, {}
    llm_x = (defs or {}).get("x") if isinstance(defs, dict) else {}
    llm_y = (defs or {}).get("y") if isinstance(defs, dict) else {}
    for f in X_FEATS:
        text = str((llm_x or {}).get(f) or "").strip()
        if not text or "pending" in text.lower() or len(text) < 40:
            text = FALLBACK_DEFS["x"][f]
        out_x[f] = text
    for f in Y_FEATS:
        text = str((llm_y or {}).get(f) or "").strip()
        if not text or "pending" in text.lower() or len(text) < 40:
            text = FALLBACK_DEFS["y"][f]
        out_y[f] = text

    crit["parameter_definitions"] = {"x": out_x, "y": out_y}
    payload["industry_group"] = payload.get("industry_group") or "Packaging"
    payload["industry_category"] = (
        payload.get("industry_category") or "Packaging / Flexible Packaging"
    )

    JSON_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    write_quadrant_html_report(payload, HTML_PATH, open_browser=False)
    print("Updated", JSON_PATH)
    print("Updated", HTML_PATH)
    print("X defs:", list(out_x.keys()))
    print("Y defs:", list(out_y.keys()))
    # show first def snippet
    print("sample X:", out_x[X_FEATS[0]][:120], "...")
    print("sample Y:", out_y[Y_FEATS[0]][:120], "...")


if __name__ == "__main__":
    main()
