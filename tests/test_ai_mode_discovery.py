"""AI Mode discovery prompts + validation for the lean report schema.

Every test here encodes a failure the extraction guide documented as real:
prompt-order, fabricated fields, vague geography, URL-budget overflow, and
verdict gating.
"""
from __future__ import annotations

from vendor_intel.pipeline import ai_mode_discovery as amd


# --- schema scope ----------------------------------------------------------


def test_only_researchable_fields_are_requested():
    """The 6 contact fields were the biggest fabrication source, so the lean
    schema must not ask for them at all."""
    p = amd.discovery_prompt("Global Animal Healthcare Market", market_type="B2B", provider_categories=["Manufacturer"])
    # Check the output template — "LinkedIn" legitimately appears earlier as a
    # banned *website* value, which is the opposite of requesting it.
    tmpl = p.split("Reply with ONLY")[-1].lower()
    for banned in ("contact_person", "email", "linkedin", "office_no", "employees"):
        assert banned not in tmpl, f"{banned} must not be requested"
    assert set(amd.RESEARCH_FIELDS) == {
        "company", "website", "headquarters", "ownership", "founded",
        "verdict", "verdict_reason",
    }


def test_derived_columns_are_not_requested():
    """Role, X, Y, Overall and Quadrant are computed downstream — asking the
    model for them would let it override the scoring system."""
    p = amd.discovery_prompt("Global Semiconductor Market", market_type="B2B", provider_categories=["Manufacturer"])
    tmpl = p.split("Reply with ONLY")[-1]
    for derived in ('"role"', '"quadrant"', '"x"', '"y"', '"overall"', '"brand"'):
        assert derived not in tmpl.lower()


# --- prompt construction ---------------------------------------------------


def test_json_template_comes_last():
    """Constraints stated after the output template get applied less
    reliably, so the template must be the final thing in the prompt."""
    p = amd.discovery_prompt("M", market_type="B2B", provider_categories=["Manufacturer"])
    assert p.rstrip().endswith("]")
    assert p.index("FIELD RULES") < p.index("Reply with ONLY a JSON array")


def test_categories_are_market_specific_not_fixed():
    a = amd.discovery_prompt("Market A", market_type="B2B", provider_categories=["Manufacturer", "Distributor"])
    b = amd.discovery_prompt("Market B", market_type="B2B", provider_categories=["Platform Provider", "Integrator"])
    assert "Manufacturer, Distributor" in a
    assert "Platform Provider, Integrator" in b


def test_b2c_market_asks_for_brand_owners():
    p = amd.discovery_prompt("Potato Chips Market", market_type="B2C", provider_categories=[])
    assert "consumer-facing brand" in p
    assert '"retailer"' in p


def test_exclusions_carry_reasons_not_just_labels():
    """Listing forbidden categories without saying why makes the model apply
    its own looser definition."""
    p = amd.discovery_prompt("M", market_type="B2B", provider_categories=["Manufacturer"])
    assert "reporting on or advising a market is not operating in it" in p
    assert "name the operating subsidiary that does" in p


def test_verdict_field_is_never_guessed():
    p = amd.discovery_prompt("M", market_type="B2B", provider_categories=["Manufacturer"])
    assert "NEVER guess this field" in p
    assert "verdict_reason" in p


def test_blank_is_preferred_over_a_guess():
    """Never say "no field may be blank" — the model invents values to
    comply."""
    p = amd.discovery_prompt("M", market_type="B2B", provider_categories=["Manufacturer"])
    assert "empty string is CORRECT and preferred" in p
    assert "no field may be blank" not in p.lower()


def test_vague_geography_banned_by_exact_string():
    """"Be specific" does not work; banning the exact strings does."""
    p = amd.discovery_prompt("M", market_type="B2B", provider_categories=["Manufacturer"])
    assert '"Global"' in p and "50+ countries" in p
    assert "Thousand Oaks, California, USA" in p  # format AND an example


def test_directory_pages_banned_for_website():
    p = amd.discovery_prompt("M", market_type="B2B", provider_categories=["Manufacturer"])
    assert "LinkedIn" in p and "directory/social page" in p


# --- exclusion list / URL budget -------------------------------------------


