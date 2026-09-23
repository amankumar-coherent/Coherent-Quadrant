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


def test_catalog_path_overrides_a_wrong_yaml_axis_name(monkeypatch):
    """Regression: when the LLM call failed, the YAML name leaked through and
    markets were labelled "Packaging Solution Capability" or "Asset &
    Operating Capability" instead of Product / Business Strength."""
    monkeypatch.setenv("EXPAND_MARKET_AXIS_LLM", "0")
    monkeypatch.setenv("EXPAND_MARKET_AXIS_REQUIRE_LLM", "0")
    out = define_market_axes(
        "Global Flexible Packaging Market",
        _catalog("Packaging Solution Capability", "Commercial Reach"),
    )
    assert out["axis_x"] == AXIS_X_FIXED
    assert out["axis_y"] == AXIS_Y_FIXED
    assert out["axis_definition_method"] == "catalog"


def test_exactly_five_parameters_per_axis(monkeypatch):
    monkeypatch.setenv("EXPAND_MARKET_AXIS_LLM", "0")
    monkeypatch.setenv("EXPAND_MARKET_AXIS_REQUIRE_LLM", "0")
    out = define_market_axes("Any Market", _catalog("Whatever", "Whatever"))
    assert len(out["x"]) == PARAMS_PER_AXIS
    assert len(out["y"]) == PARAMS_PER_AXIS


def test_llm_prompt_states_the_axes_are_fixed():
    """The prompt must not invite the model to invent axis titles."""
    from vendor_intel.quadrant.axis_define import _SYSTEM

    flat = " ".join(_SYSTEM.split())
    assert "axis TITLES are FIXED" in flat
    assert '"Product Strength"' in flat and '"Business Strength"' in flat
    assert "Exactly 5 on X and 5 on Y" in flat
    # It must no longer ask for market-specific titles.
    assert "2-6 word X axis title" not in flat


def test_parameters_remain_market_specific(monkeypatch):
    """Fixing the NAMES must not fix the parameters — those stay per-market."""
    monkeypatch.setenv("EXPAND_MARKET_AXIS_LLM", "0")
    monkeypatch.setenv("EXPAND_MARKET_AXIS_REQUIRE_LLM", "0")
    a = define_market_axes("Market A", _catalog("x", "y") | {"x": ["Wafer Yield"] * 5})
    b = define_market_axes("Market B", _catalog("x", "y") | {"x": ["Barrier Film"] * 5})
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


def test_requirement_can_be_opted_out(monkeypatch):
    monkeypatch.setenv("EXPAND_MARKET_AXIS_REQUIRE_LLM", "0")
    monkeypatch.setenv("EXPAND_MARKET_AXIS_LLM", "0")
    out = define_market_axes("Test Market", _catalog("W", "W"))
    assert out["axis_definition_method"] == "catalog"
    # Even on the fallback, the axis NAMES stay fixed.
    assert out["axis_x"] == AXIS_X_FIXED


def test_llm_call_is_retried_before_failing():
    """One transient API blip must not silently downgrade a market."""
    from vendor_intel.quadrant.axis_define import _AXIS_LLM_RETRIES

    assert _AXIS_LLM_RETRIES >= 3
