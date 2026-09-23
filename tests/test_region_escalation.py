"""When the broad question runs dry, sweep regions before giving up.

Silicon Carbide stopped at 216 of a 300 target with `exhausted` after three
empty rounds — while Africa, the Middle East and Latin America had never been
asked about directly. "Give me 10 more" is spent long before the market is:
a targeted "manufacturers headquartered in Brazil" reaches local players the
broad query never ranked high enough to mention.
"""
from __future__ import annotations

from vendor_intel.pipeline import discovery_rounds as dr
from vendor_intel.pipeline.geo_rotation import REGIONS


def _key(n: str) -> str:
    return "".join(c for c in (n or "").lower() if c.isalnum())


def _co(brand: str, hq: str = "Tokyo, Japan") -> dict:
    return {"brand": brand, "company": f"{brand} Ltd", "headquarters": hq,
            "verdict": "in_market", "why_related": "Makes product."}


def test_broad_exhaustion_escalates_instead_of_stopping():
    """The exact Silicon Carbide shape: broad query dries up under target."""
    asks: list[str] = []

    def ask(system, user, label):
        asks.append(user)
        if "HEADQUARTERED IN" not in user:
            return {"companies": []}          # broad query is spent
        return {"companies": [_co(f"Local{len(asks)}", "Lagos, Nigeria")]}

    found, stats = dr.discover_in_rounds(
        "M", "Manufacturer", ask_json=ask, target=300,
        dedupe_key=_key, already_found=[_co(f"Big{i}") for i in range(216)],
    )
    assert stats["escalated"] is True
    assert len(found) > 216, "the region sweep must add companies"
    assert any("HEADQUARTERED IN" in a for a in asks)


def test_a_region_round_names_one_region_explicitly():
    _, user = dr.build_round_prompt(
        "M", "Manufacturer", excluded_names=[], focus_region="Latin America"
    )
    assert "HEADQUARTERED IN Latin America" in user
    assert "global headquarters must be in Latin America" in user


def test_a_region_round_rejects_a_local_office():
    """A plant or sales office in a region is not an HQ there."""
    _, user = dr.build_round_prompt(
        "M", "Manufacturer", excluded_names=[], focus_region="Africa"
    )
    assert "sales office, plant or distributor" in user
    assert "does NOT qualify" in user


def test_a_region_round_forbids_substituting_or_inventing():
    """Pressing for companies in an empty region invites fabrication."""
    _, user = dr.build_round_prompt(
        "M", "Manufacturer", excluded_names=[], focus_region="Oceania"
    )
    assert "do NOT substitute a company from elsewhere" in user
    assert "do NOT invent one" in user


def test_the_soft_hint_is_dropped_while_a_region_is_named():
    """Two competing region instructions in one prompt contradict."""
    _, user = dr.build_round_prompt(
        "M", "Manufacturer", excluded_names=[],
        focus_region="Africa", geo_hint="PREFER brands headquartered in: Europe",
    )
    assert "HEADQUARTERED IN Africa" in user
    assert "PREFER brands headquartered in: Europe" not in user


def test_an_empty_region_moves_on_to_the_next():
    regions_asked: list[str] = []

    def ask(system, user, label):
        for r in REGIONS:
            if f"HEADQUARTERED IN {r}" in user:
                regions_asked.append(r)
        return {"companies": []}

    found, stats = dr.discover_in_rounds(
        "M", "Manufacturer", ask_json=ask, target=50,
        dedupe_key=_key, already_found=[_co(f"X{i}") for i in range(10)],
    )
    assert len(set(regions_asked)) >= 5, "must not grind on one empty region"
    assert stats["stopped_because"] == "exhausted"
    assert len(stats["regions_swept"]) >= 5


def test_exhausted_now_means_every_region_was_asked():
    def ask(system, user, label):
        return {"companies": []}

    _, stats = dr.discover_in_rounds(
        "M", "Manufacturer", ask_json=ask, target=50,
        dedupe_key=_key, already_found=[_co("A")],
    )
    assert stats["stopped_because"] == "exhausted"
    assert set(stats["regions_swept"]) == set(REGIONS), "all nine asked directly"


def test_hitting_the_target_still_wins_over_escalation():
    def ask(system, user, label):
        return {"companies": [_co(f"N{label}")]}

    _, stats = dr.discover_in_rounds(
        "M", "Manufacturer", ask_json=ask, target=3, dedupe_key=_key,
    )
    assert stats["stopped_because"] == "target_reached"
    assert stats["escalated"] is False


def test_a_block_during_escalation_is_not_exhaustion():
    """Spec 24: a technical failure must never read as a finished market."""
    def ask(system, user, label):
        raise RuntimeError("You've reached your request limit for AI responses")

    _, stats = dr.discover_in_rounds(
        "M", "Manufacturer", ask_json=ask, target=50,
        dedupe_key=_key, already_found=[_co("A")],
    )
    assert stats["stopped_because"] == "blocked"


def test_escalation_can_be_switched_off():
    def ask(system, user, label):
        return {"companies": []}

    _, stats = dr.discover_in_rounds(
        "M", "Manufacturer", ask_json=ask, target=50, dedupe_key=_key,
        already_found=[_co("A")], escalate_regions=False,
    )
    assert stats["escalated"] is False
    assert stats["regions_swept"] == []
    assert stats["stopped_because"] == "exhausted"


def test_region_companies_are_still_deduped():
    def ask(system, user, label):
        return {"companies": [_co("Same", "Lagos, Nigeria")]}

    found, _ = dr.discover_in_rounds(
        "M", "Manufacturer", ask_json=ask, target=50,
        dedupe_key=_key, already_found=[_co("Same", "Lagos, Nigeria")],
    )
    assert [c["brand"] for c in found].count("Same") == 1
