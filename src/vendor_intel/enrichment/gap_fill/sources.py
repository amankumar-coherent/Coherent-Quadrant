"""Free external sources for automated gap-fill (search snippets + APIs)."""
from __future__ import annotations

import json
import os
import re
from typing import Any
from urllib.parse import quote

import httpx

from vendor_intel.clients.search_router import FreeSearchRouter
from vendor_intel.enrichment.gap_fill.gaps import domain_from_row, has_contact_person, has_email, has_phone, merge_contact_extracted, merge_extracted, norm


_SALES_PROC_RE = re.compile(
    r"(head of sales|vp sales|vice president of sales|sales director|"
    r"commercial director|chief commercial|chief revenue|chief sales|"
    r"procurement|purchasing|director of sales|national sales|sales head|"
    r"channel sales|business development)",
    re.I,
)


def _gap_fill_use_llm() -> bool:
    """When false, extract fields via regex only (no OpenAI SDK)."""
    raw = (os.getenv("GAP_FILL_USE_LLM") or "true").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _sales_procurement_only(extracted: dict[str, Any]) -> dict[str, Any]:
    """Drop CEO/founder/HR contacts unless the title is also sales/procurement."""
    if not extracted:
        return extracted
    out = dict(extracted)
    role = str(out.get("contact_role") or out.get("role") or "")
    person = str(out.get("contact_person") or "")
    if not person and not role:
        return out
    if _SALES_PROC_RE.search(role):
        return out
    out.pop("contact_person", None)
    out.pop("contact_role", None)
    out.pop("role", None)
    li = str(out.get("linkedin") or out.get("linkedin_url") or "")
    if "/in/" in li.lower():
        out.pop("linkedin", None)
        out.pop("linkedin_url", None)
    return out


async def _llm_extract(
    company: str,
    domain: str,
    snippets: str,
    *,
    fields_hint: str,
) -> dict[str, Any]:
    """DeepSeek writes column values from already-cleaned Google AI sentences."""
    if not snippets.strip():
        return {}
    if not _gap_fill_use_llm():
        from vendor_intel.enrichment.gap_fill.heuristic_extract import heuristic_extract_fields

        return heuristic_extract_fields(snippets, company=company)

    try:
        from vendor_intel.pipeline.chatgpt_env import deepseek_chat_config

        api_key, base_url, model = deepseek_chat_config()
    except Exception:
        api_key = (os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY") or "").strip()
        base_url = (os.getenv("OPENAI_BASE_URL") or "https://api.deepseek.com/v1").strip().rstrip("/")
        model = (os.getenv("OPENAI_MODEL") or os.getenv("DEEPSEEK_MODEL") or "deepseek-chat").strip()
    if not api_key:
        from vendor_intel.enrichment.gap_fill.heuristic_extract import heuristic_extract_fields

        print("  [gap_fill] DeepSeek column write skipped — no DEEPSEEK_API_KEY", flush=True)
        return heuristic_extract_fields(snippets, company=company)
    if not base_url.endswith("/v1"):
        base_url = base_url.rstrip("/") + "/v1"

    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    prompt = (
        f"Company: {company}\nDomain: {domain}\n\n"
        "The text below is Google AI Overview AFTER DeepSeek cleaned it to useful "
        "sentences only. Extract ONLY facts explicitly stated in those sentences. "
        f"{fields_hint}\n"
        "IDENTITY RULE: Only extract facts if the source text is clearly about the "
        f"company named \"{company}\""
        + (f" at domain \"{domain}\"" if domain else "")
        + ". If the text appears to describe a different similarly-named company, "
        "a parent OEM, or an unrelated entity, return empty strings for all keys.\n"
        "Return JSON with keys:\n"
        "- headquarters (city, country)\n"
        "- founded_year (YYYY only: business founding year when trade began, "
        "NOT later incorporation/IPO/rebrand/subsidiary registration; "
        "must be 1600–today and about THIS company only — never copy another brand's year)\n"
        "- employee_count\n"
        "- ownership (Private / Public / Subsidiary + parent if stated)\n"
        "- revenue (prefer a RANGE like '$80–100M' not a single point; "
        "if source says $100M use '$80–100M'; if $50M use '$40–50M')\n"
        "- offices / cities_regions (comma-separated cities or countries)\n"
        "- regions_served (countries/regions served)\n"
        "- linkedin_url\n"
        "- website\n"
        "- core_categories (product/service categories, semicolon-separated)\n"
        "- specialty_focus (niche focus)\n"
        "- key_brands_represented (brands distributed/partnered, semicolon-separated; "
        "NOT the company name alone)\n"
        "- distribution_type (Distributor / Wholesaler / Reseller / Dealer / VAD / SI)\n"
        "- retail_ecommerce (Retail / Ecommerce / Both / No)\n"
        "- contact_person (sales or procurement leader name if stated; never CEO/founder/HR unless title also includes sales or procurement)\n"
        "- contact_role (sales/procurement/commercial title only)\n"
        "- email (only if explicitly stated; never invent)\n"
        "- phone (only if explicitly stated; never invent)\n"
        "- summary (1-2 clean useful sentences copied/tightened from the text; "
        "no navigation, ads, or UI chrome)\n"
        "Use empty string for unknown. Do not invent data. Contacts stay empty if unknown.\n\n"
        f"{snippets[:24000]}"
    )
    try:
        print(f"  [gap_fill] DeepSeek writing useful sentences into columns ({model})", flush=True)
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0,
        )
        text = (resp.choices[0].message.content or "").strip()
        data = json.loads(text) if text else {}
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        print(f"  [gap_fill] DeepSeek column write failed: {type(exc).__name__}: {exc}", flush=True)
        from vendor_intel.enrichment.gap_fill.heuristic_extract import heuristic_extract_fields

        return heuristic_extract_fields(snippets, company=company)


