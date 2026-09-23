"""Company discovery and enrichment prompts for Google AI Mode.

Targets the lean Coherent Quadrant report schema — only the columns the HTML
report and the Company Details sheet actually show:

    Brand | Company | Role | Quadrant | X | Y | Overall | Found in

Of those, AI Mode is asked for only what genuinely needs researching:

    company, website, headquarters, ownership, founded, verdict

The rest are derived downstream and are never requested here:
  * Brand / Company  <- brand_meta.brand_display_fields(company + ownership)
  * Role             <- market_relevance two-stage LLM classifier
  * Found in         <- expand_quadrant_score._single_location(headquarters)
  * X / Y / Overall / Quadrant  <- DeepSeek scoring (untouched by this module)

Dropping the 21-column landscape schema removes the six contact fields
entirely, which is the single biggest fabrication source: a prompt that
demands a full row makes the model invent values to comply (measured
elsewhere: 94% of one email column was ``info@<own-domain>``). Fields that
cannot be researched are not requested at all.
"""
from __future__ import annotations

import re
from typing import Any

# Only these are asked of AI Mode. Everything else in the report is derived.
RESEARCH_FIELDS = (
    "company",
    "website",
    "headquarters",
    "ownership",
    "founded",
    "verdict",
    "verdict_reason",
)

# AI Mode is stateless and the whole prompt rides in ?q=, so the exclusion
# list is the only part that grows without bound. Left uncapped it overflows
# the ~7,800-char URL limit and every request 400s mid-run.
_MAX_EXCLUDED_IN_PROMPT = 40
_MAX_EXCLUSION_CHARS = 1500

# Answers truncate above ~10 companies once each needs several fields.
DEFAULT_BATCH_SIZE = 10

_VAGUE_GEO_RE = re.compile(
    r"^\s*(global|worldwide|international|multinational|various|multiple|"
    r"na|eu|apac|emea|north america|europe|asia|africa|middle east|"
    r"latin america|\d+\+?\s*(?:countries|locations|sites)?)\s*$",
    re.I,
)

_PLACEHOLDER_RE = re.compile(
    r"^\s*(n/?a|na|none|null|unknown|not\s+(?:publicly\s+)?(?:disclosed|available|known)|"
    r"tbd|-{1,3}|\?+)\s*$",
    re.I,
)


def is_placeholder(value: Any) -> bool:
    text = str(value or "").strip()
    return not text or bool(_PLACEHOLDER_RE.match(text))


def clean_value(value: Any) -> str:
    """Collapse whitespace; strip list numbering the model adds ("1. Acme")."""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return re.sub(r"^\d+[.)]\s*", "", text)


def format_excluded(excluded: list[str]) -> str:
    """Newest-first, capped exclusion block.

    Trimming is safe for correctness: this list is only a hint to the model.
    The authoritative duplicate guard is the caller's own seen-set, so a
    trimmed name that comes back anyway is dropped there. Disclosing the
    omitted count with a strategy keeps the model productive far longer than
    silently truncating.
    """
    names = [clean_value(n) for n in excluded if clean_value(n)]
    if not names:
        return "(none yet)"

    lines: list[str] = []
    used = 0
    for name in reversed(names):  # newest first: repeats cluster there
        line = f"- {name}"
        if used + len(line) + 1 > _MAX_EXCLUSION_CHARS:
            break
        if len(lines) >= _MAX_EXCLUDED_IN_PROMPT:
            break
        lines.append(line)
        used += len(line) + 1

    omitted = len(names) - len(lines)
    if omitted > 0:
        lines.append(
            f"- ...and {omitted} more already-collected companies. Do NOT repeat "
            "any well-known company you would expect to have been listed "
            "already; prefer smaller, regional or specialist companies not yet "
            "mentioned."
        )
    return "\n".join(lines)


