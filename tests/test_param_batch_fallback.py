"""Batched parameter scoring falls back to one query per company.

Batching is ~3x cheaper and, measured against live AI Mode, keeps 100% of
the per-parameter evidence at size 3. What it does NOT survive is a failed
query: one CAPTCHA loses the whole batch, and nothing above this function
retries, so those companies would ship unscored. The fallback re-asks only
the companies a batch missed.
"""
from __future__ import annotations

import importlib
import os

import pytest

from vendor_intel.quadrant import ai_mode_scorer as S

X = ["Sensor Accuracy", "Point Cloud Density"]
Y = ["Market Reach"]
NAMES = ["Alpha Ltd", "Beta Ltd", "Gamma Ltd"]


def _answer(companies: list[str], params: list[str]) -> str:
    """A reply shaped like the prose the model actually returns.

    answer_body() strips lines echoed from the prompt, so a heading that
    is ONLY the parameter name disappears and takes its section with it.
    Real replies add commentary after the name; these do the same so the
    parser sees what it would see live.
    """
    out = []
    for i, c in enumerate(companies):
        out.append(f"{chr(65 + i)}. {c}")
        for j, p in enumerate(params, 1):
            out.append(f"{j}. {p} assessment for {c}")
            out.append(
                f"Evidence: {c} ships {p} at scale, per its 2025 datasheet."
            )
            out.append(f"Score: {70 + j} / 100")
        out.append("Composite Score: 75 / 100")
    return "\n".join(out)


# --- the batch size knob ---------------------------------------------------


def _reload_with(value: str | None) -> int:
    if value is None:
        os.environ.pop("AI_MODE_PARAM_BATCH", None)
    else:
        os.environ["AI_MODE_PARAM_BATCH"] = value
    importlib.reload(S)
    return S.DEFAULT_PARAM_BATCH


def test_the_batch_size_is_configurable():
    assert _reload_with("3") == 3


def test_the_default_stays_one():
    """An existing run's behaviour must not change underneath it."""
    assert _reload_with(None) == 1


def test_five_is_allowed():
    """Five kept 100% evidence coverage once the batch prompt carried
    the worked example and per-company HQ/description."""
    assert _reload_with("5") == 5


def test_six_is_allowed():
    assert _reload_with("6") == 6


def test_above_six_is_refused():
    """Measured live at 10: the model collapses into one summary paragraph
    with no per-company blocks at all."""
    assert _reload_with("7") == 1
    assert _reload_with("10") == 1


def test_a_malformed_value_falls_back_to_one():
    assert _reload_with("abc") == 1
    assert _reload_with("0") == 1
    assert _reload_with("-2") == 1


@pytest.fixture(autouse=True)
def _restore_default():
    yield
    _reload_with(None)


# --- the fallback ----------------------------------------------------------


def test_a_whole_batch_success_needs_no_retry():
    calls = []

    def ask(query: str) -> str:
        calls.append(query)
        params = X if "Sensor Accuracy" in query else Y
        return _answer(NAMES, params)

    got = S.score_parameters_for_companies(
        NAMES, x_parameters=X, y_parameters=Y, ask=ask, batch=3
    )
    assert len(got) == 3
    assert len(calls) == 2, "one query per axis, no per-company retries"
    assert all(got[n]["x"]["parameters"] for n in NAMES)


def test_a_failed_batch_retries_each_company_singly():
    """The failure that matters: one CAPTCHA must not lose three companies."""
    calls = []

    def ask(query: str) -> str:
        calls.append(query)
        # The batched form names every company; the single form names one.
        if sum(n in query for n in NAMES) > 1:
            raise RuntimeError("CAPTCHA")
        params = X if "Sensor Accuracy" in query else Y
        one = next(n for n in NAMES if n in query)
        return _answer([one], params)

    got = S.score_parameters_for_companies(
        NAMES, x_parameters=X, y_parameters=Y, ask=ask, batch=3
    )
    assert len(got) == 3, "every company recovered"
    for n in NAMES:
        assert got[n]["x"]["parameters"], f"{n} lost its X parameters"
        assert got[n]["y"]["parameters"], f"{n} lost its Y parameters"


