"""--country X keeps every discovery round inside X, for ANY country --
not only the ones with a state list (India)."""
import pytest

from vendor_intel.pipeline import discovery_rounds as dr
from vendor_intel.pipeline.geo_rotation import states_for


def _prompts(country: str) -> list[str]:
    seen: list[str] = []

    def ask(system, user, label):
        seen.append(user)
        return {"companies": []}  # empty market -> exercises escalation too

    dr.discover_in_rounds("Smart Ring Market", "Brand / Marketer", ask_json=ask,
                          target=50, dedupe_key=str.lower, country=country)
    return seen


@pytest.mark.parametrize("country", ["india", "germany", "thailand"])
def test_every_round_is_constrained_to_the_country(country):
    prompts = _prompts(country)
    assert prompts
    assert all("HEADQUARTERED IN" in p and country in p for p in prompts)
    # never escalates to world regions / other countries
    assert not any(r in p for p in prompts for r in ("HEADQUARTERED IN Europe",
                                                      "HEADQUARTERED IN Latin America"))


def test_global_run_is_not_country_constrained_in_broad_rounds():
    first = _prompts("global")[0]
    assert "HEADQUARTERED IN" not in first


def test_country_names_starting_with_t_h_e_are_not_mangled():
    # lstrip("the ") used to turn "thailand" into "ailand"
    assert states_for("the india") == states_for("india")
