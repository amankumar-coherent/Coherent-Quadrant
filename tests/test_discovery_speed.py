"""Discovery batch size and escalation threshold are tunable per run.

A round costs one paced query whether it returns 10 names or 20, so the ask
size is the cheapest lever on a query-bound run. The escalation threshold is
the other: the broad question runs dry long before the market does, and the
country tier is where the long tail is.

Both are bounded — a runaway value makes a run worse, not faster.
"""
from __future__ import annotations

import importlib

import pytest

from vendor_intel.pipeline import discovery_rounds as dr


def _reload(batch: str | None = None, empty: str | None = None):
    import os

    for key, value in (("DISCOVER_BATCH", batch),
                       ("DISCOVER_EMPTY_BEFORE_ESCALATE", empty)):
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    importlib.reload(dr)
    return dr.DEFAULT_BATCH, dr.EMPTY_ROUNDS_BEFORE_STOP


@pytest.fixture(autouse=True)
def _restore():
    yield
    _reload(None, None)


def test_the_defaults_are_unchanged():
    """A run that sets nothing must behave exactly as before."""
    assert _reload(None, None) == (10, 3)


def test_the_batch_size_is_tunable():
    assert _reload("20", None)[0] == 20
    assert _reload("15", None)[0] == 15


def test_an_oversized_batch_is_refused():
    """Past 20 the reply truncates, and a truncated round yields FEWER
    usable companies than a smaller ask would have."""
    assert _reload("25", None)[0] == 10
    assert _reload("100", None)[0] == 10


def test_an_undersized_batch_is_refused():
    assert _reload("1", None)[0] == 10
    assert _reload("0", None)[0] == 10


def test_a_malformed_batch_falls_back():
    assert _reload("abc", None)[0] == 10
    assert _reload("", None)[0] == 10


def test_the_escalation_threshold_is_tunable():
    assert _reload(None, "1")[1] == 1


def test_an_out_of_range_threshold_is_refused():
    assert _reload(None, "0")[1] == 3
    assert _reload(None, "9")[1] == 3
    assert _reload(None, "xyz")[1] == 3


def test_the_round_prompt_asks_for_the_configured_number():
    batch, _ = _reload("20", None)
    _system, user = dr.build_round_prompt(
        "Test Market", "Manufacturer", excluded_names=[], batch=batch
    )
    assert "Give me 20 BRANDS" in user


def test_a_smaller_batch_still_renders_correctly():
    batch, _ = _reload("10", None)
    _system, user = dr.build_round_prompt(
        "Test Market", "Manufacturer", excluded_names=[], batch=batch
    )
    assert "Give me 10 BRANDS" in user
