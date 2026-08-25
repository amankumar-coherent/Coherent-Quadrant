"""Display names, acquisition suffixes, and founded-year extraction for quadrant brands."""
from __future__ import annotations

import json
import re
from typing import Any, Literal

CompanyDisplayMode = Literal["solution_provider", "consumer_brand"]

_ACQUIRED_PARENT_RE = re.compile(
    r"(?i)^\s*(?:acquired by|subsidiary of|merged into|owned by)\s+(.+?)\s*$"
)
_SUFFIX_IN_NAME_RE = re.compile(
    r"\((?:acquired by|merged into|subsidiary of)\s+[^)]+\)\s*$",
    re.I,
)
_FOUNDED_RE = re.compile(
    r"(?:founded|established|incorporated)\s*(?:in\s*)?(?:(?:the\s+)?year\s*)?(\d{4})\b",
    re.I,
)
_YEAR_ONLY_RE = re.compile(r"^(19|20)\d{2}$")

_DISPLAY_MODE_SYSTEM = """You decide how a market-comparison table should label two columns,
BRAND and COMPANY, for every company in ONE market.

Two styles exist:
- "solution_provider": the buyer chooses a PRODUCT/PLATFORM whose maker is a
  separate, often more well-known parent — e.g. Brand=Gemini, Company=Google.
  Typical of tech / software / platform / B2B solution markets, but decide
  from the market itself, not a fixed industry list.
- "consumer_brand": the brand IS the company, or is one of several
  consumer/commercial brands a parent portfolio owns — e.g. Brand=Oreo,
  Company=(acquired by Mondelez). Typical of food, energy, industrial goods,
  pharma, and most other markets where "brand" and "company" are usually the
  same legal entity, or where an acquisition is best shown as a suffix.

Return JSON only:
{"company_display_mode": "solution_provider" | "consumer_brand", "reason": "one short sentence"}
"""

# Cache of confirmed LLM verdicts, keyed by (market, industry_group,
# industry_category) lowercased. Only successful LLM calls are cached — the
# keyword fallback below is cheap enough to recompute every call, so a
# process that starts without an LLM available never poisons the cache for
# a later call that does have one.
_DISPLAY_MODE_LLM_CACHE: dict[tuple[str, str, str], "CompanyDisplayMode"] = {}


def _llm_classify_display_mode(
    market: str, industry_group: str, industry_category: str, *, settings: Any = None, client: Any = None
) -> "CompanyDisplayMode | None":
    """One cached LLM call per market: solution_provider or consumer_brand?

    Returns None (caller falls back to the keyword heuristic) when no LLM is
    configured/available or the call fails — same fail-open contract as
    axis_define.py's market axis refinement.
    """
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
        return None
    if client is None or not getattr(client, "available", False):
        return None

    payload = {
        "market": market,
        "industry_group": industry_group,
        "industry_category": industry_category,
    }
    try:
        raw = client.complete_json(
            _DISPLAY_MODE_SYSTEM,
            json.dumps(payload, ensure_ascii=False),
            model=getattr(settings, "classifier_model", None),
            max_tokens=200,
        )
    except Exception:
        return None
    if not isinstance(raw, dict):
        return None
    mode = str(raw.get("company_display_mode") or "").strip().lower()
    if mode in ("solution_provider", "consumer_brand"):
        return mode  # type: ignore[return-value]
    return None


# Keyword fallback — used only when no LLM is configured/available (tests,
# offline runs, mock mode). NOT the primary decision path: a market whose
# name matches neither list used to silently default to "consumer_brand"
# with no way to reconsider; now that only happens when the LLM path above
# couldn't run at all.
# Tech / B2B solution markets → Company = parent / solution provider (e.g. Gemini → Google)
_SOLUTION_PROVIDER_MARKERS = (
    "ict",
    "information and communication",
    "wearable",
    "medical device",
    "medtech",
    "semiconductor",
    "software",
    "saas",
    "cloud",
    "ai ",
    " artificial intelligence",
    "machine learning",
    "automation",
    "healthcare it",
    "cyber",
    "telecom",
    "technology",
    "tech ",
    "platform",
    "api ",
    "llm",
    "generative ai",
)

# Food / protein / CPG → Brand + Company; acquisitions shown as (acquired by Parent)
_CONSUMER_BRAND_MARKERS = (
    "food",
    "beverage",
    "protein",
    "dairy",
    "milk",
    "oil",
    "avocado",
    "nutrition",
    "ingredient",
    "snack",
    "meat",
    "plant-based",
    "cpg",
    "consumer",
    "cosmetic",
    "personal care",
    "packaging",
    "energy",
    "lng",
    "liquefied",
    "pharma",
    "pharmaceutical",
    "glp",
)


