"""Resuming discovery must CONTINUE, not restart.

A run stopped mid-discovery (Ctrl+C, shutdown, CAPTCHA wall) saved 134
companies. Resuming restarted the rounds loop empty, re-asked Google for names
it already had, and then `mark_step_done` overwrote the 134 with the 20 the new
pass had reached. Observed live: the checkpoint went 134 -> 20.
"""
from __future__ import annotations

from vendor_intel.pipeline import chatgpt_expand as ce
from vendor_intel.pipeline import discovery_rounds as dr


def _key(name: str) -> str:
    return "".join(ch for ch in (name or "").lower() if ch.isalnum())


def _co(brand: str) -> dict:
    return {
        "brand": brand,
        "company": f"{brand} Ltd",
        "headquarters": "Tokyo, Japan",
        "verdict": "in_market",
        "why_related": "Makes product in this market.",
    }


def test_resume_starts_from_the_saved_companies():
    prior = [_co(f"Old{i}") for i in range(30)]

    def ask(system, user, label):
        return {"companies": [_co("New1")]}

    found, stats = dr.discover_in_rounds(
        "M", "Manufacturer", ask_json=ask, target=31,
        dedupe_key=_key, already_found=prior,
    )
    assert stats["resumed_with"] == 30
    assert len(found) == 31, "the 30 saved must still be there, plus the new one"
    assert {c["brand"] for c in found} >= {"Old0", "Old29", "New1"}


def test_resume_does_not_re_ask_for_saved_names():
    """The exclusion list must carry the resumed brands or the model just
    returns them again and every round scores zero new."""
    prior = [_co(f"Old{i}") for i in range(5)]
    seen: list[str] = []

    def ask(system, user, label):
        seen.append(user)
        return {"companies": [_co("Fresh")]}

    dr.discover_in_rounds(
        "M", "Manufacturer", ask_json=ask, target=6,
        dedupe_key=_key, already_found=prior,
    )
    assert "Old0" in seen[0] and "Old4" in seen[0]


def test_a_resumed_duplicate_is_not_counted_twice():
    prior = [_co("Toshiba")]

    def ask(system, user, label):
        return {"companies": [_co("Toshiba"), _co("Rohm")]}

    found, _ = dr.discover_in_rounds(
        "M", "Manufacturer", ask_json=ask, target=2,
        dedupe_key=_key, already_found=prior,
    )
    assert [c["brand"] for c in found].count("Toshiba") == 1
    assert len(found) == 2


def test_no_resume_data_behaves_exactly_as_before():
    def ask(system, user, label):
        return {"companies": [_co("A")]}

    found, stats = dr.discover_in_rounds(
        "M", "Manufacturer", ask_json=ask, target=1, dedupe_key=_key,
    )
    assert stats["resumed_with"] == 0
    assert len(found) == 1


# --- the checkpoint round-trip that actually lost the data -----------------


def test_seed_rows_survive_a_round_trip_through_the_checkpoint():
    """_as_seed_rows -> checkpoint -> _seed_rows_as_found must preserve the
    brand, or resume silently drops every saved company."""
    original = [
        {
            "brand": "Milton",
            "company": "Hamilton Housewares Pvt. Ltd.",
            "website": "https://milton.in",
            "headquarters": "Mumbai, India",
            "ownership": "Independent",
            "ownership_confidence": "high",
            "why_related": "Owns the Milton bottle brand.",
            "verdict": "in_market",
        }
    ]
    back = ce._seed_rows_as_found(ce._as_seed_rows(original))
    assert len(back) == 1
    assert back[0]["brand"] == "Milton"
    assert back[0]["company"] == "Hamilton Housewares Pvt. Ltd."
    assert back[0]["headquarters"] == "Mumbai, India"
    assert back[0]["ownership_confidence"] == "high"


def test_round_trip_keeps_the_dedupe_identity():
    """If the brand were lost, resume would re-add every company as new."""
    original = [{"brand": f"B{i}", "company": f"C{i}", "verdict": "in_market"} for i in range(20)]
    back = ce._seed_rows_as_found(ce._as_seed_rows(original))
    assert {c["brand"] for c in back} == {f"B{i}" for i in range(20)}


def test_an_older_checkpoint_without_brands_still_resumes():
    """Rows saved before the brand split have no brand_name; falling back to
    the company keeps them out of the re-discovery path."""
    back = ce._seed_rows_as_found([{"name": "Wolfspeed, Inc.", "Company": "Wolfspeed, Inc."}])
    assert back and back[0]["brand"] == "Wolfspeed, Inc."