def test_only_the_missing_companies_are_retried():
    """A partial batch must not re-ask for companies it already returned."""
    single_asks = []

    def ask(query: str) -> str:
        named = [n for n in NAMES if n in query]
        if len(named) > 1:
            # The batch answers for the first two only.
            params = X if "Sensor Accuracy" in query else Y
            return _answer(NAMES[:2], params)
        single_asks.append(named[0])
        params = X if "Sensor Accuracy" in query else Y
        return _answer(named, params)

    got = S.score_parameters_for_companies(
        NAMES, x_parameters=X, y_parameters=Y, ask=ask, batch=3
    )
    assert len(got) == 3
    assert set(single_asks) == {"Gamma Ltd"}, f"re-asked too much: {single_asks}"


def test_a_company_that_fails_even_singly_is_left_unscored():
    """Not every failure is recoverable; the rest must still come back."""

    def ask(query: str) -> str:
        if "Beta Ltd" in query and sum(n in query for n in NAMES) == 1:
            raise RuntimeError("still blocked")
        named = [n for n in NAMES if n in query]
        if len(named) > 1:
            raise RuntimeError("CAPTCHA")
        params = X if "Sensor Accuracy" in query else Y
        return _answer(named, params)

    got = S.score_parameters_for_companies(
        NAMES, x_parameters=X, y_parameters=Y, ask=ask, batch=3
    )
    assert got["Alpha Ltd"]["x"]["parameters"]
    assert got["Gamma Ltd"]["x"]["parameters"]
    assert not got["Beta Ltd"]["x"]["parameters"], "no fabricated score"


def test_batch_one_does_not_trigger_the_fallback_path():
    """At size 1 there is no batch to fall back FROM; a failure is just a
    failure and must not produce a duplicate query."""
    calls = []

    def ask(query: str) -> str:
        calls.append(query)
        raise RuntimeError("CAPTCHA")

    got = S.score_parameters_for_companies(
        ["Alpha Ltd"], x_parameters=X, y_parameters=Y, ask=ask, batch=1
    )
    assert len(calls) == 2, "one per axis, not retried"
    assert not got["Alpha Ltd"]["x"]["parameters"]


def test_the_evidence_survives_a_fallback():
    """The point of all this: the recovered company keeps its evidence."""

    def ask(query: str) -> str:
        named = [n for n in NAMES if n in query]
        if len(named) > 1:
            raise RuntimeError("CAPTCHA")
        params = X if "Sensor Accuracy" in query else Y
        return _answer(named, params)

    got = S.score_parameters_for_companies(
        NAMES, x_parameters=X, y_parameters=Y, ask=ask, batch=3
    )
    for n in NAMES:
        for pv in got[n]["x"]["parameters"].values():
            assert pv["evidence"], "recovered rows must keep their evidence"
            assert pv["evidence"][0]["claim"].strip()


# --- echo stripping --------------------------------------------------------
#
# answer_body() drops lines that repeat the prompt. A batched prompt lists
# the companies as "A. Alpha Ltd", and the model answers under that same
# heading — so stripping it destroyed the boundaries the batch parser splits
# on, and every batched reply parsed as zero companies.


def test_a_lettered_company_heading_survives_echo_stripping():
    prompt = S.build_batch_parameter_query(NAMES, "Product Strength", X)
    body = S.answer_body(_answer(NAMES, X), prompt)
    for i, name in enumerate(NAMES):
        assert f"{chr(65 + i)}. {name}" in body, f"{name} heading was stripped"


def test_a_batched_reply_parses_every_company():
    prompt = S.build_batch_parameter_query(NAMES, "Product Strength", X)
    got = S.parse_batch_parameter_scores(_answer(NAMES, X), NAMES, X, prompt)
    assert set(got) == set(NAMES)
    for name in NAMES:
        assert len(got[name]["parameters"]) == len(X)


def test_ordinary_prompt_echo_is_still_removed():
    """The fix must not stop the echo-stripping it lives inside."""
    prompt = "Score this company.\nUse only real sources."
    answer = "Score this company.\nUse only real sources.\nEvidence: it ships."
    body = S.answer_body(answer, prompt)
    assert "Use only real sources." not in body
    assert "Evidence: it ships." in body