def test_exclusion_list_capped_for_url_budget():
    """148 names once produced a 10,701-char URL and every request 400'd."""
    block = amd.format_excluded([f"Company Number {i} Holdings Limited" for i in range(500)])
    assert len(block) <= amd._MAX_EXCLUSION_CHARS + 250  # + disclosure line
    assert block.count("\n- ") < 60


def test_exclusion_list_is_newest_first():
    """A repeat is likeliest among companies just returned."""
    block = amd.format_excluded([f"Co{i}" for i in range(100)])
    assert "Co99" in block
    assert "Co0\n" not in block


def test_omitted_count_disclosed_with_strategy():
    """Telling the model what was omitted, and what to prefer instead, keeps
    it productive far longer than silent truncation."""
    block = amd.format_excluded([f"Company Number {i} Holdings Limited" for i in range(300)])
    assert "more already-collected companies" in block
    assert "smaller, regional or specialist" in block


def test_empty_exclusion_list_is_explicit():
    assert amd.format_excluded([]) == "(none yet)"


def test_full_prompt_fits_the_url_limit():
    """The real guard: the assembled prompt must survive build_url intact."""
    from vendor_intel.scraping.google_ai_mode import MAX_URL_CHARS, build_url

    p = amd.discovery_prompt(
        "Global Liquefied Natural Gas Market",
        market_type="B2B",
        provider_categories=["Manufacturer", "Distributor", "Service Provider"],
        excluded=[f"Company Number {i} Holdings Limited" for i in range(500)],
    )
    url = build_url(p)
    assert len(url) <= MAX_URL_CHARS
    # Not truncated: the tail of the prompt (the template) must survive.
    assert "verdict_reason" in url or "verdict" in url


def test_pipeline_exclusion_helper_bounds_the_url():
    """Regression: the live pipeline capped exclusions by NAME COUNT only.
    120 real names is ~4.7KB of JSON, which pushed the URL to 8,486 chars —
    past Google's limit — so build_url silently truncated the prompt tail."""
    import json

    from vendor_intel.pipeline.chatgpt_expand import _exclusion_names
    from vendor_intel.scraping.google_ai_mode import MAX_URL_CHARS, build_url

    for count in (80, 120, 500):
        seen = [f"Company Number {i} Holdings Limited" for i in range(count)]
        block = f"Do NOT repeat these names: {json.dumps(_exclusion_names(seen))}"
        url = build_url("x" * 2700 + block)
        assert len(url) <= MAX_URL_CHARS, f"{count} names overflowed the URL"


def test_fill_prompt_drops_fabrication_prone_columns():
    """The 6 contact fields + derived codes must not be researched: they are
    the biggest fabrication source and worth nothing to X/Y scoring."""
    from vendor_intel.pipeline.chatgpt_expand import researched_columns

    cols = researched_columns()
    for dropped in (
        "Contact Person", "Role", "Email", "LinkedIn", "Office No.",
        "Country Code", "Region Code", "Distribution Type",
    ):
        assert dropped not in cols, f"{dropped} must not be researched"


def test_fill_prompt_keeps_scoring_evidence():
    """_scoring_row() concatenates these into the evidence text X/Y scoring
    reads — dropping them would silently degrade scoring, not just shrink the
    prompt."""
    from vendor_intel.pipeline.chatgpt_expand import researched_columns

    cols = researched_columns()
    for kept in (
        "Summary", "Specialty Focus", "Core Categories",
        "Key Brands Represented", "Operational Presence",
        "Continent / Geography", "Employees",
    ):
        assert kept in cols, f"{kept} is a scoring input and must be researched"


def test_researched_and_dropped_columns_cover_the_schema():
    """Trimming what is RESEARCHED must not change what is EXPORTED — the
    dropped columns are still written, populated from code/classifier."""
    from vendor_intel.pipeline.chatgpt_expand import (
        _UNRESEARCHED_COLUMNS,
        researched_columns,
    )
    from vendor_intel.pipeline.web_expand import HEADERS

    assert set(HEADERS) == set(researched_columns()) | set(_UNRESEARCHED_COLUMNS)
    # No column may be both researched and dropped.
    assert not set(researched_columns()) & set(_UNRESEARCHED_COLUMNS)


