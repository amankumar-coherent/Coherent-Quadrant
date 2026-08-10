"""Country-level runs merged into one region dataset (run_region.py)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from run_region import REGION_PRESETS, build_region_result, merge_country_rows


def _row(company, domain, quality=0.8, **extra):
    return {"company": company, "domain": domain, "quality_score": quality,
            "is_relevant": True, **extra}


def test_same_company_in_two_countries_collapses_to_one_row():
    merged = merge_country_rows([
        ("USA", [_row("Fike Corporation", "fike.com")]),
        ("Canada", [_row("Fike Corp", "www.fike.com")]),
    ])
    assert len(merged) == 1
    assert merged[0]["countries"] == "Canada; USA"
    assert merged[0]["found_in_country_count"] == 2


def test_www_and_scheme_do_not_create_duplicates():
    merged = merge_country_rows([
        ("USA", [_row("Acme", "https://www.acme.com/about")]),
        ("Canada", [_row("Acme", "acme.com")]),
    ])
    assert len(merged) == 1


def test_better_evidenced_duplicate_wins_but_countries_are_kept():
    """The higher-quality body survives; the country set must not be lost with it."""
    merged = merge_country_rows([
        ("USA", [_row("Fike Corporation", "fike.com", quality=0.5, summary="thin")]),
        ("Canada", [_row("Fike Corp", "fike.com", quality=0.95, summary="rich")]),
    ])
    assert merged[0]["summary"] == "rich"
    assert merged[0]["countries"] == "Canada; USA"


def test_distinct_companies_are_preserved():
    merged = merge_country_rows([
        ("USA", [_row("Fike", "fike.com"), _row("ZOOK", "zookdisk.com")]),
        ("Canada", [_row("Continental Disc", "contdisc.com")]),
    ])
    assert {r["company"] for r in merged} == {"Fike", "ZOOK", "Continental Disc"}
    assert all(r["found_in_country_count"] == 1 for r in merged)


def test_domainless_rows_fall_back_to_name_identity():
    merged = merge_country_rows([
        ("USA", [{"company": "Acme Corp", "domain": "", "is_relevant": True}]),
        ("Canada", [{"company": "acme corp", "domain": "", "is_relevant": True}]),
    ])
    assert len(merged) == 1


def test_rows_without_name_or_domain_are_dropped():
    assert merge_country_rows([("USA", [{"company": "", "domain": ""}])]) == []


def test_confirmed_anywhere_outranks_unverified_elsewhere():
    """A company confirmed in one country must not also appear on the watchlist."""
    result = build_region_result("North America", "Rupture Disc Market", [
        ("USA", {"relevant_companies": [_row("Fike", "fike.com")], "unverified_companies": []}),
        ("Canada", {"relevant_companies": [], "unverified_companies": [_row("Fike", "fike.com")]}),
    ])
    assert [r["company"] for r in result["relevant_companies"]] == ["Fike"]
    assert result["unverified_companies"] == []


def test_failed_country_does_not_lose_the_others():
    result = build_region_result("North America", "Rupture Disc Market", [
        ("USA", {"relevant_companies": [_row("Fike", "fike.com")]}),
        ("Canada", {"error": "boom"}),
    ])
    assert len(result["relevant_companies"]) == 1
    assert result["per_country"]["Canada"]["error"] == "boom"
    assert result["per_country"]["USA"]["relevant"] == 1


def test_merged_result_carries_region_scope_for_the_exporters():
    result = build_region_result("North America", "Rupture Disc Market", [
        ("USA", {"relevant_companies": [_row("Fike", "fike.com")], "scope": {"market": "Rupture Disc Market"}}),
        ("Canada", {"relevant_companies": []}),
    ])
    # save_pipeline_csv reads exactly these three keys
    assert result["query_context"]["country"] == "North America"
    assert result["query_context"]["industry"] == "Rupture Disc Market"
    assert result["scope"]["geography"] == "North America"
    assert result["scope"]["geographies"] == ["USA", "Canada"]
    assert "relevant_companies" in result


def test_rows_are_alphabetical():
    merged = merge_country_rows([("USA", [_row("Zeta", "z.com"), _row("Alpha", "a.com")])])
    assert [r["company"] for r in merged] == ["Alpha", "Zeta"]


def test_north_america_preset_exists():
    assert "north america" in REGION_PRESETS
    assert "USA" in REGION_PRESETS["north america"]
    assert "Canada" in REGION_PRESETS["north america"]
