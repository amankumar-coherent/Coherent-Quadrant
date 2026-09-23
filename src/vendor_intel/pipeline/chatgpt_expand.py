"""Full market expand via OpenAI ChatGPT SDK only (no run_query.py).

Steps:
  1) ChatGPT recalls known channel companies for the market
  2) OpenAI SDK web_search discovers companies (+ optional ddgs harvest)
  3) ChatGPT extracts + scores market relevance from ddgs hits (if used)
  4) ChatGPT verifies keep/reject (related to market or not)
  5) Fill columns: Google AI scraper → DDGS/SearXNG/Wikipedia/Owler first,
     then OpenAI SDK web_search residual for leftover Not publicly disclosed gaps
  6) ChatGPT final verify pass on filled rows
  7) Write wrap-formatted FINAL Excel + audit JSON
"""
from __future__ import annotations

import asyncio
import datetime
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

from openai import OpenAI

from vendor_intel.config import Settings
from vendor_intel.pipeline import openai_cost
from vendor_intel.pipeline.openai_expand_checkpoint import ExpandCheckpoint
from vendor_intel.pipeline.run_and_export import auto_seed_names, load_seeds_file
from vendor_intel.pipeline.web_expand import (
    HEADERS,
    MARKET_DEFAULTS,
    _blank_row,
    _norm,
    default_output_dir,
    market_family,
    merge_candidates,
    read_final_rows,
    resolve_final_path,
    web_harvest_candidates,
    write_final_xlsx,
)


def _seed_candidates(
    query: str,
    country: str,
    *,
    seeds_path: str | None = None,
) -> list[dict[str, str]]:
    """Load curated seed companies (e.g. queries/seeds/global_avocado_oil_market.txt)."""
    rows = load_seeds_file(seeds_path) if seeds_path else auto_seed_names(query, country)
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for name, domain, section in rows:
        key = _norm(name)
        if not key or key in seen:
            continue
        seen.add(key)
        website = f"https://{domain}" if domain else ""
        out.append(
            {
                "name": name,
                "website": website,
                "domain": domain or "",
                "snippet": section or "curated seed",
                "source_query": "seed_file",
                "discovery_source": "seed_file",
            }
        )
    return out

_JSON_FENCE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.I)

# One market-neutral hint per mode. Per-industry hints (avocado, firewall,
# smartwatch, green, renewable) were selected by keyword-matching the market
# name, so any new market sharing a word got the wrong industry's wording.
ROLE_HINTS = {
    "general": (
        "distributors, wholesalers, channel partners, VADs, resellers, dealers, "
        "system integrators relevant to the market "
        "(NOT pure OEMs/manufacturers; NOT media/associations)"
    ),
}

LANDSCAPE_ROLE_HINTS = {
    "general": (
        "manufacturers, brand owners, marketers, and solution providers that sell into this market "
        "(NOT media, associations, consultancies, or invented geo-junk names)"
    ),
}

TECH_ROLE_HINT = (
    "solution providers that develop, manufacture, or sell the technology / platform / device "
    "in this market (NOT pure resellers or distributors; NOT media or associations)"
)
BRAND_ROLE_HINT = (
    "brands and marketers of products in this market "
    "(NOT pure big-box retailers unless they own a private-label brand here; "
    "NOT media, associations, or geo-junk names)"
)


def landscape_mode() -> bool:
    """Coherent-Quadrant default: keep OEMs/players. Set EXPAND_LANDSCAPE_MODE=channel to restore vendor-intel."""
    raw = (os.getenv("EXPAND_LANDSCAPE_MODE") or "vendors").strip().lower()
    return raw not in ("0", "false", "no", "off", "channel")


def player_mode(query: str, family: str = "") -> str:
    """Tech markets → solution_provider; all other markets → consumer_brand (brand/marketer).

    Decided per market by company_display_mode's own classification, never
    by keywords in the market name.
    """
    try:
        from vendor_intel.quadrant.brand_meta import company_display_mode

        return company_display_mode(query or "")
    except Exception:
        # company_display_mode already fails open to "consumer_brand" on its
        # own LLM/classification errors — reaching here means something
        # unrelated broke (e.g. an import error), so fall back to the same
        # safe default rather than a hardware/software-style keyword guess.
        return "consumer_brand"


def player_label(query: str, family: str = "") -> str:
    """The single player type this market's landscape is built from.

    Comes from Step 0c's market analysis when it has run, so the verify
    passes require the SAME role that discovery searched for. Without this
    a B2B market whose primary role is e.g. "Substrate and Epitaxial Wafer
    Manufacturer" was verified against a hardcoded "Solution Provider" and
    rejected almost every real company (measured: 2 kept out of 24).

    Falls back to the old tech-vs-consumer binary only before Step 0c has
    run, or for callers outside the expand pipeline.
    """
    cats = _discovery_categories()
    if cats:
        return cats[0]
    if _DISCOVERY_MARKET.get("market_type") == "B2C":
        return "Brand / Marketer"
    if player_mode(query, family) == "solution_provider":
        return "Solution Provider"
    return "Brand / Marketer"



# Set once by Step 0c (market analysis) before discovery runs, so the
# discovery prompts below can ask for the company types that actually exist
# in THIS market. Empty until Step 0c has run; the wording then falls back to
# the pre-existing generic behaviour.
_DISCOVERY_MARKET: dict[str, Any] = {"market_type": "", "categories": []}


def publish_discovery_market(market_analysis: dict[str, Any]) -> list[str]:
    """Publish a Step 0c result (B2B/B2C + participant roles) to the discovery
    prompt builders and return the role list, primary role first.

    Shared by the main run and by the discover -> verify top-up rounds, so a
    top-up batch asks for exactly the same company type as the first batch.
    """
    provider_categories = [
        str(p.get("type") or "").strip()
        for p in (market_analysis.get("market_participants") or [])
        if str(p.get("type") or "").strip()
    ]
    # The LLM named which role the landscape is built from, so it leads.
    primary = str(market_analysis.get("primary_participant") or "").strip()
    if primary:
        provider_categories = [primary] + [
            c for c in provider_categories if c.lower() != primary.lower()
        ]
    set_discovery_market(market_analysis.get("market_type") or "", provider_categories)
    return provider_categories


def set_discovery_market(market_type: str, categories: list[str]) -> None:
    """Publish Step 0c's result to the discovery prompt builders.

    A landscape compares like with like, so the whole pipeline targets ONE
    player type per market. Stage 1 returns every participant category it can
    see (for Silicon Carbide: wafer manufacturer, IDM, foundry, fabless
    designer, materials refiner), but searching for all of them at once finds
    companies that are then rejected by a verify pass demanding a different
    role — measured live: 2 kept out of 24.

    So the PRIMARY category is selected here and used everywhere: discovery
    asks for it, verify requires it, and the Role column shows it. The full
    list is kept for reference/audit only.
    """
    cats = [str(c).strip() for c in categories if str(c).strip()]
    # Normalise rather than upper-case: "Hybrid B2B + B2C" is a real value
    # and .upper() would turn it into a string nothing matches.
    _DISCOVERY_MARKET["market_type"] = (
        _canonical_market_type(market_type) if str(market_type or "").strip() else ""
    )
    _DISCOVERY_MARKET["all_categories"] = cats
    # Stage 1 lists categories in order of centrality to the market, so the
    # first is the primary one. Buyer/channel roles are skipped: a hospital
    # or an end-user industry buys in this market, it does not compete in it.
    _DISCOVERY_MARKET["categories"] = [_primary_category(cats)] if cats else []


# The ONLY player types a landscape may use. Every company in a market gets
# the same one, so buyers compare like with like. "Contract Manufacturer" is
# never permitted.
HYBRID_MARKET_TYPE = "Hybrid B2B + B2C"

ALLOWED_PLAYER_TYPES = (
    "Brand / Marketer",  # B2C
    "Manufacturer",  # B2B physical product
    "Solution Provider",  # B2B technology / platform
    "Service Provider",  # B2B service
)

_PLAYER_TYPE_ALIASES = {
    "brand": "Brand / Marketer",
    "marketer": "Brand / Marketer",
    "brand/marketer": "Brand / Marketer",
    "brand and marketer": "Brand / Marketer",
    "consumer brand": "Brand / Marketer",
    "solution developer": "Solution Provider",
    "technology provider": "Solution Provider",
    "platform provider": "Solution Provider",
    "software provider": "Solution Provider",
    "system integrator": "Solution Provider",
    "integrator": "Solution Provider",
    "oem": "Manufacturer",
    "producer": "Manufacturer",
    "supplier": "Manufacturer",
}


def canonical_player_type(raw: str, *, market_type: str = "") -> str:
    """Force any role label onto the four allowed player types.

    The prompt asks for one of four strings, but a prompt is a request, not a
    guarantee — Stage 1 has returned market-specific phrases like "Silicon
    Carbide Substrate Manufacturer". Those are mapped onto the conventional
    label that is shown in every row of the Role column.

    "Contract Manufacturer" is explicitly collapsed to "Manufacturer": it is
    never allowed to appear as a player type.
    """
    text = re.sub(r"\s+", " ", str(raw or "")).strip()
    if not text:
        return "Brand / Marketer" if str(market_type).upper() == "B2C" else "Manufacturer"
    low = text.lower()

    for allowed in ALLOWED_PLAYER_TYPES:
        if low == allowed.lower():
            return allowed
    if low in _PLAYER_TYPE_ALIASES:
        return _PLAYER_TYPE_ALIASES[low]

    # Market-specific phrasing: classify by the words it contains. Order
    # matters — "…Solutions Manufacturer" is a manufacturer.
    if "manufactur" in low or "producer" in low or "refiner" in low or "fabricat" in low:
        return "Manufacturer"
    if any(w in low for w in ("platform", "software", "technology", "saas", "api", "solution")):
        return "Solution Provider"
    if "service" in low or "consult" in low or "engineering" in low:
        return "Service Provider"
    if any(w in low for w in ("brand", "marketer")):
        return "Brand / Marketer"
    return "Brand / Marketer" if str(market_type).upper() == "B2C" else "Manufacturer"


_BUYER_OR_CHANNEL_HINTS = (
    "healthcare provider",
    "clinic",
    "hospital",
    "pharmacy",
    "end-user",
    "end user",
    "reseller",
    "retailer",
)


def _primary_category(categories: list[str]) -> str:
    """The single player type this market's landscape is built from.

    Prefers the first category that is a genuine market participant rather
    than a buyer or a pure channel — Stage 1 sometimes lists "Clinic /
    Hospital" or "End-User Industry", which are who the market sells TO.
    """
    for cat in categories:
        low = cat.lower()
        if not any(h in low for h in _BUYER_OR_CHANNEL_HINTS):
            return cat
    return categories[0]


def discovery_all_categories() -> list[str]:
    """Every category Stage 1 found, for audit/reporting (not for targeting)."""
    return list(_DISCOVERY_MARKET.get("all_categories") or [])


def _discovery_categories() -> list[str]:
    return list(_DISCOVERY_MARKET.get("categories") or [])


def _is_b2b_market() -> bool:
    """True for B2B and for Hybrid B2B + B2C.

    A hybrid market has a real business side, so its own participant
    categories are meaningful and discovery should target them rather than
    falling back to the consumer-brand wording.
    """
    return _DISCOVERY_MARKET.get("market_type") in ("B2B", HYBRID_MARKET_TYPE)


def _roles_for(family: str, query: str = "") -> str:
    if landscape_mode():
        cats = _discovery_categories()
        if _is_b2b_market() and cats:
            # This market's own participant roles, from Stage 1 — not a fixed
            # hardware/software or tech/brand binary.
            return (
                "Roles that matter in THIS market: "
                + ", ".join(cats)
                + ". A company may legitimately hold more than one of these."
            )
        if _DISCOVERY_MARKET.get("market_type") == "B2C":
            return BRAND_ROLE_HINT
        return TECH_ROLE_HINT if player_mode(query, family) == "solution_provider" else BRAND_ROLE_HINT
    return ROLE_HINTS.get(family, ROLE_HINTS["general"])


def _landscape_list_nouns(query: str, family: str) -> str:
    cats = _discovery_categories()
    if _is_b2b_market() and cats:
        return "REAL companies acting as " + " / ".join(cats)
    if _DISCOVERY_MARKET.get("market_type") == "B2C":
        return "REAL brands and marketers"
    if player_mode(query, family) == "solution_provider":
        return "REAL solution providers / technology vendors"
    return "REAL brands and marketers"


def _landscape_keep_line(query: str, family: str) -> str:
    cats = _discovery_categories()
    if _is_b2b_market() and cats:
        return (
            "KEEP companies whose PRIMARY business makes them one of: "
            + ", ".join(cats)
            + ". DROP consultancies, market-research firms, media, associations, "
            "pure holding companies, and geo-junk names."
        )
    if _DISCOVERY_MARKET.get("market_type") == "B2C":
        return (
            "KEEP brands and marketers of products in this market. "
            "DROP pure retailers (unless private-label in this market), media, associations, and geo-junk names."
        )
    if player_mode(query, family) == "solution_provider":
        return (
            "KEEP solution providers that build the product or platform. "
            "DROP pure resellers, media, associations, and geo-junk names."
        )
    return (
        "KEEP brands and marketers of products in this market. "
        "DROP pure retailers (unless private-label in this market), media, associations, and geo-junk names."
    )


VERIFY_MIN_CONFIDENCE = 70

_TECH_ROLES = frozenset(
    {
        "solution provider",
        "solution developer",
        "oem",
        "vendor",
        "manufacturer",
        "technology vendor",
        "platform vendor",
        "chipmaker",
        "foundry",
        "device maker",
    }
)
_BRAND_ROLES = frozenset(
    {
        "brand / marketer",
        "brand",
        "marketer",
        "brand owner",
        "manufacturer",
        "producer",
        "cpg",
        "pharma",
        "energy producer",
    }
)
_ALWAYS_DROP_ROLES = frozenset(
    {
        "reseller",
        "distributor",
        "wholesaler",
        "retailer",
        "importer",
        "dealer",
        "vad",
        "channel",
        "media",
        "association",
        "research",
        "analyst",
        "consultancy",
        "consultant",
        "geo",
        "government",
        "hospital",
        "clinic",
        "pharmacy",
        "logistics",
        "other",
    }
)


def verify_criteria_prompt(query: str, family: str = "") -> str:
    """Strict Step-4 / Step-6 verifier instructions.

    Fully market-driven: the required company type comes from THIS market's
    own Stage 1 analysis (B2B/B2C plus dynamically generated participant
    categories), so one template serves any market without a per-market
    branch. Earlier versions short-circuited to hand-written prompts for
    semiconductor / GLP-1 / packaging, which cannot scale beyond those few
    demo markets and silently ignored the market analysis.
    """
    cats = _discovery_categories()
    if _is_b2b_market() and cats:
        required = " OR ".join(cats)
        keep_line = (
            "KEEP: companies whose PRIMARY business in this market makes them "
            f"one of: {required}."
        )
        role_line = "In the JSON role field return exactly one of: " + ", ".join(cats) + "."
    else:
        required = player_label(query, family)
        keep_line = (
            "KEEP: companies whose brand is sold in this market, or who "
            "manufacture and market the product under their own name."
        )
        role_line = f"Expected role label: {required}."
    return (
        "You are a strict market-landscape verifier. Decide KEEP or DROP for "
        "each company.\n"
        f"Market: {query}\n"
        f"Required type: {required}\n"
        f"{keep_line}\n"
        "Judge by the company's PRIMARY business — what it IS, not something "
        "it also does.\n"
        "DROP: consultancies, market-research firms, news/media outlets and "
        "industry associations (reporting on or advising a market is not "
        "operating in it), pure holding companies, governments, "
        "country/city/geo labels, and any company that does not genuinely "
        "operate in this market.\n"
        "A parent that does not itself sell in THIS market is a DROP — the "
        "operating subsidiary is the company that belongs here.\n"
        "CONTRACT MANUFACTURERS, OEM/ODM makers and white-label producers are "
        "a DROP: they build to another company's specification and own no "
        "brand here, so they are never the company behind a brand.\n"
        "If you are not sure the company genuinely operates in this market, "
        "DROP.\n"
        f"{role_line}"
    )

def verify_should_keep(
    *,
    in_market: bool,
    role: str,
    builds_or_owns: bool,
    confidence: int,
    expected_role: str,
    min_confidence: int = VERIFY_MIN_CONFIDENCE,
) -> bool:
    """True only when the company matches Solution Provider (tech) or Brand/Marketer (other)."""
    if not in_market or not builds_or_owns:
        return False
    if int(confidence or 0) < int(min_confidence):
        return False
    role_n = re.sub(r"\s+", " ", str(role or "").strip().lower())
    if not role_n or role_n in _ALWAYS_DROP_ROLES:
        return False
    if any(drop in role_n for drop in ("reseller", "distributor", "retailer", "media", "association")):
        return False
    exp = (expected_role or "").strip().lower()
    # The verifier named exactly the role this market requires (any of the
    # four player types, or one of this market's own Step 0c categories):
    # that is a KEEP. Without this a Service Provider market dropped every
    # company the verifier confirmed as "Service Provider", because only the
    # Solution-Provider and Brand branches below existed.
    market_roles = {exp} | {c.strip().lower() for c in _discovery_categories()}
    if role_n in market_roles:
        return True
    if exp == "service provider":
        return "service" in role_n
    if exp == "solution provider":
        return role_n in _TECH_ROLES or "solution" in role_n or "oem" in role_n
    return role_n in _BRAND_ROLES or "brand" in role_n or "market" in role_n


def _verify_parse_row(entry: dict[str, Any], expected_role: str) -> tuple[bool, int, str, str]:
    """Return (keep, confidence, role, reason) from one LLM verify object."""
    fits = entry.get("fits_criteria")
    in_market = bool(entry.get("in_market") if "in_market" in entry else entry.get("related"))
    if fits is False or entry.get("keep") is False:
        in_market = False
    if fits is True:
        in_market = True
    builds = entry.get("builds_or_owns")
    if builds is None:
        builds = bool(fits) if fits is not None else in_market
    builds_or_owns = bool(builds)
    role = str(entry.get("role") or entry.get("commercial_role") or "").strip()
    if not role and fits is True:
        role = expected_role
    try:
        conf = int(entry.get("confidence") or 0)
    except (TypeError, ValueError):
        conf = 0
    reason = str(entry.get("reason") or "").strip()
    keep = verify_should_keep(
        in_market=in_market,
        role=role,
        builds_or_owns=builds_or_owns,
        confidence=conf,
        expected_role=expected_role,
    )
    return keep, conf, role, reason


def _base_url(settings: Settings | None = None) -> str:
    if settings is not None:
        raw = (settings.openai_base_url or "").strip()
        ds = (settings.deepseek_base_url or "").strip()
        provider = (os.getenv("LLM_PROVIDER") or getattr(settings, "llm_provider", "") or "").lower()
        if (not raw or "api.openai.com" in raw.lower()) and ds and (
            provider == "deepseek" or "deepseek" in ds.lower()
        ):
            raw = ds
            if not raw.rstrip("/").endswith("/v1"):
                raw = raw.rstrip("/") + "/v1"
    else:
        raw = (os.getenv("OPENAI_BASE_URL") or "").strip()
    return (raw or "https://api.openai.com/v1").rstrip("/")


def _is_deepseek(settings: Settings | None = None) -> bool:
    """True when OPENAI_* points at DeepSeek (OpenAI-compatible, no hosted web_search)."""
    url = _base_url(settings).lower()
    model = (
        (settings.openai_model if settings else None)
        or os.getenv("OPENAI_MODEL")
        or os.getenv("DEEPSEEK_MODEL")
        or ""
    ).lower()
    provider = (os.getenv("LLM_PROVIDER") or "").lower()
    return "deepseek" in url or model.startswith("deepseek") or provider == "deepseek"


def _supports_hosted_web_search(settings: Settings | None = None) -> bool:
    """OpenAI Responses ``web_search`` is OpenAI-hosted only — not on DeepSeek."""
    return not _is_deepseek(settings)


def _llm_label(settings: Settings | None = None) -> str:
    return "DeepSeek" if _is_deepseek(settings) else "OpenAI"


