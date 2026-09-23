"""Verify companies belong in a market; assign B2B/B2C-aware provider role(s).

Two-stage classification, both LLM-driven and cached per market (fail-open,
same pattern as axis_define.py / brand_meta.py's display-mode classifier):

Stage 1 — market analysis (`analyze_market`): decide whether the market is
B2B or B2C and, for B2B markets, what provider/participant categories
ACTUALLY exist in THIS market. There is no fixed global taxonomy — a
different market can produce a completely different category set, and a
category is only included when the LLM judges it genuinely meaningful for
that market (never a forced universal list, and "Contract Manufacturer" is
never introduced as a default/global category).

Stage 2 — company role classification (`_classify_company_roles_batch`):
for each company, decide which of that market's categories the company's
own evidence supports. B2C companies always resolve to "Brand / Marketer".
B2B companies may legitimately hold more than one role (e.g. Manufacturer
+ Solution Provider) when the evidence supports it — this is not forced to
a single category.

Two pipelines share this module (chatgpt_expand's landscape scorer and the
deep-crawl quadrant pipeline in synthesize.py), so the public function
signatures below are kept stable: `expected_roles_for_market` still returns
a set[str] of allowed role names for this market (now dynamically produced
instead of one of three fixed sets), and `verify_market_companies` still
tags each kept row's `commercial_role` as a single string (the company's
primary/first role) for that older, single-role-aware call path. New,
richer fields (`commercial_roles`, `role_reasons`) carry the full multi-role
result with reasons for callers that want them.
"""
from __future__ import annotations

import json
import re
from typing import Any

from vendor_intel.quadrant.brand_meta import plain_brand_name

_MARKET_ANALYSIS_SYSTEM = """You analyze ONE market to decide how companies in it should be compared
on a competitive landscape.

Return JSON only:
{
  "market_type": "B2B" | "B2C" | "Hybrid B2B + B2C",
  "market_type_reason": "why this market is B2B or B2C; if hybrid, say so",
  "market_definition": "one short sentence describing what this market is",
  "market_participants": [
    {"type": "...", "definition": "...", "why_relevant": "..."}
  ]
}

If the input includes "market_scope", it is an operator-supplied description
of exactly which companies this market covers. Treat it as authoritative and
narrow the market to it: it exists to separate markets whose names overlap
(e.g. "Drone Sensors" vs "Drone Imaging" vs "Drone LiDAR"). Let it drive
market_definition and which participant types you return.

market_type:
- "B2B": the primary customers/buyers are businesses, institutions, professional
  organizations, governments, or other commercial/industrial entities.
- "B2C": the primary target buyer is an individual consumer or household.
Decide this from the market's actual target customers, purchasing behavior,
distribution model, product/service positioning, buyer type, use case, and
sales channel — not from any single company's marketing language.

HYBRID markets:
If the market genuinely sells to BOTH businesses and individual consumers
(e.g. rooftop solar sold to homeowners AND commercial sites; water bottles
sold in shops AND wholesale to offices), answer "Hybrid B2B + B2C". Do not
force it to one side.
A hybrid market is still ONE landscape: the brand and the company behind it
are the same regardless of which channel a buyer uses, so never split a
company into separate B2B and B2C rows.

market_type_reason: one sentence on WHY this market is B2B, B2C or hybrid,
naming who the primary buyer is.

market_participants — ONLY for B2B markets (return an empty list for B2C):
List the distinct commercial roles that ACTUALLY exist as meaningfully
different participants in THIS specific market. Do not copy a fixed
checklist and do not force every market to have the same categories.
Possible role names include (not a required list — invent a more precise,
market-specific name when it fits better): Manufacturer, Solution Provider,
Service Provider, Distributor, Supplier, Technology Provider, Platform
Provider, Integrator, Consultant, Engineering Provider, Infrastructure
Provider, OEM, Brand / Marketer. Only include a role when it is genuinely a
distinct participant type buyers in this market actually deal with —
omit any role that would not be a meaningful, separate category here.
Never introduce "Contract Manufacturer" as a default category — only use a
market-specific manufacturing role if you have strong, specific evidence
that it is a distinct named participant type in this exact market.
"""

