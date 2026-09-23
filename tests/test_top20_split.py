"""Top 20 table, Top 20 graph and Other Noticeable Player share one dataset.

Computing the Top 20 twice is how a table and its chart drift apart, so both
read the same `split_top20` result. Every company lands in exactly one table:
none missing, none duplicated, none in both.
"""
from __future__ import annotations

import re

from vendor_intel.quadrant import html_report as H

X_PARAMS = ["P1", "P2"]
Y_PARAMS = ["Q1"]


def _companies(n: int, on_chart: int | None = None) -> list[dict]:
    """n companies; the first `on_chart` flagged as charted (None = no flag)."""
    out = []
    for i in range(n):
        c = {
            "brand": f"Brand {i}",
            "company": f"Company {i}",
            "hq_location": "Austin, Texas, USA",
            "execution": 90 - i,
            "innovation": 80 - i,
            "overall": 85 - i,
        }
        if on_chart is not None:
            c["on_chart"] = i < on_chart
        out.append(c)
    return out


def test_more_than_20_splits_exactly_20_and_the_rest():
    top, others = H.split_top20(_companies(50, on_chart=20))
    assert len(top) == 20
    assert len(others) == 30


def test_no_company_is_lost_or_duplicated():
    companies = _companies(50, on_chart=20)
    top, others = H.split_top20(companies)
    names = [c["company"] for c in top] + [c["company"] for c in others]
    assert len(names) == len(companies)
    assert len(set(names)) == len(companies), "no duplicates"
    assert set(names) == {c["company"] for c in companies}, "none missing"


def test_no_company_appears_in_both_tables():
    top, others = H.split_top20(_companies(50, on_chart=20))
    assert not ({c["company"] for c in top} & {c["company"] for c in others})


def test_fewer_than_20_puts_everyone_in_top20():
    top, others = H.split_top20(_companies(7, on_chart=7))
    assert len(top) == 7
    assert others == [], "Other Noticeable Player is empty"


def test_exactly_20_leaves_others_empty():
    top, others = H.split_top20(_companies(20, on_chart=20))
    assert len(top) == 20
    assert others == []


def test_no_companies_at_all_is_not_an_error():
    top, others = H.split_top20([])
    assert top == [] and others == []


def test_membership_follows_the_pipelines_on_chart_flag():
    """The graph plots on_chart brands; the table must use the same flag, not
    re-rank independently."""
    companies = _companies(30, on_chart=0)
    for c in companies[5:25]:
        c["on_chart"] = True
    top, others = H.split_top20(companies)
    assert {c["company"] for c in top} == {f"Company {i}" for i in range(5, 25)}
    assert len(others) == 10


def test_a_payload_without_the_flag_falls_back_to_the_first_20():
    """Older payloads have no on_chart; the chart itself falls back the same
    way, so the table must not diverge."""
    top, others = H.split_top20(_companies(30, on_chart=None))
    assert len(top) == 20 and len(others) == 10


# --- rendered HTML ---------------------------------------------------------


def _payload(n: int, on_chart: int = 20) -> dict:
    return {
        "market": "Test Market",
        "criteria": {
            "x_axis": X_PARAMS,
            "y_axis": Y_PARAMS,
            "axis_labels": {"x": "Product Strength", "y": "Business Strength"},
        },
        "brands": _companies(n, on_chart=on_chart),
    }


def test_both_sections_render_when_there_are_extras():
    html = H.render_quadrant_html(_payload(50))
    assert "Top 20 Companies" in html
    assert "Other Noticeable Player" in html


def test_other_noticeable_player_is_hidden_when_empty():
    html = H.render_quadrant_html(_payload(15, on_chart=15))
    assert "Top 20 Companies" in html
    assert "Other Noticeable Player" not in html


def test_the_standalone_scorecard_is_gone():
    """Parameters now expand from the Top 20 scores (see
    test_scorecard_expand.py), so the separate all-companies scorecard was a
    second copy of the same control."""
    html = H.render_quadrant_html(_payload(50))
    assert "Company Parameter Scorecard" not in html