def _client(settings: Settings) -> OpenAI:
    key = (settings.openai_api_key or settings.deepseek_api_key or "").strip()
    if not key:
        raise RuntimeError("OPENAI_API_KEY or DEEPSEEK_API_KEY not set in .env")
    return OpenAI(
        api_key=key,
        base_url=_base_url(settings),
    )


def _model(settings: Settings) -> str:
    if _is_deepseek(settings):
        default = (
            (settings.deepseek_model or os.getenv("DEEPSEEK_MODEL") or "deepseek-v4-flash")
            .strip()
        )
        mapped = (settings.openai_model or "").strip()
        if mapped and "gpt-" not in mapped.lower():
            return mapped
        return default
    default = "gpt-4o-mini"
    return (settings.openai_model or default).strip() or default


def _log(msg: str) -> None:
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        print(msg.encode("ascii", "replace").decode("ascii"), flush=True)


def _slim_ckpt_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop private keys (snapshots) so checkpoint JSON stays resumable and smaller."""
    return [{k: v for k, v in r.items() if not str(k).startswith("_")} for r in rows]


def _ckpt(
    ckpt: ExpandCheckpoint | None,
    step: str,
    substep: str,
    *,
    note: str = "",
    begin: bool = False,
    progress: dict[str, Any] | None = None,
    **data: Any,
) -> None:
    """Write a checkpoint for this step/substep (no-op if ckpt is None)."""
    if not ckpt:
        return
    if begin:
        ckpt.begin(step, substep, note=note, progress=progress, **data)
    else:
        ckpt.bump(step, substep, note=note, progress=progress, **data)


def _repair_json(raw: str) -> str:
    """Best-effort repair when the model truncates a JSON string mid-response."""
    s = raw.strip()
    if not s:
        return "{}"
    # close open strings / brackets roughly
    if s.count('"') % 2 == 1:
        s += '"'
    # trim broken trailing field
    s = re.sub(r",\s*\"[^\"]*$", "", s)
    s = re.sub(r",\s*$", "", s)
    open_b = s.count("{") - s.count("}")
    open_a = s.count("[") - s.count("]")
    if open_a > 0:
        s += "]" * open_a
    if open_b > 0:
        s += "}" * open_b
    return s


def _parse_json(text: str) -> Any:
    raw = (text or "").strip()
    m = _JSON_FENCE.search(raw)
    if m:
        raw = m.group(1).strip()
    start = raw.find("{")
    start_arr = raw.find("[")
    if start_arr != -1 and (start == -1 or start_arr < start):
        raw = raw[start_arr:]
    elif start != -1:
        raw = raw[start:]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        repaired = _repair_json(raw)
        return json.loads(repaired)


def _assistant_message_text(message: Any) -> str:
    """Prefer visible content; fall back to JSON buried in reasoning_content.

    deepseek-v4-flash thinking mode often spends the whole max_tokens budget on
    reasoning and leaves ``content`` as ``{}`` (2 chars) with finish=length.
    """
    if message is None:
        return ""
    content = str(getattr(message, "content", None) or "").strip()
    reasoning = str(getattr(message, "reasoning_content", None) or "").strip()
    if not content and not reasoning and isinstance(message, dict):
        content = str(message.get("content") or "").strip()
        reasoning = str(message.get("reasoning_content") or "").strip()
    if content and content not in ("{}", "[]") and len(content) > 8:
        return content
    blob = reasoning or content
    if "{" in blob:
        start = blob.find("{")
        end = blob.rfind("}")
        if end > start:
            extracted = blob[start : end + 1].strip()
            if len(extracted) > 8:
                return extracted
    if "[" in blob:
        start = blob.find("[")
        end = blob.rfind("]")
        if end > start:
            extracted = blob[start : end + 1].strip()
            if len(extracted) > 8:
                return extracted
    return content


def _json_missing_required(data: Any, require_key: str | None) -> bool:
    """True when a list-valued key is missing or empty (truncated ``{}`` parse)."""
    if not require_key:
        return False
    if not isinstance(data, dict):
        return True
    val = data.get(require_key)
    return not isinstance(val, list) or len(val) == 0


def _chat_create(client: OpenAI, kwargs: dict[str, Any], *, use_json: bool) -> Any:
    """Create a chat completion; DeepSeek JSON lists need thinking disabled."""
    call = dict(kwargs)
    deepseek = "deepseek" in str(call.get("model") or "").lower() or _is_deepseek()
    if deepseek:
        call["extra_body"] = {"thinking": {"type": "disabled"}}
    try:
        if use_json:
            return client.chat.completions.create(
                response_format={"type": "json_object"},
                **call,
            )
        return client.chat.completions.create(**call)
    except Exception as err:  # noqa: BLE001
        msg = str(err).lower()
        if "extra_body" in msg or "thinking" in msg:
            call.pop("extra_body", None)
            if use_json:
                return client.chat.completions.create(
                    response_format={"type": "json_object"},
                    **call,
                )
            return client.chat.completions.create(**call)
        raise


# Columns the discovery/fill prompts must NOT ask the model to research.
#
# The six contact fields are the single biggest fabrication source: a prompt
# that demands a complete row makes the model invent values to comply
# (measured elsewhere: 94% of one email column was info@<own-domain>, and
# every LinkedIn URL was built from a person's name). They are also worth
# nothing to X/Y scoring, so asking for them buys fabrication risk and
# prompt length for no analytical gain.
#
# Country/Region Code are derived from Headquarters in code, and Distribution
# Type now comes from the two-stage LLM classifier — so the model should not
# be guessing any of them either.
#
# Everything NOT listed here is still requested, because _scoring_row() feeds
# Summary / Specialty Focus / Core Categories / Key Brands Represented /
# Operational Presence into the evidence text that X/Y scoring reads. Dropping
# those would quietly degrade scoring rather than just shrink the prompt.
_UNRESEARCHED_COLUMNS = (
    "Contact Person",
    "Role",
    "Email",
    "LinkedIn",
    "Office No.",
    "Country Code",
    "Region Code",
    "Distribution Type",
)


def _final_verify_enabled() -> bool:
    """Whether Step 6a runs the second verification pass.

    OFF by default. It is a re-check of companies Step 4 already verified,
    scored on Summary / Core Categories / Specialty Focus — fields populated
    by column fill, which is itself off. Judging blank rows and then failing
    closed on the verdict deletes verified companies for no gain.

    Set EXPAND_FINAL_VERIFY=true to restore it (turn column fill on too, or
    it will be judging empty fields).
    """
    return str(os.getenv("EXPAND_FINAL_VERIFY") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _checkpoint_has_scores(ckpt: ExpandCheckpoint) -> bool:
    """True when EVERY checkpointed row carries an X score.

    A finished market must have scores. Without this check a run whose
    scoring step was destroyed by a quota block still counted as done, and
    the report shipped with an empty X/Y/Quadrant column.

    "Every row", not "any row": a run where AI Mode dropped out part-way
    leaves some rows scored and some not, and accepting the first score
    stranded the rest — they were never retried because the market already
    looked finished, and they shipped as blank cells outside every quadrant.
    """
    data = ckpt.state.get("data") or {}
    for key in ("final_rows", "detail_rows", "final_kept"):
        rows = [r for r in (data.get(key) or []) if isinstance(r, dict)]
        if not rows:
            continue
        return all(
            str(row.get("X Score") or row.get("X") or "").strip() for row in rows
        )
    return False


def _column_fill_enabled() -> bool:
    """Whether Step 5 researches the extra landscape columns.

    OFF by default. The report is Brand | Company | Role | Quadrant | X | Y |
    Overall | Found in, and discovery already returns headquarters, ownership
    and website in the same query that finds the company. What Step 5 adds on
    top is contact person, email, LinkedIn and office number — none of which
    reach the report, at the cost of a paced query per company.

    Set EXPAND_COLUMN_FILL=true to restore it for a run that needs the full
    landscape sheet.
    """
    return str(os.getenv("EXPAND_COLUMN_FILL") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def researched_columns() -> list[str]:
    """Landscape columns the model is asked to research."""
    return [h for h in HEADERS if h not in _UNRESEARCHED_COLUMNS]


_DISCOVERY_QUERY_SYSTEM = """You write Google search queries that surface COMPANIES operating in a market.

Return JSON only: {"queries":["...","..."]}

Write 6 queries for the given market. Each must:
- be phrased to return a LIST OF COMPANY NAMES, not articles or definitions
- use the market's OWN industry vocabulary (product names, process names,
  technical terms a practitioner would use) rather than generic wording
- target the participant roles given, when they are provided
- vary in angle: overall leaders, role-specific players, regional coverage,
  reference/encyclopedic listings, and industry-specific terminology
Keep each query under 140 characters. No quotes, no operators, no boolean
syntax — plain keywords only, as a person would type them.
Do NOT invent company names in the queries."""


def _generate_discovery_queries(
    market: str,
    *,
    market_type: str,
    categories: list[str],
    settings: Settings | None = None,
) -> list[str]:
    """Ask AI Mode (LLM when AI Mode is off) for market-specific discovery queries.

    The hand-written templates below are generic by construction — they can
    only interpolate the market name and its role names. A market with its
    own vocabulary ("monopile", "jacket foundation", "OSAT") is better served
    by queries that use those terms, and at thousands of markets no fixed
    template set can cover them.

    Best-effort: returns [] on any failure so the caller falls back to the
    templates rather than losing the step.
    """
    payload = {
        "market": market,
        "market_type": market_type or "",
        "participant_roles": categories or [],
    }
    try:
        # Reuse the pipeline's own client rather than ClaudeClient (used only when AI Mode is off):
        # placeholders/llm.py reads DEEPSEEK_API_KEY from os.environ at import
        # time, but the key lives in .env (read by Settings), so that path
        # reports itself unavailable here.
        s = settings or Settings()
        out = _chat_json(
            _client(s),
            _model(s),
            system=_DISCOVERY_QUERY_SYSTEM,
            user=json.dumps(payload, ensure_ascii=False),
            label="2g-query-gen",
            max_tokens=800,
            retries=2,
            require_key="queries",
            # AI Mode writes the queries too (small prompt, fits the URL);
            # _chat_json only uses the API when AI Mode is switched off.
            use_ai_mode=True,
        )
    except Exception as err:  # noqa: BLE001
        _log(f"    → substep 2g: query generation unavailable ({err}) — using templates")
        return []

    raw = out.get("queries") if isinstance(out, dict) else out
    queries: list[str] = []
    for q in raw or []:
        text = re.sub(r"\s+", " ", str(q or "")).strip().strip('"')
        # Reject anything that is not a usable plain-keyword query.
        if not text or len(text) > 160 or len(text) < 10:
            continue
        if text.lower() in {x.lower() for x in queries}:
            continue
        queries.append(text)
    return queries[:8]


# A Google AI Mode query is a SEARCH BOX, not a chat endpoint: the whole
# prompt rides in ?q=, and Google 400s once the URL passes ~8 KB. The guard
# below measures the ACTUAL encoded URL rather than guessing from prompt
# length — percent-encoding inflates by only ~7%, so a 5 KB prompt is fine
# while an earlier fixed 1,800-char cap needlessly diverted calls that AI
# Mode handles well.
#
# What genuinely does not work is a prompt long enough that build_url has to
# TRUNCATE it: the tail (where the JSON template lives) is cut off, and AI
# Mode answers "Something went wrong, and an AI response wasn't generated."
# Step 5's ~12 KB gap-fill prompt is that case.


def _fits_ai_mode(system: str, user: str, *, label: str = "") -> bool:
    """True when the prompt survives the AI Mode URL intact (no truncation).

    A truncated prompt loses its output template and reliably returns a
    "something went wrong" page, which the caller cannot distinguish from a
    genuinely empty result while every retry burns a paced query.
    """
    from vendor_intel.scraping.google_ai_mode import MAX_URL_CHARS, build_url

    sys_text = (system or "").strip()
    user_text = (user or "").strip()
    prompt = f"{sys_text}\n\n{user_text}" if sys_text else user_text
    # Reserve a little headroom so a prompt right at the boundary does not
    # land on a truncating request.
    encoded = len(build_url(prompt))
    if encoded <= MAX_URL_CHARS - 200:
        return True
    _log(
        f"      · {label}: prompt encodes to {encoded} URL chars "
        f"(limit {MAX_URL_CHARS}) — would be truncated and lose its "
        "output template; using the API backend for this structured call"
    )
    return False


def _verdict_rejects(row: dict[str, Any]) -> bool:
    """True when the model's own verdict says this is not an in-market company.

    The prompt asks for a self-reported ``verdict`` and says "NEVER guess
    this field", but a prompt is a request, not a guarantee — so the
    classification is gated here in code as well. A MISSING verdict is not a
    rejection: older prompts and the discovery paths do not always ask for
    one, and those rows still face the later verify + classification steps.
    """
    verdict = str(row.get("verdict") or "").strip().lower()
    return bool(verdict) and verdict not in {"in_market", "in market"}


def _dedupe_key(name: str) -> str:
    """Identity for duplicate detection during discovery.

    ``web_expand._norm`` only lowercases and collapses whitespace, so it
    treats "Bayer AG" / "Bayer" and "Centrum" / "Centrum Inc" as different
    companies. AI Mode returns exactly those variants across pages, so
    discovery needs suffix- and punctuation-insensitive matching. Shared with
    ai_mode_discovery so both paths agree.
    """
    from vendor_intel.pipeline.ai_mode_discovery import dedupe_key

    return dedupe_key(name)


def _exclusion_names(seen: Any) -> list[str]:
    """Newest-first exclusion names that fit the prompt's character budget.

    The whole prompt rides in the AI Mode URL (?q=), which Google 400s past
    ~8 KB. The exclusion list is the only part that grows per iteration, so
    capping it by NAME COUNT alone is not enough — it must be capped by
    characters. Trimming is safe: this list is only a hint to the model, and
    the authoritative duplicate guard is the caller's own `seen` set, so a
    trimmed name that comes back anyway is still dropped.
    """
    from vendor_intel.pipeline.ai_mode_discovery import (
        _MAX_EXCLUDED_IN_PROMPT,
        _MAX_EXCLUSION_CHARS,
    )

    names = [str(x).strip() for x in seen if str(x or "").strip()]
    picked: list[str] = []
    used = 0
    for name in reversed(names):  # newest first: repeats cluster there
        if len(picked) >= _MAX_EXCLUDED_IN_PROMPT:
            break
        if used + len(name) + 4 > _MAX_EXCLUSION_CHARS:
            break
        picked.append(name)
        used += len(name) + 4  # + JSON quoting/comma overhead
    return picked


_MARKET_ANALYSIS_DISCOVERY_SYSTEM = """You analyze ONE market so a research team knows what kind of companies to
look for in it.

Return JSON only:
{
  "market_type": "B2B" | "B2C" | "Hybrid B2B + B2C",
  "market_type_reason": "why this market is B2B or B2C, and if hybrid, say so",
  "market_definition": "one short sentence describing what this market is",
  "market_participants": [
    {"type": "...", "definition": "...", "why_relevant": "..."}
  ],
  "primary_participant": "...",
  "primary_reason": "one sentence on why this is the main competitive role"
}

market_type:
- "B2B": the primary customers/buyers are businesses, institutions,
  professional organizations, governments, or other commercial/industrial
  entities.
- "B2C": the primary target buyer is an individual consumer or household.
Decide from the market's actual target customers, purchasing behavior,
distribution model, product/service positioning, buyer type, use case and
sales channel — never from one company's marketing language.

HYBRID markets:
If the market genuinely sells to BOTH businesses and individual consumers
(e.g. rooftop solar sold to homeowners AND to commercial sites; water bottles
sold in shops AND wholesale to offices), answer "Hybrid B2B + B2C". Do not
force it to one side.
A hybrid market is still ONE landscape: the brand and the company behind it
are the same regardless of which channel a buyer uses, so never split a
company into separate B2B and B2C rows.

market_type_reason: one sentence on WHY this market is B2B or B2C, naming
who the primary buyer is. If the market sells to both businesses and
consumers, state that it is hybrid and that B2C was chosen because it has a
genuine consumer-facing side.

market_participants — ONLY for B2B markets (return an empty list for B2C):
List the commercial roles that ACTUALLY exist as meaningfully different
participants in THIS specific market. Do not copy a fixed checklist and do
not force every market to have the same categories. Example role names
(NOT a required list — invent a more precise, market-specific name when it
fits better): Manufacturer, Solution Provider, Service Provider,
Distributor, Supplier, Technology Provider, Platform Provider, Integrator,
Consultant, Engineering Provider, Infrastructure Provider, OEM.
Only include a role that is genuinely a distinct participant type buyers in
this market actually deal with. Never introduce "Contract Manufacturer" as
a default category.

primary_participant — the ONE player type the whole landscape is built from.
Every company in this market will be given this role, so all companies are
the same type of player and are compared like with like.

It MUST be exactly one of these four strings — never anything else, never a
market-specific phrase, never "Contract Manufacturer":
- "Brand / Marketer"   — B2C markets ONLY: a consumer-facing company that
  owns and markets the product to individual consumers/households.
- "Manufacturer"       — B2B markets whose defining offering is a PHYSICAL
  product, material, device or component the company produces under its own
  name.
- "Solution Provider"  — B2B markets whose defining offering is TECHNOLOGY:
  a platform, software, API, or an integrated technology system.
- "Service Provider"   — B2B markets whose defining offering is an ongoing
  or professional SERVICE rather than a product someone makes.

Choose by what the companies a buyer actually compares against each other
DO in this market:
- NEVER choose a customer-side role (hospital, clinic, pharmacy, end-user
  industry) — those buy in the market, they do not compete in it.
- NEVER choose a pure channel (reseller, retailer, distributor) unless the
  market IS distribution.
- NEVER choose an upstream input supplier when the market is about the
  finished product. For a market named after a material or product, the
  players are the companies that MAKE that product, not the companies that
  supply feedstock to them.

