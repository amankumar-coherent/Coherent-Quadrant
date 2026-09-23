"""X/Y scoring via Google AI Mode.

The LLM still generates the market-specific parameters; AI Mode produces the
score, asked as one consolidated question per axis.
"""
from __future__ import annotations

import pytest

from vendor_intel.quadrant import ai_mode_scorer as ams

X_PARAMS = [
    "Process/Node Leadership",
    "Product Portfolio Breadth",
    "Design IP Strength",
    "Manufacturing Capacity/Yield",
    "Quality/Compliance",
]
Y_PARAMS = [
    "Geographic & End-Market Reach",
    "Customer / Ecosystem Partnerships",
    "Financial Strength & CapEx Capacity",
    "Technology & Product Roadmap",
    "Capacity Expansion & Business Growth",
]


# --- axis naming -----------------------------------------------------------


def test_axis_names_are_fixed():
    """X is always Product Strength, Y always Business Strength — only the
    parameters underneath change per market."""
    assert ams.AXIS_X_LABEL == "Product Strength"
    assert ams.AXIS_Y_LABEL == "Business Strength"


def test_codebase_axis_labels_match():
    from vendor_intel.quadrant.criteria_catalog import AXIS_Y

    assert AXIS_Y == "Business Strength"


# --- query construction ----------------------------------------------------


def test_query_matches_the_reference_wording():
    q = ams.build_score_query("ASML Holding", "Product Strength", X_PARAMS)
    assert "single, consolidated Product Strength score out of 100" in q
    assert "ASML Holding" in q
    assert "unweighted average" in q
    for p in X_PARAMS:
        assert p in q


def test_query_uses_market_specific_parameters():
    a = ams.build_score_query("Co", "Product Strength", ["Alpha Param"])
    b = ams.build_score_query("Co", "Product Strength", ["Beta Param"])
    assert "Alpha Param" in a and "Beta Param" not in a
    assert "Beta Param" in b


def test_query_states_the_parameter_count():
    q = ams.build_score_query("Co", "Business Strength", Y_PARAMS)
    assert "these 5 parameters" in q


# --- answer parsing --------------------------------------------------------


def test_parses_reference_answer_shapes():
    """Both observed AI Mode reply forms."""
    assert ams.parse_score(
        "The single, consolidated Business Strength Score for ASML Holding "
        "across the specified parameters is 92 out of 100."
    ) == 92
    assert ams.parse_score(
        "The single, consolidated Product Strength Score for ASML Holding "
        "across the specified parameters is **89 out of 100**."
    ) == 89


def test_parses_bare_and_slash_forms():
    # A reply that is ONLY a number is the format the prompt asks for and the
    # one AI Mode most often returns, so it must parse. The pattern is
    # anchored to the whole answer, so a digit inside prose still needs one of
    # the "out of 100" / "score" / "**n**" anchors.
    assert ams.parse_score("89") == 89
    assert ams.parse_score("Score: 74") == 74
    assert ams.parse_score("It scores 81/100 overall.") == 81


def test_a_loose_number_in_prose_still_needs_an_anchor():
    """Anchoring is what keeps "founded in 1987" from becoming a score."""
    assert ams.parse_score("The company was founded in 87 by two engineers.") is None


def test_rejects_out_of_range_and_missing():
    assert ams.parse_score("") is None
    assert ams.parse_score("I cannot provide a score for this company.") is None
    assert ams.parse_score("120 out of 100") is None


def test_never_guesses_a_score():
    """A None result makes the caller fall back to the LLM scorer rather than
    inventing a number."""
    assert ams.parse_score("no response available for this search") is None


# --- scoring calls ---------------------------------------------------------


def test_score_axis_uses_injected_ask():
    seen = {}

    def _ask(prompt, **kw):
        seen["prompt"] = prompt
        return "The score is 77 out of 100."

    assert ams.score_axis("ASML", "Product Strength", X_PARAMS, ask=_ask) == 77
    assert "Product Strength" in seen["prompt"]


def test_score_company_asks_both_axes():
    calls = []

    def _ask(prompt, **kw):
        calls.append(prompt)
        return "88 out of 100"

    x, y = ams.score_company("ASML", x_parameters=X_PARAMS, y_parameters=Y_PARAMS, ask=_ask)
    assert (x, y) == (88, 88)
    assert len(calls) == 2
    assert "Product Strength" in calls[0]
    assert "Business Strength" in calls[1]


def test_failure_returns_none_not_zero():
    """A CAPTCHA must not become a score of 0."""

    def _boom(prompt, **kw):
        raise RuntimeError("CAPTCHA")

    assert ams.score_axis("Co", "Product Strength", X_PARAMS, ask=_boom) is None


def test_empty_inputs_are_safe():
    assert ams.score_axis("", "Product Strength", X_PARAMS, ask=lambda p, **k: "90") is None
    assert ams.score_axis("Co", "Product Strength", [], ask=lambda p, **k: "90") is None


# --- enable switch ---------------------------------------------------------


def test_disabled_when_ai_mode_off(monkeypatch):
    monkeypatch.setenv("GOOGLE_AI_MODE_ENABLED", "false")
    monkeypatch.delenv("EXPAND_XY_SCORER", raising=False)
    assert ams.enabled() is False


def test_enabled_when_ai_mode_on(monkeypatch):
    monkeypatch.setenv("GOOGLE_AI_MODE_ENABLED", "true")
    monkeypatch.delenv("EXPAND_XY_SCORER", raising=False)
    assert ams.enabled() is True


def test_no_llm_scorer_fallback_exists():
    """AI Mode is the only scorer; the old force-LLM switch is gone."""
    import inspect

    from vendor_intel.pipeline import expand_quadrant_score as eqs

    src = inspect.getsource(eqs)
    assert "score_company_features_async" not in src
    assert "EXPAND_XY_SCORER" not in src


def test_unavailable_leaves_row_unscored_not_zero():
    """A CAPTCHA is missing data, not a company with no strength. Writing 0
    would place it in the worst quadrant and pollute the landscape."""
    import inspect

    from vendor_intel.pipeline import expand_quadrant_score as eqs

    src = inspect.getsource(eqs.score_expand_rows)
    assert "left unscored for retry" in src
    assert '"reason": "ai_mode_unavailable"' in src


def test_scoring_is_serialized_for_ai_mode():
    """AI Mode is one browser, one query at a time — concurrency only raises
    the CAPTCHA rate."""
    import inspect

    from vendor_intel.pipeline import expand_quadrant_score as eqs

    assert "asyncio.Semaphore(1)" in inspect.getsource(eqs.score_expand_rows)
