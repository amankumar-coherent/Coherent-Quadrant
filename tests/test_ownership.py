"""Acquisition / merger detection and name annotation."""
from __future__ import annotations

import pytest

from vendor_intel.pipeline.ownership import (
    Ownership,
    annotate,
    detect,
    enqueue_questions,
    extract,
    ownership_question,
    screen,
)


# ── the screen ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("text", [
    "Oseco was acquired by Halma plc in 2019.",
    "Crosby Valve is now a wholly-owned subsidiary of Emerson Electric.",
    "Elfab merged with Oseco to form OsecoElfab.",
    "The company was purchased by a private equity group.",
    "Continental Disc Corporation is owned by Wynnchurch Capital.",
    "The brand now trades as OsecoElfab.",
])
def test_screen_flags_completed_deals(text):
    assert screen(text)[0] is True


@pytest.mark.parametrize("text", [
    "Fike Corporation is an independent family-owned business.",
    "BS&B Safety Systems manufactures rupture discs worldwide.",
])
def test_screen_ignores_ordinary_descriptions(text):
    assert screen(text)[0] is False


@pytest.mark.parametrize("text", [
    "Acme plans to acquire a competitor next year.",
    "The company agreed to acquire a rival, pending regulatory approval.",
    "Acme is reportedly in talks to be acquired.",
])
def test_screen_ignores_deals_that_have_not_closed(text):
    assert screen(text)[0] is False


def test_screen_returns_the_triggering_sentence():
    _, trigger = screen("Oseco makes discs. Oseco was acquired by Halma plc in 2019. It is UK based.")
    assert "acquired by Halma" in trigger


# ── extraction ────────────────────────────────────────────────────────────
class _Client:
    def __init__(self, payload, available=True):
        self.payload, self.available = payload, available
    def complete_json(self, *a, **k):
        return self.payload


def test_extract_builds_the_annotation():
    o = extract("Oseco", "…", "trigger", client=_Client(
        {"owned": True, "owner": "Halma plc", "relation": "acquired_by",
         "year": "2019", "confidence": 0.95}))
    assert o.owner == "Halma plc"
    assert o.suffix == "(acquired by Halma plc, 2019)"


def test_suffix_wording_follows_the_relation():
    assert Ownership("A", "B", "merged_into").suffix == "(merged into B)"
    assert Ownership("A", "B", "subsidiary_of").suffix == "(subsidiary of B)"
    assert Ownership("A", "B", "acquired_by", "2020").suffix == "(acquired by B, 2020)"


def test_acquirer_is_not_treated_as_acquired():
    """"Fike acquired a competitor" must not annotate Fike as owned."""
    assert extract("Fike", "…", "t", client=_Client({"owned": False})) is None


def test_company_owning_itself_is_rejected():
    assert extract("Halma", "…", "t", client=_Client(
        {"owned": True, "owner": "Halma", "confidence": 1.0})) is None


def test_no_llm_never_invents_an_owner():
    assert extract("Oseco", "…", "trigger", client=None) is None


def test_unparseable_confidence_does_not_clear_the_threshold():
    o = extract("Oseco", "…", "t", client=_Client(
        {"owned": True, "owner": "Halma", "confidence": "very"}))
    assert o is not None and o.confidence == 0.0


# ── annotation ────────────────────────────────────────────────────────────
def test_annotate_appends_and_preserves_the_raw_name():
    rows = [{"company": "Oseco"}, {"company": "Fike"}]
    n = annotate(rows, [Ownership("Oseco", "Halma plc", "acquired_by", "2019", 0.95)])
    assert n == 1
    assert rows[0]["company"] == "Oseco (acquired by Halma plc, 2019)"
    assert rows[0]["company_raw"] == "Oseco", "raw name must survive for joins and dedupe"
    assert rows[0]["parent_owner"] == "Halma plc"
    assert rows[1]["company"] == "Fike"


def test_annotate_is_idempotent():
    rows = [{"company": "Oseco"}]
    own = [Ownership("Oseco", "Halma plc", "acquired_by", "", 0.9)]
    annotate(rows, own)
    assert annotate(rows, own) == 0
    assert rows[0]["company"].count("acquired by") == 1


def test_annotate_matches_on_a_normalised_name():
    rows = [{"company": "Crosby Valve, Inc."}]
    assert annotate(rows, [Ownership("crosby valve inc", "Emerson", "subsidiary_of")]) == 1


# ── queueing ──────────────────────────────────────────────────────────────
def test_ownership_question_names_the_company():
    q = ownership_question("Oseco")
    assert "Oseco" in q and "acquired" in q.lower()


def test_enqueue_skips_companies_already_answered(tmp_path):
    from vendor_intel.evidence.ai_overview import AiOverviewStore, Question

    store = AiOverviewStore(tmp_path)
    rows = [{"company": "Oseco"}, {"company": "Fike"}]
    assert enqueue_questions(rows, "M", store=store) == 2

    store.put(Question(text=ownership_question("Oseco"), market="M"), "Acquired by Halma plc.")
    store.reset_queue()
    assert enqueue_questions(rows, "M", store=store) == 1, "answered company must not requeue"


def test_enqueue_uses_the_unannotated_name(tmp_path):
    """A second run must not ask about "Oseco (acquired by Halma plc)"."""
    from vendor_intel.evidence.ai_overview import AiOverviewStore

    store = AiOverviewStore(tmp_path)
    enqueue_questions([{"company": "Oseco (acquired by Halma plc)", "company_raw": "Oseco"}],
                      "M", store=store)
    assert [q.subject for q in store.pending()] == ["Oseco"]


def test_detect_without_cached_evidence_finds_nothing(tmp_path):
    from vendor_intel.evidence.ai_overview import AiOverviewStore

    assert detect([{"company": "Oseco"}], "M", store=AiOverviewStore(tmp_path)) == []