primary_reason: one sentence naming which of the four you chose and why that
is the right player type for THIS market, referring to what those companies
actually sell. If market_participants lists several roles (e.g. manufacturer,
distributor, solution provider, service provider), say explicitly why the
chosen one is the competitive player and the others are not."""


MARKET_TYPES = ("B2B", "B2C", HYBRID_MARKET_TYPE)


def _canonical_market_type(raw: Any) -> str:
    """Normalise the model's answer onto B2B / B2C / Hybrid B2B + B2C.

    A hybrid market is a real third answer, not a tie to be broken: water
    bottles sell in shops AND wholesale to offices, and forcing that to one
    side misdescribes the market. It is still ONE landscape — the brand and
    the company behind it do not change with the channel.
    """
    text = re.sub(r"\s+", " ", str(raw or "")).strip().lower()
    if not text:
        return "B2C"
    if "hybrid" in text or ("b2b" in text and "b2c" in text):
        return HYBRID_MARKET_TYPE
    if text == "b2b":
        return "B2B"
    if text == "b2c":
        return "B2C"
    return "B2C"


def _analyze_market_for_discovery(
    query: str,
    *,
    settings: Settings | None = None,
    industry_group: str = "",
) -> dict[str, Any]:
    """Stage 1 market analysis, run BEFORE discovery.

    Routes through Google AI Mode when it is on (so the market read is
    grounded in a live web answer) and raises if AI Mode fails; only when AI
    Mode is off does it use the market_relevance LLM path. Both produce the
    same shape, and the result is cached into market_relevance's own cache so
    the scoring stage does not re-ask.

    With AI Mode off, an unavailable LLM fails open to B2C with no categories.
    """
    user = json.dumps(
        {"market": query, "industry_group": industry_group or ""}, ensure_ascii=False
    )
    analysis: dict[str, Any] = {}

    if _ai_mode_active(settings):
        # AI Mode is the ONLY backend for the market read when it is on. No
        # silent DeepSeek fallback, and no silent B2C default either: a wrong
        # market type flips every B2B/B2C rule downstream, so stop the run
        # (Step 0c is checkpointed — a rerun retries just this step).
        try:
            raw = _ai_mode_json(
                _MARKET_ANALYSIS_DISCOVERY_SYSTEM,
                user,
                label="0c-market-analysis",
            )
        except Exception as err:  # noqa: BLE001
            raise RuntimeError(f"Step 0c: AI Mode market analysis failed: {err}") from err
        if not (isinstance(raw, dict) and raw.get("market_type")):
            raise RuntimeError("Step 0c: AI Mode market analysis returned no market_type")
        analysis = raw

    if not analysis.get("market_type"):
        # AI Mode switched off: the market_relevance LLM path is the backend.
        # (market_relevance owns the same two-stage prompt.)
        try:
            from vendor_intel.quadrant.market_relevance import analyze_market

            analysis = analyze_market(
                query, industry_group=industry_group or "", settings=settings
            )
        except Exception as err:  # noqa: BLE001
            _log(f"  [chatgpt] Step 0c: market analysis unavailable: {err}")
            return {"market_type": "B2C", "market_definition": "", "market_participants": []}

    market_type = _canonical_market_type(analysis.get("market_type"))
    participants = [
        p
        for p in (analysis.get("market_participants") or [])
        if isinstance(p, dict)
        and str(p.get("type") or "").strip()
        # Never a default/global Contract Manufacturer category.
        and "contract manufacturer" not in str(p.get("type")).strip().lower()
    ]
    if market_type == "B2C":
        participants = []

    # The LLM names which role a landscape of this market should be built
    # from; the code no longer guesses by taking the first category. Falls
    # back to the first non-buyer/non-channel entry only if it declined.
    primary = str(analysis.get("primary_participant") or "").strip()
    if market_type == "B2C":
        # A consumer-facing market always resolves to the single B2C role.
        primary = "Brand / Marketer"
    else:
        if primary and "contract manufacturer" in primary.lower():
            primary = ""  # never a player type
        if not primary and participants:
            primary = _primary_category([str(p.get("type") or "") for p in participants])
        # Force onto the four allowed labels, whatever the model returned.
        primary = canonical_player_type(primary, market_type=market_type)

    result = {
        "market_type": market_type,
        "market_type_reason": str(analysis.get("market_type_reason") or "").strip(),
        "market_definition": str(analysis.get("market_definition") or "").strip(),
        "market_participants": participants,
        "primary_participant": primary,
        "primary_reason": str(analysis.get("primary_reason") or "").strip(),
    }
    # Seed market_relevance's cache so Stage 1 is not paid for twice.
    try:
        from vendor_intel.quadrant import market_relevance as _mr

        # Key shape must match analyze_market()'s: stripped + lowercased.
        _mr._MARKET_ANALYSIS_CACHE[
            (
                str(query or "").strip().lower(),
                str(industry_group or "").strip().lower(),
                "",
            )
        ] = result
    except Exception:  # noqa: BLE001
        pass
    return result


def _ai_mode_active(settings: Settings | None = None) -> bool:
    """Google AI Mode drives the discovery steps (recall / discover / extract /
    verify / fill) when switched on.

    Scoring and the X/Y axis definitions are NOT affected — those go through
    ClaudeClient (DeepSeek) on a separate path and stay there.
    """
    try:
        from vendor_intel.scraping import google_ai_mode
    except Exception:  # noqa: BLE001
        return False
    if settings is not None and hasattr(settings, "google_ai_mode_enabled"):
        return bool(settings.google_ai_mode_enabled) and google_ai_mode.enabled()
    return google_ai_mode.enabled()


def _ai_mode_json(
    system: str,
    user: str,
    *,
    label: str,
    require_key: str | None = None,
    retries: int = 4,
) -> Any:
    """AI Mode call returning parsed JSON. The ONLY backend for this step.

    There is no API fallback, so this has to absorb transient failures itself
    rather than raising on the first one. The three failure modes need
    opposite responses and are deliberately not conflated: a block wants a
    long cool-off, a refusal wants an immediate reword, and a parse failure
    wants a shorter answer.
    """
    from vendor_intel.scraping import google_ai_mode as gam

    last_err: Exception | None = None
    prompt_user = user
    for attempt in range(1, retries + 1):
        _log(
            f"      · {label}: calling Google AI Mode (udm=50) "
            f"attempt {attempt}/{retries}…"
        )
        try:
            data = gam.chat_json(system, prompt_user, require_key=require_key)
            if _json_missing_required(data, require_key):
                raise ValueError(f"reply missing {require_key or 'items'}")
            _log(f"      · {label}: AI Mode JSON parse OK — {gam.session().status()}")
            return data
        except gam.AiModeCaptcha as err:
            last_err = err
            # Rate limited by IP: only waiting helps. An AI-response QUOTA
            # ("reached the request limit") needs far longer than a CAPTCHA
            # cool-off — Google is metering answers per IP, so a few minutes
            # just burns another attempt against the same wall.
            is_quota = "request limit" in str(err).lower()
            cool_off = (900.0 if is_quota else 300.0) * attempt
            _log(
                f"      · {label}: "
                + ("AI-response quota reached" if is_quota else "rate limited")
                + f" ({err}) — cooling off {cool_off / 60:.0f} min before retrying"
            )
            if attempt < retries:
                time.sleep(cool_off)
        except gam.AiModeRefusal as err:
            last_err = err
            # Waiting is useless; reword and go again immediately.
            _log(f"      · {label}: model refused — rewording and retrying now")
            prompt_user = (
                user + "\n\nAnswer concisely with valid JSON only. Fewer items is fine."
            )
        except (json.JSONDecodeError, ValueError) as err:
            last_err = err
            _log(f"      · {label}: unusable reply ({err}) — asking for shorter JSON")
            prompt_user = (
                user
                + "\n\nIMPORTANT: Return SHORTER valid JSON only. Fewer items if "
                "needed. No markdown, no commentary. Complete all brackets."
            )
        except Exception as err:  # noqa: BLE001
            last_err = err
            _log(f"      · {label}: AI Mode error: {type(err).__name__}: {err}")
    raise RuntimeError(
        f"{label}: Google AI Mode failed after {retries} attempts "
        f"(no API fallback is configured): {last_err}"
    )


def _chat_json(
    client: OpenAI,
    model: str,
    system: str,
    user: str,
    *,
    label: str = "chat",
    max_tokens: int = 4096,
    retries: int = 3,
    require_key: str | None = None,
    use_ai_mode: bool = True,
) -> Any:
    # When AI Mode is on it is the only backend for this step — no API
    # fallback, so a hard failure here stops the run rather than silently
    # spending API credits.
    #
    # use_ai_mode=False is for calls that are NOT company discovery — e.g.
    # writing the discovery queries themselves, which is a reasoning task for
    # DeepSeek, not a web lookup.
    if use_ai_mode and _ai_mode_active() and _fits_ai_mode(system, user, label=label):
        return _ai_mode_json(system, user, label=label, require_key=require_key)

    last_err: Exception | None = None
    provider = "DeepSeek" if "deepseek" in (model or "").lower() or _is_deepseek() else "OpenAI"
    use_json = True
    for attempt in range(1, retries + 1):
        _log(f"      · {label}: calling {provider} ({model}) attempt {attempt}/{retries}…")
        try:
            kwargs: dict[str, Any] = {
                "model": model,
                "temperature": 0.15,
                "max_tokens": max_tokens,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            }
            try:
                resp = _chat_create(client, kwargs, use_json=use_json)
            except Exception as fmt_err:  # noqa: BLE001
                if use_json and (
                    "response_format" in str(fmt_err).lower() or "json" in str(fmt_err).lower()
                ):
                    _log(f"      · {label}: json_object unsupported — plain chat retry")
                    use_json = False
                    resp = _chat_create(client, kwargs, use_json=False)
                else:
                    raise
            rec = openai_cost.record_response_usage(
                resp, label=label, model=model, step=label.split("-")[0]
            )
            if rec:
                sess = openai_cost.get_session()
                run_tot = sess.estimated_cost_usd if sess else rec.estimated_cost_usd
                _log(
                    f"      · {label}: tokens in={rec.prompt_tokens} "
                    f"out={rec.completion_tokens} "
                    f"cost~${rec.estimated_cost_usd:.4f} "
                    f"(run total ~${run_tot:.4f})"
                )
            message = resp.choices[0].message
            content = _assistant_message_text(message)
            finish = getattr(resp.choices[0], "finish_reason", None)
            _log(
                f"      · {label}: got response "
                f"({len(content)} chars, finish={finish})"
            )
            truncated = finish == "length" and len(content) < 40
            if truncated:
                _log(
                    f"      · {label}: thinking burned max_tokens "
                    f"(content={len(content)} chars) — retry with thinking off / shorter JSON"
                )
                last_err = RuntimeError("truncated empty JSON")
                user = (
                    user
                    + "\n\nIMPORTANT: Return compact valid JSON only. "
                    "8-12 items max. No markdown. Complete all brackets."
                )
                max_tokens = min(max(max_tokens, 8192), 16384)
                continue
            try:
                data = _parse_json(content or "{}")
            except json.JSONDecodeError as err:
                last_err = err
                _log(f"      · {label}: JSON parse failed: {err}")
                user = (
                    user
                    + "\n\nIMPORTANT: Return SHORTER valid JSON only. "
                    "Fewer items if needed. No trailing commas. Complete all brackets."
                )
                max_tokens = min(max_tokens + 1024, 16384)
                continue
            if _json_missing_required(data, require_key):
                n = 0
                if isinstance(data, dict) and isinstance(data.get(require_key), list):
                    n = len(data.get(require_key) or [])
                _log(
                    f"      · {label}: JSON parse OK but {require_key or 'items'}={n} "
                    "— retry (empty {} after truncate is not a company list)"
                )
                last_err = RuntimeError(f"missing {require_key}")
                user = (
                    user
                    + "\n\nIMPORTANT: JSON must include a non-empty "
                    f'"{require_key}" array of real companies.'
                )
                continue
            _log(f"      · {label}: JSON parse OK")
            return data
        except Exception as err:  # noqa: BLE001
            last_err = err
            _log(f"      · {label}: API error: {type(err).__name__}: {err}")
    raise RuntimeError(f"{label} failed after {retries} attempts: {last_err}")


def _response_output_text(resp: Any) -> str:
    text = getattr(resp, "output_text", None)
    if isinstance(text, str) and text.strip():
        return text
    parts: list[str] = []
    for item in getattr(resp, "output", None) or []:
        for content in getattr(item, "content", None) or []:
            t = getattr(content, "text", None)
            if isinstance(t, str) and t.strip():
                parts.append(t)
            elif isinstance(content, dict) and content.get("text"):
                parts.append(str(content["text"]))
    return "\n".join(parts).strip()


def _web_search_json(
    client: OpenAI,
    model: str,
    system: str,
    user: str,
    *,
    label: str = "web-fill",
    max_tokens: int = 4096,
    retries: int = 3,
    require_key: str | None = None,
    use_ai_mode: bool = True,
) -> Any:
    """OpenAI Responses API + hosted web_search → JSON; DeepSeek uses chat.completions.

    DeepSeek has no hosted ``web_search`` tool. Skip failed Responses retries and go
    straight to chat (pair with search-stack fill / ddgs harvest for live web facts).

    Google AI Mode, when enabled, is the only backend for this call — it
    searches the live web itself, which suits this step better than a
    knowledge-only chat completion.
    """
    if use_ai_mode and _ai_mode_active() and _fits_ai_mode(system, user, label=label):
        return _ai_mode_json(
            system
            + " Search the web and cite what you find. Mark anything you cannot"
            " verify as Not publicly disclosed.",
            user,
            label=label,
            require_key=require_key,
        )

    if not _supports_hosted_web_search():
        _log(
            f"      · {label}: DeepSeek mode — chat.completions "
            f"(no OpenAI hosted web_search) ({model})"
        )
        return _chat_json(
            client,
            model,
            system=system
            + " Use best public knowledge and any SERP/evidence in the prompt; "
            "mark unknowns Not publicly disclosed. Never invent emails/phones.",
            user=user,
            label=f"{label}-deepseek-chat",
            max_tokens=max_tokens,
            retries=retries,
            require_key=require_key,
        )

    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        _log(
            f"      · {label}: OpenAI web_search ({model}) attempt {attempt}/{retries}…"
        )
        try:
            try:
                resp = client.responses.create(
                    model=model,
                    instructions=system,
                    input=user,
                    tools=[{"type": "web_search"}],
                    tool_choice={"type": "web_search"},
                    temperature=0.15,
                    max_output_tokens=max_tokens,
                    text={"format": {"type": "json_object"}},
                )
            except Exception:
                # Older SDK / model combo: no json_object + tool_choice variants
                resp = client.responses.create(
                    model=model,
                    instructions=system
                    + " Return ONLY a single JSON object. No markdown.",
                    input=user,
                    tools=[{"type": "web_search"}],
                    temperature=0.15,
                    max_output_tokens=max_tokens,
                )
            rec = openai_cost.record_response_usage(
                resp, label=label, model=model, step=label.split("-")[0]
            )
            if rec:
                sess = openai_cost.get_session()
                run_tot = sess.estimated_cost_usd if sess else rec.estimated_cost_usd
                _log(
                    f"      · {label}: tokens in={rec.prompt_tokens} "
                    f"out={rec.completion_tokens} "
                    f"cost~${rec.estimated_cost_usd:.4f} "
                    f"(run total ~${run_tot:.4f})"
                )
            content = _response_output_text(resp) or "{}"
            _log(f"      · {label}: got response ({len(content)} chars)")
            try:
                data = _parse_json(content)
                _log(f"      · {label}: JSON parse OK")
                return data
            except json.JSONDecodeError as err:
                last_err = err
                _log(f"      · {label}: JSON parse fail — retry")
                user = (
                    user
                    + "\n\nIMPORTANT: Return SHORTER valid JSON only with all required keys."
                )
        except Exception as err:  # noqa: BLE001
            last_err = err
            _log(f"      · {label}: API error: {type(err).__name__}: {err}")
            # Fall back to chat completions (no live web) on hard failure
            if attempt == retries:
                _log(f"      · {label}: falling back to chat.completions (no web_search)")
                return _chat_json(
                    client,
                    model,
                    system=system
                    + " Use best public knowledge; mark unknowns Not publicly disclosed.",
                    user=user,
                    label=f"{label}-fallback",
                    max_tokens=max_tokens,
                )
    raise RuntimeError(f"{label} failed after {retries} attempts: {last_err}")


_EMPTYISH = frozenset(
    {
        "",
        "n/a",
        "na",
        "none",
        "null",
        "unknown",
        "-",
        "—",
        "tbd",
        "todo",
    }
)

# Must be web-evidenced or "Not publicly disclosed" — never invent / never generic defaults
_FACT_COLUMNS = frozenset(
    {
        "Founded",
        "Headquarters",
        "Continent / Geography",
        "Operational Presence",
        "Ownership",
        "Employees",
        "Website",
        "Key Brands Represented",
        "Contact Person",
        "Role",
        "Email",
        "LinkedIn",
        "Office No.",
        "Country Code",
        "Region Code",
    }
)

# Placeholder text the old per-industry canned defaults wrote into
# "Key Brands Represented". Recognising it lets rows in older checkpoints be
# treated as unfilled and re-enriched; it never adds behaviour for a market.
_GENERIC_BRAND_MARKERS = (
    "private label",
    "regional avocado",
    "bio-based solvents",
    "cisco; fortinet",
    "apple watch; samsung",
)


def _looks_generic_default(header: str, value: str, family: str) -> bool:
    v = (value or "").strip().lower()
    if not v or v in _EMPTYISH:
        return True
    if header == "Key Brands Represented":
        defaults = MARKET_DEFAULTS.get(family) or {}
        dv = str(defaults.get("Key Brands Represented") or "").strip().lower()
        if v == dv or any(m in v for m in _GENERIC_BRAND_MARKERS):
            return True
    return False


def _ensure_complete_row(
    row: dict[str, str],
    *,
    family: str,
    name: str,
    website: str,
    source: str,
    real_facts_only: bool = True,
) -> dict[str, str]:
    """Guarantee every landscape column has a value (contacts may stay empty)."""
    from vendor_intel.export.landscape_slim import finalize_slim_row

    base = _blank_row(name, website, family, source)
    if real_facts_only:
        for h in _FACT_COLUMNS:
            if h in {
                "Contact Person",
                "Role",
                "Email",
                "LinkedIn",
                "Office No.",
                "Country Code",
                "Region Code",
                "Continent / Geography",
                "Operational Presence",
            }:
                base[h] = ""
            else:
                base[h] = "Not publicly disclosed"
        if website:
            base["Website"] = website
    out = dict(base)
    for h in HEADERS:
        val = str(row.get(h) or "").strip()
        if val.lower() in _EMPTYISH:
            val = ""
        if real_facts_only and h in _FACT_COLUMNS and _looks_generic_default(h, val, family):
            val = ""
        if val:
            out[h] = val
    # Legacy column aliases from older fills
    if not out.get("Office No.") and row.get("Phone / WhatsApp"):
        out["Office No."] = str(row.get("Phone / WhatsApp") or "").strip()
    if not out.get("Continent / Geography") and row.get("Regions Served"):
        out["Continent / Geography"] = str(row.get("Regions Served") or "")
    if not out.get("Operational Presence") and row.get("Cities / Regions"):
        out["Operational Presence"] = str(row.get("Cities / Regions") or "")

    out["Company"] = name or out.get("Company") or "Unknown"
    if website and (
        not out.get("Website")
        or str(out.get("Website")).lower() in _EMPTYISH
        or out.get("Website") == "Not publicly disclosed"
    ):
        out["Website"] = website

    # Contacts stay empty unless we have evidence (do not invent)
    for c in ("Contact Person", "Role", "Email", "LinkedIn", "Office No."):
        if not out.get(c) or str(out.get(c)).lower() in _EMPTYISH or str(out.get(c)).lower() == "not publicly disclosed":
            # keep whatever evidence was set above; else blank
            if str(out.get(c) or "").lower() in _EMPTYISH or str(out.get(c) or "").lower() == "not publicly disclosed":
                if c not in row or not str(row.get(c) or "").strip() or str(row.get(c)).lower() in _EMPTYISH:
                    out[c] = ""

    for h in HEADERS:
        if not str(out.get(h) or "").strip():
            if h in {"Contact Person", "Role", "Email", "LinkedIn", "Office No.", "Country Code", "Region Code"}:
                out[h] = out.get(h) or ""
            elif real_facts_only and h in _FACT_COLUMNS:
                out[h] = "Not publicly disclosed"
            else:
                out[h] = base.get(h) or ""

    out = finalize_slim_row(out)
    # Soft confidence signals kept for internal merges (not in slim Excel)
    founded = str(out.get("Founded") or "")
    hq = str(out.get("Headquarters") or "")
    web = str(out.get("Website") or "")
    real_bits = 0
    if founded and founded != "Not publicly disclosed" and any(ch.isdigit() for ch in founded):
        real_bits += 1
    if hq and hq != "Not publicly disclosed" and len(hq) > 3:
        real_bits += 1
    if web.startswith("http") and "not publicly" not in web.lower():
        real_bits += 1
    brands = str(out.get("Key Brands Represented") or "")
    if brands and brands != "Not publicly disclosed" and not _looks_generic_default(
        "Key Brands Represented", brands, family
    ):
        real_bits += 1
    if real_bits >= 3:
        out["Data Confidence"] = "High"
        out["Quality Score"] = "4"
    elif real_bits >= 1:
        out["Data Confidence"] = "Medium"
        out["Quality Score"] = "3"
    else:
        out["Data Confidence"] = "Low"
        out["Quality Score"] = "2"
    src = out.get("Data Sources") or source
    if source and source not in src:
        out["Data Sources"] = f"{src}; {source}".strip("; ")
    return out


async def _local_web_evidence(name: str, website: str, market: str) -> str:
    """Extra SERP snippets (ddgs) to ground OpenAI fill with real public text."""
    try:
        from vendor_intel.clients.search_router import FreeSearchRouter

        router = FreeSearchRouter(Settings())
        # One fact per Google/DDGS query (same style as Google AI scraper gap-fill)
        qn = f'"{name}"' if " " in name else name
        queries = [
            f"founded year of {qn}",
            f"headquarters of {qn}",
            f"number of employees of {qn}",
            f"official website of {qn}",
            f"operational presence of {qn}",
            f"key brands represented of {qn}",
        ]
        if website:
            queries.append(
                f"site:{website.replace('https://', '').replace('http://', '').split('/')[0]} about"
            )
        bits: list[str] = []
        for q in queries[:4]:
            try:
                hits = await router.search(q, search_topic="general", validation_mode=True)
            except Exception:
                continue
            for h in (hits or [])[:4]:
                title = getattr(h, "title", "") or ""
                link = getattr(h, "link", "") or ""
                snip = getattr(h, "snippet", "") or ""
                bits.append(f"- {title} | {link} | {snip}")
        return "\n".join(bits[:12])
    except Exception as err:  # noqa: BLE001
        return f"(local evidence unavailable: {type(err).__name__})"


def _row_needs_web_refill(row: dict[str, str]) -> bool:
    """True if key firmographic / channel fields are still weak."""
    weak_keys = (
        "Founded",
        "Headquarters",
        "Business Type",
        "Core Categories",
        "Specialty Focus",
        "Website",
        "Regions Served",
        "Summary",
    )
    weak = 0
    for k in weak_keys:
        v = str(row.get(k) or "").strip().lower()
        if not v or v in _EMPTYISH or v == "not publicly disclosed":
            weak += 1
    return weak >= 3


def discover_companies_rounds(
    client: OpenAI,
    model: str,
    *,
    query: str,
    family: str,
    target: int,
    country: str = "",
    ckpt: ExpandCheckpoint | None = None,
) -> list[dict[str, str]]:
    """Find companies in ROUNDS — replaces recall + discover + list-discover.

    Those three stages all asked the same question in different words, so
    once the first took the obvious answers the others re-asked and got the
    same names back. Measured on Silicon Carbide: recall 118, discover 0 new,
    list-discover +1 across 9 queries — ~35 paced queries for almost nothing.

    One loop, one prompt shape, one exclusion list, one stopping rule.
    """
    from vendor_intel.pipeline import discovery_rounds as dr

    player_type = player_label(query, family)
    market_type = str(_DISCOVERY_MARKET.get("market_type") or "B2B")

    out: list[dict[str, str]] = list(ckpt.data("recalled") or []) if ckpt else []
    _ckpt(ckpt, "1_recall", "1a_start", begin=True, note="begin discovery rounds")
    _log(
        f"    → substep 1a: discovery rounds for {player_type} "
        f"(batch {dr.DEFAULT_BATCH}, target {target}"
        + (f", resuming with {len(out)}" if out else "")
        + ")"
    )

    def _ask(system: str, user: str, label: str) -> Any:
        return _chat_json(
            client,
            model,
            system=system,
            user=user,
            label=label,
            max_tokens=3500,
            require_key="companies",
        )

    def _on_round(n: int, new: list[dict[str, Any]], found: list[dict[str, Any]]) -> None:
        _log(f"    → substep 1a.{n}: +{len(new)} (total {len(found)})")
        if ckpt:
            # A run WILL be interrupted; losing one round is cheap, losing
            # the whole set is not.
            ckpt.bump(
                "1_recall",
                f"1a.{n}",
                progress={"round": n, "found": len(found)},
                recalled=_slim_ckpt_rows(_as_seed_rows(found)),
                note=f"round {n}: {len(found)} companies",
            )

    found, stats = dr.discover_in_rounds(
        query,
        player_type,
        ask_json=_ask,
        target=target,
        market_type=market_type,
        dedupe_key=_dedupe_key,
        accept=lambda row: not _verdict_rejects(row),
        on_round=_on_round,
        # Continue from what a previous interrupted run already collected
        # instead of re-asking for it (and then overwriting it on save).
        already_found=_seed_rows_as_found(out),
        # Scoped to one country: narrow by state rather than by world region.
        country=country,
    )

    rows = _as_seed_rows(found)
    resumed = int(stats.get("resumed_with") or 0)
    _log(
        f"    → substep 1a done: {len(rows)} companies in {stats['rounds']} rounds "
        + (f"(resumed with {resumed}) " if resumed else "")
        + f"({stats['stopped_because']})"
    )
    if ckpt:
        # Never let a completed step SHRINK the saved set. Marking the step
        # done overwrites `recalled`, so a run that somehow produced fewer
        # rows than the checkpoint already held would destroy the difference.
        if len(rows) < len(out):
            _log(
                f"    → substep 1a: keeping {len(out)} checkpointed companies "
                f"(this pass produced {len(rows)}) — refusing to shrink"
            )
            rows = out
        ckpt.mark_step_done("1_recall", recalled=_slim_ckpt_rows(rows))
    return rows


def _seed_rows_as_found(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Inverse of ``_as_seed_rows``: checkpoint rows -> discovery-round shape.

    A resumed run reads seed rows back off the checkpoint, but the rounds loop
    dedupes on ``brand`` and builds its exclusion list from it. Handing it seed
    rows unchanged would leave every brand blank, so the whole saved set would
    be dropped and re-discovered.
    """
    out: list[dict[str, Any]] = []
    for r in rows:
        brand = str(r.get("brand_name") or r.get("Market Offering") or "").strip()
        company = str(r.get("Company") or r.get("name") or "").strip()
        if not brand:
            # Older checkpoints predate the brand split; the company name is
            # the best identity available and still dedupes correctly.
            brand = company
        if not brand:
            continue
        out.append(
            {
                "brand": brand,
                "company": company or brand,
                "website": str(r.get("website") or ""),
                "headquarters": str(r.get("Headquarters") or ""),
                "ownership": str(r.get("Ownership") or ""),
                "ownership_confidence": str(r.get("ownership_confidence") or ""),
                "why_related": str(r.get("Summary") or r.get("snippet") or ""),
                "verdict": "in_market",
            }
        )
    return out


