"""Scope audit — catching companies the wider web says are in a different market.

Every string below is from a real North America run: 21 exported "rupture disc"
companies turned out to be brake-pad brands, gauge makers and MRO distributors
that cleared every per-company gate.
"""
from __future__ import annotations

import pytest

from vendor_intel.pipeline.scope_audit import (
    Verdict,
    adjudicate,
    apply_audit,
    audit_rows,
    screen,
)


# ── the cheap screen ──────────────────────────────────────────────────────
@pytest.mark.parametrize("text", [
    "Textar does not operate in the rupture disc market. Textar is an automotive brand.",
    "Noshok does not manufacture or operate in the rupture disc market.",
    "GASHER does not operate as a major manufacturer within the global rupture disc market.",
    "There appears to be a false premise in your question.",
    "There is a slight misunderstanding in the premise of your question.",
    "Vipond Controls does not operate as a direct participant in the rupture disc market.",
])
def test_screen_flags_real_negatives(text):
    is_candidate, trigger = screen(text)
    assert is_candidate is True
    assert trigger


@pytest.mark.parametrize("text", [
    "Fike Corporation is a global leader in rupture discs and overpressure protection.",
    "BS&B Safety Systems manufactures rupture discs for industrial applications.",
    "ZOOK Enterprises produces reverse-buckling rupture discs.",
])
def test_screen_passes_real_companies(text):
    assert screen(text)[0] is False


def test_screen_rescues_distributors():
    """"does not manufacture, but distributes" is a real value-chain role."""
    text = ("Setpoint Technologies does not manufacture rupture discs, but distributes "
            "and services them for process plants across Canada.")
    is_candidate, trigger = screen(text)
    assert is_candidate is False, "a distributor must not be screened as out of scope"
    assert trigger, "the negative phrase is still reported for transparency"


def test_screen_rescues_material_suppliers():
    text = ("ATI Metals does not manufacture finished rupture discs. Instead it supplies "
            "the nickel alloys used to produce them.")
    assert screen(text)[0] is False


def test_screen_returns_the_triggering_sentence():
    text = ("Acme is a large company. Acme does not operate in the rupture disc market. "
            "It was founded in 1950.")
    _, trigger = screen(text)
    assert trigger.startswith("Acme does not operate")


def test_empty_evidence_is_not_a_candidate():
    assert screen("")[0] is False
    assert screen(None)[0] is False


# ── adjudication ──────────────────────────────────────────────────────────
class _Client:
    def __init__(self, payload, available=True):
        self.payload, self.available = payload, available
    def complete_json(self, *a, **k):
        return self.payload


def test_adjudicator_verdict_is_used():
    v = adjudicate("Textar", "Rupture Disc Market", "Manufacturers", "…", "trigger",
                   client=_Client({"verdict": "out_of_scope", "confidence": 0.95,
                                   "reason": "automotive brake brand"}))
    assert v.verdict == "out_of_scope" and v.confidence == 0.95


def test_adjudicator_can_overrule_the_screen():
    """The screen is a filter, not a verdict — the LLM may keep a distributor."""
    v = adjudicate("Setpoint", "Rupture Disc Market", "Distributors", "…", "trigger",
                   client=_Client({"verdict": "in_scope", "confidence": 0.9,
                                   "reason": "distributes rupture discs"}))
    assert v.verdict == "in_scope"


def test_no_llm_never_yields_a_droppable_verdict():
    v = adjudicate("Acme", "M", "", "…", "trigger", client=None)
    assert v.verdict == "unclear" and v.confidence < 0.7


def test_bad_adjudicator_output_is_unclear_not_out_of_scope():
    for payload in ({"verdict": "nonsense"}, {"verdict": "out_of_scope", "confidence": "x"}, None):
        v = adjudicate("Acme", "M", "", "…", "t", client=_Client(payload))
        assert v.verdict in ("unclear", "out_of_scope")
        if v.verdict == "out_of_scope":
            assert v.confidence == 0.0, "unparseable confidence must not clear the threshold"


def test_adjudicator_exception_is_contained():
    class Boom:
        available = True
        def complete_json(self, *a, **k): raise RuntimeError("timeout")
    v = adjudicate("Acme", "M", "", "…", "t", client=Boom())
    assert v.verdict == "unclear"


# ── applying verdicts ─────────────────────────────────────────────────────
def test_apply_drops_only_the_named_companies():
    rows = [{"company": "Fike"}, {"company": "Textar"}, {"company": "BS&B Safety Systems"}]
    out = [Verdict("Textar", "out_of_scope", 0.95, "brake brand", "…", "http://x")]
    kept, dropped = apply_audit(rows, out)
    assert [r["company"] for r in kept] == ["Fike", "BS&B Safety Systems"]
    assert dropped[0]["export_reject"].startswith("out_of_scope:")
    assert dropped[0]["scope_evidence_url"] == "http://x"


def test_apply_matches_on_a_normalised_name():
    rows = [{"company": "ATI Metals, Inc."}]
    kept, dropped = apply_audit(rows, [Verdict("ati metals inc", "out_of_scope", 1.0, "r")])
    assert len(dropped) == 1 and kept == []


def test_audit_skips_companies_without_cached_evidence(tmp_path, monkeypatch):
    """No evidence must mean no verdict — never an implicit rejection."""
    monkeypatch.setenv("AI_OVERVIEW_CACHE_DIR", str(tmp_path))
    from vendor_intel.evidence.ai_overview import AiOverviewStore

    verdicts, out = audit_rows(
        [{"company": "Unknown Co"}], "Rupture Disc Market",
        store=AiOverviewStore(tmp_path),
    )
    assert verdicts == [] and out == []


def test_low_confidence_verdicts_are_not_dropped(tmp_path):
    from vendor_intel.evidence.ai_overview import AiOverviewStore, Question

    store = AiOverviewStore(tmp_path)
    store.put(Question(text="What does Textar do in the M?", market="M"),
              "Textar does not operate in the M. Textar is a brake brand.")
    verdicts, out = audit_rows([{"company": "Textar"}], "M", store=store, min_confidence=0.7)
    assert len(verdicts) == 1
    assert out == [], "no LLM configured -> unclear -> must not be auto-dropped"