_COMPANY_ROLE_SYSTEM = """You decide which commercial role(s) each company plays in a market, and
whether it belongs in this market's landscape at all.

You are given the market, its market_type, and — for B2B — the list of
allowed_types (this market's own participant categories, each with a
definition) that a company's role(s) MUST be chosen from.

Rules:
- B2C markets: every kept company's role is "Brand / Marketer" — the
  consumer-facing company that develops, owns, markets, distributes, sells,
  or promotes the product/service to consumers.
- B2B markets: assign one or more roles strictly from allowed_types — never
  invent a role outside that list, never assign a role the company's own
  evidence doesn't support. A company legitimately holding multiple roles
  (e.g. it manufactures the product AND delivers it as an integrated
  solution AND services it) should get all of them — do not force a single
  category onto a company the evidence shows plays more than one role.
- Use a manufacturing-type role only when the evidence indicates the company
  actually manufactures/produces the relevant physical product under its own
  production responsibility — never for a reseller, distributor, marketplace,
  or service-only company, and never merely because it sells a physical
  product.
- Use a solution-type role only when the company provides an integrated
  technology/product/system solution that solves a customer/business
  problem — never merely because it has a technology-sounding website.
- Use a service-type role only when the company's primary commercial
  offering is an ongoing or professional service (installation, maintenance,
  consulting, integration, support) rather than primarily manufacturing or
  reselling the underlying product — never merely because it has support
  staff.
- If evidence is insufficient to confidently support a role, do not assign
  it — choose the closest defensible role and explain the uncertainty rather
  than inventing one.
- Drop companies that don't belong in this market landscape at all (pure
  big-box retailers unless they own a private-label brand sold in this
  market; country-name placeholders).

For each role assigned, give a concise, market-specific reason grounded in
what the company actually does in THIS market — not a generic template that
only swaps the company name (bad: "Company is a manufacturer."; good:
"produces the filtration equipment itself and supplies it directly to
industrial customers under its own production operations.").

Return JSON only:
{
  "items": [
    {
      "i": 0,
      "in_market": true,
      "roles": [{"type": "...", "reason": "..."}],
      "confidence": 0.0-1.0
    }
  ]
}

roles must be empty when in_market is false. Every kept item MUST have at
least one role, and every role's "type" MUST be one of allowed_types (or
"Brand / Marketer" for a B2C market).
"""

_B2C_ROLE = "Brand / Marketer"

# Cached per (market, industry_group, industry_category) — one LLM call per
# unique market, same fail-open contract as axis_define.py / brand_meta.py's
# display-mode classifier.
_MARKET_ANALYSIS_CACHE: dict[tuple[str, str, str], dict[str, Any]] = {}


def _client_or_none(settings: Any, client: Any) -> tuple[Any, Any]:
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
        return None, settings
    if client is None or not getattr(client, "available", False):
        return None, settings
    return client, settings


def _scope_hint() -> str:
    """Operator-supplied scope for the market being analysed, if any.

    Set per run via MARKET_SCOPE. Several queued markets share a name stem
    ("Drone Sensors", "Drone Imaging", "Drone LiDAR") and would otherwise be
    analysed into near-identical cohorts; this states which slice is meant.
    Empty by default, so nothing changes for markets that do not set it.
    """
    import os

    return " ".join(str(os.getenv("MARKET_SCOPE") or "").split())[:900]


