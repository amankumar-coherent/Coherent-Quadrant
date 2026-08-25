"""Post-web-fill enrichment via OpenAI SDK only (no LinkedIn MCP).

Flow per company (after primary OpenAI web fill):
  1) If details still missing → OpenAI Responses ``web_search`` on LinkedIn
     (site:linkedin.com/company and /in) + public web to fill gaps
  2) Apollo People Search for Contact Person + Role (may return partial name)
  3) OpenAI web_search on LinkedIn to resolve full name from the partial
"""
from __future__ import annotations

import os
from typing import Any, Callable

from openai import OpenAI

from vendor_intel.pipeline.web_expand import HEADERS, _norm

_NPD = "not publicly disclosed"
_ChatJson = Callable[..., Any]


def _missing(val: str | None) -> bool:
    v = str(val or "").strip().lower()
    return (not v) or v in {"", "n/a", "na", "none", "-", "—", _NPD, "unknown", "tbd"}


def _partial_name(name: str) -> bool:
    """True if Apollo-style obfuscated / incomplete name."""
    n = (name or "").strip()
    if not n or _missing(n):
        return True
    if "*" in n or "…" in n or "..." in n:
        return True
    parts = n.split()
    if len(parts) == 1 and len(parts[0]) >= 2:
        return True
    if len(parts) >= 2 and len(parts[-1]) <= 2:
        return True
    return False


def _gaps(row: dict[str, str]) -> list[str]:
    """All landscape columns still empty / NPD (except Company)."""
    skip = {"Company", "Data Sources", "Data Confidence", "Quality Score"}
    return [h for h in HEADERS if h not in skip and _missing(row.get(h))]


def _apply_updates(row: dict[str, str], updates: dict[str, str]) -> dict[str, str]:
    out = dict(row)
    for h in HEADERS:
        if h not in updates:
            continue
        val = str(updates.get(h) or "").strip()
        if not val or _missing(val):
            continue
        if not _missing(out.get(h)) and h in {
            "Founded",
            "Headquarters",
            "Contact Person",
            "Website",
        }:
            if h == "Contact Person" and _partial_name(str(out.get(h) or "")) and not _partial_name(val):
                out[h] = val
            continue
        out[h] = val
    src = out.get("Data Sources") or ""
    tag = updates.get("_source_tag") or "openai_linkedin_web"
    if tag and tag not in src:
        out["Data Sources"] = f"{src}; {tag}".strip("; ")
    return out


def linkedin_gap_fill_openai(
    client: OpenAI,
    model: str,
    *,
    query: str,
    row: dict[str, str],
    web_search_json: _ChatJson,
    label: str = "li-gap",
) -> dict[str, str]:
    """Fill missing columns using OpenAI web_search on LinkedIn (+ public web). No MCP."""
    gaps = _gaps(row)
    if not gaps:
        return {}
    company = str(row.get("Company") or "").strip()
    website = str(row.get("Website") or "").strip()
    slim = {h: row.get(h) for h in HEADERS}
    data = web_search_json(
        client,
        model,
        system=(
            "You are a vendor-intelligence researcher using LIVE WEB SEARCH only. "
            "Do NOT use any external MCP or LinkedIn API login. "
            "Search the public web with priority on LinkedIn pages:\n"
            "  - site:linkedin.com/company  (company About: founded, HQ, size, specialties)\n"
            "  - site:linkedin.com/in       (people: name, title at this company)\n"
            "Also use the official website and reputable directories to confirm. "
            "Return ONLY facts found in search results. "
            'Unknown fields = \"Not publicly disclosed\". Never invent years, cities, '
            "emails, phones, or brand lists. "
            "Fill EVERY key in the required list with a short non-empty value. "
            f"Required keys exactly: {HEADERS!r}. "
            'Return JSON: {"row":{...all keys...}}'
        ),
        user=(
            f"Market: {query}\n"
            f"Company: {company}\n"
            f"Known website: {website}\n"
            f"Current row (many fields missing):\n{slim}\n"
            f"Priority missing fields: {gaps}\n\n"
            "Run these web searches (LinkedIn via web, not MCP):\n"
            f'  1) "{company}" site:linkedin.com/company\n'
            f'  2) "{company}" LinkedIn about founded headquarters employees\n'
            f'  3) "{company}" site:linkedin.com/in CEO OR founder OR "managing director" OR "vp sales"\n'
            f'  4) "{company}" official website about\n'
            f'  5) "{company}" {query} distributor brands\n'
            "Put company LinkedIn URL in LinkedIn when found. "
            "If you find a clear leadership contact on LinkedIn, set Contact Person + Role. "
            "Return a complete row object with all columns."
        ),
        label=label,
        max_tokens=3500,
    )
    if not isinstance(data, dict):
        return {}
    src_row = data.get("row") if isinstance(data.get("row"), dict) else data
    if not isinstance(src_row, dict):
        return {}
    out: dict[str, str] = {}
    for h in HEADERS:
        if h == "Company":
            continue
        if h not in gaps and not _missing(row.get(h)):
            continue
        val = str(src_row.get(h) or "").strip()
        if val and not _missing(val):
            out[h] = val
    if out:
        out["_source_tag"] = "openai_sdk_web_search+linkedin"
    return out


