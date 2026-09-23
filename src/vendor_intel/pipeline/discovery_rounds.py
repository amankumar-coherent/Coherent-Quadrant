"""Find companies in ROUNDS: one loop, not three stages asking the same thing.

The expand pipeline historically found companies in three places — Step 1
recall, Step 2a discover and Step 2g list-discover. All three ask Google the
same question in different words, so once the first has taken the obvious
answers the others re-ask and get the same names back, which are then
dropped as duplicates.

Measured on Global Silicon Carbide: recall found 118 companies, 2a found 0
new, and 2g found +1 across 9 queries. Roughly 35 paced queries produced
almost nothing while every one of them logged "JSON parse OK".

This module replaces all three with a single loop:

    round 1: ask for 10, exclusion list = []        -> 10 new
    round 2: ask for 10, exclusion list = those 10  ->  9 new
    ...
    3 consecutive empty rounds  -> market exhausted, stop

Design notes that matter (see COMPANY_DISCOVERY_ROUNDS.md):

* AI Mode is STATELESS, so "give me 10 more" means nothing — every round
  carries the names already collected.
* 10 per round: 1 wastes pacing, 25+ truncates the answer and the tail
  companies vanish silently.
* The exclusion block is capped by CHARACTERS, not just count — the whole
  prompt rides in the URL and Google 400s past ~8 KB.
* Stop on THREE empty rounds, never one, and never confuse "exhausted" with
  "blocked".
"""
from __future__ import annotations

from typing import Any, Callable

from vendor_intel.pipeline.geo_rotation import (
    COUNTRIES_BY_REGION,
    REGIONS,
    all_countries_by_coverage,
    is_single_country,
    states_for,
    coverage,
    rotation_hint,
    under_covered,
)

# Companies requested per discovery round.
#
# 10 is the conservative default: reliable for this schema, where 25+ starts
# truncating the JSON. Asking for more is the cheapest way to speed up a run
# that is query-bound rather than market-bound -- each round costs the same
# paced query whether it returns 10 names or 20.
#
# Override with DISCOVER_BATCH. Capped at 20: past that the reply routinely
# exceeds what the schema returns intact, and a truncated round yields FEWER
# usable companies than a smaller ask would have.
def _default_batch() -> int:
    import os

    try:
        value = int((os.getenv("DISCOVER_BATCH") or "10").strip())
    except (TypeError, ValueError):
        return 10
    return value if 5 <= value <= 20 else 10


DEFAULT_BATCH = _default_batch()


# Three empty rounds, not one — a single empty round is normal as a market
# thins out.
#
# Lower it (DISCOVER_EMPTY_BEFORE_ESCALATE=1) to reach the region/country
# sweep sooner. The broad ask runs dry long before the market does, and the
# country tier is where a thinning run finds its remaining companies -- but
# escalating too eagerly abandons a broad question that is still producing.
def _empty_before_escalate() -> int:
    import os

    try:
        value = int((os.getenv("DISCOVER_EMPTY_BEFORE_ESCALATE") or "3").strip())
    except (TypeError, ValueError):
        return 3
    return value if 1 <= value <= 5 else 3


EMPTY_ROUNDS_BEFORE_STOP = _empty_before_escalate()

# While sweeping one region, two empties is enough to move on. Three would
# spend an extra paced query per region across nine regions for very little.
EMPTY_ROUNDS_PER_REGION = 2

# How many times to work through all nine regions before giving up. One pass
# stopped Silicon Carbide at 216 of 300: regions that went quiet early still
# had companies left once the exclusion list had moved past the obvious names.
MAX_REGION_SWEEPS = 3

# A country gets ONE empty round, not two: there are 64 of them and most hold
# no participant in any given market, so a second confirming query is waste.
EMPTY_ROUNDS_PER_COUNTRY = 1

TOTAL_COUNTRIES = sum(len(v) for v in COUNTRIES_BY_REGION.values())

# A quota/CAPTCHA block is not an empty market, so blocked rounds are counted
# separately and never reported as "exhausted".
MAX_BLOCKED_ROUNDS = 3

_BLOCKED_MARKERS = (
    "request limit",
    "quota",
    "rate limited",
    "captcha",
    "unusual traffic",
)


def _is_blocked(err: BaseException) -> bool:
    """True when the backend refused to answer rather than finding nothing."""
    name = type(err).__name__.lower()
    if "captcha" in name:
        return True
    text = str(err).lower()
    return any(m in text for m in _BLOCKED_MARKERS)


