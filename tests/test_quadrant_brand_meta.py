"""Unit tests for quadrant brand display / founded helpers."""
from __future__ import annotations

from vendor_intel.config import Settings
from vendor_intel.quadrant.brand_meta import (
    brand_display_fields,
    company_display_mode,
    extract_founded_year,
    format_acquired_suffix,
    plain_brand_name,
)

# company_display_mode() now tries one cached LLM call per market before
# falling back to the keyword heuristic (see brand_meta.py). These tests
# exercise the fallback path specifically, so they stay fast and
# network-free regardless of which API keys are configured in the
# environment running them — pass use_mock_data=True to force
# ClaudeClient.available to False.
_NO_LLM = Settings.load().model_copy(update={"use_mock_data": True})


def test_food_market_acquired_in_brackets():
    row = {
        "company_raw": "Horizon Organic",
        "company": "Horizon Organic",
        "parent_owner": "Danone",
        "ownership_relation": "acquired_by",
        "founded_location": "Boulder, Colorado",
    }
    brand, company, founded_loc = brand_display_fields(
        row, market="Organic Milk Market", industry_category="Food and Beverages"
    )
    assert brand == "Horizon Organic"
    assert company == "(acquired by Danone)"
    assert founded_loc == "Boulder, Colorado"


def test_protein_market_mode():
    assert company_display_mode("Plant Protein Market", settings=_NO_LLM) == "consumer_brand"
    row = {"company": "Beyond Meat", "parent_owner": "Nestlé"}
    brand, company, _ = brand_display_fields(row, market="Plant Protein Market")
    assert brand == "Beyond Meat"
    assert company == "(acquired by Nestlé)"


def test_tech_solution_provider_plain_parent(monkeypatch):
    # company_display_mode now derives from market_relevance.analyze_market's
    # live B2B/B2C + dynamic-provider-category classification rather than a
    # fixed ICT/semiconductor keyword list — mock the LLM call for a
    # deterministic "this market's categories include a builder/platform
    # role" case instead of asserting a keyword match.
    import json as _json

    import vendor_intel.clients.claude as claude_mod
    from vendor_intel.quadrant import market_relevance as mr

    mr._MARKET_ANALYSIS_CACHE.clear()

    class _FakeClient:
        available = True

        def complete_json(self, system, user, model=None, max_tokens=None):
            return {
                "market_type": "B2B",
                "market_definition": "Generative AI platforms and tooling.",
                "market_participants": [
                    {"type": "Solution Provider", "definition": "Builds the platform.", "why_relevant": "x"},
                ],
            }

    monkeypatch.setattr(claude_mod, "ClaudeClient", lambda *a, **k: _FakeClient())
    assert (
        company_display_mode(
            "Generative AI Market",
            industry_group="ICT, Automation, Semiconductor",
            industry_category="Information and Communication Technology",
        )
        == "solution_provider"
    )
    mr._MARKET_ANALYSIS_CACHE.clear()
    row = {
        "company_raw": "Gemini",
        "company": "Gemini",
        "parent_owner": "Google",
        "ownership_relation": "subsidiary_of",
    }
    brand, company, _ = brand_display_fields(
        row,
        market="Generative AI Market",
        industry_category="Information and Communication Technology",
    )
    assert brand == "Gemini"
    assert company == "Google"


def test_avocado_oil_is_consumer_style():
    assert company_display_mode("Avocado Oil Market", settings=_NO_LLM) == "consumer_brand"


def test_plain_brand_strips_suffix():
    assert plain_brand_name("Oseco (acquired by Halma plc)") == "Oseco"
    assert plain_brand_name({"company": "Oseco (acquired by Halma plc)"}) == "Oseco"


def test_company_from_suffix_on_name():
    row = {"company": "Horizon Organic (acquired by Danone)", "company_raw": "Horizon Organic"}
    brand, company, _ = brand_display_fields(row, market="Organic Milk Market")
    assert brand == "Horizon Organic"
    assert company == "(acquired by Danone)"


def test_founded_from_snapshot_intel():
    row = {
        "company": "Yeo Valley",
        "evidence_snapshot": {
            "data": {"company": {"founded_year": "1961", "name": "Yeo Valley"}},
            "page_text": "",
        },
    }
    assert extract_founded_year(row) == "1961"


def test_founded_from_page_text_regex():
    row = {
        "company": "Maple Hill",
        "evidence_snapshot": {
            "data": {},
            "page_text": "Maple Hill was founded in 2009 and produces organic milk.",
        },
    }
    assert extract_founded_year(row) == "2009"


def test_format_acquired_suffix_with_year():
    assert format_acquired_suffix("Halma", year="2017") == "(acquired by Halma, 2017)"
