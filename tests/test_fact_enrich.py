"""Tests for dual fact-enrich question helpers."""
from __future__ import annotations

from vendor_intel.pipeline.fact_enrich import (
    founded_question,
    market_brands_question,
    ownership_question,
    _apply_facts,
    _regex_founded,
)


def test_ownership_and_founded_questions_include_brand():
    assert "Horizon" in ownership_question("Horizon Organic")
    assert "founded" in founded_question("Horizon Organic").lower()


def test_market_brands_question_global():
    q = market_brands_question("Organic Milk Market", "global")
    assert "Organic Milk" in q
    assert "company" in q.lower()
    assert "brand" in q.lower()


def test_regex_founded_year_and_location():
    year, loc = _regex_founded("The company was founded in Vermont in 1988 by farmers.")
    assert year == "1988"
    assert "Vermont" in loc


def test_apply_facts_sets_acquired_by_display():
    row = {"company": "Horizon Organic", "brand": "Horizon Organic"}
    _apply_facts(
        row,
        {
            "owner": "Danone",
            "relation": "acquired_by",
            "founded_year": "1991",
            "founded_location": "Colorado, USA",
            "hq_location": "Broomfield, Colorado",
        },
        source="llm+scraper",
    )
    assert row["company"] == "Horizon Organic"
    assert row["acquired_by_display"] == "acquired by Danone"
    assert row["parent_owner"] == "Danone"
    assert row["founded_year"] == "1991"
    assert row["founded_location"] == "Colorado, USA"
    assert row["hq_location"] == "Broomfield, Colorado"
    assert "llm+scraper" in row["fact_sources"]
