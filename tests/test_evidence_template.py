"""The evidence-scoring template: search per parameter, score, composite.

Shapes here were captured from live AI Mode replies on 2026-09-17 and from
the user's reference screenshots. Both are parsed, because the model varies
its formatting between runs — bulleted vs bare "Score:", composite present
or absent.
"""
from __future__ import annotations

import re

from vendor_intel.quadrant import ai_mode_scorer as S

X = [
    "Substrate & Epitaxy Quality",
    "Device Performance & Reliability",
    "Wafer Size & Defect Density",
    "R&D and Patent Strength",
    "Manufacturing Yield & Scalability",
]

# As rendered live: heading at position 0, bare "Score:", "Reason:" after,
# and citation chips ("STMicroelectronics +1") between the lines.
LIVE = """1. Substrate & Epitaxy Quality
Evidence: ST strengthened substrate capability by acquiring Norstel A.B., now
supplying more than 40% of its own SiC wafers internally. https://www.st.com
STMicroelectronics
 +1
Score: 90 / 100
Reason: Vertical integration in Catania allows tight control over epitaxy.
2. Device Performance & Reliability
Evidence: Gen 4 STPOWER SiC MOSFETs cover 650V to 2200V.
Score: 94 / 100
3. Wafer Size & Defect Density
Evidence: Transition to 200 mm across Catania and Norrkoping.
Score: 88 / 100
4. R&D and Patent Strength
Evidence: 25 years of SiC IP and ~17% of revenue reinvested in R&D.
Score: 95 / 100
5. Manufacturing Yield & Scalability
Evidence: Dual-region model in Catania and Singapore plus the Sanan JV.
Score: 90 / 100
Composite Product Strength Score: 91 / 100"""

# The reference screenshots: bulleted "- Evidence:" / "- Score: 92 / 100 (…)".
BULLETED = """1. Substrate & Epitaxy Quality
- Evidence: ST's acquisition of Norstel AB and the Catania campus shifted the
company away from third-party merchant reliance. https://www.soitec.com
- Score: 92 / 100 (Industry-leading integration).
2. Device Performance & Reliability
- Evidence: Gen 4 STPOWER SiC MOSFETs cut die size 12-15% and exceed AQG324.
- Score: 96 / 100 (Unmatched field reliability data).
3. Wafer Size & Defect Density
- Evidence: Executing the 150 mm to 200 mm transition.
- Score: 87 / 100 (Conversion still ramping).
4. R&D and Patent Strength
- Evidence: 25+ years of foundational SiC IP.
- Score: 95 / 100 (Historically protected portfolio).
5. Manufacturing Yield & Scalability
- Evidence: Dual-region manufacturing plus the Sanan JV.
- Score: 90 / 100 (Broad footprint).
Composite Product Strength Score: 92 / 100"""


# --- the query -------------------------------------------------------------


def test_the_query_dictates_a_per_parameter_layout():
    """Left to itself the model answers in one prose paragraph with a single
    number — no per-parameter breakdown at all. The layout must be spelled
    out, including a worked example of the first section."""
    q = S.build_parameter_score_query("Acme", "Product Strength", X, market="M")
    assert "Answer in EXACTLY this format" in q
    assert "one numbered section per parameter" in q
    assert "Evidence: <first specific finding" in q
    assert "Score: NN / 100" in q
    assert f"1. {X[0]}" in q, "shows the first section by name"


def test_the_query_asks_for_more_than_one_finding_per_parameter():
    """One Evidence line is one sentence. The report renders each finding as
    its own bullet, so a single line leaves nothing to break apart and a
    reader sees one assertion instead of the argument behind a score."""
    q = S.build_parameter_score_query("Acme", "Product Strength", X, market="M")
    assert q.count("Evidence:") >= 3, "template must show repeated Evidence lines"
    assert "a SECOND, different finding" in q
    assert "a THIRD finding, if one genuinely exists" in q


