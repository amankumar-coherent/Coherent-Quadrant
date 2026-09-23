"""Step 6a (final verify) is off, and the parse contract it broke is fixed.

Observed live on Silicon Carbide:

    · final-1: AI Mode JSON parse OK — 1 CAPTCHAs this run
    → substep 6a.1: empty/invalid JSON — DROP chunk (fail closed)

Both lines are about the same reply. The parser was called without
require_key, so ANY JSON counted as success; the caller then looked for
"results", found nothing, and failed closed. 16 chunks would have deleted all
152 verified companies while every log line claimed success.
"""
from __future__ import annotations

import inspect

from vendor_intel.pipeline import chatgpt_expand as ce


def test_final_verify_is_off_by_default(monkeypatch):
    monkeypatch.delenv("EXPAND_FINAL_VERIFY", raising=False)
    assert ce._final_verify_enabled() is False


def test_final_verify_can_be_restored(monkeypatch):
    monkeypatch.setenv("EXPAND_FINAL_VERIFY", "true")
    assert ce._final_verify_enabled() is True


# --- the actual defect -----------------------------------------------------


def test_both_verify_passes_require_the_results_key():
    """A reply must be retried when it lacks the key the caller reads, not
    accepted as "parse OK" and then thrown away."""
    src = inspect.getsource(ce)
    for label in ('label=f"verify-{idx}"', 'label=f"final-{idx}"'):
        assert label in src
        after = src.split(label, 1)[1][:400]
        assert 'require_key="results"' in after, f"{label} must require results"


def test_a_reply_without_results_is_treated_as_missing():
    """The guard that require_key feeds."""
    assert ce._json_missing_required({"companies": [1]}, "results") is True
    assert ce._json_missing_required({"results": []}, "results") is True
    assert ce._json_missing_required({"results": [{"Company": "X"}]}, "results") is False


def test_discovery_already_required_its_key():
    """Discovery never had the bug — it is the reference behaviour."""
    src = inspect.getsource(ce)
    after = src.split('require_key="companies"', 1)
    assert len(after) > 1
