"""Display names, acquisition suffixes, and founded-year extraction for quadrant brands."""
from __future__ import annotations

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

# Provider-category name fragments that indicate a builder/platform-owner
# style Company column (Brand=product, Company=parent/platform maker) —
# checked against THIS market's own LLM-derived provider category names
# (market_relevance.analyze_market), never against a fixed list of market
# names/keywords. A B2B market whose dynamic categories don't match any of
# these (e.g. Manufacturer / Distributor / Service Provider only) uses the
# consumer_brand style instead.
_PROVIDER_TYPE_SOLUTION_HINTS = (
    "solution provider",
    "platform provider",
    "technology provider",
    "software",
    "platform",
    "integrator",
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

    * ``solution_provider`` — builder/platform-owner style: Brand=Gemini, Company=Google
    * ``consumer_brand`` — most other markets: Brand + Company; owned → ``(acquired by Parent)``

    Derived from market_relevance.analyze_market's own market-type + dynamic
    provider-category classification (cached there per market) — a B2C
    market is always consumer_brand; a B2B market is solution_provider only
    when its own LLM-derived provider categories for THIS market actually
    include a builder/platform-style role (see
    _PROVIDER_TYPE_SOLUTION_HINTS) rather than from any fixed keyword list
    on the market's name.
    """
    try:
        from vendor_intel.quadrant.market_relevance import analyze_market, market_provider_type_names

        analysis = analyze_market(
            str(market or ""),
            industry_group=str(industry_group or ""),
            industry_category=str(industry_category or ""),
            settings=settings,
            client=client,
        )
    except Exception:
        return "consumer_brand"

    if str(analysis.get("market_type") or "").upper() != "B2B":
        return "consumer_brand"

    names = [n.lower() for n in market_provider_type_names(analysis)]
    if any(hint in n for n in names for hint in _PROVIDER_TYPE_SOLUTION_HINTS):
        return "solution_provider"
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


_LEGAL_SUFFIX_RE = re.compile(
    r"(?i)[\s,]+(?:inc|inc\.|incorporated|corp|corp\.|corporation|co|co\.|"
    r"company|ltd|ltd\.|limited|llc|l\.l\.c\.|plc|gmbh|ag|nv|n\.v\.|bv|b\.v\.|"
    r"sa|s\.a\.|as|a/s|ab|oy|spa|s\.p\.a\.|srl|s\.r\.l\.|pty|pvt|pvt\.|"
    r"private|holdings|holding|group|international|worldwide)\.?\s*$"
)


def _same_entity(a: str, b: str) -> bool:
    """True when two names denote the same company modulo legal suffixes.

    "Helen of Troy Limited" owned by "Helen of Troy" is a company owning
    itself, and printing "(acquired by ...)" for it is noise. Comparison only —
    the displayed name keeps its real suffix.
    """
    def core(name: str) -> str:
        prev = ""
        cur = (name or "").strip().lower().rstrip(".,")
        # Repeat: "Foo Group Holdings Ltd" sheds three suffixes.
        while cur != prev:
            prev = cur
            cur = _LEGAL_SUFFIX_RE.sub("", cur).strip().rstrip(".,")
        return cur

    ca, cb = core(a), core(b)
    return bool(ca) and ca == cb


def _ownership_unverified(row: dict[str, Any]) -> bool:
    """True when the row itself says the ownership claim is weakly evidenced.

    Discovery asks the model to rate its own ownership evidence. A "low" means
    it found only indirect signals — similar names, a directory listing — and
    the spec is explicit that an acquisition is stated only when verified.
    Anything other than an explicit "low" is allowed through: a missing
    confidence is the normal case for rows from older or non-AI-Mode sources,
    and treating those as unverified would strip correct suffixes wholesale.
    """
    return str(row.get("ownership_confidence") or "").strip().lower() == "low"


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

    if (
        owner
        # Legal-suffix aware: "Helen of Troy Limited" owned by "Helen of
        # Troy" is the same entity, and the suffix would be self-referential.
        and not _same_entity(owner, own_name)
        and not _same_entity(owner, brand)
        # An unverified acquisition printed as fact is worse than no
        # acquisition at all, so a self-declared "low" confidence suppresses
        # the suffix and the company stands on its own name.
        and not _ownership_unverified(row)
    ):
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
