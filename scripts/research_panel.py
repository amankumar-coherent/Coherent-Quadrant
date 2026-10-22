#!/usr/bin/env python3
"""Step 2c: the report's market framing, written per market by AI Mode.

Four pieces of client-facing text that change with the market (owner
2026-10-15), all from the market's own definition at run time -- no
per-market text in code:

* ``organisations`` -- "Organisations We Surveyed", 5 organisation types;
  manufacturers are always one of them (owner's rule).
* ``designations`` -- "Designations We Spoke To", 5 job titles.
* ``report_definition`` -- the short market definition the report shows
  (the long definition stays for discovery and the checks).
* ``player_type_reason`` -- one or two sentences under "Provider Categories":
  what the compared player type supplies in this market, and who is out.

Writes ``_pipeline/research_panel.json``. Resumable: pieces already in the file
are kept; only missing ones are asked for. A market brief's own
``report_definition`` / ``player_type_reason`` always win in the report.
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

N = 5
KEYS = ("organisations", "designations", "report_definition", "player_type_reason")
_MFR = re.compile(r"manufactur", re.I)
_INTERNAL = re.compile(r"_pipeline|market_brief|\.json|\bbrief\b", re.I)


def _clean(items: object) -> list[str]:
    out: list[str] = []
    for it in items if isinstance(items, list) else []:
        s = " ".join(str(it or "").split()).strip(" -•.;:")
        if 2 <= len(s.split()) <= 9 and s.lower() not in {o.lower() for o in out}:
            out.append(s[0].upper() + s[1:])
    return out


def _text(value: object, lo: int, hi: int) -> str:
    """A prose answer within lo..hi words, or '' (too short, too long, or
    naming an internal file)."""
    s = " ".join(str(value or "").split()).strip()
    n = len(s.split())
    return s if lo <= n <= hi and not _INTERNAL.search(s) else ""


def product_phrase(market: str) -> str:
    """'Global Data Center Market' -> 'Data center'; used only when the answer
    names no manufacturers and one line has to be added."""
    s = re.sub(r"\b(global|market|industry|analysis|india|report)\b", " ", market, flags=re.I)
    s = " ".join(s.replace("&", "and").split()).strip(" -,")
    return (s[:1].upper() + s[1:].lower()) if s else "Product"


def ensure_manufacturers(orgs: list[str], market: str) -> list[str]:
    """Manufacturers are always surveyed and lead the value chain (owner's
    rule): the manufacturers line goes first; when no line names them,
    '<product> manufacturers' is added first."""
    orgs = orgs[:N]
    mfr = [o for o in orgs if _MFR.search(o)]
    if mfr:
        return [mfr[0]] + [o for o in orgs if o != mfr[0]]
    return [f"{product_phrase(market)} manufacturers"] + orgs[: N - 1]


def build_prompt(market: str, definition: str, player: str, country: str, want: list[str],
                 excluded: list[str] | None = None) -> tuple[str, str]:
    system = ("You are the research director of a B2B market research firm writing the framing text of a market "
              "report. Return compact JSON only with the keys asked for.")
    where = "" if country.lower() in ("", "global") else f" ({country.title()} only)"
    asks = {
        "organisations": (f'"organisations": exactly {N} short lines (3-7 words), the INDUSTRY TYPES across this '
                          "market's value chain that the research team surveyed, in this order: (1) the manufacturers "
                          "/ makers of this market's products (worded with 'manufacturers'); (2) their component, "
                          "material or technology suppliers; (3) the operators, integrators or service providers of "
                          "this market; (4) the main buyer / end-use industries; (5) the regulators, government or "
                          "standards bodies. Each line names an industry type of THIS market, never a company name."),
        "designations": (f'"designations": exactly {N} job titles the team interviewed at those organisations, '
                         "specific to this market's buying, engineering, operations and sourcing roles. Titles only."),
        "report_definition": ('"report_definition": the market definition for the report, 45-75 words, two '
                              "sentences: (1) what the market covers, from the definition below; (2) which "
                              f"companies this assessment compares ({player}s) and what they supply. Precise, no "
                              "lists of every sub-segment, no marketing words."),
        "player_type_reason": ('"player_type_reason": one or two sentences, 25-60 words, explaining the provider '
                               f"category '{player}' in THIS market: what these companies supply, and which kinds of "
                               "companies are outside this assessment. Describe them in the language of that "
                               "category, not of another one."),
    }
    # Owner 2026-10-19: the slot "(2) suppliers" became "API and chemical
    # substance suppliers" in a market whose brief excludes APIs. A segment the
    # market excludes is never shown as an organisation type surveyed.
    outside = "; ".join(str(e).strip() for e in excluded or [] if str(e).strip())
    user = (f"Market: {market}{where}\n"
            f"Companies compared in the report: {player}\n"
            f"Market definition: {definition[:1800]}\n"
            + (f"EXCLUDED from this market (never list any of these as an organisation type; when a slot above "
               f"would name one, use another organisation type of this market's value chain instead): "
               f"{outside[:1200]}\n" if outside else "")
            + "\n"
            "Write:\n" + "\n".join(asks[k] for k in want)
            + "\nNo market-research firm, no website, no explanation outside the JSON.")
    return system, user


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--market", required=True)
    ap.add_argument("--country", default="global")
    ap.add_argument("--force", action="store_true", help="ask for every piece again")
    args = ap.parse_args()

    from vendor_intel.pipeline.web_expand import default_output_dir

    out_dir = Path(default_output_dir(args.market, args.country))
    pipe = out_dir / "_pipeline"
    path = pipe / "research_panel.json"
    panel: dict = {}
    if path.exists() and not args.force:
        try:
            panel = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            panel = {}
    want = [k for k in KEYS if not panel.get(k)]
    if not want:
        print(f"research panel: complete, kept {path}")
        return 0
    brief, analysis = {}, {}
    try:
        brief = json.loads((pipe / "market_brief.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    try:
        state = json.loads((out_dir / "chatgpt_checkpoint_batch_all.json").read_text(encoding="utf-8"))
        analysis = (state.get("data") or {}).get("market_analysis") or {}
    except (OSError, ValueError):
        pass
    definition = str(brief.get("market_definition") or analysis.get("market_definition") or args.market)
    player = str(brief.get("player_type") or analysis.get("primary_participant") or "companies")
    excluded = list(brief.get("adjacent_segments") or analysis.get("adjacent_segments") or [])

    from vendor_intel.pipeline.chatgpt_expand import _ai_mode_json

    for attempt in (1, 2):
        if not want:
            break
        system, user = build_prompt(args.market, definition, player, args.country, want, excluded)
        try:
            # No require_key: that check wants a non-empty LIST, and two of these
            # pieces are text -- each piece is validated below instead.
            data = _ai_mode_json(system, user, label=f"research-panel-{attempt}") or {}
            if not isinstance(data, dict):
                data = {}
        except Exception as err:  # noqa: BLE001
            print(f"research panel: AI Mode failed ({err})")
            continue
        got = {
            "organisations": _clean(data.get("organisations")),
            "designations": _clean(data.get("designations"))[:N],
            "report_definition": _text(data.get("report_definition"), 30, 90),
            "player_type_reason": _text(data.get("player_type_reason"), 15, 75),
        }
        if len(got["organisations"]) >= 3:
            got["organisations"] = ensure_manufacturers(got["organisations"], args.market)
        else:
            got["organisations"] = []
        if len(got["designations"]) < 3:
            got["designations"] = []
        for k in list(want):
            if got.get(k):
                panel[k] = got[k]
        want = [k for k in KEYS if not panel.get(k)]
    panel["source"] = "Google AI Mode, from the market definition (step 2c)"
    pipe.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(panel, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"research panel: {json.dumps({k: panel.get(k) for k in KEYS}, ensure_ascii=False)}")
    return 1 if want else 0


if __name__ == "__main__":
    raise SystemExit(main())
