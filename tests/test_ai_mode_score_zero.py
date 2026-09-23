"""A bare "0" from AI Mode is "I have never heard of this company", not a score.

Observed live:

    Provide a single, consolidated Product Strength score out of 100 for
    Abasco Trading Pty Ltd ...
    0

Taken literally this was actively harmful. normalize_row_score_floor(0, 0)
returns (65, 65), so a company AI Mode knew nothing about was promoted to a
mid-tier score and placed in a quadrant, indistinguishable from one that had
genuinely been assessed.
"""
from __future__ import annotations

from vendor_intel.quadrant import ai_mode_scorer as s
from vendor_intel.quadrant.matrix_rollup import normalize_row_score_floor


# --- the defect ------------------------------------------------------------


def test_a_bare_zero_is_not_a_score():
    assert s.parse_score("0") is None


def test_zero_out_of_100_is_not_a_score():
    assert s.parse_score("0 out of 100") is None
    assert s.parse_score("The score is 0.") is None
    assert s.parse_score("**0**") is None


def test_why_a_zero_mattered():
    """The consequence that made this worth fixing rather than tolerating."""
    assert normalize_row_score_floor(0, 0) == (65, 65)


def test_real_scores_still_parse():
    assert s.parse_score("72") == 72
    assert s.parse_score("72 out of 100") == 72
    assert s.parse_score("The score is 85.") == 85
    assert s.parse_score("**91**") == 91
    assert s.parse_score("64/100") == 64


def test_the_lowest_real_score_is_kept():
    """1 is a legitimate (if brutal) assessment; only 0 is the refusal."""
    assert s.parse_score("1 out of 100") == 1


def test_100_is_kept():
    assert s.parse_score("100 out of 100") == 100


# --- explicit refusals -----------------------------------------------------


def test_the_word_unknown_is_a_refusal():
    assert s.parse_score("UNKNOWN") is None
    assert s.parse_score("Unknown") is None


def test_prose_refusals_are_caught_even_with_digits():
    """A refusal often still contains "100" from the question itself."""
    for reply in (
        "I do not have enough information to score this company out of 100.",
        "There is insufficient information about this specific company.",
        "No public information is available for this company.",
        "I cannot determine a score out of 100 for this company.",
        "Unable to assess: no reliable data.",
    ):
        assert s.parse_score(reply) is None, reply


def test_an_unparseable_answer_is_none():
    assert s.parse_score("") is None
    assert s.parse_score("Here is some prose with no number at all.") is None


# --- the query must offer a way out ----------------------------------------


def test_the_query_allows_unknown():
    """There must be a way out other than inventing a number — otherwise the
    model answers 0, which normalises to a fabricated 65."""
    q = s.build_score_query("Abasco Trading Pty Ltd", "Product Strength", ["A", "B"])
    assert "UNKNOWN" in q


def test_a_low_score_is_permitted():
    """Without this an obscure company is answered "0" — which normalises to
    a fabricated 65 — or "UNKNOWN". It grants permission; it does not grade."""
    q = s.build_score_query("Small Co", "Product Strength", ["A"])
    assert "A low score is a valid answer" in q


def test_the_query_still_names_company_axis_and_parameters():
    q = s.build_score_query("Wolfspeed", "Product Strength", ["Wafer Quality", "Yield"])
    assert "Wolfspeed" in q
    assert "Product Strength" in q
    assert "Wafer Quality" in q and "Yield" in q


# --- end to end ------------------------------------------------------------


def test_a_zero_answer_leaves_the_company_unscored():
    x, y = s.score_company("Abasco Trading Pty Ltd", x_parameters=["A"],
                           y_parameters=["B"], ask=lambda q: "0")
    assert x is None and y is None


def test_a_real_answer_scores():
    x, y = s.score_company("Wolfspeed", x_parameters=["A"],
                           y_parameters=["B"], ask=lambda q: "88 out of 100")
    assert x == 88 and y == 88


# --- the mirror-image defect: a refusal parsed as a perfect 100 ------------


def test_a_refusal_is_not_a_perfect_score():
    """Found in the live checkpoint: an obscure Iranian producer scored
    100/100. The "score ... NN" pattern was grabbing the 100 out of the
    question's own "score out of 100" wording."""
    assert s.parse_score("Score out of 100: not available") is None
    assert s.parse_score("Product Strength score out of 100: N/A") is None
    assert s.parse_score("Score out of 100: no data") is None


def test_a_genuine_100_still_parses():
    """Over-correcting would cap every market leader at nothing."""
    assert s.parse_score("100") == 100
    assert s.parse_score("The score is 100 out of 100.") == 100
    assert s.parse_score("100 out of 100") == 100


# --- UNKNOWN was too easy to reach ----------------------------------------


