"""Verify companies belong in a market; assign a commercial role by market player-type.

The market's PLAYER TYPE is decided once per market by an LLM call (cached), same
fail-open pattern as axis_define.py / brand_meta.py's display-mode classifier:

- "hardware": the market is about physical equipment/devices/machinery/systems.
  Only Manufacturer companies (design/build/sell the hardware) belong on the
  quadrant — integrators, resellers, and component suppliers are dropped.
- "software_service": the market is about software, platforms, IT/cloud, or
  system integration / managed & professional services around a technology.
  Only Solution Developer / Service Provider / System Integrator companies
  belong — hardware-only vendors and resellers are dropped.
- "consumer": everything else (food, pharma, energy, industrial goods, other
  consumer/commercial products). Only Brand or Marketer companies belong.
"""
from __future__ import annotations

import json
import re
from typing import Any

from vendor_intel.quadrant.brand_meta import plain_brand_name

_PLAYER_TYPE_SYSTEM = """You classify ONE market by what TYPE of company should be
compared against each other on a competitive quadrant.

Return JSON only:
{"player_type": "hardware" | "software_service" | "consumer", "reason": "one short sentence"}

Definitions:
- "hardware": the market is about physical equipment / hardware / machinery / devices /
  systems (e.g. servers, chips, packaging machinery, data center equipment, medical
  hardware). Companies compared should be MANUFACTURERS that design, build, and sell
  that equipment — not integrators, resellers, or component suppliers.
- "software_service": the market is about software, platforms, IT/cloud services,
  system integration, or managed/professional services delivered around a technology
  (e.g. SaaS, cybersecurity, system integration, IT consulting, cloud migration,
  data-center managed services). Companies compared should be SOLUTION PROVIDERS /
  SERVICE PROVIDERS / SYSTEM INTEGRATORS that deliver the solution or service — not
  hardware-only vendors or resellers.
- "consumer": everything else — food, beverage, pharma, energy, industrial goods,
  other consumer/commercial products. Companies compared should be BRAND / MARKETER
  companies.
"""

_ROLE_SYSTEM = """You verify whether each company/brand belongs in THIS market landscape,
and assign its commercial role.

You are told this market's player_type and its allowed_roles — every kept company
MUST get one of the allowed_roles; drop anything that fits none of them.

- player_type "hardware": allowed role is "Manufacturer" — a company that designs,
  builds, or sells the physical equipment in this market. Drop integrators, resellers,
  distributors, and component-only suppliers.
- player_type "software_service": allowed roles are "Solution Developer" (builds the
  software/platform), "Service Provider" (delivers managed/professional services), and
  "System Integrator" (integrates/deploys the solution for customers). Drop hardware-only
  vendors and pure resellers.
- player_type "consumer": allowed roles are "Brand" and "Marketer". Decide between them
  per company, using the evidence — do not default to Brand when unsure:
    * "Brand" = owns/manufactures its own product line under its own name
      (runs the factory/plant/production line, or licenses its formulation
      to be made, and sells under that name).
    * "Marketer" = sells/distributes/converts products in this market under
      its own commercial presence, but does not itself manufacture the core
      product — a regional distributor, private-label packer, wholesaler, or
      converter reselling someone else's base material/formulation.
  If the evidence is genuinely ambiguous between the two, prefer "Marketer"
  for a company whose evidence only describes distribution/conversion/sales
  activity with no mention of owning production/manufacturing capacity.

Drop pure big-box retailers (Amazon, Walmart) unless they own a private-label brand
clearly sold in this market. Drop country-name placeholders (e.g. "Avocado Oil India").

Return JSON only:
{
  "items": [
    {
      "i": 0,
      "in_market": true,
      "commercial_role": "Brand" | "Marketer" | "Manufacturer" | "Solution Developer" | "Service Provider" | "System Integrator" | "",
      "confidence": 0.0-1.0,
      "reason": "short"
    }
  ]
}

commercial_role must be empty when in_market is false. Every kept item MUST have a
non-empty commercial_role, and it MUST be one of allowed_roles — never leave it blank
for an in_market item.
"""

_GENERIC_RETAIL = re.compile(
    r"^(amazon(?:\.com)?|walmart|costco|target|carrefour|tesco|alibaba|ebay)\b",
    re.I,
)

