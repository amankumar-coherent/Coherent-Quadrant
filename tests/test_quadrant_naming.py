"""Quadrant and axis naming: the capability scale, not a value judgement.

Both axes are read Emerging -> Best-in-class, so a quadrant states what a
company has demonstrated rather than ranking it. The names live in
quadrant_language.py, so every market — including ones run later — picks them up without a code change.
"""
from __future__ import annotations

from vendor_intel.quadrant import html_report as H
from vendor_intel.quadrant.quadrant_language import (
    AXIS_X_TITLE,
    AXIS_Y_TITLE,
    SCALE_HIGH,
    SCALE_LOW,
    axis_scale_label,
    build_quadrant_explain,
    quadrant_label,
    quadrant_position,
    quadrant_title,
)


def test_the_scale_runs_emerging_to_best_in_class():
    assert SCALE_LOW == "Emerging"
    assert SCALE_HIGH == "Best-in-class"


def test_the_axis_titles_are_capability_not_strength():
    assert AXIS_X_TITLE == "Product Capability"
    assert AXIS_Y_TITLE == "Business Capability"


def test_the_axis_label_names_its_scale():
    assert axis_scale_label("x") == "Product Capability (Emerging → Best-in-class)"
    assert axis_scale_label("y") == "Business Capability (Emerging → Best-in-class)"


def test_every_quadrant_has_its_presentation_title():
    assert quadrant_title("Leaders") == "Integrated Market Leaders"
    assert quadrant_title("Challengers") == "Scale-Driven Challengers"
    assert quadrant_title("Trailblazers") == "Innovation-Driven Trailblazers"
    assert quadrant_title("Emerging Players") == "Foundation-Building Evolving"


def test_the_capability_pair_matches_the_quadrant_position():
    """The wording is derived from where the quadrant sits, so it cannot
    drift out of step with where a company is plotted."""
    assert quadrant_position("Leaders") == (
        "Best-in-class Product, Best-in-class Business"
    )
    assert quadrant_position("Challengers") == (
        "Emerging Product, Best-in-class Business"
    )
    assert quadrant_position("Trailblazers") == (
        "Best-in-class Product, Emerging Business"
    )
    assert quadrant_position("Emerging Players") == "Emerging Product, Emerging Business"


def test_the_positioning_line_uses_the_scale():
    explain = dict((q, sub) for q, sub, _ in build_quadrant_explain("X Cap", "Y Cap"))
    assert explain["Leaders"] == "Best-in-class X Cap, Best-in-class Y Cap"
    assert explain["Challengers"] == "Emerging X Cap, Best-in-class Y Cap"
    assert explain["Trailblazers"] == "Best-in-class X Cap, Emerging Y Cap"
    assert explain["Emerging Players"] == "Emerging X Cap, Emerging Y Cap"


def test_the_old_strength_wording_is_gone():
    for _q, sub, _b in build_quadrant_explain("X Cap", "Y Cap"):
        assert "Strong " not in sub
        assert "Developing " not in sub
        assert "Focused " not in sub


# --- how it reaches a report ----------------------------------------------


def _payload() -> dict:
    return {
        "market": "Test Market",
        "criteria": {
            "x_axis": ["P1"],
            "y_axis": ["Q1"],
            "axis_labels": {"x": "Product Strength", "y": "Business Strength"},
        },
        "brands": [
            {
                "brand": f"B{i}", "company": f"C{i}", "hq_location": "Austin, Texas, USA",
                "execution": 90 - i, "innovation": 80 - i, "overall": 85 - i,
                "on_chart": i < 20,
            }
            for i in range(30)
        ],
    }


def test_the_generic_axis_default_is_restated_as_capability():
    x, y = H._axis_labels(_payload())
    assert (x, y) == (AXIS_X_TITLE, AXIS_Y_TITLE)


def test_a_market_specific_axis_title_is_overridden():
    """Axis names are fixed for EVERY market — a market-specific title in a
    saved payload is replaced by Product / Business Capability; only the
    parameters under each axis vary by market."""
    payload = _payload()
    payload["criteria"]["axis_labels"] = {
        "x": "LNG Asset & Operations Strength",
        "y": "Commercial & Portfolio Scale",
    }
    assert H._axis_labels(payload) == (AXIS_X_TITLE, AXIS_Y_TITLE)


def test_the_report_shows_the_presentation_titles():
    html = H.render_quadrant_html(_payload())
    for title in (
        "Integrated Market Leaders",
        "Scale-Driven Challengers",
        "Innovation-Driven Trailblazers",
        "Foundation-Building Evolving",
    ):
        assert title in html


def test_the_chart_axes_carry_the_scale():
    html = H.render_quadrant_html(_payload())
    assert "EMERGING → BEST-IN-CLASS" in html
    assert "PRODUCT CAPABILITY" in html
    assert "BUSINESS CAPABILITY" in html


def test_the_short_chart_labels_stay_short():
    """The plot corners still read Leaders/Challengers/... — the long titles
    would not fit and the two must stay recognisably the same quadrant."""
    html = H.render_quadrant_html(_payload())
    assert '<div class="cq-quad-label cq-tr">Leaders</div>' in html
    assert '<div class="cq-quad-label cq-br">Trailblazers</div>' in html


def test_the_positioning_lines_follow_the_scale_constants():
    """The scale word is defined once. Hardcoding it in the four templates
    left them stale the first time the high end was reworded."""
    import inspect

    from vendor_intel.quadrant import quadrant_language as QL

    src = inspect.getsource(QL)
    templates = src.split("_TEMPLATES", 1)[1].split("FALLBACK_X", 1)[0]
    assert "{hi}" in templates and "{lo}" in templates
    assert '"Proven {x}' not in templates
    assert '"Emerging {x}, Emerging {y}"' not in templates


def test_the_stored_key_is_renamed_only_for_the_reader():
    """Checkpoints, Excel files and scoring all hold "Emerging Players". The
    rename is a display mapping, so that stored data is not orphaned."""
    assert quadrant_label("Emerging Players") == "Evolving Players"
    for quad in ("Leaders", "Challengers", "Trailblazers"):
        assert quadrant_label(quad) == quad


def test_an_unknown_quadrant_passes_through():
    assert quadrant_label("Something Else") == "Something Else"
