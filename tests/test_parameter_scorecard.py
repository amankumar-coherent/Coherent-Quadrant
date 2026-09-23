"""Per-parameter scores in the HTML, evidence only in the backend.

The split that matters: the backend record carries claims and source URLs so
a score can be audited, and the HTML view model is built to make rendering
them impossible rather than merely unlikely.
"""
from __future__ import annotations

import json

import pytest

from vendor_intel.quadrant import ai_mode_scorer as S
from vendor_intel.quadrant import html_report as H

X_PARAMS = ["Substrate Quality", "Device Performance", "Wafer Size"]
Y_PARAMS = ["Market Share", "Revenue Growth"]


def _page(reply: str, prompt: str) -> str:
    return f"AI Mode conversation: {prompt}\n{prompt}\n{reply}"


def _ask_factory(n_x: int = 3, n_y: int = 2):
    def ask(q: str) -> str:
        n = n_x if "Substrate Quality" in q else n_y
        payload = {
            "parameters": {
                str(i): {
                    "score": 70 + i * 5,
                    "claim": f"Evidence {i}",
                    "source": f"https://example.com/{i}",
                }
                for i in range(1, n + 1)
            }
        }
        return _page(json.dumps(payload), q)

    return ask


# --- backend: score + evidence at every level ------------------------------


def test_every_parameter_stores_a_score_and_its_evidence():
    got = S.score_company_detailed(
        "Acme", x_parameters=X_PARAMS, y_parameters=Y_PARAMS, ask=_ask_factory()
    )
    params = got["x"]["parameters"]
    assert set(params) == set(X_PARAMS), "parameter names come from the market config"
    for name, entry in params.items():
        assert isinstance(entry["score"], int)
        assert entry["evidence"][0]["claim"]
        assert entry["evidence"][0]["source"].startswith("http")


def test_the_axis_score_carries_evidence_too():
    got = S.score_company_detailed(
        "Acme", x_parameters=X_PARAMS, y_parameters=Y_PARAMS, ask=_ask_factory()
    )
    assert got["x"]["score"] is not None
    assert len(got["x"]["evidence"]) == len(X_PARAMS)
    assert len(got["y"]["evidence"]) == len(Y_PARAMS)


def test_a_given_axis_score_is_preserved_not_recomputed():
    """Existing X/Y calculation must not change (requirement 19)."""
    got = S.score_company_detailed(
        "Acme", x_parameters=X_PARAMS, y_parameters=Y_PARAMS,
        ask=_ask_factory(), x_score=88, y_score=54,
    )
    assert got["x"]["score"] == 88
    assert got["y"]["score"] == 54
    assert got["overall_score"] == 71


def test_evidence_is_never_invented():
    """A reply with no claim stores no evidence — not a placeholder."""
    def ask(q):
        return _page('{"parameters":{"1":{"score":80}}}', q)

    got = S.score_company_detailed(
        "Acme", x_parameters=["Only"], y_parameters=["Only"], ask=ask
    )
    assert got["x"]["parameters"]["Only"]["evidence"] == []


def test_a_claim_without_a_source_is_still_kept():
    def ask(q):
        return _page('{"parameters":{"1":{"score":80,"claim":"Ships product X"}}}', q)

    got = S.score_company_detailed(
        "Acme", x_parameters=["Only"], y_parameters=["Only"], ask=ask
    )
    ev = got["x"]["parameters"]["Only"]["evidence"][0]
    assert ev["claim"] == "Ships product X"
    assert "source" not in ev, "no source is better than a fabricated one"


def test_an_unrateable_parameter_is_absent_not_zero():
    def ask(q):
        return _page('{"parameters":{"1":{"score":80,"claim":"c"},"2":{"score":null}}}', q)

    got = S.score_company_detailed(
        "Acme", x_parameters=["A", "B"], y_parameters=["A"], ask=ask
    )
    assert "A" in got["x"]["parameters"]
    assert "B" not in got["x"]["parameters"]


# --- the view model drops evidence, by construction ------------------------


def _backend_company() -> dict:
    return {
        "brand": "AcmeBrand",
        "company": "Acme Corp",
        "hq_location": "Austin, Texas, USA",
        "execution": 82,
        "innovation": 76,
        "overall": 79,
        "quadrant": "Leaders",
        "score_detail": S.score_company_detailed(
            "Acme", x_parameters=X_PARAMS, y_parameters=Y_PARAMS, ask=_ask_factory()
        ),
    }


def test_the_view_model_has_scores_but_no_evidence():
    view = H.build_view_model(_backend_company(), X_PARAMS, Y_PARAMS)
    assert view["x_score"] == 82 and view["y_score"] == 76
    assert view["x_parameters"]["Substrate Quality"] == 75
    blob = json.dumps(view)
    for banned in ("evidence", "claim", "source", "https://"):
        assert banned not in blob, f"{banned!r} must not survive into the view model"


def test_the_backend_object_still_has_its_evidence():
    """Dropping it from the view must not strip it from the record."""
    company = _backend_company()
    H.build_view_model(company, X_PARAMS, Y_PARAMS)
    assert company["score_detail"]["x"]["parameters"]["Substrate Quality"]["evidence"]


def test_an_evidence_key_in_the_view_model_is_a_hard_error():
    with pytest.raises(ValueError, match="must not reach the HTML"):
        H._assert_no_evidence({"company": "A", "evidence": ["leak"]})


# --- bubbles ---------------------------------------------------------------


@pytest.mark.parametrize(
    "score,cls",
    [(95, "cq-bub-5"), (85, "cq-bub-5"), (72, "cq-bub-4"),
     (55, "cq-bub-3"), (35, "cq-bub-2"), (10, "cq-bub-1")],
)
def test_bubble_size_follows_the_score(score, cls):
    assert cls in H._bubble(score)


def test_the_number_is_always_shown_next_to_the_bubble():
    assert ">73<" in H._bubble(73)


def test_the_bubble_never_alters_the_score():
    for n in (1, 42, 100):
        assert f">{n}<" in H._bubble(n)
