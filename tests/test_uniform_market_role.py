"""One role per market: every company in a landscape is the same player type.

A competitive quadrant compares like with like, so a market that mixes
Manufacturers with Distributors (or Brand with Marketer) is not one peer
group. The market's dominant role is applied to every kept company.
"""
from __future__ import annotations

from vendor_intel.quadrant.market_relevance import (
    _B2C_ROLE,
    _collapse_to_uniform_role,
    uniform_role_enabled,
)


def _row(primary: str, roles=None, reasons=None):
    return {
        "commercial_role": primary,
        "commercial_roles": list(roles or [primary]),
        "role_reasons": dict(reasons or {}),
    }


def test_enabled_by_default():
    assert uniform_role_enabled() is True


def test_can_be_disabled(monkeypatch):
    monkeypatch.setenv("MARKET_UNIFORM_ROLE", "false")
    assert uniform_role_enabled() is False


def test_dominant_role_wins():
    rows = [_row("Manufacturer") for _ in range(5)]
    rows += [_row("Distributor") for _ in range(2)]
    assert _collapse_to_uniform_role(rows, market_type="B2B") == "Manufacturer"
    assert {r["commercial_role"] for r in rows} == {"Manufacturer"}


def test_every_company_ends_with_exactly_one_role():
    rows = [
        _row("Manufacturer", ["Manufacturer", "Solution Provider", "Service Provider"]),
        _row("Manufacturer", ["Manufacturer"]),
        _row("Service Provider", ["Service Provider"]),
    ]
    _collapse_to_uniform_role(rows, market_type="B2B")
    assert all(len(r["commercial_roles"]) == 1 for r in rows)
    assert len({r["commercial_role"] for r in rows}) == 1


def test_b2c_market_collapses_to_brand_marketer():
    """Fixes the Brand-vs-Marketer split seen in four live markets."""
    rows = [_row("Brand"), _row("Marketer"), _row("Brand")]
    assert _collapse_to_uniform_role(rows, market_type="B2C") == _B2C_ROLE
    assert {r["commercial_role"] for r in rows} == {_B2C_ROLE}


def test_original_classification_kept_for_audit():
    """The per-company multi-role result is not lost, just not displayed."""
    rows = [_row("Manufacturer", ["Manufacturer", "Solution Provider"], {"Manufacturer": "makes it"})]
    _collapse_to_uniform_role(rows, market_type="B2B")
    assert rows[0]["commercial_roles_original"] == ["Manufacturer", "Solution Provider"]
    assert rows[0]["role_reasons_original"] == {"Manufacturer": "makes it"}


def test_existing_reason_preserved_when_available():
    rows = [_row("Manufacturer", ["Manufacturer"], {"Manufacturer": "produces the equipment itself"})]
    _collapse_to_uniform_role(rows, market_type="B2B")
    assert rows[0]["role_reasons"]["Manufacturer"] == "produces the equipment itself"


def test_reason_synthesized_when_missing():
    rows = [_row("Distributor", ["Distributor"], {})]
    _collapse_to_uniform_role(rows, market_type="B2B")
    assert rows[0]["role_reasons"]["Distributor"]


def test_tie_broken_deterministically():
    rows = [_row("Manufacturer"), _row("Distributor")]
    a = _collapse_to_uniform_role(rows, market_type="B2B")
    rows2 = [_row("Distributor"), _row("Manufacturer")]
    b = _collapse_to_uniform_role(rows2, market_type="B2B")
    assert a == b == "Distributor"  # alphabetical on a tie


def test_empty_input_is_safe():
    assert _collapse_to_uniform_role([], market_type="B2B") == ""


def test_company_function_matches_the_uniform_role():
    rows = [_row("Manufacturer", ["Manufacturer", "Service Provider"])]
    _collapse_to_uniform_role(rows, market_type="B2B")
    assert rows[0]["company_function"] == "manufacturer"


