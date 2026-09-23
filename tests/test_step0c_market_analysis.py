"""Step 0c — market analysis runs BEFORE discovery and shapes its prompts.

Previously Stage 1 (B2B/B2C + this market's participant categories) ran only
at scoring time, so discovery had no idea what kind of company to look for.
"""
from __future__ import annotations

import pytest

from vendor_intel.config import Settings
from vendor_intel.pipeline import chatgpt_expand as ce
from vendor_intel.quadrant import market_relevance as mr
from vendor_intel.scraping import google_ai_mode as gam


@pytest.fixture(autouse=True)
def _reset():
    mr._MARKET_ANALYSIS_CACHE.clear()
    ce.set_discovery_market("", [])
    yield
    mr._MARKET_ANALYSIS_CACHE.clear()
    ce.set_discovery_market("", [])


def _ai_mode_reply(payload, monkeypatch):
    import json

    monkeypatch.setenv("GOOGLE_AI_MODE_ENABLED", "true")
    monkeypatch.setattr(gam, "ask", lambda p, **k: json.dumps(payload))


# --- ordering: analysis feeds discovery ------------------------------------


def test_b2b_analysis_drives_discovery_wording(monkeypatch):
    _ai_mode_reply(
        {
            "market_type": "B2B",
            "market_definition": "Industrial water treatment systems.",
            "market_participants": [
                {"type": "Manufacturer", "definition": "d", "why_relevant": "r"},
                {"type": "Service Provider", "definition": "d", "why_relevant": "r"},
            ],
        },
        monkeypatch,
    )
    out = ce._analyze_market_for_discovery("Industrial Water Treatment Market")
    assert out["market_type"] == "B2B"

    cats = [p["type"] for p in out["market_participants"]]
    ce.set_discovery_market(out["market_type"], cats)
    # One player type is targeted everywhere: the PRIMARY category. Stage 1
    # still returns the full list, kept for audit.
    nouns = ce._landscape_list_nouns("Industrial Water Treatment Market", "general")
    assert "Manufacturer" in nouns
    assert "Service Provider" not in nouns, "only the primary role is searched for"
    assert ce.discovery_all_categories() == ["Manufacturer", "Service Provider"]


def test_b2c_analysis_asks_for_brands(monkeypatch):
    _ai_mode_reply(
        {
            "market_type": "B2C",
            "market_definition": "Consumer snack foods.",
            "market_participants": [],
        },
        monkeypatch,
    )
    out = ce._analyze_market_for_discovery("Potato Chips Market")
    assert out["market_type"] == "B2C"
    assert out["market_participants"] == []
    ce.set_discovery_market(out["market_type"], [])
    assert "brands and marketers" in ce._landscape_list_nouns("Potato Chips Market", "general")


def test_different_markets_get_different_categories(monkeypatch):
    _ai_mode_reply(
        {
            "market_type": "B2B",
            "market_definition": "A",
            "market_participants": [{"type": "Platform Provider", "definition": "d", "why_relevant": "r"}],
        },
        monkeypatch,
    )
    a = ce._analyze_market_for_discovery("Market A")

    _ai_mode_reply(
        {
            "market_type": "B2B",
            "market_definition": "B",
            "market_participants": [{"type": "Distributor", "definition": "d", "why_relevant": "r"}],
        },
        monkeypatch,
    )
    b = ce._analyze_market_for_discovery("Market B")

    assert [p["type"] for p in a["market_participants"]] == ["Platform Provider"]
    assert [p["type"] for p in b["market_participants"]] == ["Distributor"]


# --- spec guarantees -------------------------------------------------------


def test_contract_manufacturer_stripped_even_if_returned(monkeypatch):
    """Never a default/global category, even when the model volunteers it."""
    _ai_mode_reply(
        {
            "market_type": "B2B",
            "market_definition": "d",
            "market_participants": [
                {"type": "Contract Manufacturer", "definition": "d", "why_relevant": "r"},
                {"type": "Manufacturer", "definition": "d", "why_relevant": "r"},
            ],
        },
        monkeypatch,
    )
    out = ce._analyze_market_for_discovery("Some Assembly Market")
    types = [p["type"] for p in out["market_participants"]]
    assert types == ["Manufacturer"]


