"""Key Takeaways grid: one row per company, one column per parameter.

Table A covers the X-axis parameters, Table B the Y-axis parameters. Each
cell holds the headline sentence for that company/parameter pair — the
scores answer "how well", the takeaway answers "on what basis" — without
making a reader open chatgpt_xy_scores_batch_all.json. Only the headline
sentence is shown, and never a source URL.
"""
from __future__ import annotations

import re

from vendor_intel.quadrant import html_report as H

X = ["Catalyst Efficiency", "Process Yield"]
Y = ["Market Share"]

CLAIM = (
    "Operates four plants with a combined 180 kt of annual capacity. "
    "This was confirmed in the 2025 annual report and a trade filing."
)


def _company(i: int, claim: str = CLAIM) -> dict:
    return {
        "brand": f"Brand {i}",
        "company": f"Company {i} GmbH",
        "hq_location": "Ludwigshafen, Germany",
        "commercial_role": "Manufacturer",
        "execution": 90 - i,
        "innovation": 80 - i,
        "overall": 85 - i,
        "quadrant": "Emerging Players",
        "on_chart": True,
        "score_detail": {
            "x": {"score": 90 - i, "parameters": {
                p: {"score": 88 - j,
                    "evidence": [{"claim": claim, "source": "https://secret.test/a"}]}
                for j, p in enumerate(X)}},
            "y": {"score": 80 - i, "parameters": {
                p: {"score": 70, "evidence": [{"claim": claim}]} for p in Y}},
        },
    }


def _payload(n: int = 3) -> dict:
    return {
        "market": "Global Test Market",
        "geography": "global",
        "criteria": {
            "x_axis": X, "y_axis": Y,
            "axis_labels": {"x": "Product Strength", "y": "Business Strength"},
        },
        "brands": [_company(i) for i in range(n)],
    }


# --- _first_sentence -------------------------------------------------------


def test_only_the_first_sentence_is_kept():
    assert H._first_sentence(CLAIM) == (
        "Operates four plants with a combined 180 kt of annual capacity."
    )


def test_a_single_sentence_survives_whole():
    one = "Holds roughly 12% share across EMEA."
    assert H._first_sentence(one) == one


def test_whitespace_and_newlines_are_flattened():
    assert H._first_sentence("  Two   plants.\n  More text.  ") == "Two plants."


def test_empty_evidence_gives_an_empty_takeaway():
    assert H._first_sentence("") == ""
    assert H._first_sentence(None) == ""


def test_an_over_long_sentence_is_cut_on_a_word_boundary():
    long = "The company " + "expands capacity steadily " * 30 + "worldwide."
    out = H._first_sentence(long, limit=80)
    assert len(out) <= 81
    assert out.endswith("…")
    assert not out[:-1].endswith(" "), "cut at a word boundary, no dangling space"


def test_a_decimal_does_not_end_the_sentence():
    """"1.5 Mt" must not be read as a sentence break."""
    text = "Capacity reached 1.5 Mt in 2025. A second line follows."
    assert H._first_sentence(text) == "Capacity reached 1.5 Mt in 2025."


# --- the rendered grids ------------------------------------------------


def test_the_tables_render_after_the_top_20():
    doc = H.render_quadrant_html(_payload())
    assert "Table A" in doc and "Table B" in doc
    assert doc.index("Top 20 Companies") < doc.index("Table A")


def test_every_charted_company_gets_a_row_in_each_table():
    doc = H.render_quadrant_html(_payload(3))
    a = _table_a(doc)
    companies = set(re.findall(r"<td>(Company \d+ GmbH)</td>", a))
    assert len(companies) == 3


def test_every_x_parameter_is_a_column_in_table_a():
    doc = H.render_quadrant_html(_payload(1))
    a = _table_a(doc)
    for p in X:
        assert f"<th>{p}</th>" in a


def test_every_y_parameter_is_a_column_in_table_b():
    doc = H.render_quadrant_html(_payload(1))
    b = _table_b(doc)
    for p in Y:
        assert f"<th>{p}</th>" in b


def test_the_source_url_is_never_rendered():
    doc = H.render_quadrant_html(_payload())
    assert "secret.test" not in doc


def test_every_evidence_sentence_reaches_the_html_as_a_bullet():
    """Each grid cell lists every stored sentence as its own bullet, not
    just the first — the full argument, not a truncated headline."""
    doc = H.render_quadrant_html(_payload())
    assert "Operates four plants" in doc
    assert "confirmed in the 2025 annual report" in doc
    assert '<ul class="cq-ta-points">' in doc
    assert doc.count("<li>") > 0


def test_each_cell_leads_with_the_score_as_the_reasoning_header():
    """A cell reads as the ANSWER to "why this score", not a bare list of
    facts — it states the score first, then the evidence that justifies
    it."""
    doc = H.render_quadrant_html(_payload(1))
    a = _table_a(doc)
    assert "Scored 88/100 — why:" in a
    assert 'class="cq-ta-score-line"' in a


def test_a_scored_parameter_with_no_evidence_still_shows_the_score():
    payload = _payload(1)
    params = payload["brands"][0]["score_detail"]["x"]["parameters"]
    params["Process Yield"]["evidence"] = []
    doc = H.render_quadrant_html(payload)
    a = _table_a(doc)
    row = [r for r in a.split("<tr>") if "Company 0 GmbH" in r][0]
    assert "Scored 87/100" in row
    assert "—" in row


