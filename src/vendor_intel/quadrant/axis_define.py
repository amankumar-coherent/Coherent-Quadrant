"""Define market-specific X/Y axis labels, scoring parameters, and explanations.

Catalog leaves provide industry baselines; the LLM refines them for the
exact market query and writes a short definition for each parameter shown
at the end of the HTML report.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any


_SYSTEM = """You define Coherent Quadrant SCORING PARAMETERS for ONE specific market.

The axis TITLES are FIXED for every market and must not be changed:
  X = "Product Strength"
  Y = "Business Strength"

You must output:
1) Exactly 5 X parameters and 5 Y parameters — these ARE the criteria used to score every company
2) A short plain-language DEFINITION for EACH of those 10 parameters (what it means in THIS market)

X parameters = product / tech / operations strength for THIS market only.
Y parameters = commercial scale / customers / finance / growth for THIS market only.

You receive an industry baseline. Refine axis titles AND all 10 parameters so they fit the
exact market query (e.g. semiconductor ≠ flexible packaging ≠ LNG ≠ GLP-1).

Return JSON only:
{
  "x": ["exactly 5 X scoring parameters"],
  "y": ["exactly 5 Y scoring parameters"],
  "x_definitions": {
    "<exact X parameter name>": "1-2 sentences: what this parameter means in this market and what evidence shows strength"
  },
  "y_definitions": {
    "<exact Y parameter name>": "1-2 sentences: what this parameter means in this market and what evidence shows strength"
  },
  "reason": "1-2 sentences why these 10 parameters fit this market"
}

Hard rules:
- The 5 X + 5 Y strings are scored one-by-one for each company. Make them concrete and
  answerable from public evidence (products, fabs, capacity, customers, geography, finance).
- x_definitions keys MUST match the "x" list exactly; y_definitions keys MUST match "y" exactly.
- Definitions must be market-specific (semiconductor process ≠ packaging barrier ≠ LNG assets).
- Do NOT reuse generic ICT fluff when the market needs different dimensions.
- Do NOT return axis titles: X is always "Product Strength" and Y is always
  "Business Strength". Only the 5 parameters under each axis change per market.

WHAT BELONGS ON EACH AXIS (this split is the whole point of the chart):
- X = PRODUCT: what the company BUILDS. Technology, performance, breadth,
  quality, R&D depth, innovation, roadmap, engineering capability.
- Y = BUSINESS: how the company SELLS and OPERATES commercially. Named
  customers and contracts, revenue and growth, funding and ownership,
  headcount, installed base, geographic footprint, channel and partner
  network, market share.
- A parameter about technology, innovation or product development belongs on
  X even if it sounds strategic. "Technology Roadmap", "Innovation Pipeline"
  and "R&D Investment" are X, never Y.
- Every Y parameter must be answerable with a COMMERCIAL fact: a customer
  name, a contract value, a revenue or growth figure, a headcount, a number
  of offices or countries, a named partner, a market share. If the only
  honest evidence for a Y parameter would be a vague phrase like "strong
  presence" or "growing partnerships", it is the wrong parameter -- replace
  it with one that has countable public evidence.
- Exactly 5 on X and 5 on Y. No empty strings. Each name under 80 characters.
- Each definition 1-2 sentences, under 280 characters, no marketing fluff.
"""

_EXPLAIN_SYSTEM = """You explain Coherent Quadrant scoring parameters for ONE market.

Given the market and the exact X/Y parameter names already chosen, write a short
plain-language definition for EACH parameter: what it means in THIS market and what
public evidence would show a company is strong on it.

Return JSON only:
{
  "x_definitions": {
    "<exact X parameter name from input>": "1-2 sentences"
  },
  "y_definitions": {
    "<exact Y parameter name from input>": "1-2 sentences"
  }
}