def test_the_query_forbids_a_zero_for_a_different_segment():
    """An abrasives maker judged on semiconductor wafer parameters came back
    0/100 — a category error, not an assessment."""
    q = S.build_parameter_score_query("Acme", "Product Strength", X, market="M")
    assert "score it on its own segment rather than giving 0" in q
    assert "must get a number between 1 and 100" in q


def test_the_query_identifies_the_company_by_hq_and_product():
    """A bare trading name is ambiguous; the row already carries both."""
    q = S.build_parameter_score_query(
        "A-One Coated Abrasive", "Product Strength", X,
        market="M", headquarters="Unjha, Gujarat, India",
        context="Manufactures silicon carbide abrasive grains.",
    )
    assert "headquartered in Unjha, Gujarat, India" in q
    assert "Manufactures silicon carbide abrasive grains." in q


def test_the_query_asks_for_a_composite():
    q = S.build_parameter_score_query("Acme", "Product Strength", X, market="M")
    assert "Composite Product Strength Score" in q


def test_the_query_forbids_invented_sources():
    q = S.build_parameter_score_query("Acme", "Product Strength", X)
    assert "Do not invent a source or a figure" in q


def test_the_query_is_company_and_market_specific():
    """A template, not a hardcoded company: both are substituted."""
    q = S.build_parameter_score_query(
        "Bosch GmbH", "Business Strength", ["Market Share"], market="Global X Market"
    )
    assert "Bosch GmbH" in q and "Global X Market" in q
    assert "1. Market Share" in q
    assert "STMicroelectronics" not in q


# --- parsing both live shapes ---------------------------------------------


def test_the_live_reply_parses_every_parameter():
    got = S._parse_parameters_prose(LIVE, X)
    assert len(got) == 5
    assert [v["score"] for v in got.values()] == [90, 94, 88, 95, 90]


def test_the_bulleted_reply_parses_every_parameter():
    got = S._parse_parameters_prose(BULLETED, X)
    assert len(got) == 5
    assert got["Device Performance & Reliability"]["score"] == 96


def test_a_heading_at_position_zero_is_found():
    """A lookbehind cannot match at index 0, and the live replies start there —
    this silently parsed nothing until the pattern allowed start-of-string."""
    assert LIVE.startswith("1. Substrate")
    assert "Substrate & Epitaxy Quality" in S._parse_parameters_prose(LIVE, X)


def test_evidence_is_captured_with_its_source():
    got = S._parse_parameters_prose(LIVE, X)
    ev = got["Substrate & Epitaxy Quality"]["evidence"][0]
    assert "Norstel" in ev["claim"]
    assert ev["source"] == "https://www.st.com"


def test_the_reason_text_is_not_swallowed_into_the_evidence():
    """Evidence must stop at the Score line, not run on into Reason."""
    got = S._parse_parameters_prose(LIVE, X)
    claim = got["Substrate & Epitaxy Quality"]["evidence"][0]["claim"]
    assert "Vertical integration in Catania" not in claim


def test_each_parameter_keeps_its_own_evidence():
    got = S._parse_parameters_prose(LIVE, X)
    assert "Gen 4" in got["Device Performance & Reliability"]["evidence"][0]["claim"]
    assert "Gen 4" not in got["Wafer Size & Defect Density"]["evidence"][0]["claim"]


# --- composite -------------------------------------------------------------


def test_the_composite_score_is_read():
    assert S.parse_composite_score(LIVE) == 91
    assert S.parse_composite_score(BULLETED) == 92


def test_a_missing_composite_is_none_not_a_guess():
    """Observed live: the model sometimes omits the composite line."""
    assert S.parse_composite_score("1. A\nEvidence: x\nScore: 90 / 100") is None


