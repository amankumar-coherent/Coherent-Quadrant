"""Other Noticeable Player: a Strength bubble instead of four score columns.

At 159 rows, Quadrant + X + Y + Overall read as noise rather than a ranking.
A fixed row of 5 circles, small-to-big left to right, filled from the
smallest by the Overall score, conveys standing at a glance; the exact
figures stay in the scorecard a section above.
"""
from __future__ import annotations

import html as _html
import re

from vendor_intel.quadrant import html_report as H

QUADS = ["Leaders", "Challengers", "Trailblazers", "Emerging Players"]


def _payload(n: int = 40) -> dict:
    brands = [
        {
            "brand": f"B{i}", "company": f"C{i}", "hq_location": "Austin, Texas, USA",
            "commercial_role": "Brand / Marketer",
            "execution": 95 - i, "innovation": 85 - i,
            # Real Overall scores are floor-65 normalized (normalize_row_
            # score_floor), so every value here stays in [65, 100] rather
            # than sweeping the full 0-100 range the raw formula would give.
            "overall": max(65, 100 - i),
            "quadrant": QUADS[i % 4], "on_chart": i < 20,
        }
        for i in range(n)
    ]
    return {
        "market": "T",
        "criteria": {"x_axis": ["A"], "y_axis": ["B"],
                     "axis_labels": {"x": "Product Strength", "y": "Business Strength"}},
        "brands": brands,
    }


def _headers(doc: str, section: str) -> list[str]:
    head = re.search(re.escape(section) + r".*?<thead>(.*?)</thead>", doc, re.S)
    return [_html.unescape(x) for x in re.findall(r"<th[^>]*>(.*?)</th>", head.group(1))]


def _cells(doc: str, section: str) -> list[list[str]]:
    body = re.search(re.escape(section) + r".*?<tbody>(.*?)</tbody>", doc, re.S).group(1)
    return [
        re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        for tr in re.findall(r"<tr>(.*?)</tr>", body, re.S)
    ]


def test_the_columns_are_brand_company_hq_role_strength():
    doc = H.render_quadrant_html(_payload())
    assert _headers(doc, "Other Noticeable Player") == [
        "BRAND", "COMPANY", "HQ", "ROLE", "STRENGTH",
    ]


def test_the_score_columns_are_gone():
    doc = H.render_quadrant_html(_payload())
    headers = _headers(doc, "Other Noticeable Player")
    for dropped in ("QUADRANT", "OVERALL SCORE"):
        assert dropped not in headers
    assert not any(h.startswith("X (") or h.startswith("Y (") for h in headers)


def test_the_top20_table_keeps_its_score_columns():
    """Only the long tail collapses — the charted 20 still show their
    numbers, which is where a reader compares them."""
    headers = _headers(H.render_quadrant_html(_payload()), "Top 20 Companies")
    assert "QUADRANT" in headers and "OVERALL SCORE" in headers


def test_every_bubble_shows_exactly_five_dots():
    doc = H.render_quadrant_html(_payload())
    rows = _cells(doc, "Other Noticeable Player")
    for r in rows:
        if "cq-strength" in r[4]:
            assert len(re.findall(r'class="cq-sdot', r[4])) == 5


def test_more_dots_are_filled_for_a_higher_score():
    doc = H.render_quadrant_html(_payload())
    rows = _cells(doc, "Other Noticeable Player")
    filled_counts = [
        len(re.findall(r'class="cq-sdot [^"]*cq-sdot-on"', r[4]))
        for r in rows if "cq-strength" in r[4]
    ]
    # Overall descends down the table, so the filled count must never rise.
    assert filled_counts == sorted(filled_counts, reverse=True)
    assert len(set(filled_counts)) > 1, "the column has to discriminate"


def test_a_high_score_fills_five_and_a_low_score_fills_one():
    from vendor_intel.quadrant.html_report import _strength_bubble

    assert len(re.findall(r'class="cq-sdot [^"]*cq-sdot-on"', _strength_bubble(95))) == 5
    assert len(re.findall(r'class="cq-sdot [^"]*cq-sdot-on"', _strength_bubble(66))) == 1


def test_strength_cell_is_bubbles_only_no_tooltip():
    """The long tail is filled bubbles only: no number, no word, no hover
    tooltip. The score itself stays in the payload/JSON."""
    payload = _payload()
    doc = H.render_quadrant_html(payload)
    rows = _cells(doc, "Other Noticeable Player")
    assert "title=" not in rows[0][4]
    assert "cq-sdot-on" in rows[0][4]
    assert all(b.get("overall") is not None for b in payload["brands"][:5])


def test_an_unscored_company_shows_a_dash_not_a_bubble():
    payload = _payload()
    for c in payload["brands"][25:]:
        c["overall"] = None
    rows = _cells(H.render_quadrant_html(payload), "Other Noticeable Player")
    assert any(r[4].strip() == "—" for r in rows)


def test_every_score_marker_uses_one_colour():
    """Colour marks filled vs empty only — every filled dot everywhere uses
    the same colour, so a 69 and a 71 read as the same kind of result."""
    doc = H.render_quadrant_html(_payload())
    css = doc.split("</style>")[0]
    colours = set()
    for line in css.split("\n"):
        line = line.strip()
        if line.startswith((".cq-bub-", ".cq-sdot-on", ".cq-disc")):
            colours.update(re.findall(r"background:\s*([^;]+);", line))
    assert colours <= {"var(--score-blue)"}, colours


def test_the_dots_are_five_fixed_ascending_sizes():
    """The 5 dot positions are always the same 5 sizes, small to big — the
    score is read from how many (starting from the smallest) are filled,
    not from which position is filled."""
    doc = H.render_quadrant_html(_payload())
    css = doc.split("</style>")[0]
    sizes = [
        int(m.group(1))
        for m in re.finditer(r"\.cq-sdot-(\d+)\s*\{[^}]*width:\s*\d+px", css)
    ]
    assert len(sizes) == 5
    assert sizes == sorted(sizes), "sizes must be declared small to big"
    assert len(set(sizes)) == 5, "all 5 sizes must be distinct"