# A contract manufacturer builds to another company's specification and owns
# no brand of its own, so it is never the "company behind the brand". The
# prompt says so, but a prompt is a request — this is the code-side gate.
_CONTRACT_MANUFACTURER_MARKERS = (
    "contract manufactur",
    "contract manufacturing",
    "oem/odm",
    "odm/oem",
    " odm",
    "white label",
    "white-label",
    "private label manufactur",
    "private-label manufactur",
    "toll manufactur",
    "toll processing",
    "electronics manufacturing services",
    " ems provider",
    "foundry service",
)


def is_contract_manufacturer(row: dict[str, Any]) -> bool:
    """True when the evidence says this entity makes other companies' product.

    Only the descriptive fields are searched. The company NAME is deliberately
    not matched on its own: a legitimate brand owner can be called
    "<X> Manufacturing", and dropping it would lose a real competitor.
    """
    blob = " ".join(
        str(row.get(k) or "")
        for k in ("why_related", "role", "ownership", "notes", "description")
    ).lower()
    return any(m in blob for m in _CONTRACT_MANUFACTURER_MARKERS)


def build_round_prompt(
    market: str,
    player_type: str,
    *,
    excluded_names: list[str],
    batch: int = DEFAULT_BATCH,
    market_type: str = "B2B",
    geo_hint: str = "",
    focus_region: str = "",
    country: str = "",
    scope: str = "",
) -> tuple[str, str]:
    """(system, user) for one discovery round.

    Seven parts in order — market, ask, who qualifies, typed exclusions with
    reasons, name exclusions, field rules, JSON template LAST. Constraints
    stated after the template are applied less reliably.

    `scope` is the operator-authored market definition (from queries/*.tsv,
    read into MARKET_SCOPE) — same text verify already judges candidates
    against. Without it here, discovery only has the bare market NAME to go
    on and verify has to reject everything discovery brings back that
    doesn't fit the definition, which wastes the whole query. Stating the
    definition up front means discovery mostly finds companies verify will
    actually keep.
    """
    # The JSON template must list EVERY field the report needs. Collecting a
    # company and looking up its details are the same lookup, so asking for
    # them together avoids a second pass per company — and the later gap-fill
    # pass was filling nothing at all when its legacy sources were down.
    #   headquarters -> "Found in" column
    #   ownership    -> "Company" column, as "Name (acquired by Parent)"
    #   offering     -> "Brand" column
    # BRAND-FIRST. The pipeline asks "what BRANDS exist in this market?" and
    # then "which company owns that brand?" — not "what companies exist?".
    # Treating every discovered company name as a brand produced rows like
    # Brand="Hamilton Housewares Pvt. Ltd." / Company="Hamilton Housewares
    # Pvt. Ltd.", which tells a reader nothing.
    #
    # SERVICE MARKETS ARE THE EXCEPTION. A Service Provider (marine seismic
    # processing, contract manufacturing, consulting, ...) does not sell a
    # named "brand" distinct from itself — it delivers a service under its
    # own corporate name. Asking the brand-first question anyway produced
    # zero results across 123 country- and city-focused rounds for a real
    # market (Marine Seismic Data Processing Services): the model correctly
    # has no brand to name and returns {"companies":[]} rather than force a
    # distinction that does not exist, even though real companies (Shearwater
    # GeoServices, Viridien, TGS) obviously operate in every one of those
    # places. Asking for the COMPANY directly is the same JSON shape the
    # rest of the pipeline already expects (brand falls back to the company
    # name), so nothing downstream needs to change.
    is_service_market = player_type.strip().lower() == "service provider"
    if is_service_market:
        system = (
            "You identify companies that ACTUALLY OPERATE in a market, "
            "delivering it as a service under their own name — not a brand "
            "distinct from the company. No invented names, no media, "
            "associations, research firms or geo labels. Return compact "
            "JSON only: "
            '{"companies":[{"brand":"...","company":"...","website":"https://...",'
            '"headquarters":"City, Country","ownership":"...",'
            '"ownership_confidence":"high|medium|low","verdict":"...",'
            '"why_related":"..."}]}'
        )
    else:
        system = (
            "You identify the BRANDS sold in a market and the COMPANY behind each "
            "brand. No invented names, no media, associations, research firms or "
            "geo labels. Return compact JSON only: "
            '{"companies":[{"brand":"...","company":"...","website":"https://...",'
            '"headquarters":"City, Country","ownership":"...",'
            '"ownership_confidence":"high|medium|low","verdict":"...",'
            '"why_related":"..."}]}'
        )

    if str(market_type).upper() == "B2C":
        qualifies = (
            f"A qualifying company's PRIMARY business must make it a "
            f"{player_type} in this market: it owns and markets a "
            "consumer-facing brand sold to individual consumers under its own "
            "name. That is what it IS, not something it also does."
        )
    else:
        qualifies = (
            f"A qualifying company's PRIMARY business must make it a "
            f"{player_type} in this market. That is what it IS, not something "
            "it also does."
        )

    # A region-focused round asks a genuinely DIFFERENT question rather than
    # appending a preference to the same one. Once the broad "give me 10 more"
    # is exhausted, repeating it returns nothing however it is decorated —
    # but "manufacturers headquartered in Brazil" reaches local players the
    # broad query never ranked high enough to mention.
    what = "COMPANIES that operate" if is_service_market else "BRANDS sold"
    company_behind = "" if is_service_market else ", each with the company behind it"
    if focus_region:
        ask = (
            f"Give me {batch} {what} in this market"
            f"{'' if is_service_market else ' whose company is'} "
            f"HEADQUARTERED IN {focus_region}"
            + (f", {country}" if country else "")
            + f"{company_behind}"
            ".\n\nThe company's own global headquarters must be in "
            f"{focus_region} — a local sales office, plant or distributor "
            "there does NOT qualify. Include national and regional companies, "
            "not only the global majors. If this region genuinely has no such "
            'company, return {"companies":[]} — do NOT substitute a company '
            "from elsewhere and do NOT invent one.\n\n"
        )
    elif country:
        # A country-scoped run must say so in the BROAD rounds too.
        # Without this only the state-focused rounds are constrained, and
        # the opening rounds fill the set with global majors that are then
        # thrown away at verification.
        ask = (
            f"Give me {batch} {what} in this market"
            f"{'' if is_service_market else ' whose company is'} "
            f"HEADQUARTERED IN {country}{company_behind}.\n\n"
            f"The company's own global headquarters must be in {country} — a "
            "local sales office, plant, subsidiary or distributor of a "
            "foreign company does NOT qualify. Include national and regional "
            "companies, not only the largest few. If there genuinely are no "
            'more such companies, return {"companies":[]} — do NOT substitute '
            "a company from another country and do NOT invent one.\n\n"
        )
    else:
        ask = f"Give me {batch} {what} in this market{company_behind}.\n\n"

    user = (
        f'Market: "{market}"\n\n'
        + (f"THIS MARKET COVERS EXACTLY: {scope}\n\n" if scope else "")
        + ask
        + f"WHO QUALIFIES:\n{qualifies}\n\n"
        "STRICTLY EXCLUDE, even if related to this market:\n"
        "- Consultancies, market-research firms, news outlets and industry "
        "associations — reporting on or advising a market is not operating "
        "in it.\n"
        "- Distributors and resellers — they carry other companies' product.\n"
        "- CONTRACT MANUFACTURERS, OEM/ODM makers, white-label and "
        "private-label producers — they build to another company's "
        "specification and own no brand of their own here. If a company's "
        "business is making products that are sold under SOMEONE ELSE'S "
        "brand, EXCLUDE it and name the brand owner instead.\n"
        "- Equipment and materials suppliers — they sell TO this market, not "
        "IN it.\n"
        "- A parent that does not itself sell in THIS market (name the "
        "operating subsidiary instead).\n"
        "If unsure, EXCLUDE.\n\n"
        f"{format_exclusions(excluded_names)}\n\n"
        # A name-exclusion list stops repeats but not the geographic habit:
        # the model keeps answering with the same few countries. The steer
        # sits here, after the exclusions and before the field rules, so the
        # rules stay adjacent to the JSON template they describe.
        # A named focus region overrides the soft preference list — two
        # competing sets of regions in one prompt contradict each other.
        + (f"{geo_hint}\n\n" if geo_hint and not focus_region else "")
        + "FIELD RULES:\n"
        + (
            (
                "- brand: repeat the company name here — a service provider has "
                "no separate consumer-facing brand, it delivers the service "
                "under its own corporate name.\n"
                "- company: the legal entity that actually DELIVERS this "
                "service. NEVER a distributor, reseller or channel partner. A "
                "parent that does not itself deliver the service in THIS market "
                "does not qualify — name the operating subsidiary instead.\n"
            )
            if is_service_market else
            (
                "- brand: the product / consumer-facing BRAND name as buyers know it "
                '(e.g. "Milton"). A brand is NOT a distributor and NOT a product '
                "category. If the company genuinely sells only under its own corporate "
                "name, repeat that name here rather than inventing a brand.\n"
                "- company: the legal entity that OWNS, manufactures under, or is "
                'responsible for that brand (e.g. "Hamilton Housewares Pvt. Ltd."). '
                "NEVER a distributor, reseller or channel partner — those carry the "
                "brand, they do not own it. If a contract manufacturer merely makes "
                "the product, the brand OWNER still goes here.\n"
            )
        )
        + "- website: the real official company domain. NEVER a LinkedIn, "
        "Bloomberg, Crunchbase or Wikipedia page.\n"
        '- headquarters: "City, Country" — exactly one global HQ, with the '
        'state for US companies (e.g. "Thousand Oaks, California, USA"). '
        'NEVER write "Global", "Worldwide", a bare region, or a count like '
        '"50+ countries".\n'
        '- ownership: "Independent", or "Acquired by <Parent>" / '
        '"Subsidiary of <Parent>" using the real parent name. State an '
        "acquisition ONLY if you can support it from the official "
        "company/brand site, an acquisition announcement, an "
        "investor-relations page, a regulatory filing or a reputable business "
        "source. NEVER infer one from similar names. If you cannot verify it, "
        'write "Independent".\n'
        "- ownership_confidence: high = an official company/brand source "
        "confirms it; medium = multiple reputable sources agree; low = only "
        "weak or indirect evidence. Be honest — a low is useful, a wrong high "
        "is not.\n"
        '- verdict: "in_market" only if it genuinely operates in this market; '
        'otherwise "unrelated" or "unknown". NEVER guess this field. Include '
        'the company ONLY if verdict is "in_market".\n'
        "- why_related: one sentence naming what it actually makes, supplies "
        "or does in THIS market.\n\n"
        "An empty string is CORRECT and preferred whenever you do not "
        "genuinely know a value. A wrong value is much worse than an empty one."
    )
    return system, user


