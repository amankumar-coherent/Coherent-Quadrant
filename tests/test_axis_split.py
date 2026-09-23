"""The axis prompt must state what separates Product from Business.

Without it the model put "Technology Roadmap & Innovation Pipeline" and
"Market Expansion & Service Network" on the BUSINESS axis for a software
market. Both are product/strategy parameters, and the second has no
countable public evidence at all — so Business Strength scores came back as
vague prose while Product Strength stayed specific.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from vendor_intel.quadrant import axis_define as A

SRC = Path(A.__file__).read_text(encoding="utf-8")


def test_the_prompt_defines_what_x_means():
    assert "X = PRODUCT: what the company BUILDS" in SRC


def test_the_prompt_defines_what_y_means():
    assert "Y = BUSINESS: how the company SELLS and OPERATES" in SRC


def test_roadmap_and_innovation_are_pinned_to_x():
    """The exact drift observed live, named so it cannot recur silently."""
    assert '"Technology Roadmap", "Innovation Pipeline"' in SRC
    assert "are X, never Y" in SRC


def test_y_parameters_must_have_countable_evidence():
    assert "answerable with a COMMERCIAL fact" in SRC
    for token in ("contract value", "revenue", "headcount", "market share"):
        assert token in SRC, f"the Y rule never mentions {token!r}"


def test_the_prompt_rejects_unfalsifiable_parameters():
    """A parameter whose only evidence is "strong presence" is the wrong
    parameter, not a scoring problem to fix later."""
    # The phrase wraps across source lines, so match on the flattened text.
    flat = " ".join(SRC.split())
    assert 'a vague phrase like "strong presence"' in flat
    assert "it is the wrong parameter" in flat


def test_the_axis_titles_are_still_fixed():
    assert A.AXIS_X_FIXED == "Product Strength"
    assert A.AXIS_Y_FIXED == "Business Strength"


@pytest.mark.parametrize("word", ["Roadmap", "Innovation", "R&D", "Technology"])
def test_product_words_are_named_in_the_x_rule(word: str):
    """These are the words that drifted; the rule must mention them."""
    block = SRC.split("WHAT BELONGS ON EACH AXIS", 1)[1][:1400]
    assert word in block