def _base_name(row: dict[str, Any]) -> str:
    raw = str(row.get("company_raw") or "").strip()
    company = str(row.get("company") or row.get("brand") or "").strip()
    if raw:
        return raw
    cleaned = _SUFFIX_IN_NAME_RE.sub("", company).strip()
    return cleaned or company


def plain_brand_name(row: dict[str, Any] | str) -> str:
    """Brand name without ``(acquired by …)`` suffix — used as scoring identity."""
    if isinstance(row, str):
        return _SUFFIX_IN_NAME_RE.sub("", row).strip() or row.strip()
    return _base_name(row)


def _owner_from_parent_field(parent: str) -> str:
    parent = (parent or "").strip()
    if not parent or parent.lower() in {"independent", "n/a", "na", "none", "-"}:
        return ""
    m = _ACQUIRED_PARENT_RE.match(parent)
    if m:
        return m.group(1).strip().rstrip(".")
    # Classifier sometimes emits "Acquired by Danone" without exact match above
    low = parent.lower()
    for prefix in ("acquired by ", "subsidiary of ", "merged into ", "owned by "):
        if low.startswith(prefix):
            return parent[len(prefix) :].strip().rstrip(".")
    return ""


def format_acquired_suffix(owner: str, *, relation: str = "acquired_by", year: str = "") -> str:
    verb = {
        "acquired_by": "acquired by",
        "merged_into": "merged into",
        "subsidiary_of": "subsidiary of",
        "owned_by": "owned by",
    }.get((relation or "acquired_by").strip(), "acquired by")
    year_bit = f", {year}" if str(year or "").strip() else ""
    return f"({verb} {owner}{year_bit})"


def company_display_mode(
    market: str = "",
    *,
    industry_group: str = "",
    industry_category: str = "",
    settings: Any = None,
    client: Any = None,
) -> CompanyDisplayMode:
    """
    Pick Company-column style for this market.

    * ``solution_provider`` — tech-style: Brand=Gemini, Company=Google
    * ``consumer_brand`` — most other markets: Brand + Company; owned → ``(acquired by Parent)``

    Decision order:
    1. Explicit catalog leaf (industry_group/industry_category already came
       from criteria_catalog.py's controlled taxonomy — a cheap, reliable
       signal when it's present).
    2. One LLM call per unique market, cached (see _llm_classify_display_mode) —
       the actual market-agnostic decision, works for any of ~1,000 markets
       without a fixed keyword list.
    3. Keyword-list fallback, only reached when no LLM is configured/available
       (tests, offline runs, mock mode).
    """
    cat = str(industry_category or "").lower()
    group = str(industry_group or "").lower()

    # 1) Explicit catalog leaf
    if any(
        x in cat or x in group
        for x in (
            "information and communication",
            "semiconductor",
            "healthcare it",
            "ict",
            "automation",
        )
    ):
        return "solution_provider"
    if any(
        x in cat or x in group
        for x in ("food", "beverage", "ingredient", "dairy", "nutrition")
    ):
        return "consumer_brand"

    # 2) LLM call, cached per (market, industry_group, industry_category)
    cache_key = (str(market or "").strip().lower(), group, cat)
    cached = _DISPLAY_MODE_LLM_CACHE.get(cache_key)
    if cached:
        return cached
    llm_mode = _llm_classify_display_mode(
        str(market or ""), str(industry_group or ""), str(industry_category or ""),
        settings=settings, client=client,
    )
    if llm_mode:
        _DISPLAY_MODE_LLM_CACHE[cache_key] = llm_mode
        return llm_mode

    # 3) Keyword fallback (no LLM available)
    blob = " ".join([str(market or ""), str(industry_group or ""), str(industry_category or "")]).lower()
    if any(m in blob for m in _CONSUMER_BRAND_MARKERS):
        return "consumer_brand"
    if any(m in blob for m in _SOLUTION_PROVIDER_MARKERS):
        return "solution_provider"
    # Default: consumer-style acquisitions in brackets (safer for CMI brand tables)
    return "consumer_brand"


def _relation_from_ownership_text(text: str) -> str:
    """Infer relation verb from Ownership / parent text prefixes."""
    low = str(text or "").strip().lower()
    if low.startswith("subsidiary of"):
        return "subsidiary_of"
    if low.startswith("merged into"):
        return "merged_into"
    if low.startswith("owned by"):
        return "owned_by"
    if low.startswith("acquired by"):
        return "acquired_by"
    m = re.search(r"\((subsidiary of|merged into|acquired by)\s+", low)
    if m:
        return {
            "subsidiary of": "subsidiary_of",
            "merged into": "merged_into",
            "acquired by": "acquired_by",
        }[m.group(1)]
    return ""