def _as_seed_rows(found: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Round output -> the seed-row shape the rest of the pipeline expects."""
    rows: list[dict[str, str]] = []
    for c in found:
        # BRAND -> COMPANY. The brand is what the market knows; the company is
        # the entity behind it. When a company sells only under its own name
        # the two are the same string, which is correct — but they are still
        # resolved separately rather than one being copied from the other.
        brand = str(c.get("brand") or c.get("name") or "").strip()
        company = str(c.get("company") or "").strip() or brand
        if not brand:
            continue
        website = str(c.get("website") or "").strip()
        row = {
            # The pipeline keys rows on `name`; that identity is the COMPANY,
            # so two brands from one owner stay two rows but resolve to the
            # same company in the report.
            "name": company,
            "website": website,
            "domain": website.replace("https://", "").replace("http://", "").split("/")[0],
            "snippet": str(c.get("why_related") or ""),
            "source_query": "discovery_rounds",
            "discovery_source": "discovery_rounds",
            "Company": company,
            # Feeds the report's Brand column via Market Offering.
            "Market Offering": brand,
            "brand_name": brand,
        }
        # Details collected in the SAME round that found the brand, so the
        # later gap-fill pass has little or nothing left to look up.
        for src, dest in (
            ("headquarters", "Headquarters"),
            ("ownership", "Ownership"),
            ("ownership_confidence", "ownership_confidence"),
            ("why_related", "Summary"),
        ):
            val = str(c.get(src) or "").strip()
            if val and val.lower() not in {"n/a", "na", "none", "unknown", ""}:
                row[dest] = val
        rows.append(row)
    return rows


def gpt_recall_companies(
    client: OpenAI,
    model: str,
    *,
    query: str,
    family: str,
    target: int,
    ckpt: ExpandCheckpoint | None = None,
) -> list[dict[str, str]]:
    """ChatGPT lists known real channel companies in small pages (avoids JSON truncate)."""
    roles = _roles_for(family, query)
    want_total = min(max(target, 40), 1200)
    page_size = 35
    out: list[dict[str, str]] = list(ckpt.data("recalled") or []) if ckpt else []
    seen: set[str] = {_dedupe_key(str(r.get("name") or "")) for r in out if r.get("name")}
    start_page = int(ckpt.progress_get("recall_page", 0) or 0) if ckpt else 0
    pages = (want_total + page_size - 1) // page_size
    _ckpt(ckpt, "1_recall", "1a_start", begin=True, note="begin ChatGPT recall")
    _log(
        f"    → substep 1a: recall up to {want_total} companies "
        f"in {pages} page(s) of {page_size}"
        + (f" (resume from page {start_page + 1}, have {len(out)})" if start_page else "")
    )

    for page in range(start_page, pages):
        # Char-budgeted, newest-first. A bare count cap is not enough: 120
        # real names is ~4.7 KB of JSON, which pushed the AI Mode URL past
        # Google's ~8 KB limit and silently truncated the prompt tail.
        exclude = _exclusion_names(seen)
        _log(f"    → substep 1a.{page + 1}: recall page {page + 1}/{pages}…")
        _ckpt(ckpt, "1_recall", f"1a.{page + 1}", begin=True, note=f"begin recall page {page + 1}")
        if landscape_mode():
            system = (
                "You list REAL companies that compete or sell in this market "
                f"({roles}). No invented names. No media, associations, or geo-junk "
                "labels. Return compact JSON only: "
                '{"companies":[{"name":"...","website":"https://...","role":"...",'
                '"country":"...","verdict":"...","why_related":"..."}]}'
            )
            # Seven-part extraction prompt: subject, ask, inclusion by PRIMARY
            # business, typed exclusions WITH reasons, name exclusions,
            # per-field rules, JSON template last (constraints after the
            # template are applied less reliably).
            user = (
                f"Market: {query}\n\n"
                f"List up to {page_size} {_landscape_list_nouns(query, family)} "
                "for this market (diverse countries).\n\n"
                "WHAT QUALIFIES:\n"
                f"{_landscape_keep_line(query, family)}\n"
                "Judge by the company's PRIMARY business — what it IS, not "
                "something it also does.\n\n"
                "STRICTLY EXCLUDE, even if related to this market:\n"
                "- Consultancies, market-research firms, news/media outlets and "
                "industry associations — reporting on or advising a market is not "
                "operating in it.\n"
                "- Pure holding companies with no operating business here.\n"
                "- A parent that does not itself sell in THIS market (name the "
                "operating subsidiary instead).\n"
                "If unsure whether a company genuinely operates here, EXCLUDE it.\n\n"
                "Do NOT repeat any of these (including subsidiaries, aliases or "
                f"former names): {json.dumps(exclude, ensure_ascii=False)}\n\n"
                "FIELD RULES:\n"
                "- name: the operating company's own legal or trade name.\n"
                "- website: the real official company domain. NEVER a LinkedIn, "
                "Bloomberg, Crunchbase or Wikipedia page.\n"
                "- country: the HQ country only.\n"
                '- verdict: "in_market" only if it genuinely operates in this '
                'market; otherwise "unrelated" or "unknown". NEVER guess this '
                'field. Include the company ONLY if verdict is "in_market".\n'
                "- why_related: one sentence naming what it actually makes, "
                "supplies or does in THIS market.\n\n"
                "An empty string is CORRECT and preferred whenever you do not "
                "genuinely know a value. NEVER construct a website from the "
                "company name. A wrong value is much worse than an empty one."
            )
        else:
            system = (
                "You list REAL companies that operate as channel partners for a market "
                f"({roles}). No invented names. No pure OEMs/brands unless they also run "
                "a distribution channel. Return compact JSON only: "
                '{"companies":[{"name":"...","website":"https://...","role":"...",'
                '"country":"...","why_related":"..."}]}'
            )
            user = (
                f"Market: {query}\n"
                f"List up to {page_size} REAL distributors/wholesalers/retailers/"
                "channel partners for this market (diverse countries).\n"
                f"Do NOT repeat these names: {json.dumps(exclude, ensure_ascii=False)}"
            )
        try:
            data = _chat_json(
                client,
                model,
                system=system,
                user=user,
                label=f"recall-page-{page + 1}",
                max_tokens=3500,
                require_key="companies",
            )
        except RuntimeError as err:
            _log(f"    → substep 1a.{page + 1}: recall JSON failed: {err}")
            data = {}
        rows = data.get("companies") if isinstance(data, dict) else []
        added = 0
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                name = str(row.get("name") or "").strip()
                if not name or _dedupe_key(name) in seen:
                    continue
                if _verdict_rejects(row):
                    continue
                seen.add(_dedupe_key(name))
                website = str(row.get("website") or "").strip()
                out.append(
                    {
                        "name": name,
                        "website": website,
                        "domain": website.replace("https://", "")
                        .replace("http://", "")
                        .split("/")[0],
                        "snippet": str(row.get("why_related") or row.get("role") or ""),
                        "source_query": str(row.get("country") or "chatgpt_recall"),
                        "discovery_source": "chatgpt_recall",
                    }
                )
                added += 1
        _log(f"    → substep 1a.{page + 1}: +{added} (total recalled={len(out)})")
        empty_streak = 0 if added else (
            int((ckpt.progress_get("recall_empty", 0) if ckpt else 0) or 0) + 1
        )
        if ckpt:
            ckpt.bump(
                "1_recall",
                f"1a.{page + 1}",
                progress={"recall_page": page + 1, "recall_empty": empty_streak},
                recalled=out,
                note=f"recall page {page + 1}",
            )
        if added == 0:
            if empty_streak >= 3:
                _log("    → substep 1a: 3 empty pages — stop recall")
                break
            _log(f"    → substep 1a: +0 on page {page + 1} (empty streak={empty_streak}) — continue")
    _log(f"    → substep 1a done: {len(out)} companies from ChatGPT knowledge")
    if ckpt:
        ckpt.mark_step_done("1_recall", recalled=out)
    return out


async def google_ai_seed_discover(
    client: OpenAI,
    model: str,
    *,
    query: str,
    family: str,
    target: int,
    exclude: list[str] | None = None,
    ckpt: ExpandCheckpoint | None = None,
) -> list[dict[str, str]]:
    """Pull company lists from Google AI Overview (port 15561), then DeepSeek extracts names."""
    from vendor_intel.clients.google_ai_scraper import (
        google_ai_ask,
        google_ai_discovery_enabled,
    )

    if not google_ai_discovery_enabled():
        return []
    if ckpt and ckpt.data("ga_discover_done"):
        return list(ckpt.data("ga_discovered") or [])

    nouns = _landscape_list_nouns(query, family)
    cats = _discovery_categories()
    # Every query is phrased for THIS market's own participant roles. A B2B
    # service market must not be asked for "manufacturers and brand owners",
    # and a B2C market must not be asked for "suppliers and service
    # providers" — the wording steers what the model returns.
    if _is_b2b_market() and cats:
        role_phrase = " and ".join(c.lower() + "s" for c in cats[:3])
        role_query = f"{query} {role_phrase} list"
        buyer_query = f"{query} suppliers to businesses and institutions list"
    else:
        role_query = f"{query} manufacturers and brand owners list"
        buyer_query = f"{query} consumer brands and product makers list"
    _yr = datetime.date.today().year
    prompts = [
        f"top companies in the {query} list names and official websites",
        f"leading {nouns} worldwide in the {query}",
        f"major {nouns} United States Europe Asia {query}",
        f"{query} key players companies list {_yr - 1} {_yr}",
        f"Wikipedia companies in the {query}",
        role_query,
        buyer_query,
    ]
    # AI Mode (or the LLM when AI Mode is off) writes queries in the market's OWN vocabulary, which the
    # templates above cannot do (they only interpolate the market name and
    # role names). Templates stay as the fallback and as extra coverage.
    generated = _generate_discovery_queries(
        query,
        market_type=str(_DISCOVERY_MARKET.get("market_type") or ""),
        categories=cats,
        settings=Settings(),
    )
    if generated:
        _log(f"    → substep 2g: {len(generated)} market-specific generated queries")
        for g in generated:
            _log(f"        · {g}")
        seen_q = {p.lower() for p in generated}
        prompts = generated + [p for p in prompts if p.lower() not in seen_q]

    seen: set[str] = {_dedupe_key(x) for x in (exclude or []) if x}
    out: list[dict[str, str]] = []

    # AI Mode is stateless, so a query with no exclusion list asks the same
    # question every time and Google returns the same well-known companies.
    # Measured live: 7 queries in a row returned +0 because all 118 already
    # collected names came back again. Naming a few and asking for others
    # pushes it past the obvious answers.
    # Real display names for the prompt. `seen` holds dedupe KEYS
    # ("mitsubishielectric"), which the model cannot read back.
    known_names: list[str] = [str(x).strip() for x in (exclude or []) if str(x).strip()]

    def _with_exclusions(base: str) -> str:
        names = _exclusion_names(known_names)
        if not names:
            return base
        # Keep it short: the whole prompt rides in the URL.
        listed = ", ".join(names[:12])
        more = f" and {len(known_names) - 12} others" if len(known_names) > 12 else ""
        return (
            f"{base}. Exclude {listed}{more} — list DIFFERENT, smaller or "
            "regional companies not already named"
        )

    _log(f"    → substep 2g: Google AI list discover ({len(prompts)} queries)…")
    for i, q in enumerate(prompts, 1):
        q = _with_exclusions(q)
        if len(out) >= target:
            break
        _log(f"    → substep 2g.{i}: Google AI list query {i}/{len(prompts)}")
        try:
            if _ai_mode_active():
                # Google AI Mode (udm=50) via the browser — NOT the old
                # port-15561 AI-Overview scraper service, which is not running.
                from vendor_intel.scraping import google_ai_mode as _gam

                md = str(await asyncio.to_thread(_gam.ask, q) or "").strip()
            else:
                data = await google_ai_ask(q, llm_clean=False)
                md = str(data.get("markdown") or "").strip()
        except Exception as err:  # noqa: BLE001
            # A refusal here used to be swallowed silently, skipping the query
            # without a reword or a session reset — so a soured session just
            # quietly produced fewer companies. Retry once on a fresh session
            # before giving up on this query.
            from vendor_intel.scraping import google_ai_mode as _gam

            if isinstance(err, _gam.AiModeRefusal) and _ai_mode_active():
                _log(
                    f"    → substep 2g.{i}: no answer generated — "
                    "resetting session and retrying once"
                )
                try:
                    await asyncio.to_thread(_gam.session().reset_session)
                    md = str(await asyncio.to_thread(_gam.ask, q) or "").strip()
                except Exception as err2:  # noqa: BLE001
                    _log(f"    → substep 2g.{i}: still failing after reset: {err2}")
                    continue
            else:
                _log(f"    → substep 2g.{i}: AI Mode error: {type(err).__name__}: {err}")
                continue
        if len(md) < 80:
            _log(f"    → substep 2g.{i}: empty overview — skip")
            continue
        try:
            extracted = _chat_json(
                client,
                model,
                system=(
                    "Extract REAL company names from the Google AI Overview text. "
                    f"{_landscape_keep_line(query, family)} "
                    "Return compact JSON only: "
                    '{"companies":[{"name":"...","website":"https://...","role":"...",'
                    '"country":"...","why_related":"..."}]}'
                ),
                user=(
                    f"Market: {query}\n"
                    f"Extract up to 25 distinct {nouns} from this text.\n"
                    f"Text:\n{md[:8000]}"
                ),
                label=f"ga-discover-{i}",
                max_tokens=3500,
                require_key="companies",
            )
        except RuntimeError as err:
            _log(f"    → substep 2g.{i}: extract failed: {err}")
            continue
        rows = extracted.get("companies") if isinstance(extracted, dict) else []
        added = 0
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                name = str(row.get("name") or "").strip()
                if not name or _dedupe_key(name) in seen:
                    continue
                if _verdict_rejects(row):
                    continue
                seen.add(_dedupe_key(name))
                # Keep the readable name so later queries in this loop can
                # exclude it — otherwise every query re-asks the same thing.
                known_names.append(name)
                website = str(row.get("website") or "").strip()
                out.append(
                    {
                        "name": name,
                        "website": website,
                        "domain": website.replace("https://", "")
                        .replace("http://", "")
                        .split("/")[0]
                        .lower(),
                        "snippet": str(row.get("why_related") or row.get("role") or ""),
                        "source_query": str(row.get("country") or "google_ai"),
                        "discovery_source": "google_ai_overview",
                        "relevance": "80",
                    }
                )
                added += 1
        _log(f"    → substep 2g.{i}: +{added} (google-ai discovered total={len(out)})")
        if ckpt:
            ckpt.bump(
                "2_discover",
                f"2g.{i}",
                ga_discovered=out,
                note=f"google AI list {i}",
            )
    _log(f"    → substep 2g done: {len(out)} companies from Google AI Overview")
    if ckpt:
        ckpt.bump(
            "2_discover",
            "2g_done",
            ga_discovered=out,
            ga_discover_done=True,
            note="google AI list discover done",
        )
    return out


def gpt_discover_companies(
    client: OpenAI,
    model: str,
    *,
    query: str,
    family: str,
    target: int,
    exclude: list[str] | None = None,
    max_pages: int = 16,
    page_size: int = 25,
    ckpt: ExpandCheckpoint | None = None,
    seed: list[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    """Find channel companies via OpenAI Responses API ``web_search`` (not ddgs).

    Keeps paging until ``target`` is reached or ``max_pages`` is exhausted.
    An empty page does **not** stop discovery (avoids stalling under target).
    """
    roles = _roles_for(family, query)
    if _is_deepseek():
        page_size = min(page_size, 12)
    out: list[dict[str, str]] = list(ckpt.data("discovered") or []) if ckpt else []
    prior_discovered = list(out)
    seen: set[str] = {_dedupe_key(x) for x in (exclude or []) if x}
    for r in out:
        seen.add(_dedupe_key(str(r.get("name") or "")))
    for r in seed or []:
        name = str(r.get("name") or "").strip()
        if not name or _dedupe_key(name) in seen:
            continue
        seen.add(_dedupe_key(name))
        out.append(r)
    want = max(target, 40)
    # Use full page budget — do not shrink pages so hard that we stop short of target
    pages = max(1, max_pages)
    start_page = int(ckpt.progress_get("discover_page", 0) or 0) if ckpt else 0
    if start_page and not prior_discovered:
        _log(
            f"    → substep 2a: resume had 0 discovered at page {start_page} "
            "— restart discover from page 1"
        )
        start_page = 0
        if ckpt:
            ckpt.state.setdefault("progress", {})["discover_page"] = 0
    geos = [
        "United States",
        "Europe",
        "India",
        "Latin America",
        "Middle East",
        "Asia Pacific",
        "Africa",
        "Canada",
        "United Kingdom",
        "Germany",
        "Brazil",
        "Southeast Asia",
        "Australia / New Zealand",
        "Japan / Korea",
        "global / multi-region",
    ]
    if landscape_mode():
        if player_mode(query, family) == "solution_provider":
            angles = [
                "solution providers and technology vendors ranked for this market",
                "platform / device / chip companies that build the product",
                "industry analyst lists of key technology players",
                "LinkedIn company search for solution providers in this market",
                "trade show exhibitors that sell the technology (not resellers)",
                "Wikipedia and company-site lists of major vendors",
            ]
        else:
            angles = [
                "brand owners and marketers ranked for this market",
                "consumer / commercial brands sold in this market",
                "industry lists of key brands (not retailers-only)",
                "LinkedIn company search for brand owners in this market",
                "trade show exhibitors that market the product",
                "Wikipedia and company-site lists of major brands",
            ]
    else:
        angles = [
            "trade association member directories and accredited distributor lists",
            "\"top distributors\" / \"largest wholesalers\" ranking articles for this market",
            "B2B marketplace seller lists and authorized reseller / partner directories",
            "import/export trading companies and regional importers for this market",
            "national and regional retail chains / specialist retailers in this market",
            "foodservice / HORECA / IT channel / wholesale catalogs (as fits the market)",
            "LinkedIn company search results for distributors and wholesalers",
            "industry expo exhibitor lists and sponsor directories",
        ]
    empty_streak = 0
    _ckpt(ckpt, "2_discover", "2a_start", begin=True, note="begin web discover")
    _log(
        f"    → substep 2a: "
        f"{'DeepSeek chat' if _is_deepseek() else 'OpenAI web_search'} discover "
        f"up to {want} companies "
        f"in ≤{pages} page(s) (continue through empty pages until target)"
        + (f" (resume page {start_page + 1}, have {len(out)})" if start_page else "")
    )
    for page in range(start_page, pages):
        if len(out) >= want:
            _log(
                f"    → substep 2a: hit target ({len(out)}/{want}) — stop discover"
            )
            break
        geo = geos[page % len(geos)]
        angle = angles[page % len(angles)]
        exclude_tail = _exclusion_names(seen)
        need = min(page_size, want - len(out))
        _log(
            f"    → substep 2a.{page + 1}: web discover page {page + 1}/{pages} "
            f"({geo}; {angle[:48]}…, need +{need})…"
        )
        _ckpt(
            ckpt,
            "2_discover",
            f"2a.{page + 1}",
            begin=True,
            note=f"begin discover page {page + 1}",
        )
        try:
            data = _web_search_json(
                client,
                model,
                system=(
                    "You find REAL companies using live web search. "
                    f"Focus on: {roles}. "
                    f"{_landscape_keep_line(query, family)} "
                    "Reject media, research firms, directories, and market-report publishers. "
                    "Return compact JSON only: "
                    '{"companies":[{"name":"...","website":"https://...","role":"...",'
                    '"country":"...","why_related":"..."}]}'
                )
                if landscape_mode()
                else (
                    "You find REAL companies using live web search. "
                    f"Focus on channel roles: {roles}. "
                    "Reject pure OEMs/brands that only manufacture, media, research firms, "
                    "directories, and market-report publishers. "
                    "Prefer distributors, wholesalers, importers, retailers, foodservice suppliers. "
                    "Return compact JSON only: "
                    '{"companies":[{"name":"...","website":"https://...","role":"...",'
                    '"country":"...","why_related":"..."}]}'
                ),
                user=(
                    f"Market: {query}\n"
                    f"Geography focus this page: {geo}\n"
                    f"Search angle this page: {angle}\n"
                    f"Web-search and list up to {need} DISTINCT {_landscape_list_nouns(query, family)} "
                    "for this market.\n"
                    "Prioritize named companies with websites. Avoid repeating prior names.\n"
                    f"Do NOT repeat these names: {json.dumps(exclude_tail, ensure_ascii=False)}"
                )
                if landscape_mode()
                else (
                    f"Market: {query}\n"
                    f"Geography focus this page: {geo}\n"
                    f"Search angle this page: {angle}\n"
                    f"Web-search and list up to {need} DISTINCT real companies that distribute / "
                    "wholesale / import / retail channel this market.\n"
                    "Prioritize named companies with websites. Avoid repeating prior names.\n"
                    "Search listicles, association directories, trade sites, LinkedIn, company sites.\n"
                    f"Do NOT repeat these names: {json.dumps(exclude_tail, ensure_ascii=False)}"
                ),
                label=f"web-discover-{page + 1}",
                max_tokens=3500,
                require_key="companies",
            )
        except RuntimeError as err:
            _log(f"    → substep 2a.{page + 1}: discover JSON failed: {err}")
            data = {}
        rows = data.get("companies") if isinstance(data, dict) else None
        if not isinstance(rows, list) and isinstance(data, dict) and data.get("name"):
            rows = [data]
        added = 0
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                name = str(row.get("name") or "").strip()
                if not name or _dedupe_key(name) in seen:
                    continue
                if _verdict_rejects(row):
                    continue
                seen.add(_dedupe_key(name))
                website = str(row.get("website") or "").strip()
                domain = (
                    website.replace("https://", "")
                    .replace("http://", "")
                    .split("/")[0]
                    .lower()
                )
                out.append(
                    {
                        "name": name,
                        "website": website,
                        "domain": domain,
                        "snippet": str(row.get("why_related") or row.get("role") or ""),
                        "source_query": str(row.get("country") or geo),
                        "discovery_source": "openai_web_search_discover",
                        "relevance": "80",
                    }
                )
                added += 1
        _log(
            f"    → substep 2a.{page + 1}: +{added} "
            f"(openai discovered total={len(out)}/{want})"
        )
        if ckpt:
            ckpt.bump(
                "2_discover",
                f"2a.{page + 1}",
                progress={"discover_page": page + 1},
                discovered=out,
                note=f"discover page {page + 1}",
            )
        if added == 0:
            empty_streak += 1
            _log(
                f"    → substep 2a: +0 new names on page {page + 1} "
                f"(empty streak={empty_streak}) — continuing until target or page budget"
            )
        else:
            empty_streak = 0
    _log(f"    → substep 2a done: {len(out)} companies from "
         f"{'DeepSeek chat' if _is_deepseek() else 'OpenAI web_search'}")
    if ckpt:
        ckpt.mark_step_done("2_discover", discovered=out)
    return out


def gpt_extract_and_score(
    client: OpenAI,
    model: str,
    *,
    query: str,
    family: str,
    candidates: list[dict[str, str]],
    ckpt: ExpandCheckpoint | None = None,
) -> list[dict[str, str]]:
    """Extract companies from search hits and score market relevance 0-100."""
    if not candidates:
        return []

    roles = _roles_for(family, query)
    kept: list[dict[str, str]] = list(ckpt.data("extracted") or []) if ckpt else []
    chunk_size = 15
    start_i = int(ckpt.progress_get("extract_offset", 0) or 0) if ckpt else 0
    total_chunks = (len(candidates) + chunk_size - 1) // chunk_size
    _ckpt(ckpt, "3_ddgs", "3b_start", begin=True, note="begin extract+score")
    _log(
        f"    → substep 3b: score {len(candidates)} web hits "
        f"in {total_chunks} ChatGPT chunk(s)"
        + (f" (resume offset={start_i}, kept={len(kept)})" if start_i else "")
    )
    for i in range(start_i, len(candidates), chunk_size):
        chunk = candidates[i : i + chunk_size]
        idx = i // chunk_size + 1
        _log(f"    → substep 3b.{idx}: extract+score chunk {idx}/{total_chunks} ({len(chunk)} hits)…")
        _ckpt(
            ckpt,
            "3_ddgs",
            f"3b.{idx}",
            begin=True,
            note=f"begin extract chunk {idx}",
        )
        payload = [
            {
                "name": c.get("name"),
                "website": c.get("website"),
                "domain": c.get("domain"),
                "snippet": (c.get("snippet") or "")[:220],
                "source_query": c.get("source_query"),
            }
            for c in chunk
        ]
        data = _chat_json(
            client,
            model,
            system=(
                f"You extract companies that belong in this market landscape. Target roles: {roles}. "
                f"{_landscape_keep_line(query, family)} "
                "Reject media, research firms, directories, job boards, "
                "unrelated product pages, geo-junk names, and companies not related to this market. "
                "Return compact JSON: {\"companies\":[{\"name\":\"...\",\"website\":\"https://...\","
                "\"role\":\"...\",\"country_hint\":\"...\",\"relevance\":0-100,"
                "\"why_related\":\"...\",\"keep\":true|false}]}"
            )
            if landscape_mode()
            else (
                f"You extract channel companies for a market. Target roles: {roles}. "
                "Reject OEMs-only, media, research firms, directories, job boards, "
                "unrelated product pages, and companies not related to this market. "
                "Return compact JSON: {\"companies\":[{\"name\":\"...\",\"website\":\"https://...\","
                "\"role\":\"...\",\"country_hint\":\"...\",\"relevance\":0-100,"
                "\"why_related\":\"...\",\"keep\":true|false}]}"
            ),
            user=(
                f"Market: {query}\nFamily: {family}\n"
                f"Web search candidates:\n{json.dumps(payload, ensure_ascii=False)}\n"
                "Only keep companies clearly related to this market (relevance >= 60)."
            ),
            label=f"extract-{idx}",
            max_tokens=3500,
        )
        rows = data.get("companies") if isinstance(data, dict) else []
        if not isinstance(rows, list):
            continue
        n_keep = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            if row.get("keep") is False:
                continue
            try:
                rel = int(row.get("relevance") or 0)
            except (TypeError, ValueError):
                rel = 0
            if rel < 60:
                continue
            name = str(row.get("name") or "").strip()
            if not name:
                continue
            website = str(row.get("website") or "").strip()
            kept.append(
                {
                    "name": name,
                    "website": website,
                    "domain": website.replace("https://", "").replace("http://", "").split("/")[0],
                    "snippet": str(row.get("why_related") or row.get("role") or ""),
                    "source_query": str(row.get("country_hint") or ""),
                    "discovery_source": "chatgpt_extract",
                    "relevance": str(rel),
                }
            )
            n_keep += 1
        _log(
            f"    → substep 3b.{idx}: kept {n_keep}/{len(chunk)} "
            f"(running total extracted={len(kept)})"
        )
        _ckpt(
            ckpt,
            "3_ddgs",
            f"3b.{idx}",
            progress={"extract_offset": i + chunk_size, "extract_chunk": idx},
            extracted=kept,
            note=f"extract chunk {idx}",
        )
    _log(f"    → substep 3b done: {len(kept)} market-related companies from web")
    return kept


def _market_scope() -> str:
    """Operator-supplied description of exactly which companies qualify.

    Set per run via MARKET_SCOPE. Discovery already uses it to steer what it
    looks for; verify needs the SAME sentence or the two disagree -- a market
    named "Advanced Seismic Data Processing" pulls in earthquake-monitoring
    and structural-engineering software, which share the word "seismic" but
    serve a different buyer entirely. Without the scope, verify has only the
    market title to judge against and keeps them.
    """
    import os

    return " ".join(str(os.getenv("MARKET_SCOPE") or "").split())[:900]


def gpt_verify_market(
    client: OpenAI,
    model: str,
    *,
    query: str,
    family: str,
    companies: list[dict[str, str]],
    ckpt: ExpandCheckpoint | None = None,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Keep only Solution Providers (tech) or Brand/Marketers (other markets)."""
    if not companies:
        return [], []

    expected_role = player_label(query, family)
    criteria = verify_criteria_prompt(query, family)
    _scope = _market_scope()
    kept: list[dict[str, str]] = list(ckpt.data("verified") or []) if ckpt else []
    rejected: list[dict[str, str]] = list(ckpt.data("rejected_mid") or []) if ckpt else []
    chunk_size = 12
    start_i = int(ckpt.progress_get("verify_offset", 0) or 0) if ckpt else 0
    total_chunks = (len(companies) + chunk_size - 1) // chunk_size or 1
    _ckpt(ckpt, "4_verify", "4a_start", begin=True, note="begin market verify")
    _log(
        f"    → substep 4a: verify {len(companies)} candidates as {expected_role} "
        f"in {total_chunks} DeepSeek chunk(s) (drop if they do not build / own-or-market)"
        + (f" (resume offset={start_i}, kept={len(kept)})" if start_i else "")
    )
    json_shape = (
        '{"results":[{"name":"...","in_market":true|false,'
        '"builds_or_owns":true|false,'
        '"role":"Solution Provider|Brand|Marketer|Reseller|Retailer|Distributor|Media|Other",'
        '"fits_criteria":true|false,"confidence":0-100,"reason":"..."}]}'
    )
    for i in range(start_i, len(companies), chunk_size):
        chunk = companies[i : i + chunk_size]
        idx = i // chunk_size + 1
        _log(f"    → substep 4a.{idx}: verify chunk {idx}/{total_chunks}…")
        _ckpt(ckpt, "4_verify", f"4a.{idx}", begin=True, note=f"begin verify chunk {idx}")
        payload = [
            {
                "name": c.get("name") or c.get("Company"),
                "website": c.get("website") or c.get("Website"),
                "snippet": (c.get("snippet") or c.get("Summary") or c.get("why_related") or "")[:280],
                "claimed_role": c.get("role") or c.get("Distribution Type") or "",
            }
            for c in chunk
        ]
        data = _chat_json(
            client,
            model,
            system=(
                f"{criteria}\n"
                + (
                    f"\nTHIS MARKET COVERS EXACTLY: {_scope}\n"
                    "A company that does not do THAT is not in this market, "
                    "however closely its field is named. Set in_market=false "
                    "and fits_criteria=false for it.\n"
                    if _scope
                    else ""
                )
                + "For EACH company you MUST return one result. Never skip a name. "
                "fits_criteria=true only if they match the required type for this market. "
                "When unsure, fits_criteria=false and in_market=false. "
                f"Return compact JSON only: {json_shape}"
            ),
            user=(
                f"Market: {query}\n"
                + (f"Market scope: {_scope}\n" if _scope else "")
                + f"Required type: {expected_role}\n"
                f"Verify these companies (KEEP only {expected_role}):\n"
                f"{json.dumps(payload, ensure_ascii=False)}"
            ),
            label=f"verify-{idx}",
            max_tokens=3500,
            # Same trap as the final pass: without this, a reply that parses
            # as JSON but carries no "results" logs "parse OK" and is then
            # dropped by fail-closed, silently rejecting a whole chunk of
            # real companies.
            require_key="results",
        )
        results = data.get("results") if isinstance(data, dict) else []
        by_name = {_norm(str(c.get("name") or c.get("Company") or "")): c for c in chunk}
        if not isinstance(results, list) or not results:
            _log(f"    → substep 4a.{idx}: empty/invalid verify JSON — DROP chunk (fail closed)")
            for src in chunk:
                rejected.append(
                    {
                        "name": str(src.get("name") or src.get("Company") or ""),
                        "reason": "verify parse failed — dropped",
                        "confidence": "0",
                    }
                )
            if ckpt:
                ckpt.bump(
                    "4_verify",
                    f"4a.{idx}",
                    progress={"verify_offset": i + chunk_size, "verify_chunk": idx},
                    verified=kept,
                    rejected_mid=rejected,
                    note=f"verify chunk {idx} parse-fail drop",
                )
            continue
        seen: set[str] = set()
        for r in results:
            if not isinstance(r, dict):
                continue
            name = str(r.get("name") or "").strip()
            key = _norm(name)
            src = by_name.get(key)
            if not src:
                continue
            seen.add(key)
            keep, conf, role, reason = _verify_parse_row(r, expected_role)
            if keep:
                from vendor_intel.pipeline.role_split import normalize_role_label

                src = dict(src)
                role_n = normalize_role_label(
                    role or expected_role,
                    query=query,
                    company=str(src.get("name") or src.get("Company") or name or ""),
                )
                src["verify_reason"] = reason
                src["verify_confidence"] = str(conf)
                src["commercial_role"] = role_n
                src["Distribution Type"] = role_n
                kept.append(src)
            else:
                rejected.append(
                    {
                        "name": name,
                        "reason": reason or f"not a {expected_role}",
                        "confidence": str(conf),
                        "role": role,
                    }
                )
        for key, src in by_name.items():
            if key in seen:
                continue
            rejected.append(
                {
                    "name": str(src.get("name") or src.get("Company") or ""),
                    "reason": f"not returned by verifier — dropped (must be {expected_role})",
                    "confidence": "0",
                }
            )
        _log(
            f"    → substep 4a.{idx}: running kept={len(kept)} "
            f"rejected={len(rejected)}"
        )
        if ckpt:
            ckpt.bump(
                "4_verify",
                f"4a.{idx}",
                progress={"verify_offset": i + chunk_size, "verify_chunk": idx},
                verified=kept,
                rejected_mid=rejected,
                note=f"verify chunk {idx}",
            )
    _log(
        f"    → substep 4a done: kept={len(kept)} rejected={len(rejected)} "
        f"(required={expected_role})"
    )
    if ckpt:
        ckpt.mark_step_done("4_verify", verified=kept, rejected_mid=rejected)
    return kept, rejected


# Company Details / Coherent Quadrant only ever displays Brand, Company, Role,
# Quadrant, X, Y, Overall, Found in (Headquarters) — X/Y/Overall come from the
# quadrant LLM scoring stage, not this fill step. Website stays in the lean
# set even though it isn't displayed: crawling/evidence still needs it.
_LEAN_FILL_COLUMNS = ("Company", "Website", "Headquarters", "Role", "Summary")


def _company_details_lean_fill_active() -> bool:
    """True when this run should skip researching columns the report never shows.

    Opt-in per run via EXPAND_OUTPUT_FOLDER=chatgpt_expand (same switch
    chatgpt_env.py already uses to restrict the Google AI scraper + DeepSeek
    residual fill to Headquarters/Website), or explicitly via
    CHATGPT_EXPAND_LEAN_FILL=1/0. Existing markets already run — this only
    changes what future runs research, not any stored data.
    """
    override = (os.getenv("CHATGPT_EXPAND_LEAN_FILL") or "").strip().lower()
    if override:
        return override in ("1", "true", "yes", "on")
    return (os.getenv("EXPAND_OUTPUT_FOLDER") or "").strip().lower() == "chatgpt_expand"


async def gpt_fill_rows(
    client: OpenAI,
    model: str,
    *,
    query: str,
    family: str,
    rows: list[dict[str, str]],
    web_fill: bool = True,
    ckpt: ExpandCheckpoint | None = None,
    use_linkedin_enrich: bool = True,
    use_apollo: bool = True,
) -> list[dict[str, str]]:
    """Fill all 35 landscape columns via ChatGPT.

    When ``web_fill`` is True (default), each company is researched with the
    OpenAI Responses API ``web_search`` tool so columns are grounded in live web
    results instead of model memory alone. Fact fields are never invented.

    After web fill, optional LinkedIn gap-fill (OpenAI web_search only — no MCP)
    and Apollo contact lookup (partial name → full name via OpenAI LinkedIn web search).
    """
    if not rows:
        return rows

    from vendor_intel.pipeline.openai_fill_enrich import enrich_row_linkedin_apollo

    # Hosted web_search = 1 company/call; DeepSeek chat batches more efficiently
    use_hosted_web = bool(web_fill) and _supports_hosted_web_search()
    chunk_size = 1 if use_hosted_web else 4
    filled: list[dict[str, str]] = list(ckpt.data("filled_part") or []) if ckpt else []
    done_names = {_norm(str(r.get("Company") or "")) for r in filled if r.get("Company")}
    pending = [
        r
        for r in rows
        if _norm(str(r.get("Company") or r.get("name") or "")) not in done_names
    ]
    total_chunks = (len(rows) + chunk_size - 1) // chunk_size or 1
    mode = (
        "OpenAI web_search (real facts only)"
        if use_hosted_web
        else (
            "DeepSeek chat + search evidence (batched)"
            if _is_deepseek()
            else "ChatGPT knowledge"
        )
    )
    _ckpt(ckpt, "5_fill", "5a_start", begin=True, note="begin column fill")
    _log(
        f"    → substep 5a: fill {len(rows)} companies via {mode} "
        f"in {total_chunks} call(s) — Founded/HQ/brands ONLY from web evidence"
        + (
            f" (resume: {len(filled)} done, {len(pending)} left)"
            if filled
            else ""
        )
    )
    rows = pending  # only process remaining
    if not rows:
        _log("    → substep 5a: all rows already filled (checkpoint) — skip")
        if ckpt:
            ckpt.mark_step_done("5_fill", filled_part=filled)
        return filled
    total_chunks = (len(rows) + chunk_size - 1) // chunk_size or 1
    already_done = len(filled)
    lean_addendum = ""
    if _company_details_lean_fill_active():
        skip_cols = [h for h in HEADERS if h not in _LEAN_FILL_COLUMNS]
        lean_addendum = (
            "\nLEAN FILL MODE (Company Details / Coherent Quadrant only needs a few "
            f"columns): only research and fill {', '.join(_LEAN_FILL_COLUMNS)}. "
            f"Do NOT spend a web search on: {', '.join(skip_cols)} — return "
            '"Not publicly disclosed" (or "" for contact fields) for those keys '
            "immediately, without researching them. Still include every key from "
            "Required keys exactly.\n"
        )
    system = (
        "You are a strict vendor-intelligence researcher. "
        "Use LIVE WEB SEARCH. Prefer official company websites, LinkedIn company pages, "
        "reputable directories, and news. "
        + lean_addendum
        + "REAL-DATA RULES (critical):\n"
        "1) Founded, Headquarters, Ownership, Employees, Website, Key Brands Represented, "
        "Continent / Geography, Operational Presence — ONLY values you can support from "
        "web results. If not found, use exactly \"Not publicly disclosed\". NEVER invent "
        "a year, city, or brand list. For Founded: use the business founding year "
        "(when the company/trade began), NOT a later incorporation, IPO, rebrand, or "
        "subsidiary registration year. Never copy another brand's year "
        "(e.g. do not give Rexel WESCO's 1922).\n"
        "2) Continent / Geography = markets served, prefer REGION(Country[, Country…]) "
        "e.g. APAC(India, Singapore); EU(Germany). "
        "Operational Presence = physical footprint countries (HQ/offices/plants) as "
        "Country; Country.\n"
        "3) Key Brands Represented = brands THIS company actually sells/distributes "
        "(from their site or reliable listing). Do NOT paste generic market brand lists.\n"
        "3b) Market Offering = what THIS company actually offers in THIS market, "
        "matched to its role. If it manufactures, name its own product line or "
        "product brand in this market (e.g. \"Apoquel\", \"Rimadyl\"). If it "
        "provides a service, name that service (e.g. \"Veterinary diagnostics "
        "laboratory services\"). If it distributes, name what it distributes. "
        "Name the specific offering, NOT the company name again, and NOT a "
        "competitor's brand. Leave it EMPTY if the company sells only under its "
        "own name with no separate product brand — an empty value is CORRECT "
        "and preferred over repeating the company name or inventing a brand.\n"
        "4) Retail / E-commerce / Both = Retail | E-commerce | Both | No when evidenced.\n"
        "5) Run one Google-style ask per column: \"founded year of {Company}\", "
        "\"operational presence of {Company}\", \"headquarters of {Company}\".\n"
        "Do NOT return contact details, personal emails, phone numbers or "
        "LinkedIn URLs — they are not requested and must not be guessed.\n"
        "An empty string is CORRECT and preferred whenever you do not genuinely "
        "know a value. A wrong value is much worse than an empty one — never "
        "construct a website from the company name, and never guess a founding "
        "year, parent company or headquarters.\n"
        f"Required keys exactly: {json.dumps(researched_columns())}. "
        "Summary must state how the company relates to the market using web evidence. "
        'Return JSON: {"rows":[{...one object per company...}]}'
    )

    for i in range(0, len(rows), chunk_size):
        chunk = rows[i : i + chunk_size]
        idx = i // chunk_size + 1
        names = ", ".join(
            str(r.get("Company") or r.get("name") or "?")[:40] for r in chunk
        )
        _log(f"    → substep 5a.{idx}: fill {idx}/{total_chunks}: {names}")
        _ckpt(ckpt, "5_fill", f"5a.{idx}", begin=True, note=f"begin fill {idx}/{total_chunks}")
        slim = []
        evidence_blocks: list[str] = []
        for r in chunk:
            cname = str(r.get("Company") or r.get("name") or "")
            cweb = str(r.get("Website") or r.get("website") or "")
            slim.append(
                {
                    "Company": cname,
                    "Website": cweb,
                    "Headquarters": r.get("Headquarters") or "",
                    "Distribution Type": r.get("Distribution Type") or r.get("snippet"),
                    "why_related": r.get("verify_reason") or r.get("snippet"),
                    "relevance": r.get("relevance") or r.get("verify_confidence"),
                }
            )
            if web_fill and cname:
                ev = await _local_web_evidence(cname, cweb, query)
                if ev and not ev.startswith("(local evidence unavailable"):
                    evidence_blocks.append(f"### Evidence for {cname}\n{ev}")
                    _log(f"      · local SERP evidence: {len(ev.splitlines())} hits")
        user = (
            f"Market: {query}\n"
            f"Web-search each company and fill the {len(researched_columns())} "
            "requested columns.\n"
            "FACT fields (Founded, Headquarters, Key Brands Represented, Continent / "
            "Geography, Operational Presence, etc.) must be REAL from the web or "
            "\"Not publicly disclosed\" — never guessed. Contacts stay empty if unknown.\n"
            f"Companies:\n{json.dumps(slim, ensure_ascii=False)}\n"
        )
        if evidence_blocks:
            user += (
                "\nExtra SERP evidence (use if consistent with your web_search):\n"
                + "\n".join(evidence_blocks)
                + "\n"
            )
        if web_fill:
            data = _web_search_json(
                client,
                model,
                system=system,
                user=user,
                label=f"web-fill-{idx}",
                max_tokens=3500,
            )
            source_tag = "openai_sdk_web_search+real_facts"
        else:
            data = _chat_json(
                client,
                model,
                system=system.replace(
                    "SEARCH THE LIVE WEB for each company",
                    "Use best public knowledge for each company",
                ),
                user=user,
                label=f"fill-{idx}",
                max_tokens=4500,
            )
            source_tag = "openai_chatgpt_sdk_fill"

        out_rows = data.get("rows") if isinstance(data, dict) else None
        if isinstance(data, dict) and not out_rows and data.get("Company"):
            out_rows = [data]
        if not isinstance(out_rows, list):
            for r in chunk:
                name = str(r.get("Company") or r.get("name") or "").strip()
                web = str(r.get("Website") or r.get("website") or "").strip()
                filled.append(
                    _ensure_complete_row(
                        {},
                        family=family,
                        name=name,
                        website=web,
                        source="chatgpt_fill_fallback",
                    )
                )
            continue

        by_name = {
            _norm(str(r.get("Company") or r.get("name") or "")): r for r in chunk
        }
        chunk_filled: list[dict[str, str]] = []
        for gr in out_rows:
            if not isinstance(gr, dict):
                continue
            name = str(gr.get("Company") or "").strip()
            base_src = by_name.get(_norm(name))
            if not name and base_src:
                name = str(base_src.get("Company") or base_src.get("name") or "")
            web = str(
                gr.get("Website")
                or (base_src or {}).get("Website")
                or (base_src or {}).get("website")
                or ""
            )
            merged = _ensure_complete_row(
                {**({k: base_src.get(k) for k in HEADERS if base_src and base_src.get(k)}), **gr},
                family=family,
                name=name,
                website=web,
                source=source_tag,
            )
            if base_src and base_src.get("verify_reason"):
                why = base_src["verify_reason"]
                if why and why not in (merged.get("Summary") or ""):
                    merged["Summary"] = (
                        f"{merged.get('Summary', '').rstrip()} Related: {why}".strip()
                    )
            # LinkedIn gap-fill + Apollo contact (partial → full name)
            if web_fill and (use_linkedin_enrich or use_apollo):
                _log(
                    f"      · enrich LinkedIn/Apollo for {merged.get('Company', '?')}…"
                )
                try:
                    merged = await enrich_row_linkedin_apollo(
                        client,
                        model,
                        query=query,
                        row=merged,
                        web_search_json=_web_search_json,
                        use_linkedin=use_linkedin_enrich,
                        use_apollo=use_apollo,
                        label_prefix=f"enrich-{idx}",
                    )
                    merged = _ensure_complete_row(
                        merged,
                        family=family,
                        name=str(merged.get("Company") or name),
                        website=str(merged.get("Website") or web),
                        source=str(merged.get("Data Sources") or source_tag),
                    )
                except Exception as err:  # noqa: BLE001
                    _log(
                        f"      · enrich failed: {type(err).__name__}: {err}"
                    )
            chunk_filled.append(merged)

        got = {_norm(r.get("Company", "")) for r in chunk_filled}
        for r in chunk:
            key = _norm(str(r.get("Company") or r.get("name") or ""))
            if key and key not in got:
                name = str(r.get("Company") or r.get("name") or "")
                web = str(r.get("Website") or r.get("website") or "")
                chunk_filled.append(
                    _ensure_complete_row(
                        r if r.get("Company") else {},
                        family=family,
                        name=name,
                        website=web,
                        source="chatgpt_fill_miss",
                    )
                )
        filled.extend(chunk_filled)
        _log(
            f"    → substep 5a.{idx}: filled {len(chunk_filled)} "
            f"(running total={len(filled)} / this pass {already_done + idx})"
        )
        if ckpt:
            ckpt.bump(
                "5_fill",
                f"5a.{len(filled)}",
                progress={"fill_count": len(filled)},
                filled_part=filled,
                to_fill_names=[
                    str(r.get("Company") or r.get("name") or "") for r in rows
                ],
                note=f"filled {len(filled)} rows",
            )

    # Second pass: re-web-search rows that still look sparse
    refill_done = set(ckpt.progress_get("refill_done_names") or []) if ckpt else set()
    if web_fill:
        weak_idx = [
            i
            for i, r in enumerate(filled)
            if _row_needs_web_refill(r)
            and _norm(str(r.get("Company") or "")) not in refill_done
        ]
        if weak_idx:
            _log(
                f"    → substep 5b: web re-fill {len(weak_idx)} sparse row(s)…"
            )
            _ckpt(ckpt, "5_fill", "5b_start", begin=True, note="begin sparse re-fill")
            for n, i in enumerate(weak_idx, 1):
                r = filled[i]
                name = r.get("Company") or ""
                _log(f"    → substep 5b.{n}: re-fill {name}")
                _ckpt(ckpt, "5_fill", f"5b.{n}", begin=True, note=f"begin re-fill {name}")
                data = _web_search_json(
                    client,
                    model,
                    system=system,
                    user=(
                        f"Market: {query}\n"
                        "This row has missing/weak fields. Web-search and fill the "
                        "requested columns for:\n"
                        f"{json.dumps({h: r.get(h) for h in researched_columns()}, ensure_ascii=False)}\n"
                        "Leave a field as an empty string if you do not genuinely "
                        "know the real value — a wrong value is worse than a blank.\n"
                        'Return JSON: {"rows":[one row]}'
                    ),
                    label=f"web-refill-{n}",
                    max_tokens=3500,
                )
                out_rows = data.get("rows") if isinstance(data, dict) else None
                if isinstance(data, dict) and data.get("Company") and not out_rows:
                    out_rows = [data]
                if isinstance(out_rows, list) and out_rows and isinstance(out_rows[0], dict):
                    filled[i] = _ensure_complete_row(
                        out_rows[0],
                        family=family,
                        name=name,
                        website=str(r.get("Website") or ""),
                        source="openai_sdk_web_search+refill",
                    )
                refill_done.add(_norm(name))
                if ckpt:
                    ckpt.bump(
                        "5_fill",
                        f"5b.{n}",
                        progress={"refill_done_names": list(refill_done)},
                        filled_part=filled,
                        note=f"refill {name}",
                    )

    # Final guarantee: zero empty cells
    filled = [
        _ensure_complete_row(
            r,
            family=family,
            name=str(r.get("Company") or ""),
            website=str(r.get("Website") or ""),
            source=str(r.get("Data Sources") or "openai_sdk_fill"),
        )
        for r in filled
    ]
    _log(f"    → substep 5a done: {len(filled)} rows, all {len(HEADERS)} columns filled")
    if ckpt:
        ckpt.mark_step_done("5_fill", filled_part=filled)
    return filled


def gpt_final_verify_rows(
    client: OpenAI,
    model: str,
    *,
    query: str,
    family: str,
    rows: list[dict[str, str]],
    ckpt: ExpandCheckpoint | None = None,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Final QA: drop rows that are not Solution Provider (tech) or Brand/Marketer (other)."""
    if not rows:
        return [], []

    expected_role = player_label(query, family)
    criteria = verify_criteria_prompt(query, family)
    kept: list[dict[str, str]] = list(ckpt.data("final_kept") or []) if ckpt else []
    rejected: list[dict[str, str]] = list(ckpt.data("rejected_final") or []) if ckpt else []
    chunk_size = 10
    start_i = int(ckpt.progress_get("final_verify_offset", 0) or 0) if ckpt else 0
    total_chunks = (len(rows) + chunk_size - 1) // chunk_size or 1
    _ckpt(ckpt, "6_final", "6a_start", begin=True, note="begin final verify")
    _log(
        f"    → substep 6a: final QA on {len(rows)} rows as {expected_role} "
        f"in {total_chunks} DeepSeek chunk(s)"
        + (f" (resume offset={start_i})" if start_i else "")
    )
    json_shape = (
        '{"results":[{"Company":"...","in_market":true|false,"builds_or_owns":true|false,'
        '"role":"Solution Provider|Brand|Marketer|Reseller|Retailer|Distributor|Media|Other",'
        '"fits_criteria":true|false,"confidence":0-100,"reason":"..."}]}'
    )
    for i in range(start_i, len(rows), chunk_size):
        chunk = rows[i : i + chunk_size]
        idx = i // chunk_size + 1
        _log(f"    → substep 6a.{idx}: final-verify chunk {idx}/{total_chunks}…")
        _ckpt(ckpt, "6_final", f"6a.{idx}", begin=True, note=f"begin final-verify chunk {idx}")
        payload = [
            {
                "Company": r.get("Company"),
                "Website": r.get("Website"),
                "Distribution Type": r.get("Distribution Type"),
                "Core Categories": r.get("Core Categories"),
                "Specialty Focus": r.get("Specialty Focus"),
                "Summary": (r.get("Summary") or "")[:180],
            }
            for r in chunk
        ]
        data = _chat_json(
            client,
            model,
            system=(
                f"{criteria}\n"
                "This is a second pass after columns were filled. Use Summary and categories. "
                "For EACH company return one result. Never skip a name. "
                "When unsure, fits_criteria=false. "
                f"Return compact JSON only: {json_shape}"
            ),
            user=(
                f"Market: {query}\nRequired type: {expected_role}\n"
                f"Rows:\n{json.dumps(payload, ensure_ascii=False)}"
            ),
            label=f"final-{idx}",
            max_tokens=3000,
            # Without this the parser accepts ANY JSON and logs "parse OK",
            # then the caller finds no "results" key and fails closed —
            # 16 chunks of verified companies dropped while every line of the
            # log claimed success. Retry on the shape the caller needs.
            require_key="results",
        )
        results = data.get("results") if isinstance(data, dict) else []
        by = {_norm(str(r.get("Company") or "")): r for r in chunk}
        if not isinstance(results, list) or not results:
            _log(f"    → substep 6a.{idx}: empty/invalid JSON — DROP chunk (fail closed)")
            for src in chunk:
                rejected.append(
                    {
                        "company": str(src.get("Company") or ""),
                        "reason": "final verify parse failed — dropped",
                    }
                )
            continue
        seen: set[str] = set()
        for r in results:
            if not isinstance(r, dict):
                continue
            name = str(r.get("Company") or r.get("name") or "").strip()
            key = _norm(name)
            src = by.get(key)
            if not src:
                continue
            seen.add(key)
            keep, conf, role, reason = _verify_parse_row(r, expected_role)
            if not keep:
                rejected.append({"company": name, "reason": reason or f"not a {expected_role}"})
                continue
            from vendor_intel.pipeline.role_split import normalize_role_label

            src = dict(src)
            role_n = normalize_role_label(role or expected_role, query=query, company=name)
            if role_n:
                src["Distribution Type"] = role_n
                src["commercial_role"] = role_n
            if reason:
                src["Data Confidence"] = src.get("Data Confidence") or "Medium"
                src["Summary"] = (src.get("Summary") or "").rstrip()
                if reason not in src["Summary"]:
                    src["Summary"] = f"{src['Summary']} Verify: {reason}".strip()
            src["verify_confidence"] = str(conf)
            kept.append(src)
        for key, src in by.items():
            if key in seen:
                continue
            rejected.append(
                {
                    "company": str(src.get("Company") or ""),
                    "reason": f"not returned by verifier — dropped (must be {expected_role})",
                }
            )
        _log(
            f"    → substep 6a.{idx}: running kept={len(kept)} "
            f"rejected={len(rejected)}"
        )
        if ckpt:
            ckpt.bump(
                "6_final",
                f"6a.{idx}",
                progress={"final_verify_offset": i + chunk_size, "final_chunk": idx},
                final_kept=kept,
                rejected_final=rejected,
                note=f"final verify chunk {idx}",
            )
    _log(
        f"    → substep 6a done: kept={len(kept)} rejected={len(rejected)} "
        f"(required={expected_role})"
    )
    if ckpt:
        ckpt.mark_step_done("6_final", final_kept=kept, rejected_final=rejected)
    return kept, rejected


def _as_landscape_rows(
    verified: list[dict[str, str]], family: str, query: str = ""
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    role_label = player_label(query, family) if landscape_mode() else ""
    for c in verified:
        if c.get("Company"):
            row = dict(c)
            raw_role = str(row.get("Distribution Type") or "").strip()
            if landscape_mode():
                from vendor_intel.pipeline.role_split import refine_row_role

                if not raw_role or "brand / marketer" in raw_role.lower():
                    row["Distribution Type"] = role_label
                refine_row_role(row, query)
            elif role_label and not raw_role:
                row["Distribution Type"] = role_label
            rows.append(row)
            continue
        name = str(c.get("name") or "").strip()
        web = str(c.get("website") or "").strip()
        row = _blank_row(name, web, family, c.get("discovery_source") or "chatgpt")
        if landscape_mode():
            from vendor_intel.pipeline.role_split import refine_row_role

            row["Distribution Type"] = str(c.get("Distribution Type") or c.get("role") or role_label)
            refine_row_role(row, query)
        elif role_label:
            row["Distribution Type"] = role_label
        if c.get("source_query") and c["source_query"] not in {
            "chatgpt_recall",
            "",
        }:
            # Discovery geo belongs in Continent / Geography only — never write
            # bare country into Headquarters (that polluted Found in as "Germany").
            row["Continent / Geography"] = c["source_query"]
        if c.get("snippet"):
            row["Specialty Focus"] = c["snippet"][:180]
        rows.append(row)
    return rows


async def run_chatgpt_expand(
    query: str,
    *,
    country: str = "global",
    target: int = 1000,
    batch: str = "all",
    max_queries: int = 300,
    merge_existing: bool = True,
    final_path: str | None = None,
    out_dir: str | None = None,
    fill_existing: bool = False,
    max_fill: int = 1000,
    seeds_only: bool = False,
    seeds_path: str | None = None,
    skip_recall: bool = False,
    web_fill: bool = True,
    openai_discover: bool = True,
    ddgs_harvest: bool = False,
    resume: bool = True,
    use_linkedin_enrich: bool = True,
    use_apollo: bool = True,
    fill_backend: str = "search",
    force: bool = False,
    family: str | None = None,
) -> dict[str, Any]:
    """Full expand: OpenAI/DeepSeek SDK for find+verify; search stack (default) for fill.

    Same steps 0–7 for ANY market (batch of 1…N). No demo-market hardcoding.

    DeepSeek: no hosted web_search — auto-enables ddgs harvest, keeps fill_backend=search,
    and uses chat.completions for verify / residual (efficient, no wasted Responses retries).
    """
    from vendor_intel.pipeline.chatgpt_env import apply_chatgpt_expand_env

    apply_chatgpt_expand_env()
    os.environ.setdefault("EXPAND_LANDSCAPE_MODE", "vendors")
    os.environ.setdefault("CHANNEL_PURITY_FILTER", "false")
    os.environ.setdefault("EXPAND_OUTPUT_FOLDER", "chatgpt_expand")
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    family = market_family(query, family=family)
    if landscape_mode():
        _log(
            f"  [chatgpt] player mode: {player_label(query, family)} "
            f"(tech=Solution Provider, other=Brand/Marketer) | target={target} "
            "so up to ~1000 remain after filter"
        )

    # DeepSeek-efficient defaults (OpenAI-compatible chat; live web via free search stack)
    # EXPAND_SKIP_DDGS_HARVEST=1 or ddgs_harvest=False with skip env → never force Step 3.
    skip_ddgs = (os.getenv("EXPAND_SKIP_DDGS_HARVEST") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    if skip_ddgs:
        ddgs_harvest = False

    # Google AI Mode is the single source of companies when it is on. The
    # ddgs/SearXNG harvest existed only because DeepSeek has no hosted
    # web_search — AI Mode searches the live web itself, so the harvest would
    # add companies from raw SERP scraping and give the landscape two
    # different provenances.
    # No `settings` argument: Settings() is not constructed until later in
    # this function, and _ai_mode_active() reads the env var when given none.
    if _ai_mode_active() and ddgs_harvest:
        ddgs_harvest = False
        _log(
            "  [chatgpt] Step 3 ddgs/SearXNG harvest DISABLED — "
            "Google AI Mode is the sole company source"
        )

    if _is_deepseek():
        if str(fill_backend).lower() in ("openai", "web", "responses"):
            _log(
                "  [chatgpt] DeepSeek: fill_backend forced to 'search' "
                "(no OpenAI hosted web_search)"
            )
            fill_backend = "search"
        if (
            not ddgs_harvest
            and not seeds_only
            and not skip_ddgs
            # Not when AI Mode is the sole source — it already searches the web.
            and not _ai_mode_active()
        ):
            ddgs_harvest = True
            _log(
                "  [chatgpt] DeepSeek: auto-enabled ddgs/SearXNG harvest for discovery"
            )
        elif skip_ddgs:
            _log("  [chatgpt] Step 3 ddgs harvest SKIPPED (EXPAND_SKIP_DDGS_HARVEST)")
        # LinkedIn via OpenAI web_search does not exist on DeepSeek — skip MCP-less path
        if use_linkedin_enrich and not _supports_hosted_web_search():
            use_linkedin_enrich = False
            _log(
                "  [chatgpt] DeepSeek: LinkedIn OpenAI-web_search enrich off "
                "(use Apollo / search stack instead)"
            )
        # Prefer higher residual parallelism on cheap DeepSeek chat
        if not (os.getenv("EXPAND_RESIDUAL_CONCURRENT") or "").strip():
            os.environ["EXPAND_RESIDUAL_CONCURRENT"] = "4"

    out_p = Path(out_dir) if out_dir else default_output_dir(query, country)
    out_p.mkdir(parents=True, exist_ok=True)
    xlsx = resolve_final_path(query, country, out_p, final_path)

    existing = read_final_rows(xlsx) if merge_existing and xlsx.exists() else []
    seeds = _seed_candidates(query, country, seeds_path=seeds_path)
    ckpt, resumed = ExpandCheckpoint.load_or_create(
        out_p,
        query=query,
        country=country,
        batch=batch,
        target=target,
        resume=resume,
        force=force,
        meta={
            "seeds_only": seeds_only,
            "web_fill": web_fill,
            "openai_discover": openai_discover,
            "ddgs_harvest": ddgs_harvest,
            "max_fill": max_fill,
            "use_linkedin_enrich": use_linkedin_enrich,
            "use_apollo": use_apollo,
            "fill_backend": fill_backend,
        },
    )
    # Skip finished markets (required for 10k batch efficiency).
    #
    # "Done" must mean SCORED, not merely reached the end. Silicon Carbide
    # was marked done with 231 verified companies and zero X/Y scores: the
    # scoring step had been wiped out by an AI Mode quota block, the run
    # wrote the report anyway, and every later attempt to rescore hit this
    # skip and exited in 0 minutes. A market with rows but no scores has not
    # finished — it has failed quietly.
    if resume and not force and ckpt.is_done() and not _checkpoint_has_scores(ckpt):
        _log(
            f"  [chatgpt] checkpoint says done but some rows carry no X score — "
            f"re-running {query!r} from scoring"
        )
        ckpt.state["status"] = "running"
        ckpt.state["step"] = "6c_xy"
        # `completed` is a dict of step -> True. Drop only the scoring and
        # export steps so the verified companies from steps 1-6 are kept.
        # It must STAY a dict: replacing it with a bool crashed a run with
        # "'bool' object has no attribute 'get'" and reset the market to
        # step 0.
        done = ckpt.state.get("completed")
        if isinstance(done, dict):
            for step in [k for k in done if str(k).startswith(("6c", "6d", "7"))]:
                done.pop(step, None)
        for key in ("final_rows", "detail_rows"):
            if key in (ckpt.state.get("data") or {}):
                ckpt.state["data"][key] = []
        try:
            ckpt.save()
        except Exception:  # noqa: BLE001
            pass
    elif resume and not force and ckpt.is_done():
        n_existing = len(existing) if existing else len(read_final_rows(xlsx) if xlsx.exists() else [])
        _log(
            f"  [chatgpt] SKIP done market: {query!r} "
            f"(checkpoint status=done, final_rows≈{n_existing}) → {xlsx}"
        )
        return {
            "skipped": True,
            "reason": "already_done",
            "query": query,
            "country": country,
            "family": family,
            "final_path": str(xlsx),
            "xlsx": str(xlsx),
            "companies": n_existing,
            "total_after": n_existing,
            "checkpoint": str(ckpt.path),
        }

    settings = Settings()
    client = _client(settings)
    model = _model(settings)
    session = openai_cost.start_run(
        market=query,
        model=model,
        family=family,
        batch=batch,
        target=target,
        max_queries=0 if seeds_only else max_queries,
        max_fill=max_fill,
        seeds=len(seeds),
        seeds_only=seeds_only,
        openai_discover=openai_discover and not seeds_only,
        ddgs_harvest=ddgs_harvest and not seeds_only,
        web_fill=web_fill,
        resume=resumed,
        checkpoint=str(ckpt.path),
    )
    _log(
        f"  [chatgpt] FULL {_llm_label(settings)} SDK pipeline (no run_query.py) | "
        f"model={model} | base={_base_url(settings)}"
    )
    _log(f"  [chatgpt] cost run_id={session.run_id} → {openai_cost.cost_dir()}")
    _log(f"  [chatgpt] existing={len(existing)} final={xlsx}")
    _log(
        f"  [chatgpt] curated seeds loaded={len(seeds)}"
        + (" (seeds-only mode)" if seeds_only else "")
    )
    if resumed:
        _log(f"  [chatgpt] RESUME checkpoint: {ckpt.summary_line()}")
    else:
        _log(f"  [chatgpt] checkpoint → {ckpt.path}")
    _log(
        "  [chatgpt] discover mode: "
        + (
            "skip (seeds-only)"
            if seeds_only
            else (
                (
                    "DeepSeek chat discover"
                    if _is_deepseek(settings)
                    else "OpenAI web_search"
                )
                + (" + ddgs harvest" if ddgs_harvest else "")
                if openai_discover
                else ("ddgs harvest" if ddgs_harvest else "none")
            )
        )
    )
    _log(
        f"  [chatgpt] fill mode: "
        + (
            "search stack first (DDGS + SearXNG + Google AI scraper), "
            f"then {_llm_label(settings)} residual for leftover gaps"
            if str(fill_backend).lower() in ("search", "searx", "ddgs", "stack")
            else (
                "OpenAI Responses API web_search (live web per company)"
                if web_fill and _supports_hosted_web_search(settings)
                else f"{_llm_label(settings)} chat knowledge / batched fill"
            )
        )
    )
    _log(
        "  [chatgpt] enrich: "
        + (
            "Step 5a = Google AI + DDGS + SearXNG + Exa + Wikipedia + Owler; "
            "Step 5b = OpenAI SDK residual for remaining NPD/gaps | "
            f"Apollo={'on' if use_apollo and (os.environ.get('APOLLO_API_KEY') or '').strip() else 'off'}"
            if str(fill_backend).lower() in ("search", "searx", "ddgs", "stack")
            else (
                f"LinkedIn web_search={'on' if use_linkedin_enrich else 'off'} (no MCP) | "
                f"Apollo={'on' if use_apollo and (os.environ.get('APOLLO_API_KEY') or '').strip() else 'off'}"
            )
        )
    )

    try:
        ckpt.begin("0_start", "0a_init", note="pipeline start")
        ckpt.bump("0_start", "0b_seeds", seeds_count=len(seeds), note="seeds loaded")

        # Step 0c — market analysis BEFORE discovery. Stage 1 of the two-stage
        # classifier decides B2B vs B2C and this market's own participant
        # categories, so every discovery prompt below can ask for the company
        # types that actually exist in THIS market instead of a generic
        # "companies in X" query. Previously this ran only at scoring time,
        # which meant discovery had no idea what it was looking for.
        market_analysis = dict(ckpt.data("market_analysis") or {})
        if not market_analysis.get("market_type"):
            # industry_group is not known yet — it is selected later from the
            # scored rows. The market name alone is what Stage 1 needs, and
            # passing "" keeps the cache key consistent with the scoring-stage
            # lookup (which also passes "" for industry_category).
            market_analysis = _analyze_market_for_discovery(
                query, settings=settings, industry_group=""
            )
            ckpt.bump(
                "0_start",
                "0c_market",
                market_analysis=market_analysis,
                note=f"market_type={market_analysis.get('market_type')}",
            )
        else:
            _log(
                f"  [chatgpt] Step 0c: SKIP (checkpoint) — "
                f"market_type={market_analysis.get('market_type')}"
            )
        provider_categories = publish_discovery_market(market_analysis)
        _log(
            f"  [chatgpt] Step 0c/6: market type = "
            f"{market_analysis.get('market_type') or 'unknown'}"
            + (
                f" | player type = {provider_categories[0]}"
                if provider_categories
                else " | player type = Brand / Marketer"
            )
        )
        # State the choice and the reasoning up front: which player type this
        # landscape uses, which other roles exist in the market, and why the
        # chosen one is the competitor rather than a buyer or a channel.
        _subs = [
            str(p.get("type") or "").strip()
            for p in (market_analysis.get("market_participants") or [])
            if str(p.get("type") or "").strip()
        ]
        if market_analysis.get("market_type_reason"):
            _log(
                f"  [chatgpt] Step 0c/6: why {market_analysis.get('market_type')}: "
                f"{market_analysis['market_type_reason']}"
            )
        if _subs:
            _log(f"  [chatgpt] Step 0c/6: roles present in market: {', '.join(_subs)}")
        if market_analysis.get("primary_reason"):
            _log(f"  [chatgpt] Step 0c/6: why this player type: {market_analysis['primary_reason']}")
        _log(
            "  [chatgpt] Step 0c/6: every company in this landscape is the "
            "same player type (never Contract Manufacturer)"
        )

        recalled: list[dict[str, str]] = []
        if ckpt.is_step_done("1_recall"):
            recalled = list(ckpt.data("recalled") or [])
            _log(f"  [chatgpt] Step 1/6: SKIP (checkpoint) — {len(recalled)} recalled")
        elif skip_recall or (seeds_only and len(seeds) >= target):
            _log("  [chatgpt] Step 1/6: skip ChatGPT recall (seeds cover target)")
            ckpt.mark_step_done("1_recall", recalled=[])
        else:
            _log("  [chatgpt] Step 1/6: ChatGPT recall known companies…")
            # One rounds loop replaces recall + discover + list-discover:
            # all three asked the same question and re-found the same
            # companies. See COMPANY_DISCOVERY_ROUNDS.md.
            recalled = discover_companies_rounds(
                client,
                model,
                query=query,
                family=family,
                target=target,
                country=country,
                ckpt=ckpt,
            )

        discovered: list[dict[str, str]] = []
        raw: list[dict[str, str]] = []
        extracted: list[dict[str, str]] = []
        if seeds_only:
            _log("  [chatgpt] Step 2/6: skip web discover (seeds-only)")
            _log("  [chatgpt] Step 3/6: skip ddgs extract (seeds-only)")
            if not ckpt.is_step_done("2_discover"):
                ckpt.mark_step_done("2_discover", discovered=[])
            if not ckpt.is_step_done("3_ddgs"):
                ckpt.mark_step_done("3_ddgs", raw=[], extracted=[])
            openai_cost.heartbeat("seeds_only", seeds=len(seeds), recalled=len(recalled))
        else:
            exclude_names = [
                *(r.get("name") or "" for r in seeds),
                *(r.get("name") or "" for r in recalled),
                *(r.get("Company") or "" for r in existing),
            ]
            need = max(0, target - len(seeds) - len(recalled))
            # Scale page budget with target (800–1000 needs ~50–70 pages @ 25/page)
            discover_pages = max(
                8,
                min(80, max(max_queries // 4 or 12, (need + 24) // 25 + 10)),
            )

            if ckpt.is_step_done("2_discover"):
                discovered = list(ckpt.data("discovered") or [])
                _log(
                    f"  [chatgpt] Step 2/6: SKIP (checkpoint) — "
                    f"{len(discovered)} openai-discovered"
                )
            elif openai_discover and need > 0 and not _ai_mode_active():
                # Steps 2a/2g are the SAME question the rounds loop already
                # asked, so on AI Mode they only re-find known companies at
                # ~20 s per paced query. Kept for the non-AI-Mode path.
                _log(
                    "  [chatgpt] Step 2/6: OpenAI SDK web_search — find companies…"
                )
                openai_cost.heartbeat(
                    "openai_discover",
                    discover_pages=discover_pages,
                    need=need,
                    recalled=len(recalled),
                    seeds=len(seeds),
                )
                ga_seed = await google_ai_seed_discover(
                    client,
                    model,
                    query=query,
                    family=family,
                    target=need,
                    exclude=exclude_names,
                    ckpt=ckpt,
                )
                discovered = gpt_discover_companies(
                    client,
                    model,
                    query=query,
                    family=family,
                    target=need,
                    exclude=exclude_names,
                    max_pages=discover_pages,
                    ckpt=ckpt,
                    seed=ga_seed,
                )
                (out_p / f"chatgpt_openai_discover_batch_{batch.lower()}.json").write_text(
                    json.dumps(discovered, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                openai_cost.heartbeat(
                    "openai_discover_done",
                    openai_discovered=len(discovered),
                )
            elif openai_discover:
                _log(
                    "  [chatgpt] Step 2/6: skip OpenAI discover "
                    f"(seeds+recall already ≥ target: {len(seeds)+len(recalled)})"
                )
                ckpt.mark_step_done("2_discover", discovered=[])
            else:
                _log("  [chatgpt] Step 2/6: OpenAI discover disabled")
                ckpt.mark_step_done("2_discover", discovered=[])

            if ckpt.is_step_done("3_ddgs"):
                raw = list(ckpt.data("raw") or [])
                extracted = list(ckpt.data("extracted") or [])
                _log(
                    f"  [chatgpt] Step 3/6: SKIP (checkpoint) — "
                    f"{len(extracted)} ddgs extracted"
                )
            elif ddgs_harvest:
                _log("  [chatgpt] Step 3/6: optional ddgs/SearXNG harvest + extract…")
                openai_cost.heartbeat(
                    "ddgs_harvest",
                    web_queries_planned=max_queries,
                )
                if ckpt.data("raw"):
                    raw = list(ckpt.data("raw") or [])
                    _log(f"    → substep 3a: SKIP harvest (checkpoint) — {len(raw)} hits")
                else:
                    ckpt.begin("3_ddgs", "3a_harvest", note="begin ddgs harvest")
                    raw = await web_harvest_candidates(
                        query,
                        country=country,
                        batch=batch,
                        max_queries=max_queries,
                    )
                    ckpt.bump("3_ddgs", "3a_harvest", raw=raw, note="ddgs harvest done")
                    (out_p / f"chatgpt_harvest_batch_{batch.lower()}.json").write_text(
                        json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8"
                    )
                extracted = gpt_extract_and_score(
                    client, model, query=query, family=family, candidates=raw, ckpt=ckpt
                )
                ckpt.mark_step_done("3_ddgs", raw=raw, extracted=extracted)
            else:
                _log(
                    "  [chatgpt] Step 3/6: skip ddgs harvest "
                    "(use --ddgs-harvest to enable; OpenAI discover is primary)"
                )
                ckpt.mark_step_done("3_ddgs", raw=[], extracted=[])

        combined = seeds + recalled + discovered + extracted
        if ckpt.is_step_done("4_verify"):
            verified = list(ckpt.data("verified") or [])
            rejected_mid = list(ckpt.data("rejected_mid") or [])
            _log(
                f"  [chatgpt] Step 4/6: SKIP (checkpoint) — "
                f"kept={len(verified)} rejected={len(rejected_mid)}"
            )
        else:
            _log(
                f"  [chatgpt] Step 4/6: ChatGPT verify market-related "
                f"({len(combined)} = {len(seeds)} seeds + {len(recalled)} recalled "
                f"+ {len(discovered)} openai-web + {len(extracted)} ddgs)…"
            )
            ckpt.bump("4_verify", "4a_start", combined_count=len(combined))
            verified, rejected_mid = gpt_verify_market(
                client,
                model,
                query=query,
                family=family,
                companies=combined,
                ckpt=ckpt,
            )
            _log(f"    → substep 4b: write rejected list ({len(rejected_mid)})")
            ckpt.begin("4_verify", "4b_rejects", note="begin write mid rejects")
            (out_p / f"chatgpt_rejected_mid_batch_{batch.lower()}.json").write_text(
                json.dumps(rejected_mid, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            ckpt.bump("4_verify", "4b_rejects", note="wrote mid rejects")

            # Deterministic market gate (wrong industry / fake / R&D / regional / acquired)
            try:
                from vendor_intel.pipeline.expand_market_gate import (
                    filter_expand_market_rows,
                    gate_enabled,
                )

                if gate_enabled():
                    before_n = len(verified)
                    verified, gate_dropped = filter_expand_market_rows(verified, query)
                    if gate_dropped:
                        rejected_mid = list(rejected_mid) + [
                            {
                                "company": d.get("company") or d.get("name"),
                                "reason": f"market_gate:{d.get('reason') or d.get('gate_reason')}",
                            }
                            for d in gate_dropped
                        ]
                        (out_p / f"chatgpt_rejected_gate_mid_batch_{batch.lower()}.json").write_text(
                            json.dumps(gate_dropped, indent=2, ensure_ascii=False),
                            encoding="utf-8",
                        )
                    _log(
                        f"    → substep 4c: market gate kept {len(verified)}/{before_n} "
                        f"(dropped {len(gate_dropped)})"
                    )
                    ckpt.bump(
                        "4_verify",
                        "4c_gate",
                        verified=verified,
                        rejected_mid=rejected_mid,
                        note=f"gate dropped {len(gate_dropped)}",
                    )
            except Exception as exc:
                _log(f"  [chatgpt] market gate (mid) skipped: {type(exc).__name__}: {exc}")

        # Merge verified into landscape-shaped rows with existing FINAL
        if ckpt.is_step_done("4b_merge") and ckpt.data("merged") and ckpt.data("to_fill"):
            merged = list(ckpt.data("merged") or [])
            to_fill = list(ckpt.data("to_fill") or [])
            _log(
                f"    → substep 4c: SKIP merge (checkpoint) — "
                f"merged={len(merged)} to_fill={len(to_fill)}"
            )
        else:
            ckpt.begin("4b_merge", "4c_start", note="begin merge landscape rows")
            landscape_new = _as_landscape_rows(verified, family, query)
            merge_in = [
                {
                    "name": r["Company"],
                    "website": r.get("Website", ""),
                    "domain": "",
                    "snippet": r.get("Specialty Focus", ""),
                    "source_query": r.get("Headquarters", ""),
                    "discovery_source": r.get("Data Sources", "chatgpt"),
                }
                for r in landscape_new
                if r.get("Company")
            ]
            merged = merge_candidates(
                existing, merge_in, family=family, target=max(target * 2, target)
            )
            by = {_norm(r.get("Company", "")): r for r in merged}
            for r in landscape_new:
                k = _norm(r.get("Company", ""))
                if k in by:
                    for h in HEADERS:
                        if r.get(h) and (
                            not by[k].get(h)
                            or by[k].get(h) == "Not publicly disclosed"
                            or (by[k].get("Data Sources") or "").startswith("web_expand")
                        ):
                            by[k][h] = r[h]
            merged = list(by.values())

            if fill_existing:
                to_fill = list(merged)
            else:
                existing_names = {_norm(r.get("Company", "")) for r in existing}
                new_rows = [
                    r for r in merged if _norm(r.get("Company", "")) not in existing_names
                ]
                weak = [
                    r
                    for r in merged
                    if "chatgpt" not in (r.get("Data Sources") or "").lower()
                    or (r.get("Headquarters") or "") == "Not publicly disclosed"
                ]
                seen: set[str] = set()
                to_fill = []
                for r in new_rows + weak:
                    k = _norm(r.get("Company", ""))
                    if not k or k in seen:
                        continue
                    seen.add(k)
                    to_fill.append(r)
            fill_cap = max(int(max_fill or 0), int(target or 0), 1)
            if len(to_fill) > fill_cap:
                to_fill = to_fill[:fill_cap]
            _log(
                f"  [chatgpt] fill ALL table rows this pass: {len(to_fill)} "
                f"(merged={len(merged)}, cap={fill_cap})"
            )
            ckpt.mark_step_done("4b_merge", merged=merged, to_fill=to_fill)

        if ckpt.is_step_done("5_fill") and ckpt.data("filled_part"):
            filled_part = list(ckpt.data("filled_part") or [])
            _log(
                f"  [chatgpt] Step 5/6: SKIP (checkpoint) — {len(filled_part)} filled"
            )
        elif not _column_fill_enabled():
            # Step 5 researches contact / LinkedIn / office columns that the
            # 8-column report does not use, and discovery already collects
            # headquarters, ownership and website per company. Running it
            # spends a paced query per row to fill fields nobody reads.
            filled_part = list(to_fill)
            _log(
                f"  [chatgpt] Step 5/6: SKIP (column fill off) — "
                f"{len(filled_part)} rows already carry their report columns"
            )
            ckpt.mark_step_done("5_fill", filled_part=filled_part)
        else:
            use_search_fill = str(fill_backend).lower() in (
                "search",
                "searx",
                "ddgs",
                "stack",
            )
            if use_search_fill:
                from vendor_intel.pipeline.search_stack_fill import search_stack_fill_rows

                ckpt.begin("5_fill", "5a_start", note="begin Google AI fill")
                _log(
                    f"  [chatgpt] Step 5/6: Google AI scraper fill FIRST (all SLIM columns), "
                    f"then {_llm_label()} residual for leftover empty / "
                    f"Not publicly disclosed gaps — {len(to_fill)} rows…"
                )
                filled_part = await search_stack_fill_rows(
                    query=query,
                    family=family,
                    rows=to_fill,
                    ckpt=ckpt,
                    sources=None,  # SEARCH_STACK_SOURCES (default: google_ai only)
                    use_apollo=use_apollo,
                )
            else:
                ckpt.begin("5_fill", "5a_start", note="begin LLM fill")
                fill_scope = (
                    f"lean fill ({', '.join(_LEAN_FILL_COLUMNS)} only)"
                    if _company_details_lean_fill_active()
                    else f"all {len(HEADERS)} columns"
                )
                _log(
                    f"  [chatgpt] Step 5/6: "
                    f"{'OpenAI web_search + ' if web_fill else ''}"
                    f"{fill_scope} ({len(to_fill)} rows)…"
                )
                filled_part = await gpt_fill_rows(
                    client,
                    model,
                    query=query,
                    family=family,
                    rows=to_fill,
                    web_fill=web_fill,
                    ckpt=ckpt,
                    use_linkedin_enrich=use_linkedin_enrich,
                    use_apollo=use_apollo,
                )
        ckpt.begin("5_fill", "5c_merge", note="begin merge filled rows")
        by = {_norm(r.get("Company", "")): r for r in merged}
        for r in filled_part:
            by[_norm(r.get("Company", ""))] = r
        filled_all = [
            _ensure_complete_row(
                r,
                family=family,
                name=str(r.get("Company") or ""),
                website=str(r.get("Website") or ""),
                source=str(r.get("Data Sources") or "openai_sdk"),
            )
            for r in by.values()
        ]
        ckpt.bump("5_fill", "5c_merge", filled_all=filled_all, note="merged filled_all")
        _log(f"    → substep 5c: merged filled rows into list ({len(filled_all)} total)")

        if ckpt.is_step_done("6_final") and ckpt.data("final_kept"):
            final_rows = list(ckpt.data("final_kept") or [])
            rejected_final = list(ckpt.data("rejected_final") or [])
            _log(
                f"  [chatgpt] Step 6/6: SKIP (checkpoint) — "
                f"kept={len(final_rows)} rejected={len(rejected_final)}"
            )
        elif not _final_verify_enabled():
            # Step 6a re-verifies companies Step 4 already verified, judging
            # them on Summary / Core Categories / Specialty Focus — fields
            # that column fill used to populate. With column fill off those
            # are empty, so the pass asks the model to re-judge blank rows and
            # then fails closed on the result, deleting verified companies.
            final_rows = list(filled_all)
            rejected_final = []
            _log(
                f"  [chatgpt] Step 6/6: SKIP (final verify off) — "
                f"keeping {len(final_rows)} rows verified in Step 4"
            )
            ckpt.mark_step_done(
                "6_final", final_kept=final_rows, rejected_final=rejected_final
            )
        else:
            _log("  [chatgpt] Step 6/6: ChatGPT final market-related verify…")
            final_rows, rejected_final = gpt_final_verify_rows(
                client,
                model,
                query=query,
                family=family,
                rows=filled_all,
                ckpt=ckpt,
            )
            _log(f"    → substep 6b: write final rejects ({len(rejected_final)})")
            ckpt.begin("6_final", "6b_rejects", note="begin write final rejects")
            (out_p / f"chatgpt_rejected_final_batch_{batch.lower()}.json").write_text(
                json.dumps(rejected_final, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            ckpt.bump("6_final", "6b_rejects", note="wrote final rejects")

            try:
                from vendor_intel.pipeline.expand_market_gate import (
                    filter_expand_market_rows,
                    gate_enabled,
                )

                if gate_enabled():
                    before_n = len(final_rows)
                    final_rows, gate_dropped = filter_expand_market_rows(final_rows, query)
                    if gate_dropped:
                        rejected_final = list(rejected_final) + [
                            {
                                "company": d.get("company")
                                or d.get("Company")
                                or d.get("name"),
                                "reason": f"market_gate:{d.get('reason') or d.get('gate_reason')}",
                            }
                            for d in gate_dropped
                        ]
                        (out_p / f"chatgpt_rejected_gate_final_batch_{batch.lower()}.json").write_text(
                            json.dumps(gate_dropped, indent=2, ensure_ascii=False),
                            encoding="utf-8",
                        )
                    _log(
                        f"    → substep 6m: market gate kept {len(final_rows)}/{before_n} "
                        f"(dropped {len(gate_dropped)})"
                    )
                    ckpt.bump(
                        "6_final",
                        "6m_gate",
                        final_kept=final_rows,
                        rejected_final=rejected_final,
                        note=f"gate dropped {len(gate_dropped)}",
                    )
            except Exception as exc:
                _log(f"  [chatgpt] market gate (final) skipped: {type(exc).__name__}: {exc}")

        final_rows.sort(key=lambda r: _norm(r.get("Company", "")))

        # Channel-partner purity (discovery stayed wide; export is channel-only)
        if ckpt.is_step_done("6_purity") and ckpt.data("purity_rows"):
            final_rows = list(ckpt.data("purity_rows") or [])
            rejected_final = list(ckpt.data("rejected_final") or rejected_final)
            _log(f"    → substep 6p: SKIP purity (checkpoint) — {len(final_rows)} rows")
        else:
            ckpt.begin("6_purity", "6p_start", note="begin channel purity")
            try:
                from vendor_intel.intelligence.channel_purity import (
                    channel_purity_enabled,
                    filter_channel_pure_rows_async,
                )

                if channel_purity_enabled():
                    before_n = len(final_rows)
                    purity_family = family
                    try:
                        from vendor_intel.intelligence.channel_purity import _resolve_family

                        purity_family = _resolve_family(family, query)
                    except Exception:
                        purity_family = family
                    final_rows, purity_dropped = await filter_channel_pure_rows_async(
                        final_rows, family=purity_family, query=query
                    )
                    _log(
                        f"  [chatgpt] Channel purity ({purity_family}): kept {len(final_rows)}/{before_n} "
                        f"(dropped {len(purity_dropped)} OEM/utility/fake/non-channel)"
                    )
                    if purity_dropped:
                        (out_p / f"chatgpt_rejected_purity_batch_{batch.lower()}.json").write_text(
                            json.dumps(purity_dropped, indent=2, ensure_ascii=False),
                            encoding="utf-8",
                        )
                        rejected_final = list(rejected_final) + [
                            {"company": d.get("company"), "reason": f"purity:{d.get('reason')}"}
                            for d in purity_dropped
                        ]
                else:
                    _log("    → substep 6p: channel purity off")
            except Exception as exc:  # noqa: BLE001
                _log(f"  [chatgpt] Channel purity skipped: {type(exc).__name__}: {exc}")
            ckpt.mark_step_done(
                "6_purity",
                purity_rows=_slim_ckpt_rows(final_rows),
                rejected_final=rejected_final,
            )

        if len(final_rows) > target:
            ckpt.begin("6_purity", "6p_trim", note="begin trim to target")

            def _rank(r: dict[str, str]) -> tuple[int, str]:
                dc = (r.get("Data Confidence") or "").lower()
                score = 2 if dc == "high" else 1 if dc == "medium" else 0
                return (-score, _norm(r.get("Company", "")))

            final_rows = sorted(final_rows, key=_rank)[:target]
            final_rows.sort(key=lambda r: _norm(r.get("Company", "")))
            ckpt.bump("6_purity", "6p_trim", purity_rows=_slim_ckpt_rows(final_rows), note="trimmed to target")

        if ckpt.is_step_done("6c_xy") and ckpt.data("xy_rows"):
            final_rows = list(ckpt.data("xy_rows") or [])
            xy_audit = dict(ckpt.data("xy_audit") or {})
            _log(f"  [chatgpt] Step 6c: SKIP (checkpoint) — {len(final_rows)} scored")
        else:
            _log("  [chatgpt] Step 6c: Coherent Quadrant X / Y / overall scores…")
            ckpt.begin("6c_xy", "6c_start", note="begin X/Y scoring")
            try:
                from vendor_intel.pipeline.expand_quadrant_score import score_expand_rows

                final_rows, xy_audit = await score_expand_rows(
                    final_rows, query, country=country, ckpt=ckpt
                )
                final_rows.sort(
                    key=lambda r: -int(str(r.get("Overall Score") or "0").split(".")[0] or 0)
                )
                (out_p / f"chatgpt_xy_scores_batch_{batch.lower()}.json").write_text(
                    json.dumps(xy_audit, indent=2, ensure_ascii=False, default=str),
                    encoding="utf-8",
                )
                _log(
                    f"    → [xy] scored {xy_audit.get('scored')} rows "
                    f"({xy_audit.get('industry_group')}/{xy_audit.get('industry_category')}) "
                    f"overall=(X+Y)/2"
                )
                ckpt.mark_step_done(
                    "6c_xy",
                    xy_rows=_slim_ckpt_rows(final_rows),
                    xy_audit={k: v for k, v in (xy_audit or {}).items() if k != "rows"},
                )
            except Exception as exc:
                xy_audit = {"error": f"{type(exc).__name__}: {exc}"}
                _log(f"  [chatgpt] X/Y scoring skipped: {xy_audit['error']}")

        if ckpt.is_step_done("6d_details") and ckpt.data("detail_rows"):
            detail_rows = list(ckpt.data("detail_rows") or [])
            _log(f"  [chatgpt] Step 6d: SKIP (checkpoint) — {len(detail_rows)} detail rows")
        else:
            _log("  [chatgpt] Step 6d: Company Details columns (Brand | Company | Quadrant | X | Y | Overall | Found in)…")
            ckpt.begin("6d_details", "6d_start", note="begin Company Details mapping")
            detail_rows: list = []
            try:
                from vendor_intel.enrichment.hq_city_country import enrich_rows_city_country_hq
                from vendor_intel.pipeline.expand_quadrant_score import (
                    export_expand_quadrant_outputs,
                    to_company_detail_rows,
                )

                ckpt.begin("6d_details", "6d_found_in", note="City, Country Found in resolve")
                fi_stats = enrich_rows_city_country_hq(final_rows, log=_log)
                _log(
                    f"    → [found-in] city/country filled={fi_stats.get('filled')} "
                    f"kept={fi_stats.get('kept')} blank={fi_stats.get('blank')}"
                )
                ckpt.bump(
                    "6d_details",
                    "6d_found_in",
                    note=(
                        f"found-in filled={fi_stats.get('filled')} "
                        f"blank={fi_stats.get('blank')}"
                    ),
                )
                ckpt.begin("6d_details", "6d_map", note="map Brand/Company/X/Y columns")
                detail_rows = to_company_detail_rows(final_rows, query, xy_audit)
                ckpt.bump("6d_details", "6d_map", note=f"mapped {len(detail_rows)} rows")
                ckpt.begin("6d_details", "6d_html", note="begin HTML/CSV export")
                extras = export_expand_quadrant_outputs(
                    out_p,
                    detail_rows,
                    query,
                    country=country,
                    audit=xy_audit,
                    chart_n=int(getattr(Settings.load(), "quadrant_chart_companies", 20) or 20),
                )
                _log(
                    f"    → [table] {len(detail_rows)} rows | graph top "
                    f"{min(20, len(detail_rows))} | html={Path(extras['html']).name}"
                )
                ckpt.bump("6d_details", "6d_html", note="wrote html/csv")
                ckpt.mark_step_done(
                    "6d_details",
                    detail_rows=_slim_ckpt_rows(detail_rows),
                )
            except Exception as exc:
                _log(f"  [chatgpt] Company Details mapping skipped: {type(exc).__name__}: {exc}")

        sheet = "Companies"

        cost_summary = openai_cost.finish_run(
            companies=len(final_rows),
            xlsx=str(xlsx),
            rejected_mid=len(rejected_mid),
            rejected_final=len(rejected_final),
            status="ok",
        )
        openai_cost.print_session_summary(cost_summary)

        audit = {
            "backend": "chatgpt",
            "uses_run_query": False,
            "model": model,
            "query": query,
            "country": country,
            "batch": batch,
            "family": family,
            "target": target,
            "existing_before": len(existing),
            "seeds_loaded": len(seeds),
            "seeds_only": seeds_only,
            "web_fill": web_fill,
            "fill_backend": fill_backend,
            "openai_discover": openai_discover and not seeds_only,
            "ddgs_harvest": ddgs_harvest and not seeds_only,
            "chatgpt_recalled": len(recalled),
            "openai_discovered": len(discovered),
            "harvested_raw": len(raw),
            "chatgpt_extracted": len(extracted),
            "verified_mid": len(verified),
            "rejected_mid": len(rejected_mid),
            "chatgpt_filled": len(filled_part),
            "rejected_final": len(rejected_final),
            "total_after": len(final_rows),
            "xlsx": str(xlsx),
            "mode": "openai_sdk_full_find_verify_fill",
            "openai_cost": cost_summary,
            "xy_scoring": {k: v for k, v in (xy_audit or {}).items() if k != "rows"},
        }
        audit["checkpoint"] = str(ckpt.path)
        audit["resumed"] = resumed
        _log(f"    → substep 7: write Excel ({len(final_rows)} rows) → {xlsx.name}")
        ckpt.begin("7_write", "7a_excel", note="begin write Excel")
        write_final_xlsx(xlsx, final_rows, sheet, audit, detail_rows=detail_rows or None)
        ckpt.bump("7_write", "7a_excel", note="wrote Excel")
        ckpt.begin("7_write", "7b_audit", note="begin write audit JSON")
        (out_p / f"chatgpt_expand_batch_{batch.lower()}_audit.json").write_text(
            json.dumps(audit, indent=2), encoding="utf-8"
        )
        ckpt.bump("7_write", "7b_audit", note="wrote audit JSON")
        ckpt.mark_done()
        _log(f"  [chatgpt] DONE (OpenAI SDK only) → {len(final_rows)} rows → {xlsx}")
        _log(f"  [chatgpt] checkpoint marked done → {ckpt.path}")
        return audit
    except Exception:
        # persist partial cost if run crashes mid-way; checkpoint stays resumable
        try:
            ckpt.bump(
                str(ckpt.state.get("step") or "error"),
                "error",
                note="interrupted — re-run same command to --resume",
            )
            _log(f"  [chatgpt] checkpoint saved for resume → {ckpt.path}")
            _log(f"  [chatgpt] {ckpt.summary_line()}")
        except Exception:
            pass
        partial = {
            "run_id": session.run_id,
            "market": query,
            "model": model,
            "calls": len(session.calls),
            "prompt_tokens": session.prompt_tokens,
            "completion_tokens": session.completion_tokens,
            "total_tokens": session.total_tokens,
            "estimated_cost_usd": session.estimated_cost_usd,
        }
        openai_cost.finish_run(status="error")
        openai_cost.print_session_summary(partial)
        raise