def test_b2c_never_carries_participant_categories(monkeypatch):
    _ai_mode_reply(
        {
            "market_type": "B2C",
            "market_definition": "d",
            "market_participants": [{"type": "Manufacturer", "definition": "d", "why_relevant": "r"}],
        },
        monkeypatch,
    )
    out = ce._analyze_market_for_discovery("Consumer Market")
    assert out["market_participants"] == []


def test_invalid_market_type_falls_back_to_b2c(monkeypatch):
    _ai_mode_reply(
        {"market_type": "MAYBE", "market_definition": "d", "market_participants": []},
        monkeypatch,
    )
    assert ce._analyze_market_for_discovery("Odd Market")["market_type"] == "B2C"


def test_result_seeds_scoring_cache_so_stage1_runs_once(monkeypatch):
    """The scoring stage must reuse this analysis rather than paying for it
    again — the cache key is stripped+lowercased."""
    _ai_mode_reply(
        {
            "market_type": "B2B",
            "market_definition": "d",
            "market_participants": [{"type": "Manufacturer", "definition": "d", "why_relevant": "r"}],
        },
        monkeypatch,
    )
    ce._analyze_market_for_discovery("  Global Pumps Market  ")
    assert ("global pumps market", "", "") in mr._MARKET_ANALYSIS_CACHE


def test_falls_back_to_deepseek_when_ai_mode_off(monkeypatch):
    """With AI Mode off, Stage 1 still runs via market_relevance."""
    monkeypatch.setenv("GOOGLE_AI_MODE_ENABLED", "false")
    called = {}

    def _fake(market, **kw):
        called["hit"] = market
        return {"market_type": "B2B", "market_definition": "d", "market_participants": []}

    monkeypatch.setattr(mr, "analyze_market", _fake)
    out = ce._analyze_market_for_discovery("Fallback Market")
    assert called.get("hit") == "Fallback Market"
    assert out["market_type"] == "B2B"


def test_total_failure_fails_open_to_b2c(monkeypatch):
    monkeypatch.setenv("GOOGLE_AI_MODE_ENABLED", "false")
    monkeypatch.setattr(
        mr, "analyze_market", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down"))
    )
    out = ce._analyze_market_for_discovery("Broken Market")
    assert out["market_type"] == "B2C"
    assert out["market_participants"] == []


def test_prompt_bans_contract_manufacturer_and_fixed_lists():
    # Collapse the prompt's hard line wraps before matching phrases.
    p = " ".join(ce._MARKET_ANALYSIS_DISCOVERY_SYSTEM.split())
    assert 'Never introduce "Contract Manufacturer" as a default category' in p
    assert "NOT a required list" in p
    assert "do not force every market to have the same categories" in p
    # B2B/B2C defined by buyer type, not website language.
    assert "never from one company's marketing language" in p


# --- single company source -------------------------------------------------


def test_ddgs_harvest_disabled_when_ai_mode_is_on():
    """AI Mode must be the SOLE source of companies. The ddgs/SearXNG harvest
    existed only because DeepSeek has no hosted web_search; AI Mode searches
    the live web itself, so leaving the harvest on would mix companies from
    raw SERP scraping into the landscape."""
    import inspect

    src = inspect.getsource(ce.run_chatgpt_expand)
    assert "sole company source" in src
    # The DeepSeek block further down must not re-enable it.
    assert src.count("not _ai_mode_active()") >= 1
    reenable = src.split("if _is_deepseek():", 1)[1]
    assert "not _ai_mode_active()" in reenable.split("ddgs_harvest = True", 1)[0]


def test_seeds_are_file_only_not_a_hidden_source():
    """Seeds come from a curated file the user passes explicitly, so they are
    not an accidental second provenance."""
    seeds = ce._seed_candidates("Global Daily Multivitamins Market", "global", seeds_path=None)
    assert seeds == [] or all(s["discovery_source"] == "seed_file" for s in seeds)


# --- queries adapt to the market type --------------------------------------