async def apollo_contact_lookup(company: str, website: str) -> dict[str, str]:
    """Apollo People Search → Contact Person (may be partial) + Role."""
    if not (os.getenv("APOLLO_API_KEY") or "").strip():
        return {}
    try:
        from vendor_intel.enrichment.apollo_contacts import ApolloContactClient
    except Exception:
        return {}
    row = {"company": company, "website": website, "domain": ""}
    try:
        async with ApolloContactClient(verbose=False) as apollo:
            hit = await apollo.find_contact(row, enrich_match=True)
    except Exception as err:
        return {"_error": f"{type(err).__name__}: {err}"}
    if not hit or hit.get("error"):
        return {}
    out: dict[str, str] = {"_source_tag": "apollo"}
    name = str(hit.get("contact_person") or "").strip()
    role = str(hit.get("contact_role") or "").strip()
    if name:
        out["Contact Person"] = name
    if role:
        out["Role"] = role
    if hit.get("linkedin"):
        out["_person_linkedin"] = str(hit["linkedin"])
    if hit.get("email"):
        out["Email"] = str(hit["email"])
    if hit.get("phone"):
        out["Office No."] = str(hit["phone"])
    if hit.get("apollo_name_obfuscated") == "true":
        out["_partial"] = "true"
    return out


def resolve_full_name_openai(
    client: OpenAI,
    model: str,
    *,
    company: str,
    partial_name: str,
    role: str,
    web_search_json: _ChatJson,
    label: str = "name-resolve",
) -> dict[str, str]:
    """From Apollo partial name → full name via OpenAI web_search on LinkedIn (no MCP)."""
    if not partial_name or _missing(partial_name):
        return {}
    first = partial_name.replace("*", "").split()[0]
    data = web_search_json(
        client,
        model,
        system=(
            "Resolve a business contact's FULL public name using LIVE WEB SEARCH only. "
            "Do NOT use LinkedIn MCP or any login tool. "
            "Search public LinkedIn via the web: site:linkedin.com/in and Google/Bing results. "
            "Only return a full name if clearly the same person at the company. "
            "If unsure, keep_partial=true and full_name empty. "
            "Do not invent emails/phones. "
            'Return JSON: {"full_name":"...","role":"...","linkedin_profile":"...",'
            '"keep_partial":false,"confidence":0-100,"evidence":"..."}'
        ),
        user=(
            f"Company: {company}\n"
            f"Partial / obfuscated name from Apollo: {partial_name}\n"
            f"Known role/title: {role}\n"
            "Web searches to run:\n"
            f'  "{first}" "{company}" site:linkedin.com/in\n'
            f'  "{first}" "{company}" LinkedIn\n'
            f'  "{partial_name}" "{company}"\n'
            f'  "{first}" {role} "{company}"\n'
            "Return full first+last name only with solid evidence."
        ),
        label=label,
        max_tokens=1200,
    )
    if not isinstance(data, dict):
        return {}
    if data.get("keep_partial") is True:
        return {}
    try:
        conf = int(data.get("confidence") or 0)
    except (TypeError, ValueError):
        conf = 0
    full = str(data.get("full_name") or "").strip()
    if not full or _partial_name(full) or conf < 60:
        return {}
    if first and len(first) >= 2:
        if _norm(full.split()[0]) != _norm(first) and first.lower() not in full.lower():
            return {}
    out: dict[str, str] = {
        "Contact Person": full,
        "_source_tag": "apollo+openai_web_search_linkedin_name",
    }
    role2 = str(data.get("role") or "").strip()
    if role2 and not _missing(role2):
        out["Role"] = role2
    li = str(data.get("linkedin_profile") or "").strip()
    if li.startswith("http") and "linkedin.com" in li:
        out["_person_linkedin"] = li
    return out


async def enrich_row_linkedin_apollo(
    client: OpenAI,
    model: str,
    *,
    query: str,
    row: dict[str, str],
    web_search_json: _ChatJson,
    use_linkedin: bool = True,
    use_apollo: bool = True,
    label_prefix: str = "enrich",
) -> dict[str, str]:
    """LinkedIn via OpenAI web_search only (no MCP) + Apollo contacts."""
    out = dict(row)
    company = str(out.get("Company") or "").strip()
    website = str(out.get("Website") or "").strip()
    if not company:
        return out

    # 1) LinkedIn + web gap fill — OpenAI SDK web_search only
    if use_linkedin and _gaps(out):
        li_updates = linkedin_gap_fill_openai(
            client,
            model,
            query=query,
            row=out,
            web_search_json=web_search_json,
            label=f"{label_prefix}-li-web",
        )
        if li_updates:
            out = _apply_updates(out, li_updates)

    # 2) Apollo contact (partial OK) → 3) full name via OpenAI LinkedIn web search
    if use_apollo and (
        _missing(out.get("Contact Person"))
        or _partial_name(str(out.get("Contact Person") or ""))
        or _missing(out.get("Role"))
    ):
        apollo = await apollo_contact_lookup(company, website)
        if apollo and not apollo.get("_error"):
            person_li = apollo.pop("_person_linkedin", "")
            partial_flag = apollo.pop("_partial", "")
            apollo.pop("_source_tag", None)
            out = _apply_updates(out, {**apollo, "_source_tag": "apollo"})
            if person_li and _missing(out.get("LinkedIn")):
                out["LinkedIn"] = person_li

            contact = str(out.get("Contact Person") or "")
            role = str(out.get("Role") or "")
            need_resolve = bool(partial_flag) or _partial_name(contact)
            if contact and need_resolve:
                resolved = resolve_full_name_openai(
                    client,
                    model,
                    company=company,
                    partial_name=contact,
                    role=role,
                    web_search_json=web_search_json,
                    label=f"{label_prefix}-name-web",
                )
                if resolved:
                    person_li2 = resolved.pop("_person_linkedin", "")
                    out = _apply_updates(out, resolved)
                    if person_li2 and (
                        _missing(out.get("LinkedIn"))
                        or "linkedin.com/company" not in str(out.get("LinkedIn") or "")
                    ):
                        out["LinkedIn"] = person_li2

    return out
