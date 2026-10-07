"""X = Product Strength, Y = Business Strength — fixed for EVERY market.
Only the 5 parameters under each axis are market-specific.
"""
from __future__ import annotations

import os

from vendor_intel.quadrant.axis_define import (
    AXIS_X_FIXED,
    AXIS_Y_FIXED,
    PARAMS_PER_AXIS,
    define_market_axes,
)


def _catalog(axis_x: str, axis_y: str) -> dict:
    return {
        "axis_x": axis_x,
        "axis_y": axis_y,
        "x": [f"X param {i}" for i in range(5)],
        "y": [f"Y param {i}" for i in range(5)],
    }


def test_axis_names_are_the_fixed_pair():
    assert AXIS_X_FIXED == "Product Strength"
    assert AXIS_Y_FIXED == "Business Strength"
    assert PARAMS_PER_AXIS == 5


class _FakeLLM:
    """Records each axis request; answers with the queued replies in turn."""

    available = True

    def __init__(self, *replies):
        self.replies, self.payloads = list(replies), []

    def complete_json(self, system, user, **_kw):
        import json as _json

        self.payloads.append(_json.loads(user))
        return self.replies.pop(0)


def _reply(n_x=5, n_y=5, tag="A"):
    x = [f"{tag} product {i}" for i in range(n_x)]
    y = [f"{tag} business {i}" for i in range(n_y)]
    return {"x": x, "y": y, "x_definitions": {p: f"{p} means ..." for p in x},
            "y_definitions": {p: f"{p} means ..." for p in y}, "reason": "fits"}


def test_llm_gets_the_market_not_a_sector_catalog(monkeypatch):
    """The parameters used to be refined from a sector catalog picked by a
    keyword map of market names; the LLM now sees only the market."""
    monkeypatch.setenv("MARKET_SCOPE", "Software that automates supplier invoices.")
    llm = _FakeLLM(_reply())
    out = define_market_axes("Any Market", _catalog("Packaging Solution Capability", "Reach"), client=llm)
    sent = llm.payloads[0]
    assert "baseline" not in sent and "industry_group" not in sent and "industry_category" not in sent
    assert sent["market_definition"] == "Software that automates supplier invoices."
    assert out["x"] == _reply()["x"] and out["axis_definition_method"] == "llm"
    assert (out["axis_x"], out["axis_y"]) == (AXIS_X_FIXED, AXIS_Y_FIXED)
    assert len(out["x"]) == len(out["y"]) == PARAMS_PER_AXIS


def test_a_short_llm_answer_is_retried_not_padded_from_a_catalog():
    llm = _FakeLLM(_reply(n_x=3), _reply(tag="B"))
    out = define_market_axes("Any Market", _catalog("x", "y"), client=llm)
    assert len(llm.payloads) == 2
    assert out["x"] == _reply(tag="B")["x"]
    assert not any(p.startswith("X param") for p in out["x"] + out["y"])


def test_llm_prompt_states_the_axes_are_fixed():
    """The prompt must not invite the model to invent axis titles."""
    from vendor_intel.quadrant.axis_define import _SYSTEM

    flat = " ".join(_SYSTEM.split())
    assert "axis TITLES are FIXED" in flat
    assert '"Product Strength"' in flat and '"Business Strength"' in flat
    assert "Exactly 5 on X and 5 on Y" in flat
    # It must no longer ask for market-specific titles.
    assert "2-6 word X axis title" not in flat


def test_parameters_remain_market_specific():
    """Fixing the NAMES must not fix the parameters -- those stay per-market."""
    a = define_market_axes("Market A", {}, client=_FakeLLM(_reply(tag="Wafer")))
    b = define_market_axes("Market B", {}, client=_FakeLLM(_reply(tag="Film")))
    assert a["x"] != b["x"]
    assert a["axis_x"] == b["axis_x"] == AXIS_X_FIXED


# --- the LLM path is mandatory --------------------------------------------


def test_llm_axis_parameters_are_required_by_default(monkeypatch):
    """Catalog parameters are GENERIC. Falling back to them silently gave a
    market parameters never tuned to it — measured live: 3 of 7 markets ran
    on catalog values with no error surfaced."""
    import pytest

    from vendor_intel.quadrant.axis_define import _axis_llm_required

    monkeypatch.delenv("EXPAND_MARKET_AXIS_REQUIRE_LLM", raising=False)
    assert _axis_llm_required() is True

    monkeypatch.setenv("EXPAND_MARKET_AXIS_LLM", "0")
    with pytest.raises(RuntimeError, match="required|off"):
        define_market_axes("Test Market", _catalog("W", "W"))


def test_catalog_fallback_cannot_be_opted_out(monkeypatch):
    """The old opt-out env var no longer lets a market run on catalog values."""
    import pytest

    monkeypatch.setenv("EXPAND_MARKET_AXIS_REQUIRE_LLM", "0")
    monkeypatch.setenv("EXPAND_MARKET_AXIS_LLM", "0")
    with pytest.raises(RuntimeError):
        define_market_axes("Test Market", _catalog("W", "W"))


def test_llm_call_is_retried_before_failing():
    """One transient API blip must not silently downgrade a market."""
    from vendor_intel.quadrant.axis_define import _AXIS_LLM_RETRIES

    assert _AXIS_LLM_RETRIES >= 3