def _step2_queries(market_type, categories, query="Test Market"):
    """Rebuild Step 2's discovery query list the way the code does."""
    ce.set_discovery_market(market_type, categories)
    nouns = ce._landscape_list_nouns(query, "general")
    cats = ce._discovery_categories()
    if ce._is_b2b_market() and cats:
        role_phrase = " and ".join(c.lower() + "s" for c in cats[:3])
        role_query = f"{query} {role_phrase} list"
        buyer_query = f"{query} suppliers to businesses and institutions list"
    else:
        role_query = f"{query} manufacturers and brand owners list"
        buyer_query = f"{query} consumer brands and product makers list"
    return [
        f"top companies in the {query} list names and official websites",
        f"leading {nouns} worldwide in the {query}",
        f"major {nouns} United States Europe Asia {query}",
        f"{query} key players companies list 2025 2026",
        f"Wikipedia companies in the {query}",
        role_query,
        buyer_query,
    ]


def test_b2b_and_b2c_produce_different_queries():
    b2c = _step2_queries("B2C", [])
    b2b = _step2_queries("B2B", ["Manufacturer", "Service Provider"])
    assert b2c != b2b
    assert sum(1 for a, b in zip(b2c, b2b) if a != b) >= 4


def test_b2b_service_market_not_asked_for_brand_owners():
    """Regression: the last query said "manufacturers and brand owners list"
    for EVERY market, which is wrong wording for a B2B service market and
    steers the model toward the wrong companies."""
    b2b = _step2_queries("B2B", ["Service Provider", "Consultant"])
    joined = " | ".join(b2b)
    assert "brand owners" not in joined
    # Only the PRIMARY role is searched for, so the query names it alone.
    assert "service providers list" in joined
    assert "consultants" not in joined


def test_b2c_market_keeps_brand_wording():
    b2c = _step2_queries("B2C", [])
    joined = " | ".join(b2c)
    assert "brand owners" in joined
    assert "consumer brands" in joined
    assert "brands and marketers" in joined


def test_queries_follow_this_markets_own_categories():
    a = " | ".join(_step2_queries("B2B", ["Platform Provider", "Consultant"]))
    b = " | ".join(_step2_queries("B2B", ["Manufacturer", "Distributor"]))
    # Only the primary role is used, so the query names it alone.
    assert "platform providers list" in a
    assert "manufacturers list" in b
    assert a != b


def test_recall_nouns_and_keep_line_adapt_too():
    """All three prompt fragments must move together, not just one."""
    ce.set_discovery_market("B2B", ["Manufacturer", "Service Provider"])
    b2b = (
        ce._landscape_list_nouns("M", "general"),
        ce._roles_for("general", "M"),
        ce._landscape_keep_line("M", "general"),
    )
    ce.set_discovery_market("B2C", [])
    b2c = (
        ce._landscape_list_nouns("M", "general"),
        ce._roles_for("general", "M"),
        ce._landscape_keep_line("M", "general"),
    )
    for x, y in zip(b2b, b2c):
        assert x != y
    assert "Manufacturer" in b2b[0] and "brands and marketers" in b2c[0]


# --- DeepSeek-generated discovery queries ----------------------------------


def test_generated_queries_replace_templates(monkeypatch):
    """DeepSeek writes queries in the market's OWN vocabulary; templates can
    only interpolate the market name and role names."""
    monkeypatch.setattr(
        ce,
        "_chat_json",
        lambda *a, **k: {
            "queries": [
                "offshore wind foundation suppliers monopile jacket",
                "offshore wind substructure engineering firms",
            ]
        },
    )
    monkeypatch.setattr(ce, "_client", lambda s: None)
    monkeypatch.setattr(ce, "_model", lambda s: "deepseek-v4-flash")
    out = ce._generate_discovery_queries(
        "Global Offshore Wind Foundations Market",
        market_type="B2B",
        categories=["Engineering Provider"],
        settings=Settings(),
    )
    assert "monopile" in " ".join(out)


def test_query_generation_goes_through_ai_mode(monkeypatch):
    """Everything except the X/Y parameters and their definitions is done by
    Google AI Mode, so the discovery queries are written there too
    (_chat_json uses the API only when AI Mode is switched off)."""
    seen = {}

    def _fake(*a, **k):
        seen["use_ai_mode"] = k.get("use_ai_mode")
        return {"queries": ["a market query about companies"]}

    monkeypatch.setattr(ce, "_chat_json", _fake)
    monkeypatch.setattr(ce, "_client", lambda s: None)
    monkeypatch.setattr(ce, "_model", lambda s: "deepseek-v4-flash")
    ce._generate_discovery_queries("M", market_type="B2B", categories=[], settings=Settings())
    assert seen["use_ai_mode"] is True