def build_strict_service_round_prompt(
    market: str,
    market_definition: str,
    qualifying_services: list[str],
    excluded_categories: list[str],
    *,
    excluded_names: list[str],
    batch: int = DEFAULT_BATCH,
    focus_region: str = "",
) -> tuple[str, str]:
    """The operator-authored strict Service-Provider template, one focus
    region per call.

    A hand-written alternative to build_round_prompt() for markets where the
    generic exclusion list (distributors, contract manufacturers, equipment
    suppliers...) is not specific enough — this market also needs to reject
    standalone SOFTWARE vendors, multi-client DATA-LIBRARY companies, and
    oil & gas companies that process seismic data only for their OWN
    internal use, none of which the generic template names. Every section
    is exactly the operator's own wording; only `focus_region` and the
    exclusion list vary per call, so a country/city sweep can drive it the
    same way it drives build_round_prompt().
    """
    system = (
        "You are a strict B2B market-research analyst.\n\n"
        "Identify companies that ACTUALLY OPERATE in the market described "
        "below, delivering the defined services under their own company "
        "name.\n\n"
        "Return compact JSON only:\n\n"
        '{"companies":[{"brand":"...","company":"...","website":"https://...",'
        '"headquarters":"City, Country","ownership":"...",'
        '"ownership_confidence":"high|medium|low",'
        '"verdict":"in_market|unrelated|unknown","why_related":"..."}]}'
    )

    services = "\n".join(f"- {s}" for s in qualifying_services)
    exclusions = "\n".join(f"- {e}" for e in excluded_categories)
    find_n = f"Find {batch} companies"
    if focus_region:
        find_n = (
            f"Find {batch} companies HEADQUARTERED IN {focus_region} — a "
            "local sales office, plant or distributor there does NOT "
            "qualify. If this region genuinely has no such company, return "
            '{"companies":[]} — do NOT substitute a company from elsewhere '
            "and do NOT invent one."
        )

    user = (
        f'Market: "{market}"\n\n'
        f"MARKET DEFINITION:\n\n{market_definition}\n\n"
        "PLAYER TYPE:\nService Provider.\n\n"
        "WHO QUALIFIES:\n\n"
        "A company qualifies only if it ACTUALLY PROVIDES the services "
        "described above to external clients.\n\n"
        "The company should perform one or more of the following as a "
        f"commercial service:\n\n{services}\n\n"
        "The company must perform the processing/work itself for clients. "
        "Evidence should indicate that it processes, images, reprocesses, "
        "or interprets client data rather than merely selling technology.\n\n"
        f"STRICTLY EXCLUDE:\n\n{exclusions}\n\n"
        "IMPORTANT:\nDo not classify a company as a Service Provider merely "
        "because it operates in the same broad industry.\n\n"
        "The company must have clear evidence that it actually performs "
        "the defined service for clients.\n\n"
        "COMPANY NAME RULE:\n\n"
        "Use the company that ACTUALLY DELIVERS the service.\n\n"
        "- Do not list a parent holding company if an operating subsidiary "
        "actually provides the service.\n"
        "- Do not list a subsidiary separately if the parent itself "
        "directly provides the service.\n"
        "- Do not list a product/software brand as the company.\n"
        '- "brand" must repeat the actual service-provider company name.\n'
        "- Do not invent brands or company names.\n\n"
        "OWNERSHIP RULE:\n\nUse:\n"
        '- "Independent"\n'
        '- "Acquired by <Parent>"\n'
        '- "Subsidiary of <Parent>"\n\n'
        "Only state an acquisition or parent relationship when it can be "
        "verified from an official company source, acquisition "
        "announcement, regulatory filing, investor-relations source, or "
        "reputable business source.\n\n"
        "If ownership cannot be reliably verified, use:\n"
        '"Independent"\n\n'
        "HEADQUARTERS RULE:\n\nGive exactly one global headquarters:\n\n"
        '"City, Country"\n\n'
        "For US companies:\n"
        '"City, State, USA"\n\n'
        "Never use:\n- Global\n- Worldwide\n- Multiple locations\n"
        "- Region names\n- Country only\n- \"50+ countries\"\n\n"
        "EVIDENCE RULE:\n\nPrioritize evidence from:\n"
        "1. Official company website\n"
        "2. Official company service pages\n"
        "3. Company brochures/technical documents\n"
        "4. Regulatory filings\n"
        "5. Reputable business sources\n\n"
        "The evidence must support that the company actually performs the "
        "defined service.\n\n"
        'VERDICT RULE:\n\n"verdict": "in_market"\n\n'
        "ONLY when the company genuinely operates as defined above.\n\n"
        "If there is uncertainty, DO NOT guess. Exclude the company from "
        "the final list.\n\n"
        "WHY_RELATED RULE:\n\nWrite one concise sentence explaining exactly "
        "what the company does in this market.\n\n"
        f"{format_exclusions(excluded_names)}\n\n"
        "FINAL REQUIREMENT:\n\nReturn ONLY companies that meet the "
        "definition above.\n\n"
        "Do not return explanations, methodology, citations, notes, or "
        "companies that are merely adjacent to the market.\n\n"
        f"{find_n}"
    )
    return system, user


