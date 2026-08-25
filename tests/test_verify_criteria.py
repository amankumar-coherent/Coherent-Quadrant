"""Step 4 verify: keep only Solution Provider (tech) or Brand/Marketer (other)."""
from __future__ import annotations

from vendor_intel.pipeline.chatgpt_expand import (
    _verify_parse_row,
    player_label,
    verify_criteria_prompt,
    verify_should_keep,
)


def test_player_label_five_markets():
    assert player_label("Global Semiconductor Market") == "Solution Provider"
    assert player_label("Global Wearable Medical Devices Market") == "Solution Provider"
    assert player_label("Global Flexible Packaging Market") == "Brand / Marketer"
    assert player_label("Global Liquefied Natural Gas Market") == "Brand / Marketer"
    assert player_label("Global GLP-1 Receptor Agonist Market") == "Brand / Marketer"


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


def test_criteria_prompt_mentions_build_or_own():
    tech = verify_criteria_prompt("Global Semiconductor Market")
    brand = verify_criteria_prompt("Global Flexible Packaging Market")
    assert "BUILD" in tech
    assert "Solution Provider" in tech
    assert "OWN or MARKET" in brand
    assert "Brand / Marketer" in brand
