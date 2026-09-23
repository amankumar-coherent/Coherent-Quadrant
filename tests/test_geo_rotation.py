"""Geographic rotation: later rounds must reach regions the market has missed.

Without a steer, AI Mode answers "brands in this market" with the same few
countries every round. The name-exclusion list stops it repeating individual
companies but not the geographic habit, so a market can finish at 300
companies that are all American, German and Japanese.
"""
from __future__ import annotations

import pytest

from vendor_intel.pipeline import discovery_rounds as dr
from vendor_intel.pipeline import geo_rotation as gr


# --- reading a country out of an HQ string ---------------------------------


@pytest.mark.parametrize(
    "hq,region",
    [
        ("Mumbai, India", "South Asia"),
        ("Thousand Oaks, California, USA", "North America"),
        ("Durham, North Carolina, USA", "North America"),
        ("Tokyo, Japan", "East Asia"),
        ("Singapore", "Southeast Asia"),
        ("Sao Paulo, Brazil", "Latin America"),
        ("Cape Town, South Africa", "Africa"),
        ("Dubai, UAE", "Middle East"),
        ("Sydney, Australia", "Oceania"),
        ("Munich, Germany", "Europe"),
    ],
)
def test_region_is_read_from_the_headquarters_string(hq, region):
    assert gr.region_of(hq) == region


def test_us_state_is_never_mistaken_for_a_country():
    """"City, State, USA" has the country LAST — reading the middle element
    would file a California company under an unknown region."""
    assert gr.country_of("Thousand Oaks, California, USA") == "usa"
    assert gr.region_of("Thousand Oaks, California, USA") == "North America"


def test_unknown_headquarters_does_not_guess_a_region():
    """A wrong region skews the coverage counts and steers the next round to
    the wrong place, so an unrecognised country steers nothing."""
    assert gr.region_of("") == ""
    assert gr.region_of("Global") == ""
    assert gr.region_of("Atlantis") == ""


# --- coverage --------------------------------------------------------------


def test_coverage_lists_every_region_including_the_empty_ones():
    """The zeroes are the point — an empty region is the one to ask about."""
    counts = gr.coverage([{"headquarters": "Munich, Germany"}])
    assert set(counts) == set(gr.REGIONS)
    assert counts["Europe"] == 1
    assert counts["Africa"] == 0


def test_under_covered_returns_the_emptiest_regions_first():
    rows = [{"headquarters": "Munich, Germany"}] * 5 + [
        {"headquarters": "Austin, Texas, USA"}
    ] * 3
    weak = gr.under_covered(rows, limit=3)
    assert "Europe" not in weak
    assert "North America" not in weak
    assert len(weak) == 3


def test_rotation_hint_is_empty_before_anything_is_found():
    """Round 1 should see where the market naturally sits."""
    assert gr.rotation_hint([]) == ""


def test_rotation_hint_names_the_missing_regions():
    rows = [{"headquarters": "Munich, Germany"}] * 4
    hint = gr.rotation_hint(rows)
    assert "PREFER brands headquartered in" in hint
    assert "Europe" not in hint.split("PREFER")[1].split(".")[0]


def test_rotation_hint_forbids_inventing_a_company_for_a_region():
    """A geographic target must never become a licence to fabricate."""
    hint = gr.rotation_hint([{"headquarters": "Munich, Germany"}])
    assert "do NOT invent one to satisfy a region" in hint.replace("\n", " ")


# --- wiring into the rounds loop -------------------------------------------


def test_round_prompt_carries_the_geographic_steer():
    _, user = dr.build_round_prompt(
        "M", "Manufacturer", excluded_names=[], geo_hint="GEOGRAPHIC COVERAGE: test"
    )
    assert "GEOGRAPHIC COVERAGE: test" in user
    # The steer must not displace the field rules or the JSON template.
    assert "FIELD RULES:" in user
    assert user.index("GEOGRAPHIC COVERAGE") < user.index("FIELD RULES:")


def test_round_prompt_without_a_steer_is_unchanged():
    _, plain = dr.build_round_prompt("M", "Manufacturer", excluded_names=[])
    assert "GEOGRAPHIC COVERAGE" not in plain


def test_later_rounds_ask_for_under_covered_regions():
    """Spec test 9: repeated rounds must not keep returning one region."""
    seen_hints: list[str] = []

    def ask(system, user, label):
        seen_hints.append(user)
        # Every answer is German, so the steer should push elsewhere.
        n = len(seen_hints)
        return {
            "companies": [
                {
                    "brand": f"B{n}",
                    "company": f"C{n} GmbH",
                    "headquarters": "Munich, Germany",
                    "verdict": "in_market",
                    "why_related": "Sells in this market.",
                }
            ]
        }

    found, stats = dr.discover_in_rounds(
        "M",
        "Manufacturer",
        ask_json=ask,
        target=3,
        dedupe_key=lambda s: s.strip().lower(),
    )
    assert len(found) == 3
    assert "GEOGRAPHIC COVERAGE" not in seen_hints[0], "round 1 is unsteered"
    assert "GEOGRAPHIC COVERAGE" in seen_hints[1], "round 2 must steer"
    assert "Europe" not in seen_hints[1].split("PREFER brands headquartered in")[1].split(".")[0]
    assert stats["region_coverage"]["Europe"] == 3


def test_rotation_can_be_switched_off():
    prompts: list[str] = []

    def ask(system, user, label):
        prompts.append(user)
        n = len(prompts)
        return {
            "companies": [
                {
                    "brand": f"B{n}",
                    "headquarters": "Munich, Germany",
                    "verdict": "in_market",
                }
            ]
        }

    dr.discover_in_rounds(
        "M",
        "Manufacturer",
        ask_json=ask,
        target=2,
        dedupe_key=lambda s: s.strip().lower(),
        rotate_geography=False,
    )
    assert all("GEOGRAPHIC COVERAGE" not in p for p in prompts)


def test_coverage_is_reported_in_the_stats():
    """A run should be auditable for spread, not assumed to have it."""

    def ask(system, user, label):
        n = len(seen) + 1
        seen.append(n)
        hq = ["Munich, Germany", "Mumbai, India", "Tokyo, Japan"][n % 3]
        return {"companies": [{"brand": f"B{n}", "headquarters": hq, "verdict": "in_market"}]}

    seen: list[int] = []
    _, stats = dr.discover_in_rounds(
        "M", "Manufacturer", ask_json=ask, target=3, dedupe_key=lambda s: s.strip().lower()
    )
    assert set(stats["region_coverage"]) == set(gr.REGIONS)
    assert sum(stats["region_coverage"].values()) == 3
