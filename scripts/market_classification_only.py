"""Market Classification + Scoring Parameters + Parameter Definitions ONLY.

A stand-alone script, not a pipeline step: it runs no discovery, no scoring
and no company research, and nothing in the pipeline calls it. It reuses the
pipeline's own functions unchanged, so the three sections read exactly as
they do in a full report:

- Market Type + Provider Categories: Step 0c market analysis in Google AI Mode
  (chatgpt_expand._analyze_market_for_discovery, canonical player type).
- 5 + 5 parameters and their definitions: the LLM (axis_define.define_market_axes,
  explain_market_parameters for any definition it leaves out), exactly as
  run_quadrant_pipeline.resolve_spec does.

Output per market: output/market_classification/<slug>/<slug>_classification.html
and .json. Each answer is saved, so a re-run asks nothing already answered.

    .venv\\Scripts\\python.exe scripts\\market_classification_only.py ^
        --market "Global Medical Films Market" --market "Global Advanced Wound Care Market"
"""
from __future__ import annotations

import argparse
import html
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vendor_intel.pipeline.chatgpt_env import apply_chatgpt_expand_env  # noqa: E402
from vendor_intel.quadrant.axis_define import PARAMS_PER_AXIS  # noqa: E402
from vendor_intel.quadrant.quadrant_language import AXIS_Y_TITLE, x_axis_title  # noqa: E402

OUT_ROOT = ROOT / "output" / "market_classification"


def slug_of(market: str, country: str) -> str:
    s = "".join(c.lower() if c.isalnum() else "_" for c in market).strip("_")
    while "__" in s:
        s = s.replace("__", "_")
    return f"{s}_{country.lower()}"


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def market_analysis(market: str, cache: Path) -> dict:
    """Step 0c in AI Mode (no API fallback, as in the pipeline)."""
    saved = read_json(cache)
    if saved and saved.get("market_type"):
        if "hybrid" in str(saved["market_type"]).lower():
            saved = as_b2b(market, saved)
            write_json(cache, saved)
        return saved
    from vendor_intel.config import Settings
    from vendor_intel.pipeline.chatgpt_expand import _ai_mode_active, _analyze_market_for_discovery

    settings = Settings.load()
    if not _ai_mode_active(settings):
        raise SystemExit("Google AI Mode is off: set GOOGLE_AI_MODE_ENABLED=true in .env")
    result = _analyze_market_for_discovery(market, settings=settings)
    if "hybrid" in str(result.get("market_type") or "").lower():
        result = as_b2b(market, result)
    write_json(cache, result)
    return result


# Owner's rule for these classification pages: a hybrid market is read as B2B
# (the institutional side is the market), never as Brand / Marketer.
B2B_NOTE = (
    "\n\nThis market is to be analysed as B2B: answer market_type \"B2B\". Treat the "
    "institutional and professional buyers as the market and ignore any consumer retail "
    "channel. primary_participant must be one of \"Manufacturer\", \"Solution Provider\" "
    "or \"Service Provider\" (never \"Brand / Marketer\"), and market_participants must "
    "list the B2B roles. Write market_definition, core_scope, adjacent_segments, "
    "market_type_reason and primary_reason for this B2B market."
)


