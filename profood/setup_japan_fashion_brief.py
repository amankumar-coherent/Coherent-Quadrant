#!/usr/bin/env python3
"""Market brief (data) for the Japan Fashion E-Commerce Market, from the client's brief + sample report.

    .venv/Scripts/python.exe profood/setup_japan_fashion_brief.py [--force]

Writes <market>/_pipeline/market_brief.json and Step 0c in the market's checkpoint, so discovery
asks for the right company type (online fashion sellers) from the first round. The wording comes
from the client's brief and the sample report's Research Definition and Scope (pages 16-18) and
Competitive Landscape (pages 51-54). Nothing here is pipeline logic.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

MARKET = "Fashion E-commerce Market"
COUNTRY = "japan"

DEFINITION = (
    "The Japan Fashion E-Commerce Market covers the online sale of apparel, footwear, and fashion "
    "accessories through online marketplaces, company- or brand-owned websites, social commerce and "
    "media, and mobile applications in Japan. The market assessment includes demand by product type, "
    "price range, age group, payment method, end user, sales channel, and geographical region, "
    "alongside pricing, consumer behaviour, supply chain and logistics, digital shopping experience, "
    "and competitive developments.")
SEGMENTATION = (
    "By Product Type: Apparel (Men's Wear: Formal, Casual, Sportswear, Ethnic; Women's Wear: Dresses, "
    "Tops, Bottoms, Ethnic, Maternity; Kidswear: Infants, Toddlers, Teen), Footwear (Sports Shoes, "
    "Casual, Formal, Slippers/Slides), Accessories (Bags and Wallets, Belts and Scarves, Hats and "
    "Headwear, Watches and Jewelry), Sunglasses and Eyewear; By Price Range: Premium, Mid-Range, "
    "Economy; By Age Group: Gen Z (18-24), Millennials (25-40), Gen X (41-56); By Payment Method: "
    "Debit/Credit Cards, E-Wallets, Bank Transfer, Cash on Delivery, Others; By End User: Men, Women, "
    "Children; By Sales Channel: Online Marketplaces, Company / Brand-Owned Websites, Social Commerce "
    "/ Media, Mobile Apps; By State: Kanto, Kansai, Chubu, Kyushu and Okinawa, Rest of Japan.")

# The client's exclusions: title + what it covers (their words, expanded to the company types).
EXCLUSIONS = [
    "Offline-only fashion retail: shops and chains that sell fashion only in physical stores, with no sales through the defined e-commerce channels",
    "Non-fashion merchandise: sellers of goods outside the defined apparel, footwear, accessories and sunglasses/eyewear categories",
    "General e-commerce unrelated to fashion: online sellers and marketplaces that carry no fashion categories",
    "Standalone technology services: e-commerce platforms, shop-building and marketplace software, sizing, search and recommendation technology sold to retailers rather than fashion merchandise",
    "Standalone logistics services: delivery, warehousing, fulfilment and returns handling for online sellers",
    "Standalone payment services: card, e-wallet, bank-transfer and buy-now-pay-later providers",
    "Marketing, advertising, influencer and creative agencies serving fashion sellers",
    "Manufacturers, wholesalers and suppliers that supply fashion to sellers without selling it online themselves",
    "Other products and services outside the defined Japan Fashion E-Commerce Market scope",
]
NOT_IN = ("offline-only fashion retail; sellers of non-fashion goods only; general e-commerce with no "
          "fashion categories; e-commerce platform, shop or marketplace software; logistics, "
          "warehousing, delivery and returns services; payment and BNPL providers; marketing, "
          "advertising and influencer agencies; manufacturers and wholesalers that do not sell online "
          "themselves")
PRODUCTS = ("apparel, footwear, fashion accessories or sunglasses and eyewear to consumers in Japan "
            "online -- on an online marketplace, their own or their brands' website or mobile app, or "
            "through social commerce")

def build() -> dict:
    scope = (f"ONLY companies that themselves sell {PRODUCTS}, whether they make the goods or buy them "
             "to resell, and also when fashion is only one category of a wider assortment. NOT in this "
             f"market: {NOT_IN}.")
    assert len(scope) <= 900, len(scope)
    core = (f"A core player is a company that itself sells {PRODUCTS}, whether it makes those goods or "
            "buys them to resell, and also when fashion is only one category of a wider assortment.")
    return {
        "source": "Client brief + sample report (owner 2026-10-29): Sample_Japan_Fashion E-commerce "
                  "Market_Coherent_Market_Insights.pdf, Research Definition pp.16-18, Competitive "
                  "Landscape pp.51-54; written by profood/setup_japan_fashion_brief.py",
        # B2C markets are Brand / Marketer (owner's rule). The landscape still holds the
        # marketplaces and retail groups the client's report profiles, because the
        # scope_test below -- not the role label -- decides that selling qualifies.
        "player_type": "Brand / Marketer",
        "market_type": "B2C",
        "market_definition": f"{DEFINITION} Segmentation: {SEGMENTATION} Exclusions: "
                             + "; ".join(e.split(":")[0] for e in EXCLUSIONS) + ".",
        "report_definition": (
            "The Japan Fashion E-Commerce Market covers the online sale of apparel, footwear, fashion "
            "accessories and eyewear in Japan through online marketplaces, company- and brand-owned "
            "websites, social commerce and mobile apps. It spans demand by product type, price range, "
            "age group, payment method, end user, sales channel and region."),
        "player_type_reason": (
            "Brands and the companies behind them: this is a consumer market, so the landscape "
            "compares the companies that sell apparel, footwear and accessories to shoppers in "
            "Japan online, under their own brands or on their own marketplaces."),
        "core_scope": core,
        "adjacent_segments": EXCLUSIONS,
        "scope": scope,
        "scope_test": "sells_in_channel",
        "adjacent_policy": "exclude",
        "chart_selection": "top_overall",
        "focus_areas": ["Kanto (Tokyo)", "Kansai (Osaka)", "Chubu (Nagoya)",
                        "Kyushu and Okinawa (Fukuoka)", "Rest of Japan"],
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
        "market_type_reason": "B2C: consumers buy fashion online. Set by the client brief.",
        "market_definition": brief["market_definition"], "core_scope": brief["core_scope"],
        "adjacent_segments": brief["adjacent_segments"],
        # ONE player type for this market (owner's rule): every company is found and
        # verified as this single role, never a mix of categories.
        "market_participants": [{"type": brief["player_type"], "definition": brief["core_scope"],
                                 "why_relevant": "They sell the fashion this market is measured on."}],
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
