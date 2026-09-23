"""After regions, ask COUNTRIES individually.

"Africa" is one query for 54 countries: the model names the two obvious South
African firms and stops, so a Nigerian or Egyptian producer is never reached.
"...headquartered in Nigeria" is a narrower question that surfaces national
players the regional ask skips.

Ladder: broad -> 9 regions -> 64 countries -> regions again (up to 3 sweeps).
"""
from __future__ import annotations

from vendor_intel.pipeline import discovery_rounds as dr
from vendor_intel.pipeline import geo_rotation as gr


def _key(n: str) -> str:
    return "".join(c for c in (n or "").lower() if c.isalnum())


def _co(brand: str, hq: str = "Tokyo, Japan") -> dict:
    return {"brand": brand, "company": f"{brand} Ltd", "headquarters": hq,
            "verdict": "in_market", "why_related": "Makes product."}


# --- the country table -----------------------------------------------------


def test_every_region_has_countries():
    for region in gr.REGIONS:
        assert gr.countries_for(region), f"{region} has no countries to ask about"


def test_africa_is_more_than_south_africa():
    """The case that motivated this: one query for a continent."""
    africa = gr.countries_for("Africa")
    assert "South Africa" in africa
    assert "Nigeria" in africa and "Egypt" in africa
    assert len(africa) >= 6


def test_countries_are_ordered_by_thinnest_region_first():
    rows = [{"headquarters": "Munich, Germany"}] * 5
    ordered = gr.all_countries_by_coverage(rows)
    assert "Germany" in ordered
    # Europe is well covered, so its countries must not come first.
    assert ordered.index("Brazil") < ordered.index("Germany")


def test_an_unknown_region_yields_no_countries():
    assert gr.countries_for("Atlantis") == []


# --- the ladder ------------------------------------------------------------


def test_countries_are_asked_after_regions_run_dry():
    asked: list[str] = []

    def ask(system, user, label):
        for line in user.split("\n"):
            if "HEADQUARTERED IN" in line:
                asked.append(line.split("HEADQUARTERED IN", 1)[1].strip().rstrip(","))
        return {"companies": []}

    _, stats = dr.discover_in_rounds(
        "M", "Manufacturer", ask_json=ask, target=500,
        dedupe_key=_key, already_found=[_co("A")],
    )
    assert stats["regions_swept"], "regions first"
    assert stats["countries_swept"], "then countries"
    joined = " ".join(asked)
    assert "Nigeria" in joined or "Egypt" in joined, "a specific country must be asked"


def test_a_country_round_names_the_country():
    _, user = dr.build_round_prompt(
        "M", "Manufacturer", excluded_names=[], focus_region="Nigeria"
    )
    assert "HEADQUARTERED IN Nigeria" in user
    assert "global headquarters must be in Nigeria" in user


def test_a_country_gets_only_one_empty_round():
    """64 countries x 2 rounds is 128 paced queries, mostly on countries with
    no participant at all."""
    assert dr.EMPTY_ROUNDS_PER_COUNTRY == 1
    assert dr.EMPTY_ROUNDS_PER_REGION == 2


def test_a_productive_country_is_not_abandoned():
    """One empty round ends a country, but a yielding one continues."""
    calls = {"n": 0}

    def ask(system, user, label):
        if "HEADQUARTERED IN Brazil" not in user:
            return {"companies": []}
        calls["n"] += 1
        if calls["n"] <= 3:
            return {"companies": [_co(f"BR{calls['n']}", "Sao Paulo, Brazil")]}
        return {"companies": []}

    found, _ = dr.discover_in_rounds(
        "M", "Manufacturer", ask_json=ask, target=500,
        dedupe_key=_key, already_found=[_co("A")],
    )
    assert sum(1 for c in found if c["brand"].startswith("BR")) == 3


def test_exhausted_now_means_regions_and_countries_were_asked():
    def ask(system, user, label):
        return {"companies": []}

    _, stats = dr.discover_in_rounds(
        "M", "Manufacturer", ask_json=ask, target=500,
        dedupe_key=_key, already_found=[_co("A")],
    )
    assert stats["stopped_because"] == "exhausted"
    assert len(stats["countries_swept"]) >= 20


def test_hitting_the_target_stops_before_the_country_sweep():
    """The ladder is a fallback, not a mandatory 64-query tax."""
    def ask(system, user, label):
        return {"companies": [_co(f"N{label}")]}

    _, stats = dr.discover_in_rounds(
        "M", "Manufacturer", ask_json=ask, target=3, dedupe_key=_key,
    )
    assert stats["stopped_because"] == "target_reached"
    assert stats["countries_swept"] == []