def test_columns_are_renamed():
    html = H.render_quadrant_html(_payload(30))
    assert "<th>HQ</th>" in html
    assert "OVERALL SCORE" in html
    assert "<th>FOUND IN</th>" not in html


def test_the_score_tables_contain_no_evidence():
    payload = _payload(30)
    for c in payload["brands"]:
        c["score_detail"] = {
            "x": {
                "score": 80,
                "evidence": [{"claim": "SECRETCLAIM", "source": "https://secret.example"}],
                "parameters": {
                    "P1": {"score": 80, "evidence": [{"claim": "SECRETCLAIM"}]},
                    "P2": {"score": 70, "evidence": []},
                },
            },
            "y": {"score": 60, "evidence": [], "parameters": {"Q1": {"score": 60, "evidence": []}}},
        }
    html = H.render_quadrant_html(payload)
    # The Key Takeaways table shows one sentence of the claim by design; the
    # score tables above it show scores only, and no source URL is ever
    # rendered anywhere.
    marker = "Table A — X-Axis Parameters"
    assert "SECRETCLAIM" not in html[: html.index(marker)]
    assert "secret.example" not in html
    # The scores from that same record must still be there.
    assert ">80<" in html


def test_the_company_details_table_is_gone():
    """Top 20 + Other Noticeable Player already list every company with the
    same columns, so a third full-list table was redundant. The Excel sheet of
    that name is unaffected — this is the HTML section only."""
    html = H.render_quadrant_html(_payload(50))
    assert "Company Details" not in html


def test_every_company_is_still_listed_somewhere():
    """Dropping a table must not hide anyone: Top 20 plus Other Noticeable
    Player still account for the whole cohort."""
    import re

    payload = _payload(50)
    html = H.render_quadrant_html(payload)

    def rows(section: str) -> int:
        m = re.search(re.escape(section) + r".*?<tbody>(.*?)</tbody>", html, re.S)
        return m.group(1).count("<tr>") if m else 0

    assert rows("Top 20 Companies") + rows("Other Noticeable Player") == 50


def test_hq_sits_next_to_the_company_in_both_tables():
    """At the far right, HQ was separated from the company name it belongs to
    by four score columns. Header and cell order must move together — a
    mismatch would silently print the HQ under ROLE."""
    import html as _html
    import re

    doc = H.render_quadrant_html(_payload(25))
    for section in ("Top 20 Companies", "Other Noticeable Player"):
        # Others ends at STRENGTH; Top 20 at OVERALL SCORE. Both must still
        # open BRAND | COMPANY | HQ.
        head = re.search(re.escape(section) + r".*?<thead>(.*?)</thead>", doc, re.S)
        headers = [_html.unescape(x) for x in re.findall(r"<th[^>]*>(.*?)</th>", head.group(1))]
        assert headers[:3] == ["BRAND", "COMPANY", "HQ"], f"{section}: {headers}"

        row = re.search(re.escape(section) + r".*?<tbody>(<tr>.*?</tr>)", doc, re.S).group(1)
        cells = [
            _html.unescape(re.sub(r"<[^>]+>", "", c)).strip()
            for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        ]
        assert len(cells) == len(headers), f"{section}: cells/headers out of step"
        assert "Austin" in cells[2], f"{section}: HQ is not in the HQ column"


def test_the_sections_read_in_dependency_order():
    """Definitions first, then the chart, then what the quadrants mean, then
    the companies in them — each block follows what it depends on."""
    payload = _payload(25)
    payload["criteria"]["relevance"] = {
        "market_type": "B2C",
        "market_definition": "Test market.",
        "keep_roles": ["Brand / Marketer"],
    }
    doc = H.render_quadrant_html(payload)
    for earlier, later in (
        ("Market Classification", "Market Scoring Parameters"),
        ("Market Scoring Parameters", "Quadrant Positioning"),
        # The quadrant definitions explain the chart, so they follow it while
        # the plot is still on screen — and precede the remaining companies.
        ("Quadrant Positioning", "Understanding the Coherent Quadrant"),
        ("Understanding the Coherent Quadrant", "Top 20 Companies"),
        ("Top 20 Companies", "Other Noticeable Player"),
    ):
        assert doc.index(earlier) < doc.index(later), f"{earlier} must precede {later}"