def build_global_strict_round_prompt(
    market: str,
    market_definition: str,
    qualifying_services: list[str],
    search_terms: list[str],
    excluded_categories: list[str],
    *,
    excluded_names: list[str],
    batch: int = 20,
) -> tuple[str, str]:
    """The operator's own global mega-prompt, one batch of `batch` per call.

    The one-shot "find up to 400" version of this prompt hit AI Mode's
    ~7800-char URL limit (measured: 7323 -> 7029 chars truncated, which cut
    into the JSON template) and returned truncated, unparseable JSON. Asking
    for a SMALL batch repeatedly keeps every single call well under that
    limit and lets the exclusion list carry state between calls, the same
    pattern build_round_prompt() already uses -- this just keeps the
    operator's own global-search wording and expanded search-term list
    instead of the pipeline's generic phrasing.
    """
    system = (
        "You are a strict global B2B market-research analyst. Identify "
        f"UNIQUE companies worldwide that ACTUALLY OPERATE in the market "
        "described below and deliver the service under their own company "
        "name. Return compact JSON only: "
        '{"companies":[{"brand":"...","company":"...","website":"https://...",'
        '"headquarters":"City, Country","ownership":"...",'
        '"ownership_confidence":"high|medium|low",'
        '"verdict":"in_market","why_related":"..."}]}'
    )

    services = "\n".join(f"- {s}" for s in qualifying_services)
    terms = "\n".join(f'"{t}"' for t in search_terms)
    exclusions = "\n".join(f"- {e}" for e in excluded_categories)

    user = (
        f'Market: "{market}"\n\n'
        f"MARKET DEFINITION:\n{market_definition}\n\n"
        "PLAYER TYPE:\nService Provider.\n\n"
        "WHO QUALIFIES:\n\n"
        "A company qualifies ONLY if it actually performs the service "
        "described above as a commercial service for external clients.\n\n"
        f"The company may provide one or more of:\n{services}\n\n"
        "IMPORTANT:\nThe company must actually EXECUTE the processing/"
        "service on client data. Merely owning, selling, licensing, "
        "distributing, acquiring, storing, or using the technology does "
        "NOT qualify.\n\n"
        "GLOBAL SEARCH REQUIREMENT:\nSearch globally and do not limit the "
        "results to large multinational companies. Actively identify large, "
        "mid-sized, small and independent specialist companies, regional "
        "specialists, and companies with a dedicated division for this "
        "service, provided the company itself commercially delivers it.\n\n"
        f"Use multiple search approaches and terminology, including:\n{terms}\n\n"
        f"STRICTLY EXCLUDE:\n{exclusions}\n\n"
        "COMPANY IDENTITY RULE:\nThe company listed must be the actual "
        "legal/commercial entity delivering the service. Do not list a "
        "product, software brand or parent holding company if an operating "
        "subsidiary actually delivers the service; do not list different "
        "regional offices of the same company as separate companies; do "
        "not invent companies.\n\n"
        '"brand" must repeat the actual company name.\n\n'
        "OWNERSHIP RULE:\nUse only \"Independent\", \"Acquired by <Parent>\" "
        "or \"Subsidiary of <Parent>\", stated only when verifiable from an "
        "official or reputable source. Otherwise use \"Independent\".\n\n"
        "HEADQUARTERS RULE:\nExactly one global headquarters, \"City, "
        "Country\" (\"City, State, USA\" for US companies). Never \"Global\", "
        "\"Worldwide\", a region, a bare country, or a count of countries.\n\n"
        "VERDICT RULE:\nOnly include companies where verdict is "
        '"in_market". Do not include "unrelated" or "unknown".\n\n'
        "WHY_RELATED RULE:\nOne concise sentence naming exactly what the "
        "company does in this market.\n\n"
        f"{format_exclusions(excluded_names)}\n\n"
        "DEDUPLICATION RULE:\nThe list must contain only unique companies "
        "-- no parent/subsidiary duplicates, former names, aliases, "
        "regional offices, or product/software brands listed separately.\n\n"
        "DO NOT INVENT COMPANIES TO REACH THE TARGET. If fewer genuinely "
        "qualify, return only those.\n\n"
        f"Find {batch} companies."
    )
    return system, user