Rules:
- Keys MUST match the input parameter names exactly (copy verbatim).
- Definitions must be specific to the given market — not generic business jargon.
- 1-2 sentences each, under 280 characters.
- No empty strings.
"""


# Axis NAMES are fixed for every market; only the parameters beneath them
# are market-specific. Exactly this many parameters per axis.
AXIS_X_FIXED = "Product Strength"
AXIS_Y_FIXED = "Business Strength"
PARAMS_PER_AXIS = 5


_AXIS_LLM_RETRIES = 3


def _axis_llm_required() -> bool:
    """LLM-derived axis parameters are mandatory by default.

    The catalog baseline is generic, so falling back to it silently gives a
    market parameters that were never tuned to it — measured live: 3 of 7
    markets ran on catalog values without any error surfacing.
    """
    raw = (os.getenv("EXPAND_MARKET_AXIS_REQUIRE_LLM") or "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _env_enabled() -> bool:
    raw = (os.getenv("EXPAND_MARKET_AXIS_LLM") or "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _clean_feat_list(raw: Any, fallback: list[str], *, n: int = 5) -> list[str]:
    out: list[str] = []
    if isinstance(raw, list):
        for item in raw:
            s = str(item or "").strip()
            if s and s not in out:
                out.append(s)
            if len(out) >= n:
                break
    while len(out) < n and len(fallback) >= n - len(out):
        for f in fallback:
            if f not in out:
                out.append(f)
            if len(out) >= n:
                break
        break
    while len(out) < n:
        out.append(f"Market Criterion {len(out) + 1}")
    return out[:n]


def _clean_axis(name: str, fallback: str) -> str:
    s = re.sub(r"\s+", " ", str(name or "").strip())
    if not s or len(s) > 80:
        return fallback
    return s


def _clean_definitions(
    raw: Any,
    features: list[str],
    *,
    market: str = "",
    axis_label: str = "",
) -> dict[str, str]:
    """Map each feature → definition; fill gaps with a neutral market-aware stub."""
    src: dict[str, str] = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            key = str(k or "").strip()
            val = re.sub(r"\s+", " ", str(v or "").strip())
            if key and val:
                src[key] = val[:400]
    # Also accept list of {parameter, definition} objects
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            key = str(
                item.get("parameter")
                or item.get("feature")
                or item.get("name")
                or ""
            ).strip()
            val = re.sub(
                r"\s+",
                " ",
                str(item.get("definition") or item.get("explanation") or item.get("text") or "").strip(),
            )
            if key and val:
                src[key] = val[:400]

    out: dict[str, str] = {}
    lower_map = {k.lower(): v for k, v in src.items()}
    mkt = market or "this market"
    axis = axis_label or "this axis"
    for feat in features:
        val = src.get(feat) or lower_map.get(feat.lower()) or ""
        if not val:
            # fuzzy contains
            for k, v in src.items():
                if feat.lower() in k.lower() or k.lower() in feat.lower():
                    val = v
                    break
        if not val:
            val = (
                f"In {mkt}, '{feat}' under {axis} measures how strong a company is "
                f"on this dimension based on public product, operational, and commercial evidence."
            )
        out[feat] = val
    return out


def _get_client(settings: Any = None, client: Any = None) -> tuple[Any, Any]:
    # Ensure .env LLM_PROVIDER / DEEPSEEK_* are loaded into placeholder modules
    # before ClaudeClient.available is checked (module defaults to anthropic).
    try:
        from vendor_intel.placeholders.load_keys import apply_env_overrides

        apply_env_overrides()
    except Exception:
        pass
    from vendor_intel.clients.claude import ClaudeClient
    from vendor_intel.config import Settings

    settings = settings or Settings.load()
    client = client or ClaudeClient(settings)
    return settings, client


def define_market_axes(
    market: str,
    industry: dict[str, Any],
    *,
    geography: str = "",
    settings: Any = None,
    client: Any = None,
) -> dict[str, Any]:
    """
    Return industry dict with market-tuned axis_x / axis_y / x / y / definitions.

    Always preserves industry_group / industry_category / selection metadata.
    On LLM failure or disable, returns catalog values and still attempts
    parameter definitions when a client is available.
    """
    base = dict(industry or {})
    # The axis NAMES are fixed for every market; only the 5 parameters under
    # each axis are market-specific. This must hold on the catalog path too:
    # when the LLM call fails the YAML name leaked through, so markets ended
    # up labelled "Packaging Solution Capability" or "Asset & Operating
    # Capability" instead of Product / Business Strength.
    axis_x = AXIS_X_FIXED
    axis_y = AXIS_Y_FIXED
    base["axis_x"] = axis_x
    base["axis_y"] = axis_y
    x_feats = list(base.get("x") or [])
    y_feats = list(base.get("y") or [])
    base["axis_definition_method"] = "catalog"
    base["parameter_definitions"] = {
        "x": dict(base.get("parameter_definitions", {}).get("x") or {}),
        "y": dict(base.get("parameter_definitions", {}).get("y") or {}),
    }

    if not _env_enabled():
        if _axis_llm_required():
            raise RuntimeError(
                "EXPAND_MARKET_AXIS_LLM is off but market-specific axis "
                "parameters are required. Turn it back on, or set "
                "EXPAND_MARKET_AXIS_REQUIRE_LLM=false to accept the generic "
                "catalog baseline."
            )
        return base

    try:
        settings, client = _get_client(settings, client)
    except Exception as exc:  # noqa: BLE001
        if _axis_llm_required():
            raise RuntimeError(
                f"market axis parameters need an LLM client for {market!r}: {exc}"
            ) from exc
        return base

    if client is None or not getattr(client, "available", False):
        if _axis_llm_required():
            raise RuntimeError(
                f"market axis parameters need an available LLM client for {market!r}"
            )
        return base

    payload = {
        "market": market,
        "geography": geography or "global",
        "industry_group": base.get("industry_group") or "",
        "industry_category": base.get("industry_category") or "",
        "baseline": {
            "axis_x": axis_x,
            "axis_y": axis_y,
            "x": x_feats,
            "y": y_feats,
        },
    }
    # The 5 parameters under each axis MUST be market-specific, so the LLM
    # path is not optional: a silent fall back to the catalog gives every
    # market the same generic baseline parameters. Retry before giving up.
    raw = None
    last_err: Exception | None = None
    for attempt in range(1, _AXIS_LLM_RETRIES + 1):
        try:
            raw = client.complete_json(
                _SYSTEM,
                json.dumps(payload, ensure_ascii=False),
                model=getattr(settings, "classifier_model", None),
                max_tokens=2500,
            )
            if isinstance(raw, dict) and raw.get("x") and raw.get("y"):
                break
            last_err = ValueError("axis JSON missing x/y")
            raw = None
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            raw = None
        print(
            f"  [quadrant] market axis LLM attempt {attempt}/{_AXIS_LLM_RETRIES} "
            f"failed: {last_err}",
            flush=True,
        )

    if raw is None:
        if _axis_llm_required():
            # Fail loudly: catalog parameters are generic, so a landscape
            # scored on them is not market-specific at all.
            raise RuntimeError(
                f"market axis parameters could not be derived for {market!r} "
                f"after {_AXIS_LLM_RETRIES} attempts: {last_err}. "
                "Set EXPAND_MARKET_AXIS_REQUIRE_LLM=false to allow the "
                "generic catalog baseline instead."
            )
        print(
            "  [quadrant] WARNING falling back to CATALOG parameters — these "
            "are generic, not market-specific",
            flush=True,
        )
        defs = explain_market_parameters(
            market,
            x_feats,
            y_feats,
            axis_x=axis_x,
            axis_y=axis_y,
            geography=geography,
            settings=settings,
            client=client,
        )
        base["parameter_definitions"] = defs
        base["axis_definition_method"] = "catalog+defs"
        return base

    new_x = _clean_axis(str(raw.get("axis_x") or ""), axis_x)
    new_y = _clean_axis(str(raw.get("axis_y") or ""), axis_y)

    # NEW: Use fixed axis labels for all markets (parameters remain dynamic per market)
    new_x_feats = _clean_feat_list(raw.get("x"), x_feats, n=PARAMS_PER_AXIS)
    new_y_feats = _clean_feat_list(raw.get("y"), y_feats, n=PARAMS_PER_AXIS)
    base["axis_x"] = AXIS_X_FIXED  # Fixed for all markets
    base["axis_y"] = AXIS_Y_FIXED  # Fixed for all markets
    base["x"] = new_x_feats
    base["y"] = new_y_feats
    base["axis_definition_method"] = "llm"
    base["axis_definition_reason"] = str(raw.get("reason") or "").strip()
    base["parameter_definitions"] = {
        "x": _clean_definitions(
            raw.get("x_definitions"),
            new_x_feats,
            market=market,
            axis_label=new_x,
        ),
        "y": _clean_definitions(
            raw.get("y_definitions"),
            new_y_feats,
            market=market,
            axis_label=new_y,
        ),
    }
    # If LLM omitted definitions, fetch them in a second call
    if not any(base["parameter_definitions"]["x"].values()) or not any(
        base["parameter_definitions"]["y"].values()
    ):
        base["parameter_definitions"] = explain_market_parameters(
            market,
            new_x_feats,
            new_y_feats,
            axis_x=new_x,
            axis_y=new_y,
            geography=geography,
            settings=settings,
            client=client,
        )
    return base


def explain_market_parameters(
    market: str,
    x_features: list[str],
    y_features: list[str],
    *,
    axis_x: str = "",
    axis_y: str = "",
    geography: str = "",
    settings: Any = None,
    client: Any = None,
) -> dict[str, dict[str, str]]:
    """LLM definitions for existing parameter names (catalog or previously chosen)."""
    x_features = [str(f).strip() for f in x_features if str(f).strip()]
    y_features = [str(f).strip() for f in y_features if str(f).strip()]
    fallback = {
        "x": _clean_definitions({}, x_features, market=market, axis_label=axis_x),
        "y": _clean_definitions({}, y_features, market=market, axis_label=axis_y),
    }
    if not x_features and not y_features:
        return fallback
    if not _env_enabled():
        return fallback

    try:
        settings, client = _get_client(settings, client)
    except Exception:
        return fallback
    if client is None or not getattr(client, "available", False):
        return fallback

    payload = {
        "market": market,
        "geography": geography or "global",
        "axis_x": axis_x,
        "axis_y": axis_y,
        "x": x_features,
        "y": y_features,
    }
    try:
        raw = client.complete_json(
            _EXPLAIN_SYSTEM,
            json.dumps(payload, ensure_ascii=False),
            model=getattr(settings, "classifier_model", None),
            max_tokens=2000,
        )
    except Exception as exc:
        print(f"  [quadrant] parameter explain LLM failed: {exc}", flush=True)
        return fallback

    if not isinstance(raw, dict):
        return fallback
    return {
        "x": _clean_definitions(
            raw.get("x_definitions") or raw.get("x"),
            x_features,
            market=market,
            axis_label=axis_x,
        ),
        "y": _clean_definitions(
            raw.get("y_definitions") or raw.get("y"),
            y_features,
            market=market,
            axis_label=axis_y,
        ),
    }
