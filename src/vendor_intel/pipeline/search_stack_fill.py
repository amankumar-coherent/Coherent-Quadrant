"""Fill landscape rows: Google AI scraper FIRST, then DeepSeek residual for empties.

Order (Step 5):
  1) Google AI scraper fills every missing SLIM column it can find (parse scrape → columns)
  2) If any column is still empty / \"Not publicly disclosed\" → DeepSeek (OPENAI_*)
     residual fill for those gaps only (never overwrites Google AI values)

Env:
  SEARCH_STACK_SOURCES=google_ai          (default; comma list if you want extras)
  SEARCH_STACK_OPENAI_RESIDUAL=true|false (default true — DeepSeek residual)
  SEARCH_STACK_RESIDUAL_COLUMNS=Headquarters,Website
      (optional; Excel header names — skip Employees/revenue/etc. for Company Details)
  GOOGLE_AI_GAP_FILL_FIELDS=headquarters,website
      (optional; Google ask only these gap keys — Company Details = HQ + site)
  EXPAND_FILL_CONCURRENT / GAP_FILL_CONCURRENT — parallel companies in 5a (default 4)
  EXPAND_RESIDUAL_CONCURRENT — parallel DeepSeek residual in 5b (default 2)
"""
from __future__ import annotations

import asyncio
import os
from typing import Any

from vendor_intel.config import Settings
from vendor_intel.pipeline.openai_expand_checkpoint import ExpandCheckpoint
from vendor_intel.pipeline.web_expand import HEADERS, MARKET_DEFAULTS, _blank_row, _norm

_NPD = frozenset(
    {
        "",
        "n/a",
        "na",
        "none",
        "-",
        "—",
        "not publicly disclosed",
        "unknown",
        "tbd",
        "todo",
        "not applicable",
    }
)

# Columns worth spending OpenAI residual fill on (slim landscape only)
_RESIDUAL_PRIORITY = (
    "Founded",
    "Headquarters",
    "Continent / Geography",
    "Operational Presence",
    "Ownership",
    "Employees",
    "Contact Person",
    "Role",
    "Email",
    "Office No.",
    "LinkedIn",
    "Website",
    "Core Categories",
    "Specialty Focus",
    "Key Brands Represented",
    "Retail / E-commerce / Both",
    "Distribution Type",
    "Country Code",
    "Region Code",
    "Summary",
)


def _log(msg: str) -> None:
    print(msg, flush=True)


def _is_npd(val: Any) -> bool:
    return str(val or "").strip().lower() in _NPD


def _openai_residual_enabled() -> bool:
    raw = (os.getenv("SEARCH_STACK_OPENAI_RESIDUAL") or "true").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _fill_concurrent() -> int:
    raw = os.getenv("EXPAND_FILL_CONCURRENT") or os.getenv("GAP_FILL_CONCURRENT") or "4"
    try:
        return max(1, int(raw))
    except ValueError:
        return 4


def _residual_concurrent() -> int:
    raw = os.getenv("EXPAND_RESIDUAL_CONCURRENT") or "2"
    try:
        return max(1, int(raw))
    except ValueError:
        return 2


def _ckpt_every() -> int:
    raw = os.getenv("EXPAND_FILL_CKPT_EVERY") or "1"
    try:
        return max(1, int(raw))
    except ValueError:
        return 10


def _prepare_step5_google_first() -> None:
    """Google AI scrape first; DeepSeek writes useful sentences into columns.

    Nested openai_residual inside gap_fill_row stays off (sources list). Residual
    DeepSeek fill runs only in substep 5b for leftover empties.
    """
    from vendor_intel.pipeline.chatgpt_env import apply_chatgpt_expand_env

    apply_chatgpt_expand_env()
    os.environ["GAP_FILL_USE_LLM"] = "true"
    os.environ.setdefault("GOOGLE_AI_SCRAPER_LLM_CLEAN", "true")
    os.environ.setdefault("GOOGLE_AI_SCRAPER_LLM_CLEAN_ONLY_WHEN_MISSING", "false")
    os.environ.pop("SEARCH_STACK_ONLY", None)