def discovery_prompt(
    market: str,
    *,
    market_type: str,
    provider_categories: list[str],
    excluded: list[str] | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> str:
    """Prompt asking AI Mode for a batch of companies in this market.

    Built in the order the guide prescribes — subject, ask, inclusion
    definition, typed exclusions with reasons, name exclusions, per-field
    rules, then the JSON template last. Constraints stated after the template
    get applied less reliably.

    ``provider_categories`` comes from the market's own two-stage
    classification, so the category definition is market-specific rather than
    a fixed global taxonomy.
    """
    categories = [c for c in (provider_categories or []) if str(c).strip()]
    cat_line = ", ".join(categories) if categories else "participant in this market"

    if str(market_type).upper() == "B2C":
        inclusion = (
            "A qualifying company's PRIMARY business must be owning and marketing "
            "a consumer-facing brand sold in this market under its own name. That "
            "is what it IS, not something it also does."
        )
        verdict_values = (
            '"in_market" for a genuine brand owner/marketer in this market; '
            '"retailer" for a shop or platform that only resells others\' brands; '
            '"supplier" for an ingredient/component/contract supplier; '
            '"unrelated"; or "unknown"'
        )
    else:
        inclusion = (
            f"A qualifying company's PRIMARY business must place it in one of these "
            f"roles for THIS market: {cat_line}. That is what it IS, not something "
            "it also does."
        )
        verdict_values = (
            '"in_market" for a genuine participant in one of the roles listed above; '
            '"reseller" for a pure reseller/agent/broker that does not build, supply '
            'or service in this market; "unrelated"; or "unknown"'
        )

    return (
        f'Market: "{market}"\n\n'
        f"Give me {batch_size} real companies that operate in this market.\n\n"
        f"WHAT QUALIFIES:\n{inclusion}\n\n"
        "STRICTLY EXCLUDE, even if related to this market:\n"
        "- Consultancies, market-research firms, news/media outlets and industry "
        "associations — reporting on or advising a market is not operating in it.\n"
        "- Pure holding companies with no operating business in this market.\n"
        "- A parent company that does not itself sell in THIS market (name the "
        "operating subsidiary that does, instead).\n"
        "- Companies that no longer exist and were not absorbed into a named "
        "successor.\n"
        "If unsure whether a company genuinely operates in this market, EXCLUDE it.\n\n"
        "Do NOT repeat any of these (including their subsidiaries, aliases or "
        f"former names):\n{format_excluded(excluded or [])}\n\n"
        "FIELD RULES (one per field):\n"
        "- company: the operating company's own legal or trade name. No ticker, "
        "no descriptive suffix like \"(manufacturer)\".\n"
        "- website: the real official company domain. NEVER a LinkedIn, Bloomberg, "
        "Crunchbase, Wikipedia or other directory/social page.\n"
        "- headquarters: \"City, Country\" — exactly one location, the global HQ. "
        "Not a street address, not a country alone, not a list of offices. "
        "Include the state for US companies, e.g. \"Thousand Oaks, California, USA\". "
        "NEVER write \"Global\", \"Worldwide\", a bare region, or a count like "
        "\"50+ countries\".\n"
        "- ownership: \"Independent\" if it is not owned by another company; "
        "otherwise \"Acquired by <Parent>\", \"Subsidiary of <Parent>\" or "
        "\"Merged into <Parent>\" using the real parent's name.\n"
        "- founded: the 4-digit founding year only, e.g. \"1998\". Not \"founded in "
        "1998\", not a range.\n"
        f"- verdict: {verdict_values}. NEVER guess this field. Include the company "
        'in your reply ONLY if verdict is "in_market".\n'
        "- verdict_reason: one sentence on why its PRIMARY business puts it in this "
        "market, naming what it actually makes, supplies or does.\n\n"
        "An empty string is CORRECT and preferred whenever you do not genuinely "
        "know a value. NEVER construct a website from the company name. NEVER "
        "guess a founding year or a parent company. A wrong value is much worse "
        "than an empty one.\n\n"
        "Reply with ONLY a JSON array, no markdown fences and no commentary, one "
        "object per company:\n"
        '[{"company": "", "website": "", "headquarters": "", "ownership": "", '
        '"founded": "", "verdict": "", "verdict_reason": ""}]'
    )


def enrichment_prompt(
    market: str,
    companies: list[dict[str, Any]],
    *,
    fields: tuple[str, ...] = ("headquarters", "ownership", "founded"),
) -> str:
    """Focused second pass for gaps only.

    A short question about known companies grounds far better than a wide
    request for every field. Only ask about gaps: re-querying filled rows
    spends queries (each risks a CAPTCHA) and risks overwriting good data.

    This is NOT independent verification — re-asking the same model can
    repeat a plausible invention. It works because the prompt rewards
    "unknown" instead of forbidding it.
    """
    listed = "\n".join(
        f"- {clean_value(c.get('company') or c.get('Company'))}"
        + (
            f" ({clean_value(c.get('website') or c.get('Website'))})"
            if (c.get("website") or c.get("Website"))
            else ""
        )
        for c in companies
    )
    asked = ", ".join(fields)
    rules = {
        "headquarters": (
            "- headquarters: \"City, Country\" — exactly one global HQ location, "
            "with the state for US companies. NEVER \"Global\" or a bare region."
        ),
        "ownership": (
            "- ownership: \"Independent\", or \"Acquired by <Parent>\" / "
            "\"Subsidiary of <Parent>\" with the real parent's name."
        ),
        "founded": "- founded: the 4-digit founding year only, e.g. \"1998\".",
        "website": (
            "- website: the real official company domain — never a directory or "
            "social page."
        ),
    }
    rule_lines = "\n".join(rules[f] for f in fields if f in rules)
    template = ", ".join(f'"{f}": ""' for f in ("company",) + tuple(fields))

    return (
        f'Market: "{market}"\n\n'
        f"For each company below, give ONLY these fields: {asked}.\n\n"
        f"Companies:\n{listed}\n\n"
        f"FIELD RULES:\n{rule_lines}\n\n"
        "An empty string is CORRECT and preferred whenever you do not genuinely "
        "know the real value. NEVER guess or construct one. Return the company "
        "name exactly as given so the rows can be matched.\n\n"
        "Reply with ONLY a JSON array, no markdown fences and no commentary:\n"
        f"[{{{template}}}]"
    )


def accept_company(item: dict[str, Any]) -> dict[str, str] | None:
    """Validate one returned company into a landscape row, or reject it.

    The prompt is a request, not a guarantee — every rule it states is
    re-checked here. Malformed values are rejected rather than repaired: a
    repaired value is indistinguishable from a researched one downstream.
    """
    if not isinstance(item, dict):
        return None

    # Hard category gate on the self-reported verdict.
    if clean_value(item.get("verdict")).lower() != "in_market":
        return None

    company = clean_value(item.get("company"))
    if not company or is_placeholder(company):
        return None

    website = clean_value(item.get("website"))
    if is_placeholder(website) or not _is_real_company_site(website):
        website = ""

    hq = clean_value(item.get("headquarters"))
    if is_placeholder(hq) or _VAGUE_GEO_RE.match(hq):
        hq = ""

    founded = re.sub(r"[^\d]", "", clean_value(item.get("founded")))[:4]
    if len(founded) != 4 or not (1600 <= int(founded) <= 2100):
        founded = ""

    ownership = clean_value(item.get("ownership"))
    if is_placeholder(ownership):
        ownership = ""

    return {
        "Company": company,
        "Website": website,
        "Headquarters": hq,
        "Founded": founded,
        "Ownership": ownership,
        # Audit-only: why the model considered it in-market. Never rendered.
        "verify_reason": clean_value(item.get("verdict_reason")),
    }


_DIRECTORY_HOSTS = (
    "linkedin.",
    "bloomberg.",
    "crunchbase.",
    "wikipedia.",
    "facebook.",
    "twitter.",
    "x.com",
    "instagram.",
    "youtube.",
    "zoominfo.",
    "dnb.com",
    "glassdoor.",
    "indeed.",
    "pitchbook.",
    "owler.",
    "google.",
)


def _is_real_company_site(website: str) -> bool:
    """Reject directory/social pages returned in place of the real domain."""
    host = re.sub(r"^https?://", "", website.lower()).split("/")[0]
    if not host or "." not in host:
        return False
    return not any(d in host for d in _DIRECTORY_HOSTS)


def dedupe_key(name: str) -> str:
    """Normalised identity so "Acme Inc" and "Acme" are one company.

    Also folds accents, because AI Mode returns both "Nestlé" and "Nestle"
    across pages and they must not become two companies.
    """
    import unicodedata

    raw = clean_value(name)
    raw = "".join(
        c for c in unicodedata.normalize("NFKD", raw) if not unicodedata.combining(c)
    ).lower()
    raw = re.sub(
        r"\b(inc|incorporated|corp|corporation|co|company|ltd|limited|llc|llp|"
        r"plc|gmbh|ag|sa|nv|bv|ab|as|oy|spa|srl|pty|pte|kk|kgaa|holdings?|"
        r"group|international|worldwide|global)\b",
        "",
        raw,
    )
    return re.sub(r"[^a-z0-9]", "", raw)