_PLAYER_TYPE_KEYWORDS = {
    "software_service": (
        "software", "saas", "platform", "system integrat", "integrator",
        "it service", "cloud service", "managed service", "cybersecurity",
        "consulting", "professional service",
    ),
    "hardware": (
        "hardware", "equipment", "machinery", "device", "server", "chip",
        "semiconductor", "appliance", "system", "infrastructure",
    ),
}

# Cached per (market, industry_group, industry_category) — one LLM call per unique
# market, same fail-open contract as axis_define.py / brand_meta.py's display mode.
_PLAYER_TYPE_CACHE: dict[tuple[str, str, str], str] = {}


def _classify_player_type(
    market: str,
    *,
    industry_group: str = "",
    industry_category: str = "",
    settings: Any = None,
    client: Any = None,
) -> str:
    """LLM decides "hardware" | "software_service" | "consumer" for this market, cached."""
    cache_key = (
        str(market or "").strip().lower(),
        str(industry_group or "").strip().lower(),
        str(industry_category or "").strip().lower(),
    )
    cached = _PLAYER_TYPE_CACHE.get(cache_key)
    if cached:
        return cached

    try:
        from vendor_intel.placeholders.load_keys import apply_env_overrides

        apply_env_overrides()
    except Exception:
        pass
    try:
        from vendor_intel.clients.claude import ClaudeClient
        from vendor_intel.config import Settings

        settings = settings or Settings.load()
        client = client or ClaudeClient(settings)
    except Exception:
        client = None

    result = ""
    if client is not None and getattr(client, "available", False):
        try:
            raw = client.complete_json(
                _PLAYER_TYPE_SYSTEM,
                json.dumps(
                    {
                        "market": market,
                        "industry_group": industry_group,
                        "industry_category": industry_category,
                    },
                    ensure_ascii=False,
                ),
                model=getattr(settings, "classifier_model", None) if settings else None,
                max_tokens=200,
            )
            if isinstance(raw, dict):
                pt = str(raw.get("player_type") or "").strip().lower()
                if pt in ("hardware", "software_service", "consumer"):
                    result = pt
        except Exception as exc:
            print(f"  [relevance] player-type LLM failed: {exc}", flush=True)

    if not result:
        # Keyword fallback — only reached when no LLM is configured/available.
        blob = f"{market} {industry_group} {industry_category}".lower()
        if any(k in blob for k in _PLAYER_TYPE_KEYWORDS["software_service"]):
            result = "software_service"
        elif any(k in blob for k in _PLAYER_TYPE_KEYWORDS["hardware"]):
            result = "hardware"
        else:
            result = "consumer"

    _PLAYER_TYPE_CACHE[cache_key] = result
    return result


def classify_player_type(
    market: str,
    *,
    industry_group: str = "",
    industry_category: str = "",
    settings: Any = None,
    client: Any = None,
) -> str:
    """Public entrypoint: "hardware" | "software_service" | "consumer" for this market.

    Other pipelines (e.g. chatgpt_expand.py's own quadrant scorer) call this
    directly so every entrypoint decides player type the same way, from the
    same cache, instead of re-implementing the classification.
    """
    return _classify_player_type(
        market,
        industry_group=industry_group,
        industry_category=industry_category,
        settings=settings,
        client=client,
    )


_ROLES_BY_PLAYER_TYPE: dict[str, set[str]] = {
    "hardware": {"Manufacturer"},
    "software_service": {"Solution Developer", "Service Provider", "System Integrator"},
    "consumer": {"Brand", "Marketer"},
}

# Default role tagged for a heuristically-confirmed row (fast path, no LLM per-row call).
_DEFAULT_ROLE_BY_PLAYER_TYPE: dict[str, str] = {
    "hardware": "Manufacturer",
    "software_service": "Solution Developer",
    "consumer": "Marketer",
}

_FUNCTION_LABEL_BY_ROLE: dict[str, str] = {
    "Manufacturer": "hardware manufacturer",
    "Solution Developer": "solution provider",
    "Service Provider": "service provider",
    "System Integrator": "system integrator",
    "Brand": "brand",
    "Marketer": "brand / marketer",
}


def expected_roles_for_market(
    market: str,
    *,
    industry_group: str = "",
    industry_category: str = "",
    settings: Any = None,
    client: Any = None,
) -> set[str]:
    """Roles to keep on the quadrant for this market's player type."""
    player_type = _classify_player_type(
        market,
        industry_group=industry_group,
        industry_category=industry_category,
        settings=settings,
        client=client,
    )
    return set(_ROLES_BY_PLAYER_TYPE.get(player_type) or {"Brand", "Marketer"})