def analyze_market(
    market: str,
    *,
    industry_group: str = "",
    industry_category: str = "",
    settings: Any = None,
    client: Any = None,
) -> dict[str, Any]:
    """Stage 1: this market's B2B/B2C type + its own dynamic provider categories.

    Cached per market. Returns:
    {"market_type": "B2B"|"B2C", "market_definition": str,
     "market_participants": [{"type","definition","why_relevant"}, ...]}
    market_participants is always [] for B2C.
    """
    scope = _scope_hint()
    cache_key = (
        str(market or "").strip().lower(),
        str(industry_group or "").strip().lower(),
        str(industry_category or "").strip().lower(),
        scope.lower(),
    )
    cached = _MARKET_ANALYSIS_CACHE.get(cache_key)
    if cached:
        return cached

    result: dict[str, Any] = {
        "market_type": "B2C",
        "market_type_reason": "",
        "market_definition": "",
        "market_participants": [],
    }
    resolved_client, resolved_settings = _client_or_none(settings, client)
    if resolved_client is not None:
        try:
            raw = resolved_client.complete_json(
                _MARKET_ANALYSIS_SYSTEM,
                json.dumps(
                    {
                        "market": market,
                        "industry_group": industry_group,
                        "industry_category": industry_category,
                        # Optional operator-supplied scope. Several markets
                        # here share a name stem ("Drone ...") but mean very
                        # different cohorts, so this says which one.
                        **({"market_scope": scope} if scope else {}),
                    },
                    ensure_ascii=False,
                ),
                model=getattr(resolved_settings, "classifier_model", None) if resolved_settings else None,
                max_tokens=1200,
            )
            if isinstance(raw, dict):
                mtype = str(raw.get("market_type") or "").strip().upper()
                if mtype in ("B2B", "B2C"):
                    result["market_type"] = mtype
                result["market_definition"] = str(raw.get("market_definition") or "").strip()
                result["market_type_reason"] = str(
                    raw.get("market_type_reason") or ""
                ).strip()
                participants = []
                if result["market_type"] == "B2B":
                    for p in raw.get("market_participants") or []:
                        if not isinstance(p, dict):
                            continue
                        ptype = str(p.get("type") or "").strip()
                        if not ptype or ptype.strip().lower() == "contract manufacturer":
                            continue
                        participants.append(
                            {
                                "type": ptype,
                                "definition": str(p.get("definition") or "").strip(),
                                "why_relevant": str(p.get("why_relevant") or "").strip(),
                            }
                        )
                result["market_participants"] = participants
        except Exception as exc:
            print(f"  [relevance] market analysis LLM failed: {exc}", flush=True)

    if result["market_type"] == "B2B" and not result["market_participants"]:
        # Fail-open floor only, reached when the LLM call above is
        # unavailable or fails to parse — never a hardcoded taxonomy the
        # LLM is otherwise forced into.
        result["market_participants"] = [
            {
                "type": "Manufacturer",
                "definition": "Produces the core product/equipment sold in this market.",
                "why_relevant": "Fallback participant used when market analysis is unavailable.",
            }
        ]

    _MARKET_ANALYSIS_CACHE[cache_key] = result
    return result


def market_provider_type_names(market_analysis: dict[str, Any]) -> list[str]:
    """This market's allowed provider category names, in order."""
    if str(market_analysis.get("market_type") or "").upper() == "B2C":
        return [_B2C_ROLE]
    return [
        str(p.get("type") or "").strip()
        for p in market_analysis.get("market_participants") or []
        if str(p.get("type") or "").strip()
    ]


def expected_roles_for_market(
    market: str,
    *,
    industry_group: str = "",
    industry_category: str = "",
    settings: Any = None,
    client: Any = None,
) -> set[str]:
    """Roles to keep on the quadrant for this market — dynamically produced
    per market (Stage 1), not one of a fixed set of global categories."""
    analysis = analyze_market(
        market,
        industry_group=industry_group,
        industry_category=industry_category,
        settings=settings,
        client=client,
    )
    names = market_provider_type_names(analysis)
    return set(names) or {_B2C_ROLE}


def _heuristic_in_market(name: str, market: str, note: str = "") -> bool | None:
    """Return True/False when confident on market-agnostic signals alone, None when unsure (needs LLM)."""
    from vendor_intel.pipeline.ai_brand_discovery import is_market_geo_artifact

    brand = plain_brand_name(name)
    if not brand or is_market_geo_artifact(brand, market):
        return False
    # No name-based company blocklist here: a hardcoded "retailers are never
    # in the market" list (Amazon, Target, Alibaba…) dropped real players in
    # markets such as cloud computing. The LLM role check decides instead.
    return None