def as_b2b(market: str, hybrid: dict) -> dict:
    """Step 0c asked again in AI Mode with the market fixed as B2B; the answer
    is normalised the way _analyze_market_for_discovery normalises one."""
    from vendor_intel.pipeline.chatgpt_expand import (
        _MARKET_ANALYSIS_DISCOVERY_SYSTEM, _ai_mode_json, canonical_player_type)

    print(f"[classify]   {hybrid.get('market_type')} -> re-asked as B2B", flush=True)
    raw = _ai_mode_json(_MARKET_ANALYSIS_DISCOVERY_SYSTEM + B2B_NOTE,
                        json.dumps({"market": market, "industry_group": ""}, ensure_ascii=False),
                        label="0c-market-analysis-b2b")
    if not isinstance(raw, dict):
        raise RuntimeError("AI Mode returned no B2B market analysis")
    participants = [p for p in raw.get("market_participants") or []
                    if isinstance(p, dict) and str(p.get("type") or "").strip()
                    and "contract manufacturer" not in str(p.get("type")).lower()]
    primary = canonical_player_type(str(raw.get("primary_participant") or ""), market_type="B2B")
    if primary == "Brand / Marketer":
        raise RuntimeError("AI Mode kept Brand / Marketer for a B2B market")
    return {
        "market_type": "B2B",
        "market_type_reason": str(raw.get("market_type_reason") or "").strip(),
        "market_definition": str(raw.get("market_definition") or "").strip(),
        "core_scope": str(raw.get("core_scope") or "").strip(),
        "adjacent_segments": [str(a).strip() for a in raw.get("adjacent_segments") or [] if str(a).strip()][:8],
        "market_participants": participants,
        "primary_participant": primary,
        "primary_reason": str(raw.get("primary_reason") or "").strip(),
        "reclassified_from": str(hybrid.get("market_type") or ""),
    }


def axes(market: str, country: str, cache: Path, scope: str = "") -> dict:
    """5 X + 5 Y parameters with definitions from the LLM (resolve_spec's path).
    ``scope`` goes to the LLM as MARKET_SCOPE (as a market brief does in the
    pipeline); saved parameters made for another scope are made again."""
    saved = read_json(cache)
    if saved and len(saved.get("x") or []) == PARAMS_PER_AXIS == len(saved.get("y") or []) \
            and str(saved.get("scope") or "") == scope:
        return saved
    from vendor_intel.config import Settings
    from vendor_intel.quadrant.axis_define import define_market_axes, explain_market_parameters

    settings = Settings.load()
    before = os.environ.get("MARKET_SCOPE")
    if scope:
        os.environ["MARKET_SCOPE"] = scope
    try:
        industry = define_market_axes(market, {}, geography=country, settings=settings)
    finally:
        if before is None:
            os.environ.pop("MARKET_SCOPE", None)
        else:
            os.environ["MARKET_SCOPE"] = before
    spec = {"x": list(industry.get("x") or []), "y": list(industry.get("y") or []),
            "parameter_definitions": industry.get("parameter_definitions") or {"x": {}, "y": {}},
            "axis_x": industry.get("axis_x"), "axis_y": industry.get("axis_y")}
    if not (len(spec["x"]) == PARAMS_PER_AXIS == len(spec["y"])):
        raise SystemExit(f"{market}: the LLM gave {len(spec['x'])} X / {len(spec['y'])} Y parameters, "
                         f"{PARAMS_PER_AXIS} each are required")
    defs = spec["parameter_definitions"]
    miss_x = [p for p in spec["x"] if not str((defs.get("x") or {}).get(p) or "").strip()]
    miss_y = [p for p in spec["y"] if not str((defs.get("y") or {}).get(p) or "").strip()]
    if miss_x or miss_y:
        fresh = explain_market_parameters(market, miss_x, miss_y, axis_x=spec["axis_x"],
                                          axis_y=spec["axis_y"], geography=country, settings=settings)
        defs.setdefault("x", {}).update({k: v for k, v in (fresh.get("x") or {}).items() if v})
        defs.setdefault("y", {}).update({k: v for k, v in (fresh.get("y") or {}).items() if v})
    spec["scope"] = scope
    write_json(cache, spec)
    return spec