async def _search_snippets(router: FreeSearchRouter, query: str, *, max_hits: int = 8) -> str:
    hits = await router.search(query, discovery_mode=True)
    if not hits:
        return ""
    lines = [f"- {h.title}: {h.snippet} ({h.link})" for h in hits[:max_hits]]
    return "\n".join(lines)


def _google_ai_gap_fill_fields() -> set[str]:
    """Fields Google AI may search. Env GOOGLE_AI_GAP_FILL_FIELDS=headquarters,website.

    ChatGPT expand Company Details only needs Found in (HQ) + website for crawl.
    Unset = full landscape set (legacy).
    """
    all_fields = {
        "headquarters",
        "founded_year",
        "employee_count",
        "ownership",
        "revenue",
        "offices",
        "regions_served",
        "core_categories",
        "specialty_focus",
        "key_brands_represented",
        "distribution_type",
        "retail_ecommerce",
        "linkedin",
        "website",
        "contact_person",
        "contact_role",
        "email",
        "phone",
        "summary",
    }
    raw = (os.getenv("GOOGLE_AI_GAP_FILL_FIELDS") or "").strip()
    if not raw:
        return all_fields
    wanted = {p.strip().lower() for p in raw.split(",") if p.strip()}
    return {f for f in all_fields if f in wanted} or all_fields