def _default_stack_sources() -> tuple[str, ...]:
    """Default: Google AI only. Override with SEARCH_STACK_SOURCES=google_ai,backfill,…"""
    raw = (os.getenv("SEARCH_STACK_SOURCES") or "google_ai").strip()
    if not raw:
        return ("google_ai",)
    parts = [p.strip().lower() for p in raw.split(",") if p.strip()]
    return tuple(parts) if parts else ("google_ai",)


def _residual_priority() -> tuple[str, ...]:
    """Excel columns DeepSeek residual may fill. Env SEARCH_STACK_RESIDUAL_COLUMNS."""
    raw = (os.getenv("SEARCH_STACK_RESIDUAL_COLUMNS") or "").strip()
    if not raw:
        return _RESIDUAL_PRIORITY
    wanted = {p.strip() for p in raw.split(",") if p.strip()}
    filtered = tuple(h for h in _RESIDUAL_PRIORITY if h in wanted)
    return filtered or _RESIDUAL_PRIORITY


def _row_gaps(row: dict[str, str]) -> list[str]:
    return [h for h in _residual_priority() if _is_npd(row.get(h))]


def landscape_to_company(row: dict[str, str], *, market: str) -> dict[str, Any]:
    """Convert Excel landscape row → gap_fill company dict."""
    name = str(row.get("Company") or row.get("name") or "").strip()
    website = str(row.get("Website") or row.get("website") or "").strip()
    crawl: dict[str, Any] = {}

    def take(src: str, dest: str) -> None:
        v = str(row.get(src) or "").strip()
        if v and not _is_npd(v):
            crawl[dest] = v

    take("Founded", "founded_year")
    take("Headquarters", "headquarters")
    take("Operational Presence", "offices")
    take("Continent / Geography", "regions_served")
    take("Ownership", "ownership")
    take("Employees", "employee_count")
    take("LinkedIn", "linkedin")
    take("Core Categories", "core_categories")
    take("Specialty Focus", "specialty_focus")
    take("Key Brands Represented", "key_brands_represented")
    take("Retail / E-commerce / Both", "retail_ecommerce")
    take("Distribution Type", "distribution_type")
    take("Contact Person", "contact_person")
    take("Role", "contact_role")
    take("Email", "email")
    take("Office No.", "phone")
    take("Summary", "summary")
    # Legacy aliases
    take("Cities / Regions", "offices")
    take("Phone / WhatsApp", "phone")
    take("Regions Served", "regions_served")
    if website:
        crawl["website"] = website

    return {
        "company": name,
        "brand": name,
        "website": website,
        "market": market,
        "query": market,
        "_crawl": crawl,
        "_crawl_raw": {
            "data": {
                "company": {"name": name},
                "location": {},
                "financials": {},
                "contact": {},
            }
        },
    }


