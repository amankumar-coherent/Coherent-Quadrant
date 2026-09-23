"""Step 4 verify: keep only Solution Provider (tech) or Brand/Marketer (other)."""
from __future__ import annotations

from vendor_intel.pipeline.chatgpt_expand import (
    _verify_parse_row,
    player_label,
    verify_criteria_prompt,
    verify_should_keep,
)


def test_player_label_is_one_of_two_valid_display_styles():
    # player_label now derives from market_relevance.analyze_market's live,
    # market-specific B2B/B2C + dynamic-provider-category classification
    # (see test_market_classification.py) rather than a fixed
    # hardware/software keyword list — so the exact label per market name is
    # no longer a hardcoded constant here. This only pins the output shape.
    for market in (
        "Global Semiconductor Market",
        "Global Wearable Medical Devices Market",
        "Global Flexible Packaging Market",
        "Global Liquefied Natural Gas Market",
        "Global GLP-1 Receptor Agonist Market",
    ):
        assert player_label(market) in ("Solution Provider", "Brand / Marketer")


def test_keep_tsmc_as_solution_provider():
    assert verify_should_keep(
        in_market=True,
        role="Solution Provider",
        builds_or_owns=True,
        confidence=90,
        expected_role="Solution Provider",
    )


def test_drop_arrow_reseller_in_semiconductor():
    assert not verify_should_keep(
        in_market=True,
        role="Distributor",
        builds_or_owns=False,
        confidence=95,
        expected_role="Solution Provider",
    )


def test_keep_amcor_as_brand():
    assert verify_should_keep(
        in_market=True,
        role="Brand / Marketer",
        builds_or_owns=True,
        confidence=88,
        expected_role="Brand / Marketer",
    )


def test_drop_walmart_retailer_in_packaging():
    assert not verify_should_keep(
        in_market=True,
        role="Retailer",
        builds_or_owns=False,
        confidence=80,
        expected_role="Brand / Marketer",
    )


def test_drop_low_confidence():
    assert not verify_should_keep(
        in_market=True,
        role="Solution Provider",
        builds_or_owns=True,
        confidence=40,
        expected_role="Solution Provider",
    )


def test_drop_media_and_geo():
    assert not verify_should_keep(
        in_market=False,
        role="Media",
        builds_or_owns=False,
        confidence=99,
        expected_role="Brand / Marketer",
    )


def test_parse_fits_criteria_false_drops():
    keep, _, _, _ = _verify_parse_row(
        {
            "name": "Arrow Electronics",
            "in_market": True,
            "builds_or_owns": False,
            "role": "Distributor",
            "fits_criteria": False,
            "confidence": 92,
            "reason": "reseller not a builder",
        },
        "Solution Provider",
    )
    assert keep is False


def test_parse_novo_brand_keep():
    keep, conf, role, _ = _verify_parse_row(
        {
            "Company": "Novo Nordisk",
            "in_market": True,
            "builds_or_owns": True,
            "role": "Brand / Marketer",
            "fits_criteria": True,
            "confidence": 95,
            "reason": "owns and markets GLP-1 brands",
        },
        "Brand / Marketer",
    )
    assert keep is True
    assert conf == 95
    assert "Brand" in role


def test_criteria_prompt_is_market_driven(monkeypatch):
    """verify_criteria_prompt no longer branches on hand-written per-market
    special cases (semiconductor / GLP-1 / packaging). The required company
    type now comes from THIS market's Stage 1 analysis, so one template
    serves any market — which is what makes running thousands of markets
    possible."""
    import vendor_intel.pipeline.chatgpt_expand as chatgpt_expand

    # B2B market: required type is that market's own participant categories.
    chatgpt_expand.set_discovery_market("B2B", ["Manufacturer", "Service Provider"])
    b2b = verify_criteria_prompt("Global Robotics Market")
    # ONE role: verify must require exactly what discovery searched for.
    assert "Required type: Manufacturer" in b2b
    assert "Service Provider" not in b2b
    assert "PRIMARY business" in b2b

    # A different B2B market gets different categories, same template.
    chatgpt_expand.set_discovery_market("B2B", ["Platform Provider", "Consultant"])
    other = verify_criteria_prompt("Global Analytics Market")
    assert "Required type: Platform Provider" in other
    assert other != b2b

    # B2C market falls back to the consumer-facing label.
    chatgpt_expand.set_discovery_market("B2C", [])
    b2c = verify_criteria_prompt("Global Snack Foods Market")
    assert "Brand / Marketer" in b2c

    chatgpt_expand.set_discovery_market("", [])


def test_criteria_prompt_has_no_hardcoded_market_names(monkeypatch):
    """A market-name keyword must not select a hand-written prompt — that
    approach cannot scale past the few demo markets it was written for."""
    import inspect

    import vendor_intel.pipeline.chatgpt_expand as chatgpt_expand

    body = inspect.getsource(chatgpt_expand.verify_criteria_prompt)
    body = body.split('"""')[2]  # skip the docstring, which names what was removed
    for banned in ("semiconductor", "packaging", "glp-1", "wafer", "foundry"):
        assert banned not in body.lower(), f"{banned} still branches the prompt"

    # The same market name must not force a fixed prompt any more.
    chatgpt_expand.set_discovery_market("B2B", ["Distributor"])
    p = verify_criteria_prompt("Global Semiconductor Market")
    assert "Distributor" in p
    assert "IDM, fabless" not in p
    chatgpt_expand.set_discovery_market("", [])