def test_a_parameter_with_no_score_and_no_evidence_shows_an_em_dash():
    payload = _payload(1)
    params = payload["brands"][0]["score_detail"]["x"]["parameters"]
    params["Process Yield"] = {"score": None, "evidence": []}
    doc = H.render_quadrant_html(payload)
    a = _table_a(doc)
    row = [r for r in a.split("<tr>") if "Company 0 GmbH" in r][0]
    cells = re.findall(r"<td>([^<]*)</td>", row)
    assert "—" in cells


def test_a_company_with_no_scored_parameters_is_skipped():
    payload = _payload(2)
    payload["brands"][1]["score_detail"] = {}
    doc = H.render_quadrant_html(payload)
    a = _table_a(doc)
    companies = set(re.findall(r"<td>(Company \d+ GmbH)</td>", a))
    assert companies == {"Company 0 GmbH"}


def test_the_table_needs_no_javascript():
    doc = H.render_quadrant_html(_payload())
    assert "<script" not in doc and "onclick" not in doc


def test_claim_text_is_escaped():
    payload = _payload(1)
    params = payload["brands"][0]["score_detail"]["x"]["parameters"]
    params["Catalyst Efficiency"]["evidence"] = [
        {"claim": "Supplies <Acme> & Partners."}
    ]
    doc = H.render_quadrant_html(payload)
    assert "<Acme>" not in doc
    assert "&lt;Acme&gt; &amp; Partners." in doc


def test_the_styles_for_the_grid_are_present():
    doc = H.render_quadrant_html(_payload())
    assert ".cq-ta td" in doc


def test_a_typical_full_sentence_is_not_truncated():
    """The default limit is a runaway guard. Real first sentences from the
    scored markets run to ~350 characters, so they must survive whole."""
    sentence = (
        "Infineon confirmed it completed its milestone transition to 200 mm "
        "SiC technology, delivering the first batch of customer products "
        "manufactured at its Villach and Kulim sites during 2025, which puts "
        "it ahead of most competitors still qualifying 150 mm lines today."
    )
    assert 240 < len(sentence) < 420
    assert H._first_sentence(sentence) == sentence


# --- inline sources ---------------------------------------------------------
#
# The scorer sometimes writes the source into the claim as a Markdown link.
# The takeaway keeps the finding and drops the URL; the full claim, link and
# all, stays in the scores JSON.


def test_a_markdown_link_keeps_its_label_and_drops_the_url():
    claim = (
        "As reported in the [Fronius Symo Specification Sheet]"
        "(https://www.fronius.com/datasheet.pdf \"Gen24 efficiency\"), "
        "the inverter reaches 98.2% peak conversion efficiency."
    )
    out = H._first_sentence(claim)
    assert "fronius.com" not in out
    assert "https://" not in out
    assert "Fronius Symo Specification Sheet" in out
    assert "98.2%" in out


def test_a_bare_url_is_removed():
    claim = "Capacity reached 4 GW in 2025 https://example.com/report.pdf and rising."
    out = H._first_sentence(claim)
    assert "example.com" not in out
    assert "Capacity reached 4 GW in 2025" in out
    assert "  " not in out, "no double space where the URL was"


def test_stripping_a_link_does_not_leave_empty_brackets():
    claim = "Per the [annual report](https://x.test/a.pdf), revenue grew 18%."
    out = H._first_sentence(claim)
    assert "()" not in out
    assert out == "Per the annual report, revenue grew 18%."


def test_no_rendered_takeaway_contains_a_link():
    payload = _payload(1)
    params = payload["brands"][0]["score_detail"]["x"]["parameters"]
    params["Catalyst Efficiency"]["evidence"] = [
        {"claim": "Per the [datasheet](https://vendor.test/d.pdf), yield is 94%."}
    ]
    doc = H.render_quadrant_html(payload)
    assert "vendor.test" not in doc
    assert "yield is 94%" in doc


# --- four tables: charted vs. the rest, X vs. Y -----------------------------
#
# The charted 20 get their own Table A / Table B; everyone else gets a
# second pair of the same grids, titled for "Other Noticeable Players".


def _table_a(doc: str) -> str:
    start = doc.index("Table A — X-Axis Parameters")
    end = doc.find('<div class="panel">', start)
    return doc[start:end] if end > start else doc[start:]


def _table_b(doc: str) -> str:
    start = doc.index("Table B — Y-Axis Parameters")
    end = doc.find('<div class="panel">', start)
    return doc[start:end] if end > start else doc[start:]


def _payload_split(total: int = 25, charted: int = 20) -> dict:
    payload = _payload(total)
    for i, c in enumerate(payload["brands"]):
        c["on_chart"] = i < charted
    return payload


def test_only_the_charted_takeaway_tables_render():
    """Other Noticeable Player gets its own strength table, but no takeaway
    grid — only the charted 20 get the parameter-by-parameter breakdown."""
    doc = H.render_quadrant_html(_payload_split())
    assert "Table A — X-Axis Parameters" in doc
    assert "Table B — Y-Axis Parameters" in doc
    assert "Other Noticeable Players)" not in doc


def test_no_company_outside_the_chart_appears_in_the_takeaway_tables():
    doc = H.render_quadrant_html(_payload_split(25, 20))
    a = _table_a(doc)
    for i in range(20, 25):
        assert f"Company {i} GmbH" not in a, f"Company {i} should not be charted"


def test_the_tables_follow_their_own_company_tables():
    doc = H.render_quadrant_html(_payload_split(25, 20))
    for earlier, later in (
        ("Top 20 Companies", "Table A — X-Axis Parameters"),
        ("Table B — Y-Axis Parameters", "Other Noticeable Player"),
    ):
        assert doc.index(earlier) < doc.index(later), f"{earlier} must precede {later}"
