"""Every report change applies to any market, including ones not yet run.

These live in html_report.render_quadrant_html, so a new market picks them up
with no per-report work. This file is the contract: it renders a market that
has never existed and asserts the full agreed layout, so a later edit that
quietly drops one of them fails here rather than in a delivered report.
"""
from __future__ import annotations

import re

from vendor_intel.quadrant import html_report as H

QUADS = ["Leaders", "Challengers", "Trailblazers", "Emerging Players"]
X = ["Catalyst Efficiency", "Process Yield", "Purity Control"]
Y = ["Market Share", "Revenue Growth"]


def _fresh_payload(n: int = 60) -> dict:
    brands = []
    for i in range(n):
        brands.append({
            "brand": f"Brand {i}", "company": f"Company {i} GmbH",
            "hq_location": "Ludwigshafen, Germany", "commercial_role": "Manufacturer",
            "execution": 95 - i, "innovation": 90 - i, "overall": 92 - i,
            "quadrant": QUADS[i % 4], "on_chart": i < 20,
            "score_detail": {
                "x": {"score": 95 - i, "parameters": {
                    p: {"score": 90 - j,
                        "evidence": [{"claim": "LEAK", "source": "https://leak.test"}]}
                    for j, p in enumerate(X)}},
                "y": {"score": 90 - i, "parameters": {
                    p: {"score": 85 - j, "evidence": []} for j, p in enumerate(Y)}},
            },
        })
    return {
        "market": "Global Brand New Market", "geography": "global",
        "criteria": {
            "x_axis": X, "y_axis": Y,
            "axis_labels": {"x": "Product Strength", "y": "Business Strength"},
            "relevance": {"market_type": "B2B", "market_definition": "A fresh market.",
                          "keep_roles": ["Manufacturer"]},
        },
        "brands": brands,
    }


def _doc() -> str:
    return H.render_quadrant_html(_fresh_payload())


def _rows(doc: str, section: str) -> int:
    m = re.search(re.escape(section) + r".*?<tbody>(.*?)</tbody>", doc, re.S)
    return m.group(1).count("<tr>") if m else 0


# --- tables that were removed ----------------------------------------------


def test_the_standalone_scorecard_is_not_rendered():
    assert "Company Parameter Scorecard" not in _doc()


def test_the_company_details_table_is_not_rendered():
    assert "Company Details" not in _doc()


# --- Top 20 ----------------------------------------------------------------


def test_top20_holds_the_charted_twenty():
    assert _rows(_doc(), "Top 20 Companies") == 20


def test_top20_scores_expand_to_their_parameters():
    doc = _doc()
    body = re.search(r"Top 20 Companies.*?<tbody>(.*?)</tbody>", doc, re.S).group(1)
    assert body.count("<details") == 40, "X and Y expand on each of 20 rows"


def test_hq_follows_the_company_column():
    assert "<th>BRAND</th><th>COMPANY</th><th>HQ</th>" in _doc()


def test_overall_is_labelled_overall_score():
    doc = _doc()
    assert "OVERALL SCORE" in doc
    assert "<th>OVERALL</th>" not in doc


# --- Other Noticeable Player ----------------------------------------------


def test_others_shows_strength_not_four_score_columns():
    doc = _doc()
    head = re.search(r"Other Noticeable Player.*?<thead>(.*?)</thead>", doc, re.S).group(1)
    assert "<th>STRENGTH</th>" in head
    for dropped in ("QUADRANT", "OVERALL SCORE"):
        assert dropped not in head


def test_strength_is_a_run_of_circles():
    assert "cq-sdot-" in _doc()


# --- wording ---------------------------------------------------------------


def test_the_capability_scale_is_used():
    doc = _doc()
    assert "Best-in-class Product" in doc
    assert "PRODUCT CAPABILITY" in doc and "BUSINESS CAPABILITY" in doc


def test_the_quadrant_titles_are_used():
    doc = _doc()
    for title in ("Integrated Market Leaders", "Scale-Driven Challengers",
                  "Innovation-Driven Trailblazers", "Foundation-Building Evolving"):
        assert title in doc


def test_the_reader_never_sees_the_old_emerging_players_label():
    """The quadrant KEY stays "Emerging Players" so checkpoints and workbooks
    keep resolving, but nothing rendered may still say it."""
    doc = _doc()
    assert "Evolving Players" in doc
    assert "Emerging Players" not in doc


def test_key_takeaways_follow_the_top_20():
    """A new market gets the takeaways grids too, not just the four markets
    it was built for.

    The single "Key Takeaways by Parameter" table was replaced by one grid
    per axis (Table A / Table B), each one company per row and one column
    per parameter.
    """
    doc = _doc()
    assert "Table A — X-Axis Parameters" in doc
    assert "Table B — Y-Axis Parameters" in doc
    assert doc.index("Top 20 Companies") < doc.index("Table A — X-Axis Parameters")
    assert doc.index("Table B — Y-Axis Parameters") < doc.index("Other Noticeable Player")


# --- layout ----------------------------------------------------------------


def test_sections_read_in_dependency_order():
    doc = _doc()
    for earlier, later in (
        ("Market Classification", "Market Scoring Parameters"),
        ("Market Scoring Parameters", "Quadrant Positioning"),
        ("Quadrant Positioning", "Understanding the Coherent Quadrant"),
        ("Understanding the Coherent Quadrant", "Top 20 Companies"),
        ("Top 20 Companies", "Other Noticeable Player"),
    ):
        assert doc.index(earlier) < doc.index(later), f"{earlier} must precede {later}"


def test_every_company_is_listed_once():
    doc = _doc()
    assert _rows(doc, "Top 20 Companies") + _rows(doc, "Other Noticeable Player") == 60


# --- invariants that must never regress ------------------------------------


def test_one_colour_for_every_score_marker():
    assert "--score-blue:#1e3a8a" in _doc().replace(" ", "")


def test_source_urls_never_reach_the_html():
    """Claims now surface as one-sentence takeaways, but a source URL is
    never rendered — the full evidence record stays in the scores JSON."""
    doc = _doc()
    assert "leak.test" not in doc


def test_the_score_tables_carry_no_claim_text():
    """Everything above the takeaways table is scores only, which is what
    build_view_model guarantees."""
    doc = _doc()
    assert "LEAK" not in doc[: doc.index("Table A — X-Axis Parameters")]


def test_the_report_needs_no_javascript():
    doc = _doc()
    assert "<script" not in doc and "onclick" not in doc
