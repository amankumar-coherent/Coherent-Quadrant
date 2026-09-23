"""Score 30 companies per query, not one.

Two queries per batch (X and Y) instead of two per company takes a
230-company market from ~460 paced queries to ~16. The saving is not only
time: every query is a chance to draw a CAPTCHA or trip the AI-response
quota, and those blocks repeatedly destroyed whole scoring runs.
"""
from __future__ import annotations

from vendor_intel.quadrant import ai_mode_scorer as s

NAMES = ["Wolfspeed, Inc.", "STMicroelectronics N.V.", "Elfusa Geral de Eletrofusão Ltda"]
X = ["Substrate Quality", "Device Performance"]
Y = ["Market Share", "Revenue Growth"]


def _page(reply: str, prompt: str) -> str:
    return f"AI Mode conversation: {prompt}\n{prompt}\n{reply}"


# --- the query -------------------------------------------------------------


def test_the_batch_query_numbers_every_company():
    q = s.build_batch_score_query(NAMES, "Product Strength", X, market="M")
    assert "1. Wolfspeed, Inc." in q
    assert "3. Elfusa Geral de Eletrofusão Ltda" in q


def test_the_reply_is_keyed_by_number_not_name():
    """AI Mode reformats names ("Co., Ltd." -> "Co Ltd"), so matching a
    returned name back to the row silently loses companies. An index cannot
    drift."""
    q = s.build_batch_score_query(NAMES, "Product Strength", X, market="M")
    assert '"scores":{"1":72' in q.replace(" ", "")


def test_the_batch_query_keeps_the_parameters_and_market():
    q = s.build_batch_score_query(NAMES, "Product Strength", X, market="Global SiC Market")
    assert "Substrate Quality" in q and "Device Performance" in q
    assert "Global SiC Market" in q
    assert "Product Strength" in q


def test_the_batch_query_fits_the_url_budget():
    """30 real-length names must stay well inside Google's ~8 KB ceiling."""
    from vendor_intel.scraping.google_ai_mode import MAX_URL_CHARS, build_url

    many = [f"Some Fairly Long Company Name {i} Co., Ltd." for i in range(30)]
    q = s.build_batch_score_query(many, "Product Strength", X, market="Global X Market")
    assert len(build_url(q)) < MAX_URL_CHARS


# --- parsing ---------------------------------------------------------------


def test_scores_map_back_to_the_right_companies():
    q = "PROMPT"
    got = s.parse_batch_scores(_page('{"scores":{"1":88,"2":91,"3":25}}', q), NAMES, q)
    assert got == {NAMES[0]: 88, NAMES[1]: 91, NAMES[2]: 25}


def test_null_leaves_a_company_unscored():
    """A gap is honest; a zero would be fabricated."""
    q = "PROMPT"
    got = s.parse_batch_scores(_page('{"scores":{"1":88,"2":null,"3":25}}', q), NAMES, q)
    assert NAMES[1] not in got
    assert got[NAMES[0]] == 88


def test_quoted_and_decimal_numbers_parse():
    q = "PROMPT"
    got = s.parse_batch_scores(_page('{"scores":{"1":"88","2":45.6}}', q), NAMES, q)
    assert got[NAMES[0]] == 88
    assert got[NAMES[1]] == 45


def test_zero_is_rejected_in_a_batch_too():
    """0 means "I decline", and it normalises to a fabricated 65."""
    q = "PROMPT"
    got = s.parse_batch_scores(_page('{"scores":{"1":0,"2":70}}', q), NAMES, q)
    assert NAMES[0] not in got
    assert got[NAMES[1]] == 70


def test_out_of_range_indexes_are_ignored():
    q = "PROMPT"
    got = s.parse_batch_scores(_page('{"scores":{"9":50,"0":40,"1":60}}', q), NAMES, q)
    assert got == {NAMES[0]: 60}


def test_json_surrounded_by_prose_parses():
    q = "PROMPT"
    reply = 'Here are the scores:\n{"scores":{"1":77}}\nShow Code'
    assert s.parse_batch_scores(_page(reply, q), NAMES, q) == {NAMES[0]: 77}


def test_an_unparseable_reply_yields_nothing():
    q = "PROMPT"
    assert s.parse_batch_scores(_page("I cannot help with that.", q), NAMES, q) == {}
    assert s.parse_batch_scores("", NAMES, q) == {}


# --- the driver ------------------------------------------------------------


def test_two_queries_per_batch_not_two_per_company():
    calls = []

    def ask(q):
        calls.append(q)
        return _page('{"scores":{"1":80,"2":70,"3":30}}', q)

    got = s.score_companies(NAMES, x_parameters=X, y_parameters=Y, ask=ask, market="M")
    assert len(calls) == 2, "one X query and one Y query for the whole batch"
    assert got[NAMES[0]] == (80, 80)
    assert got[NAMES[2]] == (30, 30)


def test_batching_splits_at_the_configured_size():
    calls = []

    def ask(q):
        calls.append(q)
        return _page('{"scores":{"1":50}}', q)

    many = [f"Co {i}" for i in range(7)]
    s.score_companies(many, x_parameters=X, y_parameters=Y, ask=ask, market="M", batch=3)
    assert len(calls) == 6, "3 batches x 2 axes"


def test_a_failed_batch_does_not_lose_the_others():
    calls = []

    def ask(q):
        calls.append(q)
        if len(calls) == 1:
            raise RuntimeError("quota")
        return _page('{"scores":{"1":60,"2":60,"3":60}}', q)

    got = s.score_companies(NAMES, x_parameters=X, y_parameters=Y, ask=ask, market="M")
    # X failed, Y succeeded: X is None, Y is kept rather than the row dropped.
    assert got[NAMES[0]][0] is None
    assert got[NAMES[0]][1] == 60


def test_every_requested_company_appears_in_the_result():
    def ask(q):
        return _page('{"scores":{"1":40}}', q)

    got = s.score_companies(NAMES, x_parameters=X, y_parameters=Y, ask=ask)
    assert set(got) == set(NAMES)
    assert got[NAMES[1]] == (None, None)
