"""Parse the ANSWER, not the page it arrived on.

AI Mode returns the whole rendered page: nav chrome, the prompt echoed twice
("AI Mode conversation: <prompt>" then the bubble), then the reply. Every part
carries digits, so parsing the raw text scored the furniture:

* four different companies all scored 10 (a nav digit) — Wolfspeed is not a 10
* a refusal scored 100, lifted from the prompt's own "score out of 100"

Captured from a live run on 2026-09-12.
"""
from __future__ import annotations

from vendor_intel.quadrant.ai_mode_scorer import answer_body, parse_score

PROMPT = (
    "Provide a single, consolidated Product Strength score out of 100 for the "
    "company Elfusa Geral de Eletrofusao Ltda in the Global Silicon Carbide "
    "Market. Reply with ONLY the number."
)
CHROME = (
    "Skip to main content\nAccessibility help\nAI Mode\nAll\nImages\nVideos\n"
    "News\nMore\n(https://www.google.co.in/intl/en/about/products?tab=wh)\n"
    "Sign in\n"
)


def _page(reply: str) -> str:
    """The real page shape: chrome, prompt echoed twice, then the reply."""
    return f"{CHROME}AI Mode conversation: {PROMPT}\n{PROMPT}\n{reply}"


def test_the_body_is_only_the_reply():
    assert answer_body(_page("24"), PROMPT) == "24"


def test_a_bare_number_answer_parses():
    """The score the user saw on screen for this exact company."""
    assert parse_score(_page("24"), PROMPT) == 24


def test_nav_chrome_is_not_a_score():
    """The bug that gave four different companies the same 10."""
    assert parse_score(_page("UNKNOWN"), PROMPT) is None


def test_the_prompts_own_out_of_100_is_not_a_score():
    """The bug that turned a refusal into a perfect 100."""
    refusal = (
        'There is no standardized or publicly published single "Product '
        'Strength score out of 100" for Elfusa Geral de Eletrofusao Ltda, as '
        "proprietary market research evaluations assign confidential metrics."
    )
    assert parse_score(_page(refusal), PROMPT) is None


def test_a_real_answer_inside_prose_still_parses():
    assert parse_score(_page("The score is 62 out of 100."), PROMPT) == 62


def test_parsing_still_works_without_the_prompt():
    """Older callers pass only the answer; chrome must still be stripped."""
    assert parse_score(f"{CHROME}47") == 47


def test_an_empty_body_is_not_a_score():
    assert parse_score(_page(""), PROMPT) is None
    assert answer_body(CHROME, PROMPT) == ""


def test_the_ready_marker_does_not_break_a_bare_number():
    """The page appends "AI Mode response is ready" AFTER the reply, so "88"
    arrives as "88 AI Mode response is ready" and stops looking like a bare
    number. Live capture: Wolfspeed scored 88 and parsed as None."""
    assert answer_body(_page("88 AI Mode response is ready"), PROMPT) == "88"
    assert parse_score(_page("88 AI Mode response is ready"), PROMPT) == 88


def test_the_flattened_prompt_echo_is_removed():
    """The echo is the whole multi-line prompt rendered as ONE line with the
    newlines collapsed, so line-by-line matching never saw it."""
    multi = "Score X out of 100.\nUse 1-100.\nReply with the number."
    flat_echo = "Score X out of 100. Use 1-100. Reply with the number."
    page = f"{CHROME}AI Mode conversation: {flat_echo}\n{flat_echo}\n42"
    assert answer_body(page, multi) == "42"
    assert parse_score(page, multi) == 42


def test_small_companies_score_low_rather_than_refusing():
    """Live smoke test, 2026-09-12: Wolfspeed 90, STMicro 88, Adesis 28,
    Elfusa 25, Abasco 5 — leaders high, small regional producers low, and the
    two non-English names scored normally."""
    for reply, expected in (("90", 90), ("88", 88), ("28", 28), ("25", 25), ("5", 5)):
        assert parse_score(_page(f"{reply} AI Mode response is ready"), PROMPT) == expected


# --- furniture rendered AFTER the answer -----------------------------------
#
# Captured live 2026-09-13 by logging the unparsed replies. Every one of these
# was a REAL score being discarded, so scoring reported "AI Mode unavailable"
# for 3 of every 4 companies while AI Mode was answering perfectly well.


def test_show_code_after_the_number():
    assert parse_score(_page("20.4 Show Code"), PROMPT) == 20
    assert parse_score(_page("1 Show Code"), PROMPT) == 1


def test_the_ai_disclaimer_after_the_number():
    reply = (
        "43 AI responses may include mistakes. For financial advice, consult "
        "a professional. Learn more"
    )
    assert parse_score(_page(reply), PROMPT) == 43


def test_stacked_furniture_is_all_removed():
    assert parse_score(_page("90 Show more Sources"), PROMPT) == 90


def test_a_decimal_average_parses():
    """Averaging five integer ratings legitimately gives 20.4; the score is
    the whole part, not a parse failure."""
    assert parse_score(_page("20.4"), PROMPT) == 20
    assert parse_score(_page("65.8"), PROMPT) == 65


def test_a_decimal_zero_is_still_a_refusal():
    assert parse_score(_page("0.0"), PROMPT) is None


def test_unknown_still_refuses_after_the_noise_stripping():
    assert parse_score(_page("UNKNOWN"), PROMPT) is None