def _classify_company_roles_batch(
    batch: list[dict[str, Any]],
    *,
    market: str,
    market_type: str,
    allowed_types: list[dict[str, Any]],
    client: Any,
) -> dict[int, dict[str, Any]]:
    """One LLM call for a batch of companies. Returns {local_i: item_dict}."""
    payload = {
        "market": market,
        "market_type": market_type,
        "allowed_types": (
            [{"type": _B2C_ROLE, "definition": "Consumer-facing brand/marketer."}]
            if market_type == "B2C"
            else [
                {"type": p.get("type"), "definition": p.get("definition")}
                for p in allowed_types
            ]
        ),
        "companies": [
            {
                "i": i,
                "brand": plain_brand_name(r),
                "company": str(r.get("company") or ""),
                "note": str(
                    r.get("ai_overview_note") or r.get("summary") or r.get("role_description") or ""
                )[:300],
            }
            for i, r in enumerate(batch)
        ],
    }
    try:
        raw = client.complete_json(_COMPANY_ROLE_SYSTEM, json.dumps(payload, ensure_ascii=False), max_tokens=3000)
    except Exception as exc:
        print(f"  [relevance] role classification batch failed: {exc}", flush=True)
        return {}
    by_i: dict[int, dict[str, Any]] = {}
    if isinstance(raw, dict):
        for item in raw.get("items") or []:
            if isinstance(item, dict) and "i" in item:
                try:
                    by_i[int(item["i"])] = item
                except (TypeError, ValueError):
                    pass
    return by_i


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
    Drop geo artifacts / off-market rows; tag commercial role(s) for keepers.

    Each kept row gets:
      commercial_role   — primary role, a single string (first assigned role;
                           kept for callers that only understand one role).
      commercial_roles  — every assigned role name, as a list[str].
      role_reasons      — {role_name: reason}, internal/audit use only —
                           never rendered in user-facing HTML/artifacts.
      company_function  — human-readable role summary derived from the
                           assigned role name(s), not a fixed lookup table.

    Returns (filtered_rows, stats).
    """
    from vendor_intel.pipeline.ai_brand_discovery import is_market_geo_artifact

    analysis = analyze_market(
        market, industry_group=industry_group, industry_category=industry_category, settings=settings,
    )
    market_type = str(analysis.get("market_type") or "B2C").upper()
    allowed_types = analysis.get("market_participants") or []
    keep_roles = set(market_provider_type_names(analysis))
    default_role = _B2C_ROLE if market_type == "B2C" else (next(iter(keep_roles), "Manufacturer"))
    stats: dict[str, Any] = {
        "input": len(rows),
        "geo_artifacts": 0,
        "heuristic_drop": 0,
        "llm_drop": 0,
        "kept": 0,
        "player_type": market_type,
        "market_type": market_type,
        "market_definition": analysis.get("market_definition") or "",
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
            _tag_role(row, [default_role], {default_role: "Confirmed by market-fit screening."})
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
                by_i = _classify_company_roles_batch(
                    [r for _, r in batch],
                    market=market,
                    market_type=market_type,
                    allowed_types=allowed_types,
                    client=client,
                )
                if not by_i:
                    for _, r in batch:
                        r2 = dict(r)
                        _tag_role(r2, [default_role], {default_role: "Kept — role classification unavailable this pass."})
                        r2["in_market"] = True
                        llm_keep.append(r2)
                    continue
                for local_i, (_, r) in enumerate(batch):
                    item = by_i.get(local_i) or {}
                    in_m = bool(item.get("in_market", True))
                    raw_roles = [
                        rr for rr in (item.get("roles") or [])
                        if isinstance(rr, dict) and str(rr.get("type") or "").strip()
                    ]
                    role_names = [str(rr.get("type")).strip() for rr in raw_roles]
                    role_names = [rn for rn in role_names if rn in keep_roles]
                    if not in_m or not role_names:
                        stats["llm_drop"] += 1
                        print(
                            f"  [relevance] drop {plain_brand_name(r)!r}: "
                            f"{'out of market' if not in_m else 'no supported role in this market'}",
                            flush=True,
                        )
                        continue
                    reasons = {
                        str(rr.get("type")).strip(): str(rr.get("reason") or "").strip()
                        for rr in raw_roles
                        if str(rr.get("type")).strip() in role_names
                    }
                    r2 = dict(r)
                    _tag_role(r2, role_names, reasons)
                    r2["in_market"] = True
                    llm_keep.append(r2)
        else:
            # No LLM: keep unsure with default role (still drop artifacts/retail)
            for _, r in need_llm:
                r2 = dict(r)
                _tag_role(r2, [default_role], {default_role: "Kept — no classifier available."})
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

    if uniform_role_enabled():
        chosen = _collapse_to_uniform_role(deduped, market_type=market_type)
        stats["uniform_role"] = chosen
        stats["keep_roles"] = [chosen] if chosen else stats["keep_roles"]

    print(
        f"  [relevance] {market}: in={stats['input']} geo_drop={stats['geo_artifacts']} "
        f"heur_drop={stats['heuristic_drop']} llm_drop={stats['llm_drop']} "
        f"kept={stats['kept']} market_type={market_type} "
        + (
            f"uniform_role={stats.get('uniform_role')}"
            if uniform_role_enabled()
            else f"roles={sorted(keep_roles)}"
        ),
        flush=True,
    )
    return deduped, stats


def uniform_role_enabled() -> bool:
    """One role for every company in a market (default ON).

    A competitive quadrant compares like with like, so a landscape that mixes
    Manufacturers with Distributors is not really one peer group. With this
    on, the market's single dominant role is applied to every kept company.

    Set MARKET_UNIFORM_ROLE=false to keep true per-company multi-role
    classification instead.
    """
    import os

    raw = (os.getenv("MARKET_UNIFORM_ROLE") or "").strip().lower()
    if not raw:
        return True
    return raw in {"1", "true", "yes", "on"}


def _collapse_to_uniform_role(
    rows: list[dict[str, Any]], *, market_type: str
) -> str:
    """Force every row onto the market's dominant role, in place.

    The dominant role is the one the LLM assigned most often across this
    market's companies — so it is still evidence-driven, just resolved to a
    single peer group rather than taken per company. Each row keeps its
    original classification in ``commercial_roles_original`` /
    ``role_reasons_original`` for audit.
    """
    if not rows:
        return ""
    if str(market_type).upper() == "B2C":
        chosen = _B2C_ROLE
    else:
        counts: dict[str, int] = {}
        for row in rows:
            # Weight by primary role: that is the company's strongest signal.
            primary = str(row.get("commercial_role") or "").strip()
            if primary:
                counts[primary] = counts.get(primary, 0) + 1
        if not counts:
            return ""
        # Highest count wins; ties broken alphabetically for determinism.
        chosen = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]

    for row in rows:
        original = row.get("commercial_roles") or []
        if original and "commercial_roles_original" not in row:
            row["commercial_roles_original"] = list(original)
            row["role_reasons_original"] = dict(row.get("role_reasons") or {})
        reason = (row.get("role_reasons") or {}).get(chosen) or (
            f"Classified as {chosen}, the primary participant role for this market."
        )
        row["commercial_role"] = chosen
        row["commercial_roles"] = [chosen]
        row["role_reasons"] = {chosen: reason}
        row["company_function"] = chosen.lower()
    return chosen


def _tag_role(row: dict[str, Any], role_names: list[str], reasons: dict[str, str]) -> None:
    role_names = list(dict.fromkeys(n for n in role_names if n))  # de-dupe, keep order
    row["commercial_role"] = role_names[0] if role_names else _B2C_ROLE
    row["commercial_roles"] = role_names or [_B2C_ROLE]
    row["role_reasons"] = reasons
    row["company_function"] = ", ".join(n.lower() for n in row["commercial_roles"])


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
        re.sub(r"[^a-z0-9]", "", plain_brand_name(r).lower()): r for r in kept
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
        src = role_by.get(key) or {}
        nb["commercial_role"] = src.get("commercial_role") or nb.get("commercial_role") or _B2C_ROLE
        nb["commercial_roles"] = src.get("commercial_roles") or [nb["commercial_role"]]
        nb["role_reasons"] = src.get("role_reasons") or {}
        nb["company_function"] = src.get("company_function") or nb["commercial_role"].lower()
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