def test_the_query_names_the_market():
    """Without the market, "Product Strength" has no yardstick and a small
    regional producer reads as unanswerable rather than simply low."""
    q = s.build_score_query("X Ltd", "Product Strength", ["A"],
                            market="Global Silicon Carbide Market")
    assert "in the Global Silicon Carbide Market" in q


def test_the_query_carries_the_company_description():
    """A non-English legal name alone is ambiguous; discovery already knows
    what the company does, so the scorer says so."""
    q = s.build_score_query(
        "Adesis Vakum ve Yari Iletken Teknolojileri San. Tic. Ltd. Sti.",
        "Product Strength", ["A"],
        market="Global Silicon Carbide Market",
        context="Manufactures thin SiC discs and substrate wafers.",
    )
    assert "About this company: Manufactures thin SiC discs" in q


def test_there_is_no_scoring_guide_only_the_parameters():
    """The five parameters ARE the rubric — they are generated per market for
    exactly this purpose. Any general band table pulls the answer toward a
    size or reputation judgement instead of the parameters themselves."""
    q = s.build_score_query("X Ltd", "Product Strength", ["A"])
    assert "Rate each parameter from 1 to 100" in q
    # No band table, in any of its past wordings.
    for banned in (
        "Scoring guide", "Per-parameter scale", "global leader",
        "niche producer", "best-in-class", "80-100", "60-79", "1-19",
        "adequate/mid-range", "market presence",
    ):
        assert banned not in q, f"scoring guide leaked back in: {banned!r}"


def test_unknown_is_narrowed_to_unidentifiable_companies():
    q = s.build_score_query("X Ltd", "Product Strength", ["A"])
    assert "Reply UNKNOWN only if you cannot identify this company at all" in q


def test_the_query_works_without_market_or_context():
    """Both are optional — an older caller must still produce a valid ask."""
    q = s.build_score_query("X Ltd", "Product Strength", ["A", "B"])
    assert "X Ltd" in q and "Product Strength" in q
    assert "in the " not in q
    assert "About this company:" not in q


def test_market_and_context_reach_the_backend():
    seen = []

    def ask(q):
        seen.append(q)
        return "35"

    x, y = s.score_company("Adesis", x_parameters=["A"], y_parameters=["B"],
                           ask=ask, market="Global Silicon Carbide Market",
                           context="Makes SiC wafers in Ankara.")
    assert (x, y) == (35, 35)
    assert all("Global Silicon Carbide Market" in q for q in seen)
    assert all("Makes SiC wafers in Ankara." in q for q in seen)


def test_unknown_still_leaves_the_row_unscored():
    """Narrowing UNKNOWN must not stop it working when genuinely returned."""
    x, y = s.score_company("Nonexistent Co", x_parameters=["A"],
                           y_parameters=["B"], ask=lambda q: "UNKNOWN")
    assert x is None and y is None


# --- a bare 0 is a decline: ask once more ---------------------------------
#
# Live 2026-09-13: NXP Semiconductors N.V. came back "0" while scoring Silicon
# Carbide. These companies already passed market verification, so dropping the
# row loses a real participant — 29 rows went that way in one pass.


def _page(reply: str, prompt: str) -> str:
    return f"AI Mode conversation: {prompt}\n{prompt}\n{reply}"


def test_a_zero_reply_is_retried_and_can_recover():
    calls = []

    def ask(q):
        calls.append(q)
        return _page("0" if len(calls) == 1 else "55", q)

    got = s.score_axis("NXP Semiconductors N.V.", "Product Strength",
                       ["A", "B"], ask=ask, market="M")
    assert got == 55
    assert len(calls) == 2, "exactly one retry"
    assert "0 is NOT a valid answer" in calls[1]


def test_the_retry_still_allows_unknown():
    """The nudge must not push the model into inventing a number."""
    calls = []

    def ask(q):
        calls.append(q)
        return _page("0" if len(calls) == 1 else "UNKNOWN", q)

    assert s.score_axis("X", "Product Strength", ["A"], ask=ask) is None
    assert "or UNKNOWN" in calls[1]


def test_unknown_is_not_retried():
    """UNKNOWN is a considered answer, not a decline — retrying wastes a
    paced query per company."""
    calls = []

    def ask(q):
        calls.append(q)
        return _page("UNKNOWN", q)

    assert s.score_axis("X", "Product Strength", ["A"], ask=ask) is None
    assert len(calls) == 1


def test_a_decimal_zero_also_retries():
    calls = []

    def ask(q):
        calls.append(q)
        return _page("0.0" if len(calls) == 1 else "31", q)

    assert s.score_axis("X", "Product Strength", ["A"], ask=ask) == 31


def test_a_real_score_is_never_retried():
    calls = []

    def ask(q):
        calls.append(q)
        return _page("72", q)

    assert s.score_axis("X", "Product Strength", ["A"], ask=ask) == 72
    assert len(calls) == 1