def _resolve_owner(row: dict[str, Any]) -> tuple[str, str]:
    """Return (owner_name, ownership_relation)."""
    parent_owner = str(row.get("parent_owner") or "").strip()
    parent = str(row.get("parent") or row.get("parent_or_independent") or "").strip()
    company_field = str(row.get("company") or "").strip()
    explicit = str(row.get("ownership_relation") or "").strip()
    inferred = _relation_from_ownership_text(parent) or _relation_from_ownership_text(
        company_field
    )
    relation = explicit or inferred or "acquired_by"

    owner = parent_owner or _owner_from_parent_field(parent)
    if not owner and _SUFFIX_IN_NAME_RE.search(company_field):
        m = re.search(
            r"\((?:acquired by|merged into|subsidiary of)\s+([^)]+)\)\s*$",
            company_field,
            re.I,
        )
        if m:
            owner = m.group(1).strip()
            # Drop year bit if present: "Danone, 2017"
            owner = re.sub(r",\s*(19|20)\d{2}\s*$", "", owner).strip()
            if not explicit and not inferred:
                relation = _relation_from_ownership_text(company_field) or relation
    return owner, relation


def _legal_or_provider_name(row: dict[str, Any], brand: str) -> str:
    """Best non-brand company / solution-provider label on the row."""
    for key in (
        "solution_provider",
        "parent_company",
        "legal_name",
        "company_legal",
        "owner_company",
    ):
        val = str(row.get(key) or "").strip()
        if val and val.lower() not in {brand.lower(), "independent", "n/a", "na"}:
            if not _SUFFIX_IN_NAME_RE.search(val):
                return val
            return plain_brand_name(val)
    return ""


def brand_display_fields(
    row: dict[str, Any],
    *,
    market: str = "",
    industry_group: str = "",
    industry_category: str = "",
    mode: CompanyDisplayMode | str | None = None,
) -> tuple[str, str, str]:
    """
    Return (brand_name, company_column, founded_location).

    Brand is always the plain brand / product name.

    Company column is always populated — never blank — with the company's own
    (legal / trade) name:
    * Acquired / subsidiary / merged: ``Company Name (acquired by Parent)``
    * Independent (no owner, or owner IS the same entity as the brand):
      just the company name — same style for every market, no fixed
      tech-vs-consumer branching.
    """
    base = _base_name(row)
    company_field = str(row.get("company") or "").strip()
    brand = base or company_field
    owner, relation = _resolve_owner(row)
    year = str(row.get("ownership_year") or "").strip()

    # The company's own name — never falls back to blank; brand is the last resort.
    own_name = (
        _legal_or_provider_name(row, brand)
        or str(row.get("legal_name") or "").strip()
        or company_field
        or brand
    )

    if owner and owner.lower() != own_name.lower() and owner.lower() != brand.lower():
        company_col = f"{own_name} {format_acquired_suffix(owner, relation=relation, year=year)}"
    else:
        # Independent, or the "owner" field is really just the company itself.
        company_col = own_name

    location = str(row.get("founded_location") or "").strip()
    if not location:
        location = str(row.get("hq_location") or "").strip()

    return brand, company_col, location


def extract_founded_year(row: dict[str, Any], kb: dict[str, Any] | None = None) -> str:
    """Pull founded year from row fields, evidence_snapshot INTEL, or KB text."""
    for key in ("founded_year", "founded_in", "founded"):
        val = row.get(key)
        year = _normalize_year(val)
        if year:
            return year

    snap = row.get("evidence_snapshot")
    if isinstance(snap, dict):
        data = snap.get("data") if isinstance(snap.get("data"), dict) else {}
        company = data.get("company") if isinstance(data.get("company"), dict) else {}
        year = _normalize_year(company.get("founded_year") or company.get("founded"))
        if year:
            return year
        blob = " ".join(
            [
                str(snap.get("page_text") or ""),
                str((snap.get("classify") or {}).get("summary") or "")
                if isinstance(snap.get("classify"), dict)
                else "",
            ]
        )
        m = _FOUNDED_RE.search(blob)
        if m:
            return m.group(1)

    if kb:
        year = _normalize_year(kb.get("founded_year") or kb.get("founded_in"))
        if year:
            return year
        blob = " ".join(str(c.get("text") or "") for c in (kb.get("chunks") or []))
        m = _FOUNDED_RE.search(blob)
        if m:
            return m.group(1)

    return ""


def _normalize_year(val: Any) -> str:
    if val is None:
        return ""
    s = str(val).strip()
    if not s:
        return ""
    if _YEAR_ONLY_RE.match(s):
        return s
    m = re.search(r"(19|20)\d{2}", s)
    return m.group(0) if m else ""


def extract_founded_from_kb(kb: dict[str, Any]) -> str:
    return extract_founded_year({}, kb=kb)