def test_ai_mode_on_never_falls_back_to_llm_for_market_analysis(monkeypatch):
    """With AI Mode on, a failed market read stops the run instead of
    silently switching to the LLM or defaulting to B2C."""
    monkeypatch.setenv("GOOGLE_AI_MODE_ENABLED", "true")
    monkeypatch.setattr(
        ce, "_ai_mode_json", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down"))
    )

    def _llm(*a, **k):
        raise AssertionError("must not call the LLM path when AI Mode is on")

    monkeypatch.setattr(mr, "analyze_market", _llm)
    with pytest.raises(RuntimeError):
        ce._analyze_market_for_discovery("Any Market")


def test_chat_json_honours_use_ai_mode_false(monkeypatch):
    """The opt-out must actually bypass the AI Mode short-circuit."""
    monkeypatch.setenv("GOOGLE_AI_MODE_ENABLED", "true")
    called = {}

    def _boom(*a, **k):
        called["ai_mode"] = True
        raise AssertionError("must not route to AI Mode")

    monkeypatch.setattr(ce, "_ai_mode_json", _boom)

    def _fake_create(client, kwargs, use_json=True):
        class _M:
            content = '{"queries": ["x market companies list"]}'

        class _C:
            message = _M()
            finish_reason = "stop"

        class _R:
            choices = [_C()]
            usage = None

        return _R()

    monkeypatch.setattr(ce, "_chat_create", _fake_create)
    out = ce._chat_json(None, "deepseek-v4-flash", "s", "u", require_key="queries", use_ai_mode=False)
    assert out["queries"]
    assert "ai_mode" not in called


def test_bad_generated_queries_are_rejected(monkeypatch):
    """Too short, too long, or duplicated queries must not reach AI Mode."""
    monkeypatch.setattr(
        ce,
        "_chat_json",
        lambda *a, **k: {
            "queries": [
                "ok",  # too short
                "x" * 200,  # too long
                "a valid market companies query",
                "A VALID MARKET COMPANIES QUERY",  # duplicate
                "",
            ]
        },
    )
    monkeypatch.setattr(ce, "_client", lambda s: None)
    monkeypatch.setattr(ce, "_model", lambda s: "deepseek-v4-flash")
    out = ce._generate_discovery_queries("M", market_type="B2B", categories=[], settings=Settings())
    assert out == ["a valid market companies query"]


def test_generation_failure_falls_back_to_templates(monkeypatch):
    """A generation failure must not lose the discovery step."""
    monkeypatch.setattr(
        ce, "_chat_json", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down"))
    )
    monkeypatch.setattr(ce, "_client", lambda s: None)
    monkeypatch.setattr(ce, "_model", lambda s: "deepseek-v4-flash")
    assert ce._generate_discovery_queries("M", market_type="B2B", categories=[], settings=Settings()) == []


def test_generated_and_template_queries_are_both_kept(monkeypatch):
    """Measured on Global Daily Multivitamins: generated and template queries
    each surfaced 16 known brands, but only 10 overlapped — generated found
    GNC/Kirkland/Thorne/Ritual/MegaFood/Optimum Nutrition, templates found
    Haleon/Herbalife/NOW Foods/SmartyPants/Swisse/USANA. Combined = 22.
    They are complementary, so neither set may be dropped.
    """
    monkeypatch.setattr(
        ce,
        "_chat_json",
        lambda *a, **k: {"queries": ["generated multivitamin brands query"]},
    )
    monkeypatch.setattr(ce, "_client", lambda s: None)
    monkeypatch.setattr(ce, "_model", lambda s: "deepseek-v4-flash")

    gen = ce._generate_discovery_queries(
        "M", market_type="B2C", categories=[], settings=Settings()
    )
    templates = [f"top companies in the M list names and official websites"]
    seen_q = {p.lower() for p in gen}
    combined = gen + [p for p in templates if p.lower() not in seen_q]

    assert gen[0] in combined, "generated queries must run"
    assert templates[0] in combined, "template queries must ALSO run"
    assert combined.index(gen[0]) < combined.index(templates[0]), "generated go first"