# The exclusion block is the only part that grows per round. 120 real names
# is ~4.7 KB of JSON, which once pushed the URL to 8,486 chars — past
# Google's limit — and the truncated tail took the JSON template with it.
MAX_EXCLUDED_IN_PROMPT = 40
MAX_EXCLUSION_CHARS = 1500


def format_exclusions(names: list[str]) -> str:
    """Newest-first, character-capped exclusion block.

    Trimming is safe: this list is only a hint. The authoritative duplicate
    guard is the caller's own seen-set against full history, so a trimmed
    name that comes back is dropped in code.
    """
    clean = [str(n).strip() for n in names if str(n).strip()]
    if not clean:
        return "Do NOT repeat any company you have already named."

    lines: list[str] = []
    used = 0
    for name in reversed(clean):  # newest first: repeats cluster there
        if len(lines) >= MAX_EXCLUDED_IN_PROMPT:
            break
        line = f"- {name}"
        if used + len(line) + 1 > MAX_EXCLUSION_CHARS:
            break
        lines.append(line)
        used += len(line) + 1

    omitted = len(clean) - len(lines)
    tail = ""
    if omitted > 0:
        # Disclosing the omission with a strategy keeps the model productive
        # far longer than silent truncation.
        tail = (
            f"\n- ...and {omitted} more already-collected companies. Do NOT "
            "repeat any well-known company you would expect to have been "
            "listed already; prefer smaller, regional or specialist companies "
            "not yet named."
        )
    return (
        "Do NOT repeat any of these (including subsidiaries, aliases or "
        "former names):\n" + "\n".join(lines) + tail
    )