def company_to_landscape(
    company_row: dict[str, Any],
    *,
    family: str,
    base: dict[str, str] | None = None,
    source: str = "search_stack_fill",
) -> dict[str, str]:
    """Map gap_fill company dict back onto landscape HEADERS."""
    crawl = company_row.get("_crawl") if isinstance(company_row.get("_crawl"), dict) else {}
    name = str(
        company_row.get("company")
        or company_row.get("brand")
        or (base or {}).get("Company")
        or ""
    ).strip()
    website = str(
        company_row.get("website")
        or crawl.get("website")
        or (base or {}).get("Website")
        or ""
    ).strip()
    out = _blank_row(name, website, family, source)
    if base:
        for h in HEADERS:
            bv = str(base.get(h) or "").strip()
            if bv and not _is_npd(bv):
                out[h] = bv

    mapping = {
        "Founded": crawl.get("founded_year"),
        "Headquarters": crawl.get("headquarters") or crawl.get("contact_address"),
        "Operational Presence": crawl.get("offices") or crawl.get("operational_presence"),
        "Continent / Geography": crawl.get("regions_served"),
        "Ownership": crawl.get("ownership"),
        "Employees": crawl.get("employee_count"),
        "LinkedIn": crawl.get("linkedin"),
        "Core Categories": crawl.get("core_categories"),
        "Specialty Focus": crawl.get("specialty_focus"),
        "Key Brands Represented": crawl.get("key_brands_represented"),
        "Retail / E-commerce / Both": crawl.get("retail_ecommerce"),
        "Distribution Type": crawl.get("distribution_type"),
        "Contact Person": crawl.get("contact_person"),
        "Role": crawl.get("contact_role"),
        "Email": crawl.get("email"),
        "Office No.": crawl.get("phone"),
        "Summary": crawl.get("summary"),
        "Website": website or crawl.get("website"),
    }
    for h, val in mapping.items():
        s = str(val or "").strip()
        if s and not _is_npd(s):
            out[h] = s

    from vendor_intel.enrichment.known_founded import apply_known_founded_to_row

    out = apply_known_founded_to_row(out)

    defaults = MARKET_DEFAULTS.get(family) or {}
    for h, dv in defaults.items():
        if h in HEADERS and (_is_npd(out.get(h)) or not str(out.get(h) or "").strip()):
            out[h] = dv

    # Contacts stay empty when unknown (do not invent / do not write NPD)
    _contact = ("Email", "Office No.", "LinkedIn", "Contact Person", "Role")
    for c in _contact:
        if _is_npd(out.get(c)):
            out[c] = ""
    for h in HEADERS:
        if not str(out.get(h) or "").strip():
            if h in _contact or h in ("Country Code", "Region Code"):
                out[h] = out.get(h) or ""
            else:
                out[h] = "Not publicly disclosed"
    src = out.get("Data Sources") or ""
    if source not in src:
        out["Data Sources"] = f"{src}; {source}".strip("; ")
    if not str(out.get("Summary") or "").strip() or _is_npd(out.get("Summary")):
        out["Summary"] = (
            f"{name} — channel company for this market; "
            "details filled via Google AI scraper"
            + (" + DeepSeek residual" if "openai" in source or "residual" in source else "")
            + ("+Apollo" if "apollo" in source else "")
            + "."
        )
    try:
        from vendor_intel.export.landscape_slim import finalize_slim_row

        out = finalize_slim_row(out)
    except Exception:
        pass
    return out


def _apply_residual_updates(row: dict[str, str], updates: dict[str, str]) -> dict[str, str]:
    """Fill only empty/NPD fields; never overwrite good search-stack values."""
    out = dict(row)
    changed = 0
    for h, val in updates.items():
        if h.startswith("_") or h == "Company" or h not in HEADERS:
            continue
        s = str(val or "").strip()
        if not s or _is_npd(s):
            continue
        if not _is_npd(out.get(h)):
            continue
        out[h] = s
        changed += 1
    if changed:
        src = str(out.get("Data Sources") or "")
        tag = "openai_sdk_residual"
        if tag not in src:
            out["Data Sources"] = f"{src}; {tag}".strip("; ")
    return out