def test_market_offering_is_researched():
    """Feeds the report's Brand column, which previously just repeated
    Company in 191 of 192 rows because nothing ever researched it."""
    from vendor_intel.pipeline.chatgpt_expand import researched_columns

    assert "Market Offering" in researched_columns()


def test_pipeline_exclusion_helper_is_newest_first():
    from vendor_intel.pipeline.chatgpt_expand import _exclusion_names

    assert _exclusion_names([f"Co{i}" for i in range(100)])[0] == "Co99"


# --- validation ------------------------------------------------------------


def _item(**kw):
    base = {
        "company": "Zoetis",
        "website": "https://www.zoetis.com",
        "headquarters": "Parsippany, New Jersey, USA",
        "ownership": "Independent",
        "founded": "1952",
        "verdict": "in_market",
        "verdict_reason": "Develops and manufactures animal vaccines.",
    }
    base.update(kw)
    return base


def test_accepts_a_clean_company():
    row = amd.accept_company(_item())
    assert row["Company"] == "Zoetis"
    assert row["Founded"] == "1952"
    assert row["Headquarters"] == "Parsippany, New Jersey, USA"


def test_verdict_gate_rejects_non_market_companies():
    """Never trust the category implicitly — gate on it in code."""
    for bad in ("reseller", "unrelated", "unknown", "", "retailer"):
        assert amd.accept_company(_item(verdict=bad)) is None


def test_directory_website_is_blanked_not_kept():
    row = amd.accept_company(_item(website="https://www.linkedin.com/company/zoetis"))
    assert row is not None
    assert row["Website"] == ""


def test_vague_headquarters_blanked():
    for vague in ("Global", "Worldwide", "Europe", "50+ countries", "APAC"):
        row = amd.accept_company(_item(headquarters=vague))
        assert row["Headquarters"] == "", vague


def test_multiword_city_survives():
    """Regression: an earlier location fix truncated "Thousand Oaks" to
    "Thousand"."""
    row = amd.accept_company(_item(headquarters="Thousand Oaks, California, USA"))
    assert row["Headquarters"] == "Thousand Oaks, California, USA"


def test_founded_year_extracted_and_bounded():
    assert amd.accept_company(_item(founded="Founded in 1998"))["Founded"] == "1998"
    assert amd.accept_company(_item(founded="98"))["Founded"] == ""
    assert amd.accept_company(_item(founded="N/A"))["Founded"] == ""


def test_placeholders_become_blank_not_text():
    row = amd.accept_company(_item(ownership="Not publicly disclosed", headquarters="unknown"))
    assert row["Ownership"] == ""
    assert row["Headquarters"] == ""


def test_numbered_company_name_cleaned():
    row = amd.accept_company(_item(company="1. Elanco Animal Health"))
    assert row["Company"] == "Elanco Animal Health"


def test_reason_is_audit_only_not_a_report_column():
    row = amd.accept_company(_item())
    assert "verify_reason" in row
    for shown in ("Role", "Quadrant", "X", "Y", "Overall", "Brand"):
        assert shown not in row


# --- dedupe ----------------------------------------------------------------


def test_dedupe_ignores_legal_suffixes():
    assert amd.dedupe_key("Acme Inc") == amd.dedupe_key("Acme")
    assert amd.dedupe_key("Bayer AG") == amd.dedupe_key("Bayer")
    assert amd.dedupe_key("Zoetis Inc.") == amd.dedupe_key("zoetis")


def test_dedupe_keeps_different_companies_apart():
    assert amd.dedupe_key("Merck & Co") != amd.dedupe_key("Merck KGaA Darmstadt")


# --- enrichment pass -------------------------------------------------------


def test_enrichment_asks_only_named_fields():
    p = amd.enrichment_prompt(
        "Global Animal Healthcare Market",
        [{"company": "Ceva Sante", "website": "https://ceva.com"}],
        fields=("headquarters", "founded"),
    )
    assert "headquarters, founded" in p
    assert "Ceva Sante" in p
    assert "ownership" not in p.split("FIELD RULES")[1]