async def fill_from_google_ai_scraper(row: dict[str, Any]) -> list[str]:
    """Fill landscape gaps: Google AI extracts text → DeepSeek useful sentences → columns.

    DeepSeek residual (step 5b) only runs later for columns still empty.
    Restrict asks with GOOGLE_AI_GAP_FILL_FIELDS (e.g. headquarters,website).
    """
    from vendor_intel.clients.google_ai_scraper import (
        google_ai_ask,
        google_ai_gap_fill_enabled,
        google_ai_ping,
        heuristic_clean_scrape_markdown,
    )
    from vendor_intel.enrichment.gap_fill.gaps import (
        domain_from_row,
        identity_text_matches,
        merge_extracted,
        missing_fields,
        sync_crawl_from_raw,
    )

    if not google_ai_gap_fill_enabled():
        return []

    gaps = missing_fields(row)
    _google_fields = _google_ai_gap_fill_fields()
    needed = [g for g in gaps if g in _google_fields]
    if not needed:
        return []
    if not await google_ai_ping():
        return []

    company = norm(row.get("company") or row.get("brand"))
    if not company:
        return []
    domain = domain_from_row(row)

    from vendor_intel.enrichment.gap_fill.heuristic_extract import heuristic_extract_fields
    from vendor_intel.enrichment.gap_fill.search_queries import field_query_pairs

    # One Google AI query per allowed missing column (e.g. headquarters of {company}).
    default_max = str(max(len(needed), 2))
    try:
        max_q = max(1, min(24, int(os.getenv("GOOGLE_AI_GAP_FILL_MAX_QUERIES") or default_max)))
    except ValueError:
        max_q = max(len(needed), 2)
    pairs = field_query_pairs(
        company,
        needed,
        domain=domain,
        max_queries=max_q,
    )
    if not pairs:
        return []

    _field_keep: dict[str, frozenset[str]] = {
        "founded_year": frozenset({"founded_year"}),
        "headquarters": frozenset({"headquarters"}),
        "employee_count": frozenset({"employee_count"}),
        "revenue": frozenset({"revenue"}),
        "offices": frozenset({"offices", "operational_presence", "cities_regions"}),
        "ownership": frozenset({"ownership"}),
        "core_categories": frozenset({"core_categories"}),
        "specialty_focus": frozenset({"specialty_focus"}),
        "key_brands_represented": frozenset({"key_brands_represented"}),
        "distribution_type": frozenset({"distribution_type"}),
        "retail_ecommerce": frozenset({"retail_ecommerce", "retail_e_commerce", "retail"}),
        "regions_served": frozenset({"regions_served"}),
        "contact_person": frozenset({"contact_person"}),
        "contact_role": frozenset({"contact_role", "role"}),
        "email": frozenset({"email"}),
        "phone": frozenset({"phone", "office_no"}),
        "linkedin": frozenset({"linkedin", "linkedin_url"}),
        "website": frozenset({"website"}),
        "summary": frozenset({"summary", "company_summary"}),
    }

    snippets_chunks: list[str] = []
    any_updates = False
    # Google AI Overview (long) → DeepSeek useful sentences → fill this column
    for field, q in pairs:
        print(f"  [gap_fill] google ask: {q}", flush=True)
        data = await google_ai_ask(q, llm_clean=True)
        markdown = str(data.get("markdown") or "").strip()
        raw_md = str(data.get("markdown_raw") or "").strip()
        if not markdown and raw_md:
            markdown = heuristic_clean_scrape_markdown(raw_md)
        if not markdown:
            continue
        if data.get("llm_cleaned"):
            print(
                f"  [gap_fill] deepseek cleaned overview for {field} "
                f"({len(raw_md)}→{len(markdown)} chars)",
                flush=True,
            )
        snippets_chunks.append(f"QUERY: {q}\n{markdown}")
        citations = data.get("citations") or []
        if isinstance(citations, list) and citations:
            snippets_chunks.append(
                "Citations:\n" + "\n".join(str(c) for c in citations[:8])
            )
        id_ok = identity_text_matches(company, domain, markdown) or identity_text_matches(
            company, domain, raw_md
        )
        heur = heuristic_extract_fields(markdown, company=company)
        keep = _field_keep.get(field) or {field}
        slim = {k: v for k, v in heur.items() if k in keep and v}
        if field in {"contact_person", "contact_role", "linkedin"}:
            slim = _sales_procurement_only(slim)
        if slim:
            updates = merge_extracted(
                row,
                slim,
                source="google_ai_scraper",
                evidence_text=markdown,
                force_commit=id_ok,
            )
            if updates:
                any_updates = True
                print(f"  [gap_fill] filled {', '.join(updates)} from: {q}", flush=True)

    if not snippets_chunks:
        return []

    still = [g for g in missing_fields(row) if g in _google_fields]
    snippets = "\n\n".join(snippets_chunks)[:40000]
    if still:
        fields_hint = (
            "Each block starts with QUERY: <column ask> (example: founded year of \"Acme\"). "
            "Fill ONLY these still-empty fields from the matching Google AI block: "
            + ", ".join(still)
            + ". Leave empty string when not stated. Never invent emails or phones. "
            "Contact person/role must be sales or procurement — not CEO/founder."
        )
        extracted = await _llm_extract(
            company,
            domain,
            snippets,
            fields_hint=fields_hint,
        )
        extracted = _sales_procurement_only(extracted)
        id_ok = identity_text_matches(company, domain, snippets)
        updates = merge_extracted(
            row,
            extracted,
            source="google_ai_scraper",
            evidence_text=snippets,
            force_commit=id_ok,
        )
        if updates:
            any_updates = True
            print(f"  [gap_fill] llm filled {', '.join(updates)}", flush=True)

    if any_updates:
        sync_crawl_from_raw(row)
        return ["google_ai_scraper"]
    return []