def test_the_axis_falls_back_to_the_parameter_average():
    def ask(q):
        # Echo the REAL prompt, as the rendered page does. A stand-in like
        # "P" also occurs inside the answer, so the echo-stripper cuts in the
        # wrong place and the test measures the harness, not the code.
        return f"AI Mode conversation: {q}\n{q}\n" + LIVE.replace(
            "Composite Product Strength Score: 91 / 100", ""
        )

    got = S.score_company_detailed(
        "Acme", x_parameters=X, y_parameters=X, ask=ask
    )
    # (90 + 94 + 88 + 95 + 90) / 5 = 91.4 -> 91
    assert got["x"]["score"] == 91
    assert got["x"]["composite_reported"] is None, "no composite in this reply"


def test_a_caller_supplied_score_wins_over_the_composite():
    """Requirement 19: the existing X/Y calculation must not be overridden."""
    def ask(q):
        return f"AI Mode conversation: {q}\n{q}\n" + LIVE

    got = S.score_company_detailed(
        "Acme", x_parameters=X, y_parameters=X, ask=ask, x_score=77
    )
    assert got["x"]["score"] == 77
    assert got["x"]["composite_reported"] == 91, "the composite is still recorded"


# --- batched: 5 companies per query, one query per axis --------------------
#
# One company per query costs ~460 paced queries for a 230-company market.
# Five per query costs ~92, and every one of those saved queries is also one
# fewer chance to draw a CAPTCHA or trip the AI-response quota.

COS = ["STMicroelectronics N.V.", "ROHM Co., Ltd.", "Wolfspeed, Inc."]
PARAMS = ["Substrate Quality", "Device Performance"]

BATCH_REPLY = """A. STMicroelectronics N.V.
1. Substrate Quality
Evidence: Acquired Norstel AB, now supplying 40% of its own wafers. https://www.st.com
Score: 90 / 100
2. Device Performance
Evidence: Gen 4 STPOWER MOSFETs cover 650V-2200V.
Score: 94 / 100
Composite Product Strength Score: 92 / 100
B. ROHM Co., Ltd.
1. Substrate Quality
Evidence: SiCrystal subsidiary in Germany supplies in-house substrate.
Score: 88 / 100
2. Device Performance
Evidence: 4th-gen trench MOSFETs with low on-resistance.
Score: 91 / 100
Composite Product Strength Score: 90 / 100
C. Wolfspeed, Inc.
1. Substrate Quality
Evidence: Mohawk Valley 200mm fab; 33.7% substrate share.
Score: 95 / 100
2. Device Performance
Evidence: Gen 4 devices under 1 failure per billion device hours.
Score: 92 / 100
Composite Product Strength Score: 93 / 100"""


def _batch_page(prompt: str) -> str:
    return f"AI Mode conversation: {prompt}\n{prompt}\n{BATCH_REPLY}"


def test_the_batch_query_letters_companies_and_numbers_parameters():
    q = S.build_batch_parameter_query(COS, "Product Strength", PARAMS, market="M")
    assert "A. STMicroelectronics N.V." in q
    assert "C. Wolfspeed, Inc." in q
    assert "1. Substrate Quality" in q


def test_the_batch_query_still_demands_evidence_and_a_composite():
    q = S.build_batch_parameter_query(COS, "Product Strength", PARAMS)
    assert "Evidence:" in q and "Score: NN / 100" in q
    assert "Composite Product Strength Score" in q
    assert "Do not invent a source or a figure" in q


def test_the_batch_query_shows_a_worked_example():
    """The load-bearing part: without a worked layout the model answers
    a multi-company question with a table of bare numbers and drops the
    evidence entirely."""
    q = S.build_batch_parameter_query(COS, "Product Strength", PARAMS)
    assert f"A. {COS[0]}" in q, "no worked example for the first company"
    assert f"B. {COS[1]}" in q, "the example must show a SECOND block"
    assert "Do not answer with a markdown table" in q
    assert "Do not skip a company" in q
    # Leading with the OUTPUT SHAPE is what stops the model answering a
    # multi-company ask with one summary paragraph about the market.
    assert q.startswith("Produce a SCORING TABLE")
    assert "do not answer in prose" in q


