"""A country-scoped run narrows by STATE, not by world region.

The region ladder cannot steer a run where every company shares one country:
"prefer under-covered regions" is meaningless when the answer is always India.
The equivalent narrowing is one level down, and the country constraint has to
reach the BROAD rounds too — otherwise the opening rounds fill the set with
global majors that verification then throws away.
"""
from __future__ import annotations

from vendor_intel.pipeline import discovery_rounds as dr
from vendor_intel.pipeline.geo_rotation import (
    REGIONS,
    is_single_country,
    states_for,
)


# --- the state list --------------------------------------------------------


def test_india_has_a_state_list():
    assert len(states_for("India")) >= 15


def test_the_state_lookup_is_case_and_article_insensitive():
    assert states_for("india") == states_for("India") == states_for("  INDIA ")


def test_the_major_industrial_states_are_covered():
    joined = " ".join(states_for("India")).lower()
    for place in ("maharashtra", "karnataka", "tamil nadu", "gujarat",
                  "telangana", "delhi"):
        assert place in joined


def test_states_are_not_duplicated():
    states = states_for("India")
    assert len(set(states)) == len(states)


def test_a_country_with_no_state_list_returns_empty():
    """Falls back to the existing ladder rather than inventing place names."""
    assert states_for("Latvia") == []
    assert states_for("") == []


def test_global_is_not_a_single_country():
    for value in ("global", "Global", "worldwide", "world", ""):
        assert not is_single_country(value)


def test_a_real_country_is_a_single_country():
    assert is_single_country("India")


# --- the prompt ------------------------------------------------------------


def _broad(country: str = "") -> str:
    return dr.build_round_prompt(
        "Drone LiDAR", "Manufacturer", excluded_names=[], country=country
    )[1]


def test_the_broad_round_names_the_country():
    """Without this the opening rounds return global companies."""
    user = _broad("India")
    assert "HEADQUARTERED IN India" in user


def test_the_broad_round_rejects_foreign_subsidiaries():
    user = _broad("India")
    assert "subsidiary" in user.lower()
    assert "does NOT qualify" in user


def test_the_broad_round_forbids_substituting_another_country():
    user = _broad("India")
    assert "do NOT substitute" in user


def test_a_global_run_keeps_the_unconstrained_broad_ask():
    user = _broad("")
    assert "HEADQUARTERED IN" not in user
    assert "Give me 10 BRANDS sold in this market, each with" in user


def test_a_state_round_is_anchored_inside_the_country():
    """"Karnataka" alone is ambiguous to the model; ", India" pins it."""
    user = dr.build_round_prompt(
        "Drone LiDAR", "Manufacturer", excluded_names=[],
        country="India", focus_region="Karnataka (Bengaluru)",
    )[1]
    assert "HEADQUARTERED IN Karnataka (Bengaluru), India" in user


def test_a_state_round_without_a_country_is_unchanged():
    user = dr.build_round_prompt(
        "Drone LiDAR", "Manufacturer", excluded_names=[], focus_region="Brazil",
    )[1]
    assert "HEADQUARTERED IN Brazil, each with" in user


# --- the escalation ladder -------------------------------------------------


def _run(country: str, answers: list[list[dict]]) -> dict:
    """Drive discovery with canned answers; return the stats."""
    calls: list[str] = []
    seq = list(answers)

    def ask(system: str, user: str, label: str):
        calls.append(user)
        return {"companies": seq.pop(0) if seq else []}

    _found, stats = dr.discover_in_rounds(
        "Drone LiDAR", "Manufacturer", ask_json=ask, target=500,
        dedupe_key=lambda n: n.strip().lower(), country=country,
    )
    stats["_calls"] = calls
    return stats


def test_an_india_run_sweeps_states_not_regions():
    stats = _run("India", [[{"brand": "A", "company": "A Ltd"}]])
    asked = " ".join(stats["_calls"])
    assert "Maharashtra" in asked, "the state tier never ran"
    for region in ("Latin America", "Africa", "Oceania"):
        assert region not in asked, f"{region} is outside the country scope"


def test_an_india_run_never_leaves_india():
    stats = _run("India", [[{"brand": "A", "company": "A Ltd"}]])
    asked = " ".join(stats["_calls"])
    for foreign in ("Brazil", "Germany", "the United States", "Japan"):
        assert f"HEADQUARTERED IN {foreign}" not in asked


def test_a_global_run_still_uses_the_region_ladder():
    """The India path must not regress the existing global behaviour."""
    stats = _run("global", [[{"brand": "A", "company": "A Ltd"}]])
    asked = " ".join(stats["_calls"])
    assert any(r in asked for r in REGIONS), "regions were never swept"


def test_an_india_run_stops_rather_than_widening():
    """Running out of states ends discovery; it must not fall through to the
    global country ladder and start returning foreign companies."""
    stats = _run("India", [[{"brand": "A", "company": "A Ltd"}]])
    assert stats["stopped_because"] in ("exhausted", "max_rounds")
    asked = " ".join(stats["_calls"])
    assert "HEADQUARTERED IN Brazil" not in asked