async def fill_from_search_backfill(row: dict[str, Any], router: FreeSearchRouter) -> list[str]:
    from vendor_intel.enrichment.search_backfill import backfill_row

    if await backfill_row(row, router):
        from vendor_intel.enrichment.gap_fill.gaps import sync_crawl_from_raw

        sync_crawl_from_raw(row)
        return ["search_backfill"]
    return []


async def fill_from_linkedin(row: dict[str, Any], *, idx: int = 0, total: int = 0) -> list[str]:
    """Fill missing firmographics via LinkedIn MCP (preferred), then page-scrape fallback.

    LinkedIn MCP both **fills** gaps (Founded, HQ, employees, LinkedIn URL) and
    **verifies/corrects** existing Founded + HQ when the MCP profile differs.
    """
    from vendor_intel.enrichment.gap_fill.gaps import (
        has_employees,
        has_founded,
        has_headquarters,
        has_linkedin,
        row_has_gaps,
        sync_crawl_from_raw,
    )
    from vendor_intel.integrations.linkedin_mcp import linkedin_mcp_available

    applied: list[str] = []
    name = norm(row.get("company") or row.get("brand"))[:50]

    # 1) LinkedIn MCP — fill missing columns + verify/correct Founded & HQ
    if linkedin_mcp_available():
        try:
            from vendor_intel.enrichment.linkedin_firmographic_verify import (
                verify_row_firmographics_via_mcp,
            )

            mcp_updates = await verify_row_firmographics_via_mcp(row)
            if mcp_updates:
                applied.append("linkedin_mcp")
                print(
                    f"  [gap_fill] [{idx}/{total}] {name} linkedin_mcp +{mcp_updates}",
                    flush=True,
                )
        except Exception as exc:
            print(f"  [gap_fill] linkedin_mcp failed for {name}: {exc}", flush=True)

    # 2) Page scrape / Jina fallback when key firmographics still missing
    still_need = (
        not has_founded(row)
        or not has_headquarters(row)
        or not has_linkedin(row)
        or not has_employees(row)
    )
    if still_need or row_has_gaps(row):
        from vendor_intel.enrichment.linkedin_enrich import enrich_company_linkedin

        before = (
            has_headquarters(row),
            has_founded(row),
            has_linkedin(row),
            has_employees(row),
        )
        await enrich_company_linkedin(row, idx=idx, total=total)
        sync_crawl_from_raw(row)
        after = (
            has_headquarters(row),
            has_founded(row),
            has_linkedin(row),
            has_employees(row),
        )
        if after != before:
            applied.append("linkedin")
    return applied



async def fill_from_owler(row: dict[str, Any], *, client: Any, router: FreeSearchRouter, model: str) -> list[str]:
    from vendor_intel.enrichment.gap_fill.gaps import row_has_gaps
    from vendor_intel.enrichment.owler_enrich import _fetch_owler_fields, apply_owler_to_row

    if not row_has_gaps(row):
        return []
    name = norm(row.get("company") or row.get("brand"))
    domain = domain_from_row(row)
    if not name:
        return []
    extracted = await _fetch_owler_fields(name, domain, client=client, router=router, model_name=model)
    updates = apply_owler_to_row(row, extracted)
    if updates:
        from vendor_intel.enrichment.gap_fill.gaps import sync_crawl_from_raw

        sync_crawl_from_raw(row)
        return ["owler"]
    return []


