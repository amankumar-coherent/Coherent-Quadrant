"""Focused Google / Google-AI query builders for Step-5 fill.

One Google AI ask per Excel column, e.g.:
  founded year of "Acme Dist"
  operational presence of "Acme Dist"
  headquarters of "Acme Dist"
"""
from __future__ import annotations

import re


def _clean_company(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip())


def _clean_domain(domain: str) -> str:
    d = (domain or "").strip().lower()
    d = d.removeprefix("https://").removeprefix("http://").removeprefix("www.")
    return d.split("/")[0].strip()


def _quoted(name: str) -> str:
    n = _clean_company(name)
    if not n:
        return ""
    if " " in n or any(c in n for c in ".-&"):
        return f'"{n}"'
    return n


# Gap key → phrase in: "{phrase} of {company}"
# Matches landscape Excel columns (Founded, Operational Presence, …).
_FIELD_PHRASE: dict[str, str] = {
    "founded_year": "founded year",
    "headquarters": "headquarters city country",
    "employee_count": "number of employees",
    "revenue": "revenue",
    "offices": "operational presence",
    "ownership": "ownership",
    "core_categories": "core categories",
    "specialty_focus": "specialty focus",
    "key_brands_represented": "key brands represented",
    "distribution_type": "distribution type",
    "retail_ecommerce": "retail or ecommerce",
    "regions_served": "continent and geography",
    "contact_person": "sales or procurement contact person name",
    "contact_role": "sales or procurement contact person role",
    "email": "public contact email",
    "phone": "office phone number",
    "linkedin": "sales or procurement LinkedIn",
    "website": "official website",
    "summary": "company summary",
}

# Preferred ask order when several gaps are open
_FIELD_ORDER: tuple[str, ...] = (
    "founded_year",
    "headquarters",
    "employee_count",
    "ownership",
    "offices",
    "regions_served",
    "website",
    "core_categories",
    "specialty_focus",
    "key_brands_represented",
    "distribution_type",
    "retail_ecommerce",
    "revenue",
    "linkedin",
    "contact_person",
    "contact_role",
    "email",
    "phone",
    "summary",
)


def field_query(company: str, field: str, *, domain: str = "") -> str:
    """One Google AI query per column: ``founded year of {company}``."""
    qn = _quoted(company)
    if not qn:
        return ""
    phrase = _FIELD_PHRASE.get(field) or field.replace("_", " ")
    q = f"{phrase} of {qn}"
    return q


def field_query_pairs(
    company: str,
    fields: list[str] | tuple[str, ...] | set[str],
    *,
    domain: str = "",
    max_queries: int = 22,
) -> list[tuple[str, str]]:
    """``(gap_key, "founded year of {company}")`` for each missing column."""
    wanted = {str(f).strip() for f in fields if str(f).strip()}
    if not wanted:
        return []

    ranked: list[tuple[str, str]] = []
    for key in _FIELD_ORDER:
        if key not in wanted:
            continue
        q = field_query(company, key, domain=domain)
        if q:
            ranked.append((key, q))

    for key in sorted(wanted):
        if key in _FIELD_PHRASE or key in _FIELD_ORDER:
            continue
        q = field_query(company, key, domain=domain)
        if q:
            ranked.append((key, q))

    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for field, q in ranked:
        k = q.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append((field, q))
        if len(out) >= max_queries:
            break
    return out


def queries_for_fields(
    company: str,
    fields: list[str] | tuple[str, ...] | set[str],
    *,
    domain: str = "",
    market: str = "",
    max_queries: int = 22,
) -> list[str]:
    """Build ``{phrase} of {company}`` queries for the given gaps."""
    return [q for _, q in field_query_pairs(company, fields, domain=domain, max_queries=max_queries)]


def firmographic_queries(company: str, *, domain: str = "") -> list[str]:
    """HQ / founded / employees — one query per fact (legacy helper)."""
    return queries_for_fields(
        company,
        ("founded_year", "headquarters", "employee_count"),
        domain=domain,
        max_queries=3,
    )


def leadership_queries(company: str, *, domain: str = "") -> list[str]:
    """Sales / procurement contact — never CEO-only."""
    qn = _quoted(company)
    if not qn:
        return []
    out = [
        f"sales or procurement contact person name of {qn}",
        f"head of sales of {qn}",
    ]
    return out


def category_queries(company: str, *, market: str = "", domain: str = "") -> list[str]:
    return queries_for_fields(
        company,
        ("core_categories", "key_brands_represented", "specialty_focus"),
        domain=domain,
        market=market,
        max_queries=3,
    )


def build_gap_fill_queries(
    company: str,
    *,
    domain: str = "",
    market: str = "",
    need_firmographics: bool = False,
    need_categories: bool = False,
    need_contact: bool = False,
    needed_fields: list[str] | tuple[str, ...] | set[str] | None = None,
    max_queries: int = 22,
) -> list[str]:
    """Pick field-specific Google queries for missing landscape gaps.

    Prefer ``needed_fields`` (exact gap keys). Legacy booleans still work.
    """
    fields: list[str] = []
    if needed_fields:
        fields.extend(str(f) for f in needed_fields)
    else:
        if need_firmographics:
            fields.extend(
                ("founded_year", "headquarters", "offices", "employee_count", "revenue")
            )
        if need_categories:
            fields.extend(
                ("core_categories", "specialty_focus", "key_brands_represented")
            )
        if need_contact:
            fields.append("contact_person")

    # De-dupe preserving order
    seen: set[str] = set()
    uniq: list[str] = []
    for f in fields:
        if f in seen:
            continue
        seen.add(f)
        uniq.append(f)

    return queries_for_fields(
        company,
        uniq,
        domain=domain,
        market=market,
        max_queries=max_queries,
    )


def backfill_queries(company: str, *, domain: str = "", max_queries: int = 3) -> list[str]:
    """DDGS/SearXNG firmographic queries (one fact each)."""
    return queries_for_fields(
        company,
        ("founded_year", "headquarters", "employee_count"),
        domain=domain,
        max_queries=max_queries,
    )


def backfill_query(company: str, *, domain: str = "") -> str:
    """Single DDGS/SearXNG query (first firmographic ask). Prefer ``backfill_queries``."""
    qs = backfill_queries(company, domain=domain, max_queries=1)
    return qs[0] if qs else ""