def test_enrichment_prefers_blank_over_guess():
    p = amd.enrichment_prompt("M", [{"company": "X"}], fields=("founded",))
    assert "empty string is CORRECT and preferred" in p
    assert "NEVER guess" in p


# --- report Brand column ---------------------------------------------------


def _detail(**over):
    from vendor_intel.pipeline.expand_quadrant_score import to_company_detail_rows

    row = {
        "Company": "Zoetis",
        "Ownership": "Independent",
        "Founded": "1952",
        "Headquarters": "Parsippany, New Jersey, USA",
        "Distribution Type": "Manufacturer",
        "X Score": "90",
        "Y Score": "88",
        "Overall Score": "89",
        "Quadrant": "Leaders",
    }
    row.update(over)
    return to_company_detail_rows([row], "Global Animal Healthcare Market")[0]


def test_brand_shows_researched_product_not_company_name():
    """Brand previously duplicated Company in 191/192 rows."""
    out = _detail(**{"Market Offering": "Apoquel"})
    assert out["Brand"] == "Apoquel"
    assert out["Company"] == "Zoetis"


def test_brand_shows_named_service_for_service_provider():
    out = _detail(
        Company="IDEXX",
        **{
            "Market Offering": "Veterinary diagnostics laboratory services",
            "Distribution Type": "Service Provider",
        },
    )
    assert out["Brand"] == "Veterinary diagnostics laboratory services"
    assert out["Role"] == "Service Provider"


def test_brand_falls_back_to_company_when_no_separate_offering():
    """Correct for a company selling only under its own name."""
    assert _detail()["Brand"] == "Zoetis"


def test_brand_ignores_placeholder_offering():
    for junk in ("N/A", "unknown", "Not publicly disclosed", ""):
        assert _detail(**{"Market Offering": junk})["Brand"] == "Zoetis"


def test_company_keeps_acquisition_suffix():
    out = _detail(
        Company="Adisseo",
        Ownership="Subsidiary of Bluestar Adisseo",
        **{"Market Offering": "Rhodimet"},
    )
    assert out["Brand"] == "Rhodimet"
    assert "Adisseo" in out["Company"] and "Bluestar Adisseo" in out["Company"]


def test_offering_does_not_change_scoring_identity():
    """plain_brand_name() keys scoring — it must stay the company name."""
    from vendor_intel.quadrant.brand_meta import plain_brand_name

    meta = {
        "company": "Zoetis",
        "company_raw": "Zoetis",
        "brand": "Zoetis",
        "market_offering": "Apoquel",
    }
    assert plain_brand_name(meta) == "Zoetis"


# --- duplicate removal ------------------------------------------------------


def test_pipeline_dedupe_collapses_legal_suffix_variants():
    """web_expand._norm only lowercases, so it treated "Bayer AG" and "Bayer"
    as two companies. AI Mode returns exactly those variants across pages."""
    from vendor_intel.pipeline.chatgpt_expand import _dedupe_key as k

    for a, b in [
        ("Centrum", "Centrum Inc"),
        ("Bayer AG", "Bayer"),
        ("Nature Made", "Nature Made, LLC"),
        ("Pfizer Inc.", "pfizer"),
        ("GNC Holdings", "GNC"),
        ("One A Day", "One-A-Day"),
    ]:
        assert k(a) == k(b), f"{a} and {b} must dedupe together"


def test_pipeline_dedupe_folds_accents():
    """AI Mode returns both spellings of Nestle across pages."""
    from vendor_intel.pipeline.chatgpt_expand import _dedupe_key as k

    assert k("Nestl\u00e9") == k("Nestle")
    assert k("Nestl\u00e9 Health Science") == k("Nestle Health Science")


def test_pipeline_dedupe_keeps_distinct_companies_apart():
    """Over-aggressive matching would silently delete real companies."""
    from vendor_intel.pipeline.chatgpt_expand import _dedupe_key as k

    assert k("Merck & Co") != k("Merck KGaA Darmstadt")
    assert k("Centrum") != k("Centrum Silver")
    assert k("Nature Made") != k("Natures Bounty")