async def fill_from_crunchbase(row: dict[str, Any], router: FreeSearchRouter) -> list[str]:
    from vendor_intel.enrichment.gap_fill.gaps import row_has_gaps

    if not row_has_gaps(row):
        return []
    name = norm(row.get("company") or row.get("brand"))
    if not name:
        return []
    snippets = await _search_snippets(router, f'site:crunchbase.com/organization "{name}"')
    extracted = await _llm_extract(
        name,
        domain_from_row(row),
        snippets,
        fields_hint="Crunchbase-style startup firmographics.",
    )
    updates = merge_extracted(
        row, extracted, source="crunchbase", evidence_text=snippets
    )
    return ["crunchbase"] if updates else []


async def fill_from_wikidata(row: dict[str, Any]) -> list[str]:
    """Free Wikidata SPARQL firmographics (no API key). Prefer before Wikipedia."""
    from vendor_intel.enrichment.gap_fill.gaps import row_has_gaps, sync_crawl_from_raw
    from vendor_intel.placeholders.wikidata import is_enabled as wikidata_enabled, lookup_company

    if not wikidata_enabled() or not row_has_gaps(row):
        return []
    name = norm(row.get("company") or row.get("brand"))
    domain = domain_from_row(row)
    if not name and not domain:
        return []

    firm = await lookup_company(name, domain=domain)
    if not firm:
        return []

    extracted = {
        "headquarters": firm.get("headquarters") or "",
        "founded_year": firm.get("founded_year") or "",
        "employee_count": firm.get("employee_count") or "",
        "revenue": "",
        "offices": "",
        "linkedin_url": "",
    }
    evidence = " ".join(
        str(x)
        for x in (
            name,
            domain,
            firm.get("website"),
            firm.get("headquarters"),
            firm.get("wikidata_qid"),
        )
        if x
    )
    updates = merge_extracted(
        row,
        extracted,
        source="wikidata",
        evidence_text=evidence,
        force_commit=True,
    )

    # Store structured extras that merge_extracted doesn't cover.
    crawl = dict(row.get("_crawl") or {})
    extras: list[str] = []
    if firm.get("wikidata_qid") and not crawl.get("wikidata_qid"):
        crawl["wikidata_qid"] = firm["wikidata_qid"]
        extras.append("wikidata_qid")
    if firm.get("website") and not crawl.get("wikidata_website"):
        crawl["wikidata_website"] = firm["website"]
        extras.append("wikidata_website")
    if firm.get("industry") and not crawl.get("industry"):
        crawl["industry"] = firm["industry"]
        extras.append("industry")
    if firm.get("parent_org") and not crawl.get("parent_org"):
        crawl["parent_org"] = firm["parent_org"]
        extras.append("parent_org")
    if extras:
        crawl["firmographic_source_wikidata"] = True
        row["_crawl"] = crawl
        sync_crawl_from_raw(row)
        updates.extend(extras)

    return ["wikidata"] if updates else []


async def fill_from_wikipedia(row: dict[str, Any]) -> list[str]:
    from vendor_intel.enrichment.gap_fill.gaps import identity_text_matches, row_has_gaps

    if not row_has_gaps(row):
        return []
    name = norm(row.get("company") or row.get("brand"))
    if not name:
        return []
    domain = domain_from_row(row)

    snippets = ""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # Prefer name + domain disambiguation when website is known
            sr = quote(f"{name} {domain}".strip() if domain else name)
            search_url = (
                "https://en.wikipedia.org/w/api.php?"
                f"action=query&list=search&srsearch={sr}&format=json&srlimit=5"
            )
            resp = await client.get(search_url)
            if resp.status_code == 200:
                data = resp.json()
                hits = (data.get("query") or {}).get("search") or []
                parts: list[str] = []
                for hit in hits[:4]:
                    title = hit.get("title") or ""
                    snippet = hit.get("snippet") or ""
                    probe = f"{title} {snippet}"
                    if not identity_text_matches(name, domain, probe):
                        continue
                    parts.append(f"[Wikipedia: {title}] {snippet}")
                    summary_url = (
                        "https://en.wikipedia.org/w/api.php?"
                        f"action=query&prop=extracts&exintro=1&explaintext=1&titles={quote(title)}&format=json"
                    )
                    sresp = await client.get(summary_url)
                    if sresp.status_code == 200:
                        pages = (sresp.json().get("query") or {}).get("pages") or {}
                        for page in pages.values():
                            extract = page.get("extract") or ""
                            if extract and identity_text_matches(name, domain, extract):
                                parts.append(extract[:2000])
                    if len(parts) >= 3:
                        break
                snippets = "\n\n".join(parts)
    except Exception:
        snippets = ""

    if not snippets:
        return []
    extracted = await _llm_extract(
        name,
        domain,
        snippets,
        fields_hint="Wikipedia infobox-style facts.",
    )
    updates = merge_extracted(
        row,
        extracted,
        source="wikipedia",
        evidence_text=snippets,
    )
    return ["wikipedia"] if updates else []


