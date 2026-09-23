"""Parameter detail must survive the ownership suffix on the display name.

The report's Company column reads "Hanwha Q CELLS Co., Ltd. (subsidiary of
Hanwha)"; scoring stored the plain legal name it actually asked about. Exact
matching missed 36 of 179 companies in Solar Rooftop, so their parameter
cells rendered as em-dashes beside a perfectly good Product Strength score —
which is what made the report look self-contradictory.
"""
from __future__ import annotations

from vendor_intel.pipeline.expand_quadrant_score import _detail_key, _lookup_detail

DETAIL = {"x": {"score": 93, "parameters": {"P1": {"score": 90, "evidence": []}}}}


def test_a_subsidiary_suffix_is_ignored():
    assert _detail_key("Hanwha Q CELLS Co., Ltd. (subsidiary of Hanwha)") == (
        "hanwha q cells co., ltd."
    )


def test_an_acquired_suffix_is_ignored():
    assert _detail_key("Yellow Door Energy Limited (acquired by Actis)") == (
        "yellow door energy limited"
    )


def test_a_plain_name_is_unchanged():
    assert _detail_key("Plain Co Ltd") == "plain co ltd"


def test_a_genuine_parenthetical_name_is_kept():
    """Only ownership tails are stripped — not every bracket."""
    assert _detail_key("ACME (Holdings) Inc.") == "acme (holdings) inc."


def test_the_suffixed_row_finds_its_detail():
    index = {"hanwha q cells co., ltd.": DETAIL}
    got = _lookup_detail(index, "Hanwha Q CELLS Co., Ltd. (subsidiary of Hanwha)", "")
    assert got["x"]["score"] == 93


def test_the_brand_is_tried_when_the_company_misses():
    index = {"qcells": DETAIL}
    assert _lookup_detail(index, "Some Other Name", "QCELLS")["x"]["score"] == 93


def test_a_genuine_miss_returns_empty_not_none():
    """Callers index into the result, so it must always be a dict."""
    assert _lookup_detail({}, "Nobody", "Nobody") == {}


def test_lookup_is_case_insensitive():
    index = {"acme corp": DETAIL}
    assert _lookup_detail(index, "ACME CORP", "")["x"]["score"] == 93