def test_the_batch_query_identifies_each_company():
    """A bare trading name got an abrasives maker judged on wafer
    parameters; in a batch that error repeats for every company."""
    q = S.build_batch_parameter_query(
        COS, "Product Strength", PARAMS,
        hq_by_company={COS[0]: "Geneva, Switzerland"},
        context_by_company={COS[0]: "Makes SiC power devices"},
    )
    assert "headquartered in Geneva, Switzerland" in q
    assert "Makes SiC power devices" in q


def test_the_batch_query_forbids_a_zero_for_a_different_segment():
    q = S.build_batch_parameter_query(COS, "Product Strength", PARAMS)
    assert "rather than giving 0" in q
    assert "between 1 and 100" in q


def test_the_batch_query_fits_the_url_budget():
    from vendor_intel.scraping.google_ai_mode import MAX_URL_CHARS, build_url

    many = [f"Some Long Company Name {i} Co., Ltd." for i in range(5)]
    q = S.build_batch_parameter_query(many, "Product Strength", X, market="Global X Market")
    assert len(build_url(q)) < MAX_URL_CHARS


def test_every_company_in_the_batch_is_parsed():
    q = S.build_batch_parameter_query(COS, "Product Strength", PARAMS)
    got = S.parse_batch_parameter_scores(_batch_page(q), COS, PARAMS, q)
    assert set(got) == set(COS)


def test_evidence_stays_with_the_right_company():
    """The failure that matters: one company's evidence attributed to another."""
    q = S.build_batch_parameter_query(COS, "Product Strength", PARAMS)
    got = S.parse_batch_parameter_scores(_batch_page(q), COS, PARAMS, q)
    st = got["STMicroelectronics N.V."]["parameters"]["Substrate Quality"]
    rohm = got["ROHM Co., Ltd."]["parameters"]["Substrate Quality"]
    assert "Norstel" in st["evidence"][0]["claim"]
    assert "SiCrystal" in rohm["evidence"][0]["claim"]
    assert "Norstel" not in rohm["evidence"][0]["claim"]


def test_each_company_keeps_its_own_composite():
    q = S.build_batch_parameter_query(COS, "Product Strength", PARAMS)
    got = S.parse_batch_parameter_scores(_batch_page(q), COS, PARAMS, q)
    assert got["STMicroelectronics N.V."]["composite"] == 92
    assert got["ROHM Co., Ltd."]["composite"] == 90
    assert got["Wolfspeed, Inc."]["composite"] == 93


def test_two_queries_per_batch_not_two_per_company():
    calls = []

    def ask(q):
        calls.append(q)
        return _batch_page(q)

    S.score_parameters_for_companies(
        COS, x_parameters=PARAMS, y_parameters=PARAMS, ask=ask, batch=5
    )
    assert len(calls) == 2, "one X query and one Y query for the whole batch"


def test_batching_splits_at_the_configured_size():
    """12 companies at batch 5 is 3 groups: [1-5], [6-10], [11-12].

    Asserted on the group SIZES the scorer asks for, which is what "batch
    size" means. Total query count is not the measure: a group whose batched
    reply omits a company is followed by a single-company retry for that
    company (see test_param_batch_fallback.py).
    """
    sizes = []

    def ask(q):
        # Count the "Companies:" block only. The worked example repeats
        # "A. <name>" further down, which would double the count.
        block = q.split("Companies:", 1)[-1].split("Score these", 1)[0]
        listed = re.findall(r"^[A-Z]\. (Co \d+)", block, re.M)
        if listed:
            sizes.append(len(listed))
        return _batch_page(q)

    many = [f"Co {i}" for i in range(12)]
    S.score_parameters_for_companies(
        many, x_parameters=PARAMS, y_parameters=PARAMS, ask=ask, batch=5
    )
    # Each group is asked once per axis, so every size appears twice.
    assert sizes == [5, 5, 5, 5, 2, 2], f"unexpected group sizes: {sizes}"