def test_uniform_role_survives_to_the_report():
    """commercial_roles must win over a stale per-row Distribution Type, or
    the Brand/Marketer split reappears in the Role column."""
    from vendor_intel.pipeline.expand_quadrant_score import to_company_detail_rows

    base = {
        "Ownership": "Independent",
        "Founded": "2000",
        "Headquarters": "Berlin, Germany",
        "X Score": "80",
        "Y Score": "75",
        "Overall Score": "78",
        "Quadrant": "Leaders",
    }
    rows = [
        {**base, "Company": "Co0", "commercial_roles": ["Manufacturer"], "Distribution Type": "Manufacturer"},
        {**base, "Company": "Co1", "commercial_roles": ["Manufacturer"], "Distribution Type": "Marketer"},
    ]
    out = to_company_detail_rows(rows, "Global Flexible Packaging Market")
    assert {o["Role"] for o in out} == {"Manufacturer"}


# --- one player type targeted from the START, not collapsed afterwards -----


def _ce():
    from vendor_intel.pipeline import chatgpt_expand as ce

    return ce


def test_step0c_selects_a_single_primary_role():
    """A landscape compares like with like, so discovery/verify/Role must all
    target ONE player type. Stage 1 lists every participant category it can
    see; only the primary one is used."""
    ce = _ce()
    ce.set_discovery_market(
        "B2B",
        [
            "Substrate and Epitaxial Wafer Manufacturer",
            "IDM (Integrated Device Manufacturer)",
            "Foundry",
        ],
    )
    try:
        assert ce._discovery_categories() == ["Substrate and Epitaxial Wafer Manufacturer"]
        assert len(ce.discovery_all_categories()) == 3, "full list kept for audit"
    finally:
        ce.set_discovery_market("", [])


def test_discovery_and_verify_target_the_same_role():
    """Regression: discovery searched for all 5 SiC categories while verify
    demanded a hardcoded "Solution Provider" — 2 companies kept out of 24."""
    ce = _ce()
    ce.set_discovery_market("B2B", ["Substrate and Epitaxial Wafer Manufacturer", "Foundry"])
    try:
        role = ce.player_label("Global Silicon Carbide Market")
        assert role == "Substrate and Epitaxial Wafer Manufacturer"
        assert role in ce._landscape_list_nouns("Global Silicon Carbide Market", "general")
        assert f"Required type: {role}" in ce.verify_criteria_prompt(
            "Global Silicon Carbide Market"
        )
    finally:
        ce.set_discovery_market("", [])


def test_buyer_and_channel_roles_are_not_chosen_as_primary():
    """A hospital or an end-user industry BUYS in the market; it does not
    compete in it, so it must never become the landscape's player type."""
    ce = _ce()
    for cats, expected in [
        (
            ["Healthcare Provider", "Clinic / Hospital", "Pharmaceutical Manufacturer"],
            "Pharmaceutical Manufacturer",
        ),
        (["End-User Industry", "Raw Material Supplier"], "Raw Material Supplier"),
        (["Reseller / Distributor", "Telecom Carrier"], "Telecom Carrier"),
    ]:
        ce.set_discovery_market("B2B", cats)
        try:
            assert ce.player_label("M") == expected, cats
        finally:
            ce.set_discovery_market("", [])


def test_b2c_market_still_resolves_to_brand_marketer():
    ce = _ce()
    ce.set_discovery_market("B2C", [])
    try:
        assert ce.player_label("Global Solar Rooftop Market") == "Brand / Marketer"
    finally:
        ce.set_discovery_market("", [])


# --- constrained player-type vocabulary ------------------------------------


def test_only_four_player_types_are_allowed():
    """B2C -> Brand / Marketer. B2B -> Manufacturer (physical), Solution
    Provider (technology) or Service Provider (service). Nothing else."""
    ce = _ce()
    assert ce.ALLOWED_PLAYER_TYPES == (
        "Brand / Marketer",
        "Manufacturer",
        "Solution Provider",
        "Service Provider",
    )


def test_market_specific_phrases_map_to_conventional_labels():
    """Stage 1 returns phrases like "Silicon Carbide Substrate Manufacturer";
    the Role column must show a clean conventional label instead."""
    ce = _ce()
    for raw, expected in [
        ("Silicon Carbide Substrate Manufacturer", "Manufacturer"),
        ("Polyurethane Systems House", "Manufacturer"),
        ("Raw Material Supplier", "Manufacturer"),
        ("Communication Platform as a Service Provider", "Solution Provider"),
        ("Independent Software Vendor (ISV)", "Solution Provider"),
        ("Design and Engineering Service Provider", "Service Provider"),
    ]:
        assert ce.canonical_player_type(raw, market_type="B2B") == expected, raw