async def _openai_residual_fill_rows(
    *,
    query: str,
    family: str,
    rows: list[dict[str, str]],
    ckpt: ExpandCheckpoint | None = None,
) -> list[dict[str, str]]:
    """LLM residual (OpenAI web_search or DeepSeek chat) for rows still gapped after search stack."""
    if not rows or not _openai_residual_enabled():
        _log("    → substep 5b: LLM residual SKIP (disabled or no rows)")
        return rows

    need = [(i, r) for i, r in enumerate(rows) if _row_gaps(r)]
    if not need:
        _log("    → substep 5b: LLM residual SKIP (no remaining gaps)")
        return rows

    try:
        from vendor_intel.pipeline.chatgpt_expand import (
            _client,
            _model,
            _web_search_json,
            _llm_label,
        )
    except Exception as err:  # noqa: BLE001
        _log(f"    → substep 5b: LLM residual unavailable: {err}")
        return rows

    settings = Settings()
    try:
        client = _client(settings)
        model = _model(settings)
    except Exception as err:  # noqa: BLE001
        _log(f"    → substep 5b: LLM residual SKIP (no client): {err}")
        return rows

    label = _llm_label(settings)
    _log(
        f"    → substep 5b: {label} residual fill for {len(need)}/{len(rows)} "
        f"companies still gapped after Google AI/DDGS/SearXNG…"
    )
    out = list(rows)
    sem = asyncio.Semaphore(_residual_concurrent())
    done_count = 0
    lock = asyncio.Lock()

    async def _one(n: int, idx: int, row: dict[str, str]) -> None:
        nonlocal done_count
        gaps = _row_gaps(row)
        name = str(row.get("Company") or "?")
        async with sem:
            _log(f"    → substep 5b.{n}: residual {n}/{len(need)}: {name} gaps={gaps[:8]}")
            slim = {h: row.get(h) for h in HEADERS}
            try:
                data = await asyncio.to_thread(
                    _web_search_json,
                    client,
                    model,
                    system=(
                        "You are a vendor-intelligence researcher (DeepSeek residual fill). "
                        "Google AI already tried; fill ONLY the missing empty / "
                        '"Not publicly disclosed" fields listed. Keep every already-filled '
                        "field unchanged. Do NOT invent founded years, HQ cities, emails, "
                        "phones, or brand lists. If a fact is not found, omit that key or use "
                        '"Not publicly disclosed" (contacts: leave empty, never invent). '
                        f"Required landscape keys: {list(HEADERS)!r}. "
                        'Return JSON: {"row":{...only keys you can fill or confirm...}}'
                    ),
                    user=(
                        f"Market: {query}\n"
                        f"Family: {family}\n"
                        f"Company: {name}\n"
                        f"Website: {row.get('Website') or ''}\n"
                        f"Current row (already filled by Google AI — do not overwrite):\n{slim}\n"
                        f"EMPTY columns still to fill: {gaps}\n\n"
                        "Use public knowledge + any evidence in the prompt. "
                        "Prefer official website, LinkedIn company page, directories, and news."
                    ),
                    label=f"residual-{n}",
                    max_tokens=3500,
                )
            except Exception as err:  # noqa: BLE001
                _log(f"      · residual error: {type(err).__name__}: {err}")
                return

            src_row: dict[str, Any] = {}
            if isinstance(data, dict):
                maybe = data.get("row") if isinstance(data.get("row"), dict) else data
                if isinstance(maybe, dict):
                    src_row = maybe
            updates = {
                h: str(src_row.get(h) or "").strip()
                for h in gaps
                if str(src_row.get(h) or "").strip()
            }
            async with lock:
                if updates:
                    out[idx] = _apply_residual_updates(row, updates)
                    filled_n = sum(1 for h in gaps if not _is_npd(out[idx].get(h)))
                    _log(f"      · residual filled {filled_n}/{len(gaps)} gap fields")
                else:
                    _log("      · residual: no new facts found")
                done_count += 1
                if ckpt and done_count % _ckpt_every() == 0:
                    ckpt.bump(
                        "5_fill",
                        f"5b.{done_count}",
                        progress={
                            "residual_count": done_count,
                            "fill_backend": "search+openai_residual",
                        },
                        filled_part=out,
                        note=f"openai residual {done_count}/{len(need)}",
                    )
                    ckpt.bump(
                        "5_fill",
                        f"5b.{done_count}",
                        progress={
                            "residual_count": done_count,
                            "fill_backend": "search+openai_residual",
                        },
                        filled_part=out,
                        note=f"openai residual {done_count}/{len(need)}",
                    )

    await asyncio.gather(*[_one(n, idx, row) for n, (idx, row) in enumerate(need, 1)])

    if ckpt:
        ckpt.bump(
            "5_fill",
            "5b_done",
            progress={"fill_backend": "search+openai_residual"},
            filled_part=out,
            note="openai residual complete",
        )
    still = sum(1 for r in out if _row_gaps(r))
    _log(f"    → substep 5b done: {still}/{len(out)} rows still have priority gaps")
    return out


