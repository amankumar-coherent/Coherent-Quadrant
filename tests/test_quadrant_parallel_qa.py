"""Batched Q&A packing for quadrant parallelism."""
from __future__ import annotations

from vendor_intel.quadrant.qa_scorer import (
    _answers_from_batch_raw,
    _pack_feature_results,
    score_company_features,
)
from vendor_intel.quadrant.schema import FeatureQuestions, QuestionItem


def _demo_features() -> list[FeatureQuestions]:
    return [
        FeatureQuestions(
            feature="Product Portfolio Breadth",
            axis="Solution Capability",
            items=[
                QuestionItem(text="How diverse is the portfolio?", weight=0.4),
                QuestionItem(text="Does it cover core SKUs?", weight=0.3),
                QuestionItem(text="Is the portfolio innovative?", weight=0.3),
            ],
        ),
        FeatureQuestions(
            feature="Geographic Expansion",
            axis="Business Strategy",
            items=[
                QuestionItem(text="Does the vendor operate in multiple regions?", weight=0.4),
                QuestionItem(text="Is global support available?", weight=0.3),
                QuestionItem(text="Are regional teams present?", weight=0.3),
            ],
        ),
    ]


def test_batch_raw_maps_ids_to_answers():
    feats = _demo_features()
    items = [
        ("f0_q0", feats[0].feature, feats[0].axis, feats[0].items[0].text, 0.4),
        ("f0_q1", feats[0].feature, feats[0].axis, feats[0].items[1].text, 0.3),
        ("f0_q2", feats[0].feature, feats[0].axis, feats[0].items[2].text, 0.3),
    ]
    raw = {
        "answers": [
            {
                "id": "f0_q0",
                "score": 8,
                "answer": "Wide product line.",
                "grounding": "supported",
                "evidence_snippets": ["portfolio of devices"],
            },
            {
                "id": "f0_q1",
                "score": 7,
                "answer": "Covers imaging SKUs.",
                "grounding": "partial",
            },
            # f0_q2 missing → heuristic
        ]
    }
    by_id = _answers_from_batch_raw(
        raw,
        items,
        "Acme portfolio of devices for dental clinics.",
        brand="Acme",
        score_floor=4,
        allow_model_knowledge=True,
    )
    assert by_id["f0_q0"].score == 8
    assert by_id["f0_q0"].grounding == "supported"
    assert by_id["f0_q1"].score == 7  # no longer hard-capped by partial
    assert by_id["f0_q1"].grounding == "partial"
    assert "f0_q2" in by_id


def test_pack_feature_results_preserves_order():
    feats = _demo_features()
    by_id = {
        "f0_q0": type("A", (), {"score": 8, "weight": 0.4, "question": "q"})(),
    }
    # Use real QuestionAnswer via clamp path instead — simpler: run heuristic pack
    from vendor_intel.quadrant.schema import QuestionAnswer

    by_id = {
        f"f{fi}_q{qi}": QuestionAnswer(
            question=item.text,
            weight=item.weight,
            score=5 + qi,
            grounding="partial",
            answer="ok",
        )
        for fi, fq in enumerate(feats)
        for qi, item in enumerate(fq.items)
    }
    packed = _pack_feature_results(feats, by_id)
    assert len(packed) == 2
    assert packed[0]["feature"] == "Product Portfolio Breadth"
    assert packed[0]["scores"] == [5.0, 6.0, 7.0]
    assert packed[1]["axis"] == "Business Strategy"


def test_score_company_features_company_batch_without_llm():
    """No LLM client → heuristics still return 2 features × 3 answers."""
    feats = _demo_features()
    kb = {
        "brand": "Acme",
        "domain": "acme.com",
        "chunks": [
            {
                "source_url": "https://acme.com",
                "text": "Acme offers a diverse dental product portfolio across Africa with regional support teams.",
                "origin": "page_text",
            }
        ],
    }

    class _NoClient:
        available = False

    packed = score_company_features(
        kb, feats, client=_NoClient(), batch_mode="company"
    )
    assert len(packed) == 2
    assert all(len(p["answers"]) == 3 for p in packed)