async def fill_from_sec_edgar(row: dict[str, Any]) -> list[str]:
    from vendor_intel.enrichment.gap_fill.gaps import has_revenue, row_has_gaps

    if not row_has_gaps(row) or has_revenue(row):
        return []
    name = norm(row.get("company") or row.get("brand"))
    if not name:
        return []

    snippets = ""
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            url = f"https://efts.sec.gov/LATEST/search-index?q={quote(name)}&forms=10-K"
            resp = await client.get(url, headers={"User-Agent": "CoherentGapFill/1.0 (research@local)"})
            if resp.status_code == 200:
                data = resp.json()
                hits = (data.get("hits") or {}).get("hits") or []
                parts: list[str] = []
                for hit in hits[:5]:
                    src = hit.get("_source") or {}
                    parts.append(
                        f"[SEC] {src.get('display_names', [''])[0] if src.get('display_names') else name} "
                        f"| {src.get('biz_locations', '')} | {src.get('file_date', '')}"
                    )
                snippets = "\n".join(parts)
    except Exception:
        snippets = ""

    if not snippets:
        return []
    extracted = await _llm_extract(
        name,
        domain_from_row(row),
        snippets,
        fields_hint="US SEC EDGAR public company filings.",
    )
    updates = merge_extracted(
        row, extracted, source="sec_edgar", evidence_text=snippets, force_commit=True
    )
    return ["sec_edgar"] if updates else []


async def fill_from_locations_search(row: dict[str, Any], router: FreeSearchRouter) -> list[str]:
    from vendor_intel.enrichment.gap_fill.gaps import has_offices, row_has_gaps

    if not row_has_gaps(row) or has_offices(row):
        return []
    name = norm(row.get("company") or row.get("brand"))
    domain = domain_from_row(row)
    if not name:
        return []
    q = f'"{name}" locations offices worldwide'
    if domain:
        q += f" site:{domain}"
    snippets = await _search_snippets(router, q)
    extracted = await _llm_extract(
        name,
        domain,
        snippets,
        fields_hint="Office locations and cities/regions served.",
    )
    updates = merge_extracted(
        row, extracted, source="locations", evidence_text=snippets
    )
    return ["locations"] if updates else []


async def fill_from_contact_page(row: dict[str, Any]) -> list[str]:
    from vendor_intel.enrichment.gap_fill.contact_page import extract_contact_from_website

    if has_email(row) and has_phone(row):
        return []
    domain = domain_from_row(row)
    if not domain:
        return []
    extracted = await extract_contact_from_website(row)
    updates = merge_contact_extracted(row, extracted, source="contact_page")
    return ["contact_page"] if updates else []