async def search_stack_fill_rows(
    *,
    query: str,
    family: str,
    rows: list[dict[str, str]],
    ckpt: ExpandCheckpoint | None = None,
    sources: tuple[str, ...] | None = None,
    use_apollo: bool = True,
    openai_residual: bool | None = None,
) -> list[dict[str, str]]:
    """Fill via Google AI first; then DeepSeek residual for leftover NPD/gaps."""
    if not rows:
        return rows

    _prepare_step5_google_first()

    from vendor_intel.clients.search_router import FreeSearchRouter
    from vendor_intel.enrichment.gap_fill.orchestrator import gap_fill_row
    from vendor_intel.enrichment.gap_fill.sources import parse_sources

    settings = Settings()
    router = FreeSearchRouter(settings)
    if sources is None:
        src_tuple = parse_sources(",".join(_default_stack_sources()))
    else:
        src_tuple = (
            parse_sources(",".join(sources))
            if isinstance(sources, tuple)
            else parse_sources(str(sources))
        )
    # Keep LinkedIn MCP out of this path; Google AI is primary
    allowed = {
        "google_ai",
        "backfill",
        "wikipedia",
        "owler",
        "wikidata",
        "locations",
        "crunchbase",
        "sec",
        "contact_page",
        "leadership",
    }
    src_tuple = tuple(s for s in src_tuple if s in allowed and s != "linkedin")
    if not src_tuple:
        src_tuple = ("google_ai",)
    # Always put google_ai first when present
    if "google_ai" in src_tuple:
        src_tuple = ("google_ai",) + tuple(s for s in src_tuple if s != "google_ai")

    try:
        from vendor_intel.integrations.agent_reach_client import exa_search_enabled

        exa_on = bool(exa_search_enabled())
    except Exception:
        exa_on = False

    filled: list[dict[str, str]] = list(ckpt.data("filled_part") or []) if ckpt else []
    # If checkpoint already finished residual, return as-is
    if ckpt and ckpt.is_step_done("5_fill") and filled:
        _log(f"    → substep 5: SKIP (checkpoint) — {len(filled)} filled")
        return filled

    done = {_norm(str(r.get("Company") or "")) for r in filled if r.get("Company")}
    pending = [
        r
        for r in rows
        if _norm(str(r.get("Company") or r.get("name") or "")) not in done
    ]
    apollo_on = use_apollo and bool((os.getenv("APOLLO_API_KEY") or "").strip())
    do_residual = _openai_residual_enabled() if openai_residual is None else bool(openai_residual)
    conc = _fill_concurrent()
    if ckpt:
        ckpt.begin(
            "5_fill",
            "5a_start",
            note=f"begin Google AI fill {len(pending)} pending",
        )
    _log(
        f"    → substep 5a: Google AI fill FIRST {len(rows)} companies "
        f"(sources={','.join(src_tuple)}; Exa={'on' if exa_on else 'off'}; "
        f"Apollo={'on' if apollo_on else 'off'}; concurrent={conc}; "
        f"DeepSeek residual later={'on' if do_residual else 'off'})"
        + (f" — resume {len(filled)} done, {len(pending)} left" if filled else "")
    )
    if not pending and filled:
        _log("    → substep 5a: search-stack already complete (checkpoint)")
    elif not pending:
        _log("    → substep 5a: nothing pending")
        if ckpt:
            ckpt.mark_step_done("5_fill", filled_part=filled)
        return filled

    total = len(pending)
    sem = asyncio.Semaphore(conc)
    lock = asyncio.Lock()
    ckpt_every = _ckpt_every()

    async def _fill_one(i: int, row: dict[str, str]) -> dict[str, str]:
        name = str(row.get("Company") or row.get("name") or "?")
        async with sem:
            _log(f"    → substep 5a.{i}: search-fill {i}/{total}: {name}")
            company = landscape_to_company(row, market=query)
            try:
                stats = await gap_fill_row(
                    company,
                    router=router,
                    owler_client=None,
                    owler_model="",
                    sources=src_tuple,
                    idx=i,
                    total=total,
                )
                applied = stats.get("sources") or []
                _log(f"      · sources applied: {applied or 'none'}")
            except Exception as err:  # noqa: BLE001
                _log(f"      · search-fill error: {type(err).__name__}: {err}")

            if apollo_on:
                try:
                    from vendor_intel.pipeline.openai_fill_enrich import apollo_contact_lookup

                    _log(f"      · apollo lookup… {name}")
                    try:
                        apollo_timeout = float(os.getenv("APOLLO_CONTACT_TIMEOUT_SEC") or "25")
                    except ValueError:
                        apollo_timeout = 25.0
                    hit = await asyncio.wait_for(
                        apollo_contact_lookup(
                            name, str(row.get("Website") or company.get("website") or "")
                        ),
                        timeout=max(5.0, apollo_timeout),
                    )
                    if hit and not hit.get("_error"):
                        crawl = company.setdefault("_crawl", {})
                        if hit.get("Contact Person"):
                            crawl["contact_person"] = hit["Contact Person"]
                        if hit.get("Role"):
                            crawl["contact_role"] = hit["Role"]
                        if hit.get("Email"):
                            crawl["email"] = hit["Email"]
                        if hit.get("Office No.") or hit.get("Phone / WhatsApp"):
                            crawl["phone"] = hit.get("Office No.") or hit["Phone / WhatsApp"]
                        if hit.get("_person_linkedin") and not crawl.get("linkedin"):
                            crawl["linkedin"] = hit["_person_linkedin"]
                        _log("      · apollo contact applied")
                    else:
                        _log("      · apollo: no sales/procurement hit")
                except asyncio.TimeoutError:
                    _log(f"      · apollo skip: timeout ({apollo_timeout:.0f}s)")
                except Exception as err:  # noqa: BLE001
                    _log(f"      · apollo skip: {type(err).__name__}")

            src_label = "+".join(src_tuple) if src_tuple else "google_ai"
            if apollo_on:
                src_label += "+apollo"
            landscape = company_to_landscape(
                company,
                family=family,
                base=row if row.get("Company") else None,
                source=src_label,
            )
            async with lock:
                filled.append(landscape)
                if ckpt and len(filled) % ckpt_every == 0:
                    ckpt.bump(
                        "5_fill",
                        f"5a.{len(filled)}",
                        progress={"fill_count": len(filled), "fill_backend": "search"},
                        filled_part=filled,
                        note=f"search-filled {len(filled)}",
                    )
            return landscape

    await asyncio.gather(*[_fill_one(i, row) for i, row in enumerate(pending, 1)])

    _log(f"    → substep 5a done: {len(filled)} rows via Google AI scraper")

    # 5b — DeepSeek (OPENAI_*) only for leftover gaps / Not publicly disclosed
    if do_residual:
        if ckpt:
            ckpt.begin("5_fill", "5b_start", note="begin DeepSeek residual")
        filled = await _openai_residual_fill_rows(
            query=query,
            family=family,
            rows=filled,
            ckpt=ckpt,
        )
    else:
        _log("    → substep 5b: DeepSeek residual disabled (SEARCH_STACK_OPENAI_RESIDUAL=false)")

    if ckpt:
        ckpt.mark_step_done("5_fill", filled_part=filled)
    _log(
        f"    → substep 5 done: {len(filled)} rows "
        f"(Google AI first"
        f"{'; DeepSeek residual for remaining empty columns' if do_residual else ''})"
    )
    return filled