def build_payload(market: str, country: str, ma: dict, spec: dict) -> dict:
    player = str(ma.get("primary_participant") or "").strip()
    # Same title rule as the report: X follows the player type, Y is fixed.
    x_title = x_axis_title({"criteria": {"relevance": {"keep_roles": [player]}}})
    defs = spec.get("parameter_definitions") or {}

    def params(names, d):
        return [{"name": n, "definition": str((d or {}).get(n) or "").strip()} for n in names]

    return {
        "market": market,
        "geography": country,
        "market_classification": {
            "market": market,
            "market_type": ma.get("market_type") or "",
            "market_definition": ma.get("market_definition") or "",
            "provider_categories": [player] if player else [],
            "provider_rationale": ma.get("primary_reason") or "",
        },
        "market_scoring_parameters": {
            "x_axis": {"title": x_title, "parameters": params(spec["x"], defs.get("x"))},
            "y_axis": {"title": AXIS_Y_TITLE, "parameters": params(spec["y"], defs.get("y"))},
        },
    }


# Same look as the interactive report (quadrant_viewer.html): hero, cards, panels.
CSS = """
:root{--slate900:#0f172a;--slate800:#1e293b;--slate700:#334155;--slate600:#475569;--slate500:#64748b;
--slate200:#e2e8f0;--slate50:#f8fafc}
*{box-sizing:border-box}
body{margin:0;font-family:Arial,Helvetica,sans-serif;background:#eef2f6;color:var(--slate800);line-height:1.5;
-webkit-font-smoothing:antialiased}
.wrap{max-width:1280px;margin:0 auto;padding:24px;display:grid;gap:24px}
.hero{border-radius:14px;padding:26px 28px;color:#f8fafc;
background:linear-gradient(135deg,#0f172a 0%,#1e3a5f 50%,#0d9488 100%)}
.hero h1{margin:0 0 8px;font-size:1.6rem}.hero p{margin:0;opacity:.9}
.card{background:#fff;border:1px solid var(--slate200);border-radius:12px;padding:20px;
box-shadow:0 1px 2px rgba(15,23,42,.05)}
h2{margin:0 0 12px;font-size:1.1rem;color:var(--slate900)}
.grid2{display:grid;gap:16px;grid-template-columns:1fr}
@media(min-width:860px){.grid2{grid-template-columns:1fr 1fr}}
.panel{background:var(--slate50);border:1px solid var(--slate200);border-radius:10px;padding:16px}
.panel .lbl{font-weight:700;color:var(--slate900);margin-bottom:4px}
.panel .val{font-size:.92rem;color:var(--slate700)}
.muted{color:var(--slate500);font-size:.84rem;margin-top:8px}
ol{margin:0;padding-left:1.2rem}ol li{margin-bottom:6px;color:var(--slate700)}
.pname{font-weight:600;color:var(--slate900)}
.pdef{margin-top:2px;font-size:.88rem;color:var(--slate600);line-height:1.55}
.lead{margin:0 0 16px;font-size:.92rem;color:var(--slate500)}
"""