def test_weaker_norm_is_no_longer_used_for_discovery_dedupe():
    """Regression guard: the discovery paths must not fall back to _norm for
    duplicate checks."""
    import inspect

    from vendor_intel.pipeline import chatgpt_expand as ce

    for fn in (ce.gpt_recall_companies, ce.google_ai_seed_discover):
        src = inspect.getsource(fn)
        assert "_norm(name) in seen" not in src, f"{fn.__name__} still uses _norm"


# --- live pipeline prompt compliance (extraction guide) ---------------------


def _recall_prompt_text():
    """The recall prompt as the model receives it.

    Built from the source by evaluating the concatenated string literals, so
    phrases split across lines are matched the way the model sees them.
    """
    import ast
    import inspect

    from vendor_intel.pipeline import chatgpt_expand as ce

    tree = ast.parse(inspect.getsource(ce.gpt_recall_companies).lstrip())
    parts = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            parts.append(node.value)
        elif isinstance(node, ast.JoinedStr):  # f-string
            for v in node.values:
                if isinstance(v, ast.Constant) and isinstance(v.value, str):
                    parts.append(v.value)
    return " ".join(" ".join(parts).split())


def test_live_recall_prompt_has_verdict_field():
    """The guide's single best filter: make the model DECLARE the
    classification as data, then gate on it in code."""
    p = _recall_prompt_text()
    assert '"verdict"' in p or "verdict:" in p
    assert "NEVER guess this field" in p


def test_live_recall_prompt_anchors_on_primary_business():
    assert "PRIMARY business" in _recall_prompt_text()


def test_live_recall_prompt_exclusions_carry_reasons():
    """Bare labels let the model apply its own looser definition."""
    p = _recall_prompt_text()
    assert "reporting on or advising a market is not operating in it" in p
    assert "name the operating subsidiary instead" in p


def test_live_recall_prompt_prefers_blank_over_guess():
    p = _recall_prompt_text()
    assert "empty string is CORRECT and preferred" in p
    assert "no field may be blank" not in p.lower()


def test_live_recall_prompt_bans_directory_websites():
    assert "NEVER a LinkedIn" in _recall_prompt_text()


def test_verdict_gate_rejects_in_code():
    """The prompt is a request, not a guarantee."""
    from vendor_intel.pipeline.chatgpt_expand import _verdict_rejects

    assert _verdict_rejects({"verdict": "unrelated"})
    assert _verdict_rejects({"verdict": "unknown"})
    assert _verdict_rejects({"verdict": "reseller"})
    assert not _verdict_rejects({"verdict": "in_market"})
    assert not _verdict_rejects({"verdict": "IN_MARKET"})


def test_missing_verdict_is_not_a_rejection():
    """Discovery paths that do not ask for a verdict must not lose every
    company — those rows still face the later verify + classify steps."""
    from vendor_intel.pipeline.chatgpt_expand import _verdict_rejects

    assert not _verdict_rejects({})
    assert not _verdict_rejects({"verdict": ""})


def test_discovery_queries_carry_readable_exclusion_names():
    """Regression: substep 2g sent generic queries with NO exclusion list, so
    AI Mode returned the same well-known companies every time — 7 queries in
    a row yielded +0 because all 118 already-collected names came back.

    The names must also be READABLE: `seen` holds dedupe keys
    ("mitsubishielectric"), which the model cannot match against."""
    import inspect

    from vendor_intel.pipeline import chatgpt_expand as ce

    src = inspect.getsource(ce.google_ai_seed_discover)
    assert "_with_exclusions" in src, "2g queries must carry an exclusion list"
    assert "known_names" in src, "must use display names, not dedupe keys"
    assert "known_names.append(name)" in src, (
        "the list must grow during the loop, or later queries re-ask the same thing"
    )


def test_exclusion_suffix_stays_within_the_url_budget():
    from vendor_intel.pipeline.chatgpt_expand import _exclusion_names
    from vendor_intel.scraping.google_ai_mode import MAX_URL_CHARS, build_url

    known = [f"Company Number {i} Holdings Limited" for i in range(300)]
    names = _exclusion_names(known)
    q = (
        "top companies in the Global Silicon Carbide Market list names and websites. "
        f"Exclude {', '.join(names[:12])} and {len(known) - 12} others - list DIFFERENT "
        "companies not already named"
    )
    assert len(build_url(q)) <= MAX_URL_CHARS