def test_the_result_matches_the_single_company_shape():
    """Callers and the HTML view model must not care which path produced it."""
    def ask(q):
        return _batch_page(q)

    got = S.score_parameters_for_companies(
        COS, x_parameters=PARAMS, y_parameters=PARAMS, ask=ask
    )
    rec = got["STMicroelectronics N.V."]
    assert set(rec) == {"x", "y"}
    assert rec["x"]["score"] == 92
    assert rec["x"]["axis"] == S.AXIS_X_LABEL
    assert rec["x"]["parameters"]["Substrate Quality"]["score"] == 90
    assert rec["x"]["evidence"], "aggregate evidence is the union of parameters"


def test_a_failed_axis_does_not_lose_the_other():
    calls = []

    def ask(q):
        calls.append(q)
        if len(calls) == 1:
            raise RuntimeError("quota")
        return _batch_page(q)

    got = S.score_parameters_for_companies(
        COS, x_parameters=PARAMS, y_parameters=PARAMS, ask=ask
    )
    assert got["STMicroelectronics N.V."]["x"]["score"] is None
    assert got["STMicroelectronics N.V."]["y"]["score"] == 92


def test_unnumbered_headings_still_parse():
    """Asked for "1. <name>", the model often renders just "<name>" and drops
    the numbering. Captured live 2026-09-17: a reply with five good scores
    and full evidence parsed as ZERO parameters because of it."""
    body = """Substrate & Epitaxy Quality
Evidence: SiC abrasive grains at 99.5% purity, P80 to P600, per IndiaMART.
Score: 75 / 100
Device Performance & Reliability
Evidence: Miki SiC Latex Waterproof Abrasive Sheet for wet and dry finishing.
Score: 72 / 100
Wafer Size & Defect Density
Evidence: Uniform grit sizing prevents uneven scratch defects.
Score: 70 / 100
R&D and Patent Strength
Evidence: In-house laboratory at Unjha, Gujarat.
Score: 65 / 100
Manufacturing Yield & Scalability
Evidence: Operational since 1985 with a structured manufacturing line.
Score: 68 / 100
Composite Product Strength Score: 70 / 100"""
    got = S._parse_parameters_prose(body, X)
    assert len(got) == 5
    assert [v["score"] for v in got.values()] == [75, 72, 70, 65, 68]
    assert "99.5% purity" in got["Substrate & Epitaxy Quality"]["evidence"][0]["claim"]


def test_a_niche_company_scores_on_its_own_segment():
    """The same company previously came back 0/100 for the whole axis."""
    body = """Substrate & Epitaxy Quality
Evidence: Industrial-grade SiC grains at 99.5% purity.
Score: 75 / 100
Composite Product Strength Score: 70 / 100"""
    got = S._parse_parameters_prose(body, X[:1])
    assert got["Substrate & Epitaxy Quality"]["score"] == 75


# --- axis-specific evidence ------------------------------------------------
#
# Asked the same way on both axes, the model answers Product Strength with
# named systems and figures but Business Strength with unfalsifiable phrases.
# Measured on a finished market: 45% of Business claims carried no number at
# all, against 15% of Product claims.


def test_the_business_axis_asks_for_commercial_facts():
    q = S.build_batch_parameter_query(COS, S.AXIS_Y_LABEL, PARAMS)
    for want in ("named customer", "revenue", "market share", "units shipped"):
        assert want in q.lower(), f"Business query never asks for {want!r}"


def test_the_business_axis_names_what_is_not_evidence():
    """Naming the failure mode is what stops it."""
    q = S.build_batch_parameter_query(COS, S.AXIS_Y_LABEL, PARAMS)
    assert "is NOT evidence" in q
    assert "strong partnerships" in q