async def fill_from_leadership(row: dict[str, Any], router: FreeSearchRouter) -> list[str]:
    from vendor_intel.enrichment.gap_fill.contact_page import extract_leadership_from_website

    if has_contact_person(row):
        return []
    domain = domain_from_row(row)
    name = norm(row.get("company") or row.get("brand"))
    if not domain or not name:
        return []

    extracted = await extract_leadership_from_website(row)
    updates = merge_contact_extracted(row, extracted, source="leadership")

    if not has_contact_person(row):
        q = f'"{name}" "head of sales" OR "sales director" OR "commercial director" OR procurement site:{domain}'
        snippets = await _search_snippets(router, q, max_hits=6)
        if snippets:
            from backend.config import get_settings, sync_opencode_to_openai_env
            from openai import AsyncOpenAI
            import json as _json
            import os as _os

            sync_opencode_to_openai_env()
            cfg = get_settings()
            if cfg.openai_api_key:
                client = AsyncOpenAI(api_key=cfg.openai_api_key)
                model = (_os.getenv("OPENAI_MODEL") or cfg.model_extract or "gpt-4o-mini").strip()
                prompt = (
                    f"Company: {name}\nDomain: {domain}\n\n"
                    "From the search snippets below, extract ONLY if explicitly stated:\n"
                    "contact_person (sales or procurement leader full name), contact_role (sales/procurement title only).\n"
                    "Return JSON: contact_person, contact_role. Empty string if unknown. Do not guess.\n\n"
                    f"{snippets[:5000]}"
                )
                try:
                    resp = await client.chat.completions.create(
                        model=model,
                        messages=[{"role": "user", "content": prompt}],
                        response_format={"type": "json_object"},
                        temperature=0,
                    )
                    text = (resp.choices[0].message.content or "").strip()
                    data = _json.loads(text) if text else {}
                    if isinstance(data, dict):
                        search_updates = merge_contact_extracted(row, data, source="leadership_search")
                        updates.extend(search_updates)
                except Exception:
                    pass

    return ["leadership"] if updates else []


def _openai_residual_enabled() -> bool:
    """OpenAI residual after Google AI / DDGS / SearXNG (any market). Default on."""
    for key in ("GAP_FILL_OPENAI_RESIDUAL", "SEARCH_STACK_OPENAI_RESIDUAL"):
        raw = (os.getenv(key) or "").strip().lower()
        if raw in ("0", "false", "no", "off"):
            return False
        if raw in ("1", "true", "yes", "on"):
            return True
    return True  # default on when unset