def discover_in_rounds(
    market: str,
    player_type: str,
    *,
    ask_json: Callable[[str, str, str], Any],
    target: int,
    market_type: str = "B2B",
    batch: int = DEFAULT_BATCH,
    dedupe_key: Callable[[str], str],
    accept: Callable[[dict[str, Any]], bool] | None = None,
    on_round: Callable[[int, list[dict[str, Any]], list[dict[str, Any]]], None] | None = None,
    max_rounds: int = 0,
    rotate_geography: bool = True,
    already_found: list[dict[str, Any]] | None = None,
    escalate_regions: bool = True,
    country: str = "",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Run discovery rounds until the target is met or the market is exhausted.

    ``ask_json(system, user, label)`` performs one call and returns parsed
    JSON; the caller owns the backend, retries and failure classification.
    ``on_round`` is called after each round so the caller can checkpoint —
    a run will be interrupted, and losing a round is cheap while losing the
    whole set is not.

    Returns (companies, stats). ``stats["stopped_because"]`` is one of
    "target_reached", "exhausted" or "max_rounds", so a stop is explained
    rather than silent.
    """
    # Resuming: a run stopped mid-discovery hands back the companies it had
    # already collected. Without this the loop restarts empty, re-asks for
    # names it already has, and the caller's checkpoint write then REPLACES
    # the larger saved set with the smaller new one — an interrupted market
    # silently lost its work.
    found: list[dict[str, Any]] = list(already_found or [])
    seen: set[str] = set()
    for row in found:
        key = dedupe_key(str(row.get("brand") or row.get("name") or "").strip())
        if key:
            seen.add(key)
    empty_streak = 0
    blocked = 0
    rounds = 0
    # Region escalation. The broad question runs dry long before the market
    # does: Silicon Carbide stopped at 216 with three empty rounds while whole
    # regions had never been asked about. Rather than stopping there, work
    # through the regions one at a time — least-covered first — and only call
    # the market exhausted once a targeted ask has also failed everywhere.
    region_queue: list[str] = []
    focus_region = ""
    region_empty = 0
    regions_swept: list[str] = []
    countries_swept: list[str] = []
    country_queue: list[str] = []
    countries_done = False
    escalating = False
    sweeps = 1
    # A run scoped to one country narrows by STATE, not by region: every
    # company is in the same country, so the region ladder has nothing to
    # steer with and the country tier is a single ask. Falls back to the
    # region ladder for a country with no state list.
    state_queue: list[str] = states_for(country) if is_single_country(country) else []
    single_country = bool(state_queue)
    # A round yields at most `batch`, so allow headroom for empty rounds
    # rather than stopping early on an arbitrary cap.
    limit = max_rounds or max(6, (target // max(1, batch)) * 3)
    if not max_rounds and escalate_regions:
        # The region sweep needs its own headroom, or the cap cuts it off
        # part-way and the market looks exhausted when it was merely capped.
        limit += len(REGIONS) * (EMPTY_ROUNDS_PER_REGION + 1) * MAX_REGION_SWEEPS
        # Plus the country tier: every country gets at least one ask, and a
        # productive one gets more. Without this headroom the sweep is cut off
        # part-way and a capped run is misreported as a finished market.
        limit += TOTAL_COUNTRIES * (EMPTY_ROUNDS_PER_COUNTRY + 1)
    if not max_rounds and single_country:
        # Same reasoning for the state tier: without headroom the sweep is cut
        # off part-way and a capped run is misreported as a finished market.
        limit += len(state_queue) * (EMPTY_ROUNDS_PER_COUNTRY + 1)

    while len(found) < target and rounds < limit:
        rounds += 1
        system, user = build_round_prompt(
            market,
            player_type,
            excluded_names=[
                str(c.get("brand") or c.get("name") or "") for c in found
            ],
            batch=batch,
            market_type=market_type,
            # Steer toward regions this market has not covered yet. Empty on
            # round 1, so the market shows where it naturally sits first.
            # Suppressed while escalating: the round already names one region
            # explicitly, and a second list of preferred regions contradicts it.
            # Also suppressed for a single-country run: the world-region
            # preference list ("prefer North America, Latin America ...")
            # directly contradicts the country constraint in the same prompt.
            geo_hint=(
                ""
                if (focus_region or single_country)
                else (rotation_hint(found) if rotate_geography else "")
            ),
            focus_region=focus_region,
            # Keeps every round inside the country a run is scoped to.
            country=country if single_country else "",
        )
        try:
            data = ask_json(system, user, f"discover-round-{rounds}")
        except Exception as err:  # noqa: BLE001
            # A BLOCKED round is not an empty market. Swallowing every error
            # as "empty" meant an AI-response quota looked identical to
            # genuine exhaustion: three quota errors in a row and the loop
            # declared the market finished at 10 companies.
            if _is_blocked(err):
                blocked += 1
                if on_round is not None:
                    on_round(rounds, [], found)
                if blocked >= MAX_BLOCKED_ROUNDS:
                    break
                continue  # does NOT count toward the empty streak
            data = None

        rows = []
        if isinstance(data, dict):
            rows = data.get("companies") or []
        elif isinstance(data, list):
            rows = data

        new: list[dict[str, Any]] = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            # Dedupe on the BRAND: one company can legitimately own several
            # brands in a market, so each brand is its own row.
            name = str(row.get("brand") or row.get("name") or "").strip()
            if not name:
                continue
            row.setdefault("brand", name)
            key = dedupe_key(name)
            if not key or key in seen:
                continue
            if is_contract_manufacturer(row):
                continue
            if accept is not None and not accept(row):
                continue
            seen.add(key)
            new.append(row)

        found.extend(new)
        empty_streak = 0 if new else empty_streak + 1
        if on_round is not None:
            on_round(rounds, new, found)

        if not escalate_regions:
            if empty_streak >= EMPTY_ROUNDS_BEFORE_STOP:
                break
            continue

        if focus_region:
            # Sweeping a specific region. Two empties means this region has
            # nothing more; move to the next rather than grinding on it.
            region_empty = 0 if new else region_empty + 1
            in_country = focus_region not in REGIONS
            allowed = EMPTY_ROUNDS_PER_COUNTRY if in_country else EMPTY_ROUNDS_PER_REGION
            if region_empty >= allowed:
                (countries_swept if in_country else regions_swept).append(focus_region)
                focus_region = region_queue.pop(0) if region_queue else ""
                region_empty = 0
                if not focus_region and single_country:
                    # Every state has been asked. The global country and
                    # region tiers would leave the country the run is scoped
                    # to, so this is genuinely the end of the ladder.
                    break
                if not focus_region:
                    # Every region has been asked once. Go NARROWER before
                    # giving up: "Africa" is one query for 54 countries, so the
                    # model names the two obvious South African firms and
                    # stops. Asking "...headquartered in Nigeria" is a
                    # different question that reaches national players.
                    if len(found) < target and not country_queue and not countries_done:
                        countries_done = True
                        country_queue = all_countries_by_coverage(found)
                    if country_queue:
                        focus_region = country_queue.pop(0)
                        region_empty = 0
                    elif len(found) < target and sweeps < MAX_REGION_SWEEPS:
                        # Then sweep the regions again: names surface once the
                        # exclusion list has moved past the obvious ones.
                        sweeps += 1
                        region_queue = list(under_covered(found, limit=len(REGIONS)))
                        focus_region = region_queue.pop(0) if region_queue else ""
                        regions_swept = []
                        # `countries_done` deliberately stays True: the 64
                        # country asks are the expensive part of the ladder and
                        # re-running them each sweep costs ~130 paced queries
                        # to re-confirm the same empties.
                    if not focus_region:
                        break  # asked every region AND every country
        elif empty_streak >= EMPTY_ROUNDS_BEFORE_STOP:
            # The broad question is spent. Switch to region-by-region rather
            # than declaring a market of 216 finished while Africa, the Middle
            # East and Latin America were never asked about.
            escalating = True
            if single_country:
                # States, not regions: "prefer under-covered regions" cannot
                # steer a run where every company shares one country.
                region_queue = list(state_queue)
                state_queue = []
            else:
                region_queue = [r for r in under_covered(found, limit=len(REGIONS))]
            focus_region = region_queue.pop(0) if region_queue else ""
            region_empty = 0
            empty_streak = 0
            if not focus_region:
                break

    if len(found) >= target:
        stopped = "target_reached"
    elif blocked >= MAX_BLOCKED_ROUNDS:
        # Never report "exhausted" when the backend was refusing to answer —
        # that mislabels a temporary block as a finished market.
        stopped = "blocked"
    elif rounds >= limit:
        # Checked BEFORE exhaustion: hitting the cap mid-sweep is a cap, not a
        # finished market, and calling it "exhausted" would hide real headroom.
        stopped = "max_rounds"
    elif escalate_regions and escalating and not focus_region:
        # Every region was asked about directly and still produced nothing.
        stopped = "exhausted"
    elif not escalate_regions and empty_streak >= EMPTY_ROUNDS_BEFORE_STOP:
        stopped = "exhausted"
    else:
        stopped = "max_rounds"

    return found, {
        "rounds": rounds,
        "resumed_with": len(already_found or []),
        "regions_swept": regions_swept,
        "region_sweeps": sweeps if escalating else 0,
        "countries_swept": countries_swept,
        "escalated": escalating,
        "found": len(found),
        "target": target,
        "empty_streak": empty_streak,
        "blocked_rounds": blocked,
        "stopped_because": stopped,
        # Reported so a run can be audited for geographic spread rather than
        # the spread being assumed from the steer having been switched on.
        "region_coverage": coverage(found),
    }
