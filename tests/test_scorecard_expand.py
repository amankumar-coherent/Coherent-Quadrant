"""Each axis score opens its own parameter box, in the Top 20 table.

Twelve parameter columns forced a horizontal scroll that pushed the company
name off screen, so the parameters moved behind a per-axis disclosure and the
standalone scorecard was dropped entirely.

Built on <details>/<summary>, not JavaScript: the report is a standalone file
opened from disk, so native disclosure keeps it working with scripts off and
navigable by keyboard.
"""
from __future__ import annotations

import html as _html
import re

from vendor_intel.quadrant import html_report as H

X = ["Module Efficiency", "System Design", "Product Durability"]
Y = ["Geographic Coverage", "Customer Acquisition"]


def _payload(with_detail: bool = True) -> dict:
    brand = {
        "brand": "B0",
        "company": "Hanwha Q CELLS Co., Ltd.",
        "hq_location": "Seoul, South Korea",
        "execution": 93,
        "innovation": 79,
        "overall": 86,
        "quadrant": "Leaders",
        "on_chart": True,
    }
    if with_detail:
        brand["score_detail"] = {
            "x": {"score": 93, "parameters": {
                "Module Efficiency": {"score": 91, "evidence": [{"claim": "SECRET"}]},
                "System Design": {"score": 93, "evidence": []},
                "Product Durability": {"score": 94, "evidence": []},
            }},
            "y": {"score": 79, "parameters": {
                "Geographic Coverage": {"score": 78, "evidence": []},
                "Customer Acquisition": {"score": 80, "evidence": []},
            }},
        }
    return {
        "market": "T",
        "criteria": {"x_axis": X, "y_axis": Y,
                     "axis_labels": {"x": "Product Strength", "y": "Business Strength"}},
        "brands": [brand],
    }


def _scorecard(doc: str) -> str:
    """The Top 20 table — where the expandable scores now live."""
    return re.search(
        r"Top 20 Companies.*?<tbody>(.*?)</tbody>", doc, re.S
    ).group(1)


def test_the_standalone_scorecard_is_gone():
    """Its expandable discs moved into the Top 20 table, so a separate
    all-companies table was a second copy of the same control."""
    doc = H.render_quadrant_html(_payload())
    assert "Company Parameter Scorecard" not in doc


def test_each_axis_gets_its_own_toggle():
    body = _scorecard(H.render_quadrant_html(_payload()))
    assert body.count("<details") == 2, "Product and Business expand independently"


def test_the_disc_shows_the_axis_score():
    """The two axis discs (each wrapped in its own expand/collapse toggle)
    show their own axis score. Overall Score also renders as a same-style
    disc elsewhere in the row, but it has no parameter breakdown of its own
    so it is never wrapped in a <details> toggle -- scoping the search to
    inside <details> is what keeps this test about the axis discs only."""
    body = _scorecard(H.render_quadrant_html(_payload()))
    toggles = re.findall(r"<details.*?</details>", body, re.S)
    assert [re.search(r'cq-disc [^"]+">(\d+)<', t).group(1) for t in toggles] == \
        ["93", "79"]


def test_the_box_lists_that_axis_parameters_only():
    body = _scorecard(H.render_quadrant_html(_payload()))
    boxes = re.findall(r'<div class="cq-pp-box">(.*?)</div></details>', body, re.S)
    assert len(boxes) == 2
    assert "Module Efficiency" in boxes[0] and "Geographic Coverage" not in boxes[0]
    assert "Geographic Coverage" in boxes[1] and "Module Efficiency" not in boxes[1]


def test_every_parameter_and_score_is_listed():
    body = _scorecard(H.render_quadrant_html(_payload()))
    pairs = [
        (_html.unescape(a), b)
        for a, b in re.findall(
            r'cq-pp-name">(.*?)</span><span class="cq-pp-score">(\d+)<', body
        )
    ]
    assert pairs == [
        ("Module Efficiency", "91"), ("System Design", "93"),
        ("Product Durability", "94"), ("Geographic Coverage", "78"),
        ("Customer Acquisition", "80"),
    ]


def test_the_disc_colour_follows_the_score():
    body = _scorecard(H.render_quadrant_html(_payload()))
    assert "cq-bub-5" in body, "93 is the top band"
    assert "cq-bub-4" in body, "79 is the band below"


def _before_takeaways(doc: str) -> str:
    """Everything above the Key Takeaways table.

    Takeaways deliberately render a one-sentence claim, so a whole-document
    search for claim text no longer isolates the score tables. These checks
    are about the score tables and the expanded box, which sit above it.
    """
    marker = "Table A — X-Axis Parameters"
    return doc[: doc.index(marker)] if marker in doc else doc


def test_evidence_never_reaches_the_expanded_box():
    """The box shows scores only — the claims stay in the backend JSON."""
    doc = H.render_quadrant_html(_payload())
    assert "SECRET" not in _before_takeaways(doc)


