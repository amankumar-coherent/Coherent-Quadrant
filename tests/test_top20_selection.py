"""The Top 20 table lists exactly the 20 companies plotted on the chart.

Those 20 are 5 per quadrant, chosen for the clearest separation from the
cohort midlines — not the 20 highest Overall scores. In Solar Rooftop, Chint,
Ginlong and Trina all score 91 yet sit in Other Noticeable Player, while
companies scoring 72 are in the Top 20. That is correct for a quadrant chart
(a pure top-20 fills with Leaders and empties the other three cells), but the
table has to SAY so or it reads as a broken ranking.
"""
from __future__ import annotations

import html as _html
import re
from collections import Counter

from vendor_intel.quadrant import html_report as H

QUADS = ["Leaders", "Challengers", "Trailblazers", "Emerging Players"]

# What the Quadrant column PRINTS. The stored key above is unchanged; only
# the reader-facing label differs (quadrant_language.QUADRANT_LABELS).
SHOWN = ["Leaders", "Challengers", "Trailblazers", "Evolving Players"]


def _payload(n: int = 40, on_chart: int = 20) -> dict:
    brands = []
    for i in range(n):
        brands.append({
            "brand": f"B{i}", "company": f"C{i}",
            "hq_location": "Austin, Texas, USA",
            "execution": 90 - i, "innovation": 80 - i, "overall": 85 - i,
            "quadrant": QUADS[i % 4], "on_chart": i < on_chart,
        })
    return {
        "market": "T",
        "criteria": {"x_axis": ["A"], "y_axis": ["B"],
                     "axis_labels": {"x": "Product Strength", "y": "Business Strength"}},
        "brands": brands,
    }


def _rows(doc: str, section: str) -> list[list[str]]:
    body = re.search(re.escape(section) + r".*?<tbody>(.*?)</tbody>", doc, re.S).group(1)
    return [
        [_html.unescape(re.sub(r"<[^>]+>", "", c)).strip()
         for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
        for tr in re.findall(r"<tr>(.*?)</tr>", body, re.S)
    ]


def test_the_table_lists_exactly_the_charted_companies():
    """One dataset for both, so the table and the plot cannot disagree."""
    payload = _payload()
    charted = {c["company"] for c in payload["brands"] if c["on_chart"]}
    listed = {
        r[1]
        for r in _rows(H.render_quadrant_html(payload), "Top 20 Companies")
    }
    assert listed == charted


def test_the_chart_holds_five_per_quadrant():
    payload = _payload()
    rows = _rows(H.render_quadrant_html(payload), "Top 20 Companies")
    assert Counter(r[4] for r in rows) == {q: 5 for q in SHOWN}


def test_the_caption_reports_the_actual_spread():
    """The caption names the 5-per-quadrant rule the selection actually
    used, rather than asserting a fixed string."""
    doc = H.render_quadrant_html(_payload())
    heading = _html.unescape(
        re.search(r"<h2>Top 20 Companies.*?</h2>", doc, re.S).group(0)
    )
    for quad in SHOWN:
        assert f"{quad} 5" in heading


def test_every_other_company_lands_in_the_second_table():
    payload = _payload()
    doc = H.render_quadrant_html(payload)
    top = {r[1] for r in _rows(doc, "Top 20 Companies")}
    others = {r[1] for r in _rows(doc, "Other Noticeable Player")}
    assert not (top & others), "no company in both"
    assert top | others == {c["company"] for c in payload["brands"]}


def test_a_higher_scoring_company_may_sit_in_others():
    """Documents the deliberate consequence: quadrant balance beats raw score,
    so this is expected behaviour rather than a selection bug.

    Mirrors Solar Rooftop, where Chint/Ginlong/Trina score 91 off-chart while
    a 72 sits in the Top 20 — the charted set is picked per quadrant, and a
    high scorer can miss out when its quadrant is already full.
    """
    payload = _payload(40, on_chart=0)
    # Charted: five per quadrant, but NOT the strongest — deliberately the
    # mid-range ones, as quadrant balance produces in a real market.
    for i, c in enumerate(payload["brands"]):
        c["overall"] = 95 - i          # C0 highest, C39 lowest
        c["on_chart"] = 10 <= i < 30   # the strongest ten are left off
    doc = H.render_quadrant_html(payload)
    lowest_top = min(int(r[7]) for r in _rows(doc, "Top 20 Companies"))
    # Other Noticeable Player shows a Strength bubble, not an Overall column,
    # so the comparison is made against the source data.
    charted = {r[1] for r in _rows(doc, "Top 20 Companies")}
    off_chart = [
        c for c in payload["brands"] if c["company"] not in charted
    ]
    assert any(int(c["overall"]) > lowest_top for c in off_chart)


# --- two tables, each honest about what it is ------------------------------
#
# A single "Top 20" could not be both a score ranking and a balanced chart
# legend. Splitting them gives the ranking readers expect AND keeps every
# quadrant populated on the plot.


def test_the_chart_table_keeps_five_per_quadrant():
    rows = _rows(H.render_quadrant_html(_payload()), "Top 20 Companies")
    assert Counter(r[4] for r in rows) == {q: 5 for q in SHOWN}


def test_the_table_says_it_lists_the_charted_companies():
    """One Top 20 table: the companies on the chart, 5 per quadrant. The
    caption names that rule so the title does not imply a score ranking —
    a company in Other Noticeable Player can out-score the lowest entry."""
    doc = H.render_quadrant_html(_payload())
    assert "the 20 companies plotted on the chart above" in doc


def test_the_sections_follow_the_reading_order():
    """Chart, then the definitions that explain it, then the companies
    plotted there, then everyone else."""
    doc = H.render_quadrant_html(_payload())
    for earlier, later in (
        ("Quadrant Positioning", "Understanding the Coherent Quadrant"),
        ("Understanding the Coherent Quadrant", "Top 20 Companies"),
        ("Top 20 Companies", "Other Noticeable Player"),
    ):
        assert doc.index(earlier) < doc.index(later), f"{earlier} must precede {later}"


def test_there_is_only_one_top20_table():
    """A second, score-ranked table listed different companies from the
    chart — two tables both called "top 20" is worse than one clear rule."""
    doc = H.render_quadrant_html(_payload())
    assert "by Overall Score" not in doc
    assert doc.count("<h2>Top 20 Companies") == 1


def test_a_small_market_lists_everyone_and_invents_nobody():
    payload = _payload(8, on_chart=8)
    doc = H.render_quadrant_html(payload)
    assert len(_rows(doc, "Top 20 Companies")) == 8
    assert "Other Noticeable Player" not in doc, "nobody left over"