def test_contract_manufacturer_never_survives_as_a_player_type():
    """Explicitly excluded — it must collapse to Manufacturer, never appear."""
    ce = _ce()
    got = ce.canonical_player_type("Contract Manufacturer", market_type="B2B")
    assert got == "Manufacturer"
    assert "contract" not in got.lower()


def test_b2c_always_resolves_to_brand_marketer():
    ce = _ce()
    assert ce.canonical_player_type("", market_type="B2C") == "Brand / Marketer"
    assert ce.canonical_player_type("Consumer Brand", market_type="B2C") == "Brand / Marketer"


def test_canonical_output_is_always_in_the_allowed_set():
    """Whatever the model returns, the Role column shows one of the four."""
    ce = _ce()
    for raw in [
        "Telecom Carrier",
        "Distributor and Authorized Reseller",
        "Abrasive and Industrial Materials Refiner",
        "Clinic / Hospital",
        "",
        "something nobody expected",
    ]:
        assert ce.canonical_player_type(raw, market_type="B2B") in ce.ALLOWED_PLAYER_TYPES


# --- hybrid markets resolve to B2C -----------------------------------------


def test_hybrid_rule_is_stated_in_both_stage1_prompts():
    """A market with BOTH a business and a consumer side must resolve to B2C.
    The rule has to exist in both Stage 1 prompts, because either can run
    depending on whether AI Mode is available."""
    from vendor_intel.pipeline import chatgpt_expand as ce
    from vendor_intel.quadrant import market_relevance as mr

    for prompt in (ce._MARKET_ANALYSIS_DISCOVERY_SYSTEM, mr._MARKET_ANALYSIS_SYSTEM):
        flat = " ".join(prompt.split())
        assert "HYBRID markets" in flat
        assert "sells to BOTH businesses and individual consumers" in flat
        # Hybrid is now its own third market type, not folded into B2C.
        assert 'answer "Hybrid B2B + B2C"' in flat
        assert "never split a company into separate B2B and B2C rows" in flat


def test_market_type_reason_is_requested_in_both_prompts():
    """The B2B/B2C call must be explainable, not just asserted."""
    from vendor_intel.pipeline import chatgpt_expand as ce
    from vendor_intel.quadrant import market_relevance as mr

    for prompt in (ce._MARKET_ANALYSIS_DISCOVERY_SYSTEM, mr._MARKET_ANALYSIS_SYSTEM):
        flat = " ".join(prompt.split())
        assert "market_type_reason" in flat


def test_b2c_analysis_forces_brand_marketer_and_no_categories(monkeypatch):
    """Even if the model returns B2B-style categories alongside B2C."""
    import json

    from vendor_intel.pipeline import chatgpt_expand as ce
    from vendor_intel.quadrant import market_relevance as mr
    from vendor_intel.scraping import google_ai_mode as gam

    mr._MARKET_ANALYSIS_CACHE.clear()
    monkeypatch.setenv("GOOGLE_AI_MODE_ENABLED", "true")
    monkeypatch.setattr(
        gam,
        "ask",
        lambda p, **k: json.dumps(
            {
                "market_type": "B2C",
                "market_type_reason": "Hybrid, but sold to homeowners too, so B2C.",
                "market_definition": "Rooftop solar.",
                "market_participants": [{"type": "Installer", "definition": "d", "why_relevant": "r"}],
                "primary_participant": "Installer",
            }
        ),
    )
    try:
        out = ce._analyze_market_for_discovery("Global Solar Rooftop Market")
        assert out["market_type"] == "B2C"
        assert out["primary_participant"] == "Brand / Marketer"
        assert out["market_participants"] == []
        assert "hybrid" in out["market_type_reason"].lower()
    finally:
        mr._MARKET_ANALYSIS_CACHE.clear()
