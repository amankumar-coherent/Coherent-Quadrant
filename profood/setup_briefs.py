#!/usr/bin/env python3
"""Market briefs for a list of markets, from a markets JSON (data, not code).

    .venv\\Scripts\\python.exe profood\\setup_briefs.py profood\\markets.json

The file: {"markets": [{"market", "country", "player_type", "market_type",
"definition", "inclusion", "exclusion"}, ...]}. For each market this writes

* ``<market>/_pipeline/market_brief.json`` -- definition, scope, exclusions,
  player type, B2B/B2C (excluded company types are removed entirely); and
* Step 0c in the market's checkpoint, from the brief, so discovery asks for the
  right company type from the first round instead of re-deriving it.

Idempotent: an existing brief is kept (``--force`` rewrites it); companies
already found or verified are never touched. Nothing market-specific lives in
this script -- every word of a market comes from the markets file.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# How each player type is described (the four canonical types):
# (singular verb phrase, plural verb phrase, what they supply).
_DOES = {
    "Brand / Marketer": ("owns and sells under its own brand", "own and sell under their own brand", "products"),
    "Manufacturer": ("makes and sells under its own name", "make and sell under their own name", "products"),
    "Solution Provider": ("develops and sells under its own name", "develop and sell under their own name",
                          "solutions"),
    "Service Provider": ("delivers under its own name", "deliver under their own name", "services"),
}


def exclusions(text: str) -> list[str]:
    """'Exclude: Raw milk trading; dairy machinery. Also exclude unrelated
    upstream/downstream market revenue.' -> ['Raw milk trading', 'Dairy machinery',
    'Unrelated upstream/downstream market revenue']."""
    s = re.sub(r"^\s*exclude[sd]?\s*:\s*", "", str(text or ""), flags=re.I)
    parts = re.split(r";|\.\s+|\balso exclude\b|\bexcluding\b", s, flags=re.I)
    out = []
    for p in parts:
        p = p.strip(" .,:-")
        if len(p) > 3:
            out.append(p[0].upper() + p[1:])
    return out


def brief_for(m: dict) -> dict:
    market, country = m["market"], str(m.get("country") or "global").lower()
    player = m.get("player_type") or "Manufacturer"
    single = country not in ("global", "", "worldwide")
    where = f"HEADQUARTERED IN {country.title()}" if single else ""
    excl = exclusions(m.get("exclusion") or "")
    definition = " ".join(str(m.get("definition") or market).split())
    if m.get("inclusion"):
        definition += " Inclusion: " + " ".join(str(m["inclusion"]).split())
    if single:
        definition += (f" Geography: {country.title()} -- companies {where} (a foreign company's local "
                       "office, branch, subsidiary or distributor does not qualify).")
    one, many, what = _DOES.get(player, _DOES["Manufacturer"])
    core = (f"A core player{' is ' + where + ' and' if single else ''} {one} the {what} of the {market}; "
            "diversified groups qualify when this is one of their own product or business lines.")
    scope = (f"ONLY companies{' ' + where if single else ''} that {many} the {what} of the {market}: "
             + " ".join(str(m.get("inclusion") or "").split())
             + (" NOT in this market: " + "; ".join(excl + [
                 "distributors, traders and resellers of other companies' products",
                 "companies that only buy these products (the customers)"]) + "."))
    return {
        "source": f"Markets file ({m.get('id', '')}: {m.get('ecosystem', '')}); written by profood/setup_briefs.py",
        "player_type": player,
        "market_type": m.get("market_type") or "B2B",
        "market_definition": definition,
        "core_scope": core,
        "adjacent_segments": excl + ["Distributors, traders and resellers", "Buyers / users of these products"],
        "scope": scope,
        "scope_test": "own_product_line",
        "adjacent_policy": "exclude",
        "focus_areas": [],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("markets_file")
    ap.add_argument("--force", action="store_true", help="rewrite existing briefs and Step 0c")
    args = ap.parse_args()

    from vendor_intel.pipeline.openai_expand_checkpoint import ExpandCheckpoint
    from vendor_intel.pipeline.web_expand import default_output_dir

    markets = json.loads(Path(args.markets_file).read_text(encoding="utf-8"))["markets"]
    wrote = kept = 0
    for m in markets:
        country = str(m.get("country") or "global").lower()
        out = Path(default_output_dir(m["market"], country))
        path = out / "_pipeline" / "market_brief.json"
        if path.exists() and not args.force:
            kept += 1
            continue
        brief = brief_for(m)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(brief, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        analysis = {
            "market_type": brief["market_type"],
            "market_type_reason": f"{brief['market_type']}: set by the markets file for this report.",
            "market_definition": brief["market_definition"], "core_scope": brief["core_scope"],
            "adjacent_segments": brief["adjacent_segments"],
            "market_participants": [{"type": brief["player_type"], "definition": brief["core_scope"],
                                     "why_relevant": "They supply what this market is measured on."}],
            "primary_participant": brief["player_type"],
            "primary_reason": "Defined by the scope of this report.",
        }
        ck = (ExpandCheckpoint.load(ExpandCheckpoint.path_for(out, "all"))
              or ExpandCheckpoint.create(out, query=m["market"], country=country, batch="all", target=160))
        if args.force or not (ck.state.get("data") or {}).get("market_analysis"):
            ck.bump("0_start", "0c_market", market_analysis=analysis, note="market brief (markets file)")
        wrote += 1
    print(f"briefs: {wrote} written, {kept} kept (already there) -- {len(markets)} markets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