def _heuristic_in_market(name: str, market: str, note: str = "") -> bool | None:
    """Return True/False when confident on market-agnostic signals alone, None when unsure (needs LLM)."""
    from vendor_intel.pipeline.ai_brand_discovery import is_market_geo_artifact

    brand = plain_brand_name(name)
    if not brand or is_market_geo_artifact(brand, market):
        return False
    if _GENERIC_RETAIL.match(brand):
        return False
    return None


def verify_market_companies(
    rows: list[dict[str, Any]],
    market: str,
    *,
    settings: Any = None,
    industry_group: str = "",
    industry_category: str = "",
    batch_size: int = 12,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Drop geo artifacts / off-market rows; tag commercial_role for keepers.

    Returns (filtered_rows, stats).
    """
    from vendor_intel.pipeline.ai_brand_discovery import is_market_geo_artifact

    player_type = _classify_player_type(
        market, industry_group=industry_group, industry_category=industry_category,
        settings=settings,
    )
    keep_roles = expected_roles_for_market(
        market, industry_group=industry_group, industry_category=industry_category,
        settings=settings,
    )
    default_role = _DEFAULT_ROLE_BY_PLAYER_TYPE.get(player_type, "Marketer")
    stats: dict[str, Any] = {
        "input": len(rows),
        "geo_artifacts": 0,
        "heuristic_drop": 0,
        "llm_drop": 0,
        "kept": 0,
        "player_type": player_type,
        "keep_roles": sorted(keep_roles),
    }

    survivors: list[dict[str, Any]] = []
    need_llm: list[tuple[int, dict[str, Any]]] = []

    for row in rows:
        name = plain_brand_name(row)
        note = str(row.get("ai_overview_note") or row.get("summary") or row.get("company") or "")
        if not name or is_market_geo_artifact(name, market):
            stats["geo_artifacts"] += 1
            continue
        verdict = _heuristic_in_market(name, market, note)
        if verdict is False:
            stats["heuristic_drop"] += 1
            continue
        if verdict is True:
            row = dict(row)
            row["commercial_role"] = default_role
            row["company_function"] = _FUNCTION_LABEL_BY_ROLE.get(default_role, default_role.lower())
            row["in_market"] = True
            survivors.append(row)
            continue
        need_llm.append((len(survivors) + len(need_llm), row))

    # LLM adjudicate unsure rows
    llm_keep: list[dict[str, Any]] = []
    if need_llm:
        from vendor_intel.clients.claude import ClaudeClient

        client = ClaudeClient(settings) if settings is not None else None
        if client is not None and getattr(client, "available", False):
            for start in range(0, len(need_llm), batch_size):
                batch = need_llm[start : start + batch_size]
                payload = {
                    "market": market,
                    "industry_group": industry_group,
                    "industry_category": industry_category,
                    "player_type": player_type,
                    "allowed_roles": sorted(keep_roles),
                    "companies": [
                        {
                            "i": i,
                            "brand": plain_brand_name(r),
                            "company": str(r.get("company") or ""),
                            "note": str(
                                r.get("ai_overview_note")
                                or r.get("summary")
                                or r.get("role_description")
                                or ""
                            )[:300],
                        }
                        for i, (_, r) in enumerate(batch)
                    ],
                }
                try:
                    raw = client.complete_json(
                        _ROLE_SYSTEM, json.dumps(payload, ensure_ascii=False), max_tokens=2500
                    )
                except Exception as exc:
                    print(f"  [relevance] LLM batch failed: {exc} — keep unsure rows", flush=True)
                    for _, r in batch:
                        r2 = dict(r)
                        r2["commercial_role"] = default_role
                        r2["company_function"] = _FUNCTION_LABEL_BY_ROLE.get(
                            default_role, default_role.lower()
                        )
                        r2["in_market"] = True
                        llm_keep.append(r2)
                    continue
                by_i: dict[int, dict[str, Any]] = {}
                if isinstance(raw, dict):
                    for item in raw.get("items") or []:
                        if isinstance(item, dict) and "i" in item:
                            try:
                                by_i[int(item["i"])] = item
                            except (TypeError, ValueError):
                                pass
                for local_i, (_, r) in enumerate(batch):
                    item = by_i.get(local_i) or {}
                    in_m = bool(item.get("in_market", True))
                    role = str(item.get("commercial_role") or "").strip()
                    if not in_m or (role and role not in keep_roles):
                        stats["llm_drop"] += 1
                        print(
                            f"  [relevance] drop {plain_brand_name(r)!r}: "
                            f"{item.get('reason') or 'out of market / wrong role'}",
                            flush=True,
                        )
                        continue
                    if not role:
                        # Leaving commercial_role blank used to collapse every company to
                        # "Brand" unconditionally. Default to this player type's weaker/
                        # safer claim instead of assuming a role the LLM didn't actually say.
                        role = default_role
                    if role not in keep_roles:
                        stats["llm_drop"] += 1
                        continue
                    r2 = dict(r)
                    r2["commercial_role"] = role
                    r2["company_function"] = _FUNCTION_LABEL_BY_ROLE.get(role, role.lower())
                    r2["in_market"] = True
                    r2["relevance_reason"] = str(item.get("reason") or "")[:200]
                    llm_keep.append(r2)
        else:
            # No LLM: keep unsure with default role (still drop artifacts/retail)
            for _, r in need_llm:
                r2 = dict(r)
                r2["commercial_role"] = default_role
                r2["company_function"] = _FUNCTION_LABEL_BY_ROLE.get(
                    default_role, default_role.lower()
                )
                r2["in_market"] = True
                llm_keep.append(r2)

    out = survivors + llm_keep
    # Dedupe by brand key
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for r in out:
        key = re.sub(r"[^a-z0-9]", "", plain_brand_name(r).lower())
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    stats["kept"] = len(deduped)
    print(
        f"  [relevance] {market}: in={stats['input']} geo_drop={stats['geo_artifacts']} "
        f"heur_drop={stats['heuristic_drop']} llm_drop={stats['llm_drop']} "
        f"kept={stats['kept']} player_type={player_type} roles={sorted(keep_roles)}",
        flush=True,
    )
    return deduped, stats


def filter_quadrant_brands_payload(
    brands: list[dict[str, Any]],
    market: str,
    *,
    settings: Any = None,
    industry_group: str = "",
    industry_category: str = "",
    chart_n: int = 18,
) -> list[dict[str, Any]]:
    """Filter already-scored quadrant brand dicts; re-mark on_chart top chart_n."""
    # Adapt brand dicts to row-like for verify
    rows = []
    for b in brands:
        rows.append(
            {
                "brand": b.get("brand") or b.get("display_name"),
                "company": b.get("company") or b.get("brand"),
                "company_raw": b.get("brand") or b.get("display_name"),
                "ai_overview_note": b.get("top_strength") or "",
                "summary": b.get("company") or "",
                "_orig": b,
            }
        )
    kept, _stats = verify_market_companies(
        rows,
        market,
        settings=settings,
        industry_group=industry_group,
        industry_category=industry_category,
    )
    keep_keys = {
        re.sub(r"[^a-z0-9]", "", plain_brand_name(r).lower()) for r in kept
    }
    role_by = {
        re.sub(r"[^a-z0-9]", "", plain_brand_name(r).lower()): r.get("commercial_role")
        for r in kept
    }
    filtered: list[dict[str, Any]] = []
    for b in brands:
        key = re.sub(
            r"[^a-z0-9]",
            "",
            plain_brand_name(str(b.get("brand") or b.get("display_name") or "")).lower(),
        )
        if key not in keep_keys:
            continue
        nb = dict(b)
        nb["commercial_role"] = role_by.get(key) or nb.get("commercial_role") or "Brand"
        nb["company_function"] = _FUNCTION_LABEL_BY_ROLE.get(
            nb["commercial_role"], str(nb["commercial_role"]).lower()
        )
        filtered.append(nb)

    # Re-rank chart: top chart_n by overall among filtered
    ranked = sorted(
        filtered,
        key=lambda x: int(x.get("overall") or 0),
        reverse=True,
    )
    chart_keys = {
        re.sub(r"[^a-z0-9]", "", plain_brand_name(str(b.get("brand") or "")).lower())
        for b in ranked[: max(1, chart_n)]
    }
    for b in filtered:
        key = re.sub(
            r"[^a-z0-9]",
            "",
            plain_brand_name(str(b.get("brand") or "")).lower(),
        )
        b["on_chart"] = key in chart_keys
    return filtered