def test_the_product_axis_keeps_its_own_definition():
    q = S.build_batch_parameter_query(COS, S.AXIS_X_LABEL, PARAMS)
    assert "named product or model" in q
    # The commercial wording belongs to the other axis and must not leak in.
    assert "units shipped" not in q


def test_the_two_axes_get_different_instructions():
    x = S.build_batch_parameter_query(COS, S.AXIS_X_LABEL, PARAMS)
    y = S.build_batch_parameter_query(COS, S.AXIS_Y_LABEL, PARAMS)
    assert S.evidence_hint(S.AXIS_X_LABEL) != S.evidence_hint(S.AXIS_Y_LABEL)
    assert S.evidence_hint(S.AXIS_X_LABEL) in x
    assert S.evidence_hint(S.AXIS_Y_LABEL) in y


def test_the_single_company_query_gets_the_hint_too():
    """Batched and single paths must agree, or a fallback retry would ask a
    materially different question than the batch it replaces."""
    q = S.build_parameter_score_query("Acme Ltd", S.AXIS_Y_LABEL, PARAMS)
    assert S.evidence_hint(S.AXIS_Y_LABEL) in q


def test_an_unknown_axis_adds_no_hint():
    assert S.evidence_hint("Something Else") == ""


# --- several findings per parameter ----------------------------------------
#
# The report renders each finding as its own bullet. Capturing a run of
# Evidence lines as ONE claim would collapse them back into a paragraph,
# which is the thing the multi-finding ask exists to avoid.

MULTI = """1. Substrate & Epitaxy Quality
Evidence: ST acquired Norstel AB and now supplies over 40% of its own wafers.
Evidence: The Catania campus runs a dedicated epitaxy line. https://www.st.com
Evidence: Qualified 200 mm substrates entered production in 2025.
Score: 92 / 100
2. Device Performance & Reliability
Evidence: Gen 4 STPOWER SiC MOSFETs cover 650V to 2200V.
Score: 94 / 100"""


def test_every_evidence_line_becomes_its_own_finding():
    got = S._parse_parameters_prose(MULTI, X)
    ev = got["Substrate & Epitaxy Quality"]["evidence"]
    assert len(ev) == 3, [e["claim"][:40] for e in ev]


def test_the_findings_keep_their_own_text():
    got = S._parse_parameters_prose(MULTI, X)
    claims = [e["claim"] for e in got["Substrate & Epitaxy Quality"]["evidence"]]
    assert "Norstel" in claims[0]
    assert "Catania campus" in claims[1]
    assert "200 mm substrates" in claims[2]


def test_a_single_finding_still_parses_as_one():
    got = S._parse_parameters_prose(MULTI, X)
    assert len(got["Device Performance & Reliability"]["evidence"]) == 1


def test_findings_stop_at_the_score_line():
    got = S._parse_parameters_prose(MULTI, X)
    for e in got["Substrate & Epitaxy Quality"]["evidence"]:
        assert "94 / 100" not in e["claim"]
        assert "Gen 4" not in e["claim"]


def test_a_repeated_finding_is_not_stored_twice():
    dupe = (
        "1. Substrate & Epitaxy Quality\n"
        "Evidence: ST acquired Norstel AB.\n"
        "Evidence: ST acquired Norstel AB.\n"
        "Score: 90 / 100"
    )
    got = S._parse_parameters_prose(dupe, X)
    assert len(got["Substrate & Epitaxy Quality"]["evidence"]) == 1


def test_the_old_single_line_shape_still_parses():
    """Replies predating the multi-finding ask must not break."""
    got = S._parse_parameters_prose(LIVE, X)
    assert len(got) == 5
    assert got["Substrate & Epitaxy Quality"]["evidence"]


def test_the_batch_query_demands_two_findings_per_parameter():
    q = S.build_batch_parameter_query(COS, "Product Strength", PARAMS)
    assert "a SECOND, different finding" in q
    assert "AT LEAST TWO Evidence lines" in q
    assert "must be a DIFFERENT fact" in q