def render_html(p: dict) -> str:
    e = html.escape
    mc, sp = p["market_classification"], p["market_scoring_parameters"]
    xa, ya = sp["x_axis"], sp["y_axis"]
    geo = p["geography"][:1].upper() + p["geography"][1:]
    cats = "".join(f"<li>{e(c)}</li>" for c in mc["provider_categories"])
    rationale = f'<div class="muted">{e(mc["provider_rationale"])}</div>' if mc["provider_rationale"] else ""

    def names(axis):
        return "".join(f'<li><span class="pname">{e(q["name"])}</span></li>' for q in axis["parameters"])

    def defs(axis):
        return "".join(f'<li><span class="pname">{e(q["name"])}</span>'
                       + (f'<div class="pdef">{e(q["definition"])}</div>' if q["definition"] else "")
                       + "</li>" for q in axis["parameters"])

    n = len(xa["parameters"]) + len(ya["parameters"])
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(p['market'])} - Market Classification</title><style>{CSS}</style></head>
<body><div class="wrap">
<div class="hero"><h1>Coherent Quadrant</h1><p>{e(p['market'])} &middot; {e(geo)} &middot;
{e(", ".join(mc['provider_categories']) or 'companies')} assessed on {e(xa['title'])} (X) and {e(ya['title'])} (Y)</p></div>
<section class="card"><h2>Market Classification</h2><div class="grid2">
<div class="panel"><div class="lbl">Market</div><div class="val" style="margin-bottom:12px">{e(mc['market'])}</div>
<div class="lbl">Market Type</div><div class="val">{e(mc['market_definition'])}</div></div>
<div class="panel"><div class="lbl" style="margin-bottom:8px">Provider Categories in this Market</div><ol>{cats}</ol>{rationale}</div>
</div></section>
<section class="card"><h2>Market Scoring Parameters</h2>
<p class="lead">The X and Y axes and these {n} parameters were defined for
<strong style="color:var(--slate700)">{e(p['market'])}</strong> and form the basis on which its companies are scored.</p>
<div class="grid2">
<div class="panel"><div class="lbl" style="margin-bottom:8px">X &mdash; {e(xa['title'])}</div><ol>{names(xa)}</ol></div>
<div class="panel"><div class="lbl" style="margin-bottom:8px">Y &mdash; {e(ya['title'])}</div><ol>{names(ya)}</ol></div>
</div></section>
<section class="card"><h2>Parameter Definitions</h2>
<p class="lead">What each parameter measures and the evidence that shows strength.</p>
<div class="grid2">
<div class="panel"><div class="lbl" style="margin-bottom:8px">X &mdash; {e(xa['title'])}</div><ol>{defs(xa)}</ol></div>
<div class="panel"><div class="lbl" style="margin-bottom:8px">Y &mdash; {e(ya['title'])}</div><ol>{defs(ya)}</ol></div>
</div></section>
</div></body></html>
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--market", action="append", required=True, help="repeat for several markets")
    ap.add_argument("--country", default="global")
    ap.add_argument("--slot", type=int, default=41, help="AI Mode browser profile data/ai_mode_batch_<slot>")
    args = ap.parse_args()

    apply_chatgpt_expand_env(root=ROOT)  # .env + DeepSeek mapping, as the pipeline scripts do
    # One AI Mode browser, set up the way the pipeline sets up a slot.
    os.environ.setdefault("GOOGLE_AI_MODE_PROFILE_DIR", str(ROOT / "data" / f"ai_mode_batch_{args.slot:02d}"))
    os.environ.setdefault("GOOGLE_AI_MODE_BROWSER", "chromium")
    os.environ["PYTHONIOENCODING"] = "utf-8"

    rc = 0
    try:
        for market in args.market:
            out = OUT_ROOT / slug_of(market, args.country)
            print(f"[classify] {market} -> {out}", flush=True)
            try:
                ma = market_analysis(market, out / "market_analysis.json")
                print(f"[classify]   market type {ma.get('market_type')}, player type "
                      f"{ma.get('primary_participant')}", flush=True)
                # A market re-read as B2B gets parameters for that B2B market.
                scope = " ".join(f"{ma.get('market_definition') or ''} {ma.get('core_scope') or ''}".split()) \
                    if ma.get("reclassified_from") else ""
                spec = axes(market, args.country, out / "axes_spec.json", scope)
                print(f"[classify]   X {spec['x']}\n[classify]   Y {spec['y']}", flush=True)
            except Exception as err:  # noqa: BLE001
                print(f"[classify]   FAILED: {err}", flush=True)
                rc = 1
                continue
            payload = build_payload(market, args.country, ma, spec)
            write_json(out / f"{out.name}_classification.json", payload)
            (out / f"{out.name}_classification.html").write_text(render_html(payload), encoding="utf-8")
            print(f"[classify]   written {out.name}_classification.html / .json", flush=True)
    finally:
        try:
            from vendor_intel.scraping.google_ai_mode import close_session

            close_session()
        except Exception:  # noqa: BLE001
            pass
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