async def fill_from_openai_residual(
    row: dict[str, Any],
    router: FreeSearchRouter | None = None,
) -> list[str]:
    """Last-resort OpenAI SDK fill for gaps left after Google AI / DDGS / SearXNG / etc.

    Market-agnostic: uses company name + market/query from the row. Never overwrites
    fields already filled by earlier sources.
    """
    from vendor_intel.enrichment.gap_fill.gaps import (
        has_contact_person,
        has_core_categories,
        has_founded,
        has_headquarters,
        has_key_brands,
        has_offices,
        has_revenue,
        has_specialty_focus,
        missing_fields,
        sync_crawl_from_raw,
    )

    if not _openai_residual_enabled():
        return []
    if not _gap_fill_use_llm():
        return []

    gaps = missing_fields(row)
    if not gaps:
        return []

    name = norm(row.get("company") or row.get("brand"))
    if not name:
        return []
    domain = domain_from_row(row)
    market = norm(row.get("market") or row.get("query") or row.get("industry") or "")

    hint_bits: list[str] = []
    if not has_founded(row):
        hint_bits.append("founded year")
    if not has_headquarters(row):
        hint_bits.append("headquarters")
    if not has_offices(row):
        hint_bits.append("cities/regions")
    if not has_revenue(row):
        hint_bits.append("turnover RANGE e.g. $80–100M")
    if not has_core_categories(row):
        hint_bits.append("core categories")
    if not has_specialty_focus(row):
        hint_bits.append("specialty focus")
    if not has_key_brands(row):
        hint_bits.append("key brands represented")
    if not has_contact_person(row):
        hint_bits.append("sales or procurement contact + role")
    if not hint_bits:
        return []

    # Prefer OpenAI Responses web_search (sync client in thread) when available;
    # else DDGS/SearXNG snippets + chat extract.
    snippets = ""
    try:
        from openai import OpenAI
        from backend.config import get_settings, sync_opencode_to_openai_env

        sync_opencode_to_openai_env()
        cfg = get_settings()
        api_key = (cfg.openai_api_key or os.getenv("OPENAI_API_KEY") or "").strip()
        if api_key:
            model = (os.getenv("OPENAI_MODEL") or cfg.model_extract or "gpt-4o-mini").strip()
            client = OpenAI(
                api_key=api_key,
                base_url=(os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/"),
            )
            system = (
                "You research ONE company with LIVE WEB SEARCH. "
                "Return ONLY facts found on the web. Do not invent. "
                "Empty string for unknown. "
                "Return JSON keys: headquarters, founded_year, employee_count, revenue, "
                "offices, linkedin_url, core_categories, specialty_focus, "
                "key_brands_represented, contact_person, contact_role."
            )
            user = (
                f"Market context: {market or 'general vendor landscape'}\n"
                f"Company: {name}\n"
                f"Domain: {domain or 'unknown'}\n"
                f"Fill only these missing fields: {', '.join(hint_bits)}\n"
                "Search official site, LinkedIn company page, directories, news."
            )
            try:
                resp = client.responses.create(
                    model=model,
                    instructions=system,
                    input=user,
                    tools=[{"type": "web_search"}],
                    temperature=0.1,
                    max_output_tokens=2000,
                    text={"format": {"type": "json_object"}},
                )
                text = getattr(resp, "output_text", None) or ""
                if not text:
                    # fallback gather
                    parts = []
                    for item in getattr(resp, "output", None) or []:
                        for c in getattr(item, "content", None) or []:
                            t = getattr(c, "text", None)
                            if t:
                                parts.append(str(t))
                    text = "\n".join(parts)
                data = json.loads(text) if text.strip().startswith("{") else {}
                if isinstance(data, dict) and data:
                    updates = merge_extracted(
                        row,
                        data,
                        source="openai_sdk_residual",
                        evidence_text=f"{name} {domain} {market}",
                    )
                    if updates:
                        sync_crawl_from_raw(row)
                        return ["openai_sdk_residual"]
            except Exception:
                pass
    except Exception:
        pass

    # Fallback: free search stack snippets + LLM extract
    if router is not None:
        q_bits = [
            f"{name} founded headquarters",
            f"{name} {market} distributor".strip(),
            f"{name} official website about",
        ]
        chunks = []
        for q in q_bits[:3]:
            sn = await _search_snippets(router, q, max_hits=6)
            if sn:
                chunks.append(sn)
        snippets = "\n\n".join(chunks)[:8000]
    if not snippets:
        return []

    extracted = await _llm_extract(
        name,
        domain,
        snippets,
        fields_hint="Fill: " + ", ".join(hint_bits) + ".",
    )
    updates = merge_extracted(
        row, extracted, source="openai_sdk_residual", evidence_text=snippets
    )
    if updates:
        sync_crawl_from_raw(row)
        return ["openai_sdk_residual"]
    return []


# Default order for ANY market (batch of 1…N): free/search first, OpenAI residual last.
DEFAULT_SOURCES = (
    "google_ai",  # 1) Google AI scraper
    "backfill",  # 2) DDGS / SearXNG / router web search
    "wikipedia",
    "wikidata",
    "owler",
    "linkedin",
    "crunchbase",
    "sec",
    "locations",
    "contact_page",
    "leadership",
    "openai_residual",  # 3) OpenAI SDK only for leftover gaps
)

CONTACT_DEFAULT_SOURCES = (
    "contact_page",
    "leadership",
)


def parse_sources(spec: str | None) -> tuple[str, ...]:
    if not spec or spec.strip().lower() in ("all", "default"):
        return DEFAULT_SOURCES
    if spec.strip().lower() in ("contact", "contact_all"):
        return CONTACT_DEFAULT_SOURCES
    valid = set(DEFAULT_SOURCES) | set(CONTACT_DEFAULT_SOURCES) | {"openai_residual"}
    out = [s.strip().lower() for s in spec.split(",") if s.strip()]
    # aliases
    normalized = []
    for s in out:
        if s in ("openai", "openai_sdk", "residual"):
            normalized.append("openai_residual")
        else:
            normalized.append(s)
    return tuple(s for s in normalized if s in valid) or DEFAULT_SOURCES
