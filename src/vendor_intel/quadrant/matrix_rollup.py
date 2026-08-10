"""Vendor Evaluation Matrix rollup math (exact sheet formula)."""
from __future__ import annotations

from typing import Sequence


def weighted_question_average(scores: Sequence[float], weights: Sequence[float]) -> float:
    """sub_avg = Σ(q_weight × q_score). Weights should sum to ~1."""
    if not scores:
        return 0.0
    n = min(len(scores), len(weights))
    if n == 0:
        return 0.0
    w = [float(weights[i]) for i in range(n)]
    total_w = sum(w) or 1.0
    w = [x / total_w for x in w]
    return sum(float(scores[i]) * w[i] for i in range(n))


def feature_contribution(feature_weight: float, sub_avg: float) -> float:
    """contribution = feature_weight × (sub_avg / 10)."""
    return float(feature_weight) * (float(sub_avg) / 10.0)


def axis_overall(contributions: Sequence[float]) -> float:
    """Sum of feature contributions on one axis (0–1 scale)."""
    return float(sum(float(c) for c in contributions))


def scale_to_100(axis_score_0_1: float) -> int:
    """Map 0–1 axis overall to 0–100 integer for CMI execution/innovation."""
    return int(round(max(0.0, min(1.0, float(axis_score_0_1))) * 100))


def rollup_axis(
    *,
    feature_weights: Sequence[float],
    feature_question_scores: Sequence[Sequence[float]],
    question_weights: Sequence[Sequence[float]],
) -> dict:
    """
    Roll up one axis.

    feature_question_scores[i] = list of 1-10 scores for feature i
    question_weights[i] = weights for those questions
    """
    details = []
    contributions: list[float] = []
    n = min(len(feature_weights), len(feature_question_scores), len(question_weights))
    for i in range(n):
        sub = weighted_question_average(feature_question_scores[i], question_weights[i])
        contrib = feature_contribution(feature_weights[i], sub)
        contributions.append(contrib)
        details.append(
            {
                "feature_index": i,
                "feature_weight": float(feature_weights[i]),
                "sub_avg": round(sub, 6),
                "contribution": round(contrib, 6),
            }
        )
    overall = axis_overall(contributions)
    return {
        "features": details,
        "axis_overall": round(overall, 6),
        "score_0_100": scale_to_100(overall),
    }
