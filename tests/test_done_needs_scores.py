"""A market is only "done" when its rows are SCORED.

Silicon Carbide was marked status=done with 231 verified companies and zero
X/Y scores: an AI Mode quota block wiped out the scoring step, the run wrote
the report anyway, and every later attempt to rescore hit the done-check and
exited in 0 minutes:

    [chatgpt] SKIP done market: 'Global Silicon Carbide Market'
    === DONE Global Silicon Carbide Market: ok, 230 companies, 0 min ===

A market with rows but no scores has not finished — it has failed quietly.
"""
from __future__ import annotations

import inspect

from vendor_intel.pipeline import chatgpt_expand as ce


class _Ckpt:
    def __init__(self, data):
        self.state = {"data": data}


def test_rows_without_scores_are_not_done():
    ck = _Ckpt({"final_kept": [{"Company": "A"}, {"Company": "B"}]})
    assert ce._checkpoint_has_scores(ck) is False


def test_a_partially_scored_market_is_not_done():
    """Regression: AI Mode dropped out part-way through an India run and 4 of
    11 companies were left unscored. Accepting the first score marked the
    market done, so those 4 were never retried and shipped as blank cells
    outside every quadrant."""
    ck = _Ckpt({"final_kept": [{"Company": "A"}, {"Company": "B", "X Score": "72"}]})
    assert ce._checkpoint_has_scores(ck) is False


def test_a_fully_scored_market_is_done():
    ck = _Ckpt({"final_kept": [{"Company": "A", "X Score": "65"},
                               {"Company": "B", "X Score": "72"}]})
    assert ce._checkpoint_has_scores(ck) is True


def test_the_detail_sheet_column_name_also_counts():
    """The report sheet calls it "X", the landscape sheet "X Score"."""
    assert ce._checkpoint_has_scores(_Ckpt({"detail_rows": [{"X": "64"}]})) is True


def test_a_blank_score_string_does_not_count():
    ck = _Ckpt({"final_kept": [{"Company": "A", "X Score": ""},
                               {"Company": "B", "X Score": "   "}]})
    assert ce._checkpoint_has_scores(ck) is False


def test_an_empty_checkpoint_is_not_scored():
    assert ce._checkpoint_has_scores(_Ckpt({})) is False


def test_the_done_skip_consults_the_score_check():
    """Guard: the skip must not go back to trusting the flag alone."""
    src = inspect.getsource(ce.expand_market_async) if hasattr(
        ce, "expand_market_async"
    ) else inspect.getsource(ce)
    assert "_checkpoint_has_scores(ckpt)" in src
    assert "ckpt.is_done() and not _checkpoint_has_scores(ckpt)" in src


def test_an_unscored_done_market_is_reset_to_scoring():
    src = inspect.getsource(ce)
    block = src.split("ckpt.is_done() and not _checkpoint_has_scores(ckpt)", 1)[1][:700]
    assert '"6c_xy"' in block, "it must resume at scoring, not re-discover"
    assert '"running"' in block


def test_the_reset_keeps_completed_as_a_dict():
    """`completed` is a dict of step -> True. Replacing it with a bool
    crashed a run with "'bool' object has no attribute 'get'" and reset the
    market to step 0, losing the resume position for 231 companies."""
    src = inspect.getsource(ce)
    block = src.split("ckpt.is_done() and not _checkpoint_has_scores(ckpt)", 1)[1][:900]
    assert "isinstance(done, dict)" in block
    assert "completed" in block


def test_the_reset_keeps_the_earlier_steps():
    """Only scoring and export are cleared — re-verifying 231 companies would
    cost hundreds of paced queries for no reason."""
    src = inspect.getsource(ce)
    block = src.split("ckpt.is_done() and not _checkpoint_has_scores(ckpt)", 1)[1][:900]
    assert '("6c", "6d", "7")' in block