def test_a_company_without_detail_shows_a_plain_score():
    """An arrow that opens an empty box is worse than no arrow."""
    body = _scorecard(H.render_quadrant_html(_payload(with_detail=False)))
    assert "<details" not in body
    assert 'cq-disc' in body, "the axis score is still shown"


def test_it_works_without_javascript():
    """<details> is native; a script-driven dropdown would not open from a
    file:// page with scripts blocked."""
    doc = H.render_quadrant_html(_payload())
    assert "<script" not in doc
    assert "onclick" not in doc


def test_the_arrow_sits_to_the_right_of_the_score():
    doc = H.render_quadrant_html(_payload())
    summary = re.search(r'<summary class="cq-pp-toggle".*?</summary>', doc, re.S).group(0)
    assert summary.index("cq-disc") < summary.index("cq-pp-arrow")


def test_the_arrow_points_back_at_the_score():
    """Tucked against the disc and pointing at it, so the two read as one
    control — detached and pointing away, it looked like a stray mark."""
    doc = H.render_quadrant_html(_payload())
    assert "border-right: 7px solid" in doc, "caret points left, back at the disc"
    assert "gap: 7px" in doc, "a clear gap between the disc and the caret"
    assert ".cq-pp[open] .cq-pp-arrow { transform: rotate(-90deg); }" in doc


def test_hovering_a_score_explains_it_is_clickable():
    doc = H.render_quadrant_html(_payload())
    assert 'title="Click a score for the breakdown"' in doc


def test_the_hover_affordance_is_css_only():
    """No JavaScript: the report is opened from disk, where scripts may be
    blocked, so the cue has to be a native tooltip plus CSS :hover."""
    doc = H.render_quadrant_html(_payload())
    assert ".cq-pp-toggle:hover .cq-disc" in doc
    assert ".cq-pp-toggle:hover .cq-pp-arrow" in doc
    assert "<script" not in doc and "onmouseover" not in doc


def test_keyboard_users_get_a_visible_focus_ring():
    doc = H.render_quadrant_html(_payload())
    assert ".cq-pp-toggle:focus-visible" in doc


# --- the same control in the Top 20 table ----------------------------------


def _top20_payload() -> dict:
    quads = ["Leaders", "Challengers", "Trailblazers", "Emerging Players"]
    brands = []
    for i in range(30):
        brands.append({
            "brand": f"B{i}", "company": f"C{i}", "hq_location": "Seoul, South Korea",
            "commercial_role": "Brand / Marketer",
            "execution": 93 - i, "innovation": 90 - i, "overall": 92 - i,
            "quadrant": quads[i % 4], "on_chart": i < 20,
            "score_detail": {
                "x": {"score": 93 - i, "parameters": {
                    p: {"score": 90, "evidence": [{"claim": "SECRET"}]} for p in X}},
                "y": {"score": 90 - i, "parameters": {
                    p: {"score": 88, "evidence": []} for p in Y}},
            },
        })
    return {
        "market": "T",
        "criteria": {"x_axis": X, "y_axis": Y,
                     "axis_labels": {"x": "Product Strength", "y": "Business Strength"}},
        "brands": brands,
    }


def _section(doc: str, name: str) -> str:
    return re.search(re.escape(name) + r".*?<tbody>(.*?)</tbody>", doc, re.S).group(1)


def test_the_top20_scores_expand_too():
    """Same control as the scorecard, so a reader does not have to scroll
    back to a different table for the breakdown."""
    body = _section(H.render_quadrant_html(_top20_payload()), "Top 20 Companies")
    assert body.count("<details") == 40, "two toggles per row, 20 rows"


def test_the_top20_box_lists_the_parameters():
    body = _section(H.render_quadrant_html(_top20_payload()), "Top 20 Companies")
    pairs = re.findall(r'cq-pp-name">(.*?)</span><span class="cq-pp-score">(\d+)<', body)
    assert (X[0], "90") in pairs
    assert (Y[0], "88") in pairs


def test_the_two_tables_do_not_share_toggle_state():
    """Duplicate <details> ids would make opening a scorecard row open the
    matching Top 20 row as well."""
    doc = H.render_quadrant_html(_top20_payload())
    ids = re.findall(r'<details class="cq-pp" id="([^"]+)"', doc)
    assert len(ids) == len(set(ids)), "every toggle needs its own id"


def test_evidence_stays_out_of_the_top20_table():
    doc = H.render_quadrant_html(_top20_payload())
    assert "SECRET" not in _before_takeaways(doc)


def test_the_overall_column_is_a_plain_score():
    """Overall has no parameters of its own — an arrow there would open an
    empty box."""
    body = _section(H.render_quadrant_html(_top20_payload()), "Top 20 Companies")
    cells = re.findall(r"<td[^>]*>(.*?)</td>", re.search(r"<tr>(.*?)</tr>", body, re.S).group(1), re.S)
    assert "<details" not in cells[7]
