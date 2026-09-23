"""Market Classification shows the REASONING behind B2B/B2C and the player
type, not just the label -- a reader otherwise has to take "Solution
Provider" on faith with no explanation of why service providers or
manufacturers were not compared instead.
"""
from __future__ import annotations

from vendor_intel.quadrant import html_report as H

X = ["P1", "P2"]
Y = ["Q1"]


def _payload(**relevance_extra) -> dict:
    return {
        "market": "Advanced Seismic Data Processing Solutions Market",
        "criteria": {
            "x_axis": X, "y_axis": Y,
            "axis_labels": {"x": "Product Strength", "y": "Business Strength"},
            "relevance": {
                "market_type": "B2B",
                "market_definition": "Software for processing seismic data.",
                "keep_roles": ["Solution Provider"],
                **relevance_extra,
            },
        },
        "brands": [{
            "brand": "B0", "company": "C0", "hq_location": "Houston, USA",
            "commercial_role": "Solution Provider",
            "execution": 90, "innovation": 85, "overall": 88,
            "quadrant": "Leaders", "on_chart": True,
        }],
    }


def test_the_market_type_reason_is_shown():
    doc = H.render_quadrant_html(_payload(
        market_type_reason="The primary buyers are oil and gas companies "
                            "and geophysical services firms.",
    ))
    assert "primary buyers are oil and gas companies" in doc


def test_the_player_type_reason_is_shown():
    doc = H.render_quadrant_html(_payload(
        player_type_reason="Solution Provider was chosen because the "
                            "competitive landscape is driven by software "
                            "platforms rather than service delivery.",
    ))
    assert "driven by software platforms" in doc


def test_no_reason_means_no_extra_line():
    """A market whose analysis genuinely gave no reason must not render an
    empty explanatory line."""
    doc = H.render_quadrant_html(_payload())
    i = doc.index("Market Classification")
    end = doc.index("</div>\n</div>\n", i) if "</div>\n</div>\n" in doc[i:] else len(doc)
    # Neither reason key was set, so neither reason string can appear.
    assert "was chosen because" not in doc[i:i + 1500]


def test_both_reasons_can_appear_together():
    doc = H.render_quadrant_html(_payload(
        market_type_reason="Buyers are enterprises, not consumers.",
        player_type_reason="Software vendors define the competitive set.",
    ))
    assert "Buyers are enterprises" in doc
    assert "Software vendors define" in doc


def test_the_reasons_sit_near_their_own_label():
    """The type reason belongs under Market Type; the player reason belongs
    under Provider Categories -- not swapped."""
    doc = H.render_quadrant_html(_payload(
        market_type_reason="TYPE-REASON-MARKER",
        player_type_reason="PLAYER-REASON-MARKER",
    ))
    type_i = doc.index("Market Type")
    player_i = doc.index("Provider Categories in this Market")
    type_reason_i = doc.index("TYPE-REASON-MARKER")
    player_reason_i = doc.index("PLAYER-REASON-MARKER")
    assert type_i < type_reason_i < player_i
    assert player_i < player_reason_i
