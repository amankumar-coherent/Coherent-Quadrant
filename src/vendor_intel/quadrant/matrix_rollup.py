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


NORM_FLOOR = 65.0
NORM_CEILING = 100.0


def normalize_scores_proportionally(
    values: Sequence[float],
    *,
    floor: float = NORM_FLOOR,
    ceiling: float = NORM_CEILING,
) -> list[float]:
    """Proportional min-max normalize one axis's raw scores to [floor, ceiling].

        new = floor + ((old - min(values)) / (max(values) - min(values))) * (ceiling - floor)

    Must be called ONCE per normalization scope, with the COMPLETE population
    of raw scores for that scope already collected — never per-row, never on
    a partial/streaming subset, and never mixed across scopes that aren't
    meant to be compared on the same scale (see call site in synthesize.py:
    each market's X/Y criteria are LLM-defined per market, so the scope is
    one market's full company list, not the union of unrelated markets).

    Preserves relative ranking within the scope: the lowest raw score in the
    population maps to `floor`, the highest maps to `ceiling`, everything
    else lands proportionally in between — no score is independently forced
    to `floor` regardless of how it compares to its peers.

    Edge cases:
    - Empty input -> [].
    - All values identical (max == min): there is no spread to preserve, so
      neither snapping everyone to `floor` (implies "all worst") nor to
      `ceiling` (implies "all best") is justified by the data. Falls back to
      the midpoint of [floor, ceiling] for every value — documented here as
      the deliberate choice, not an oversight.
    """
    n = len(values)
    if n == 0:
        return []
    vals = [float(v) for v in values]
    lo, hi = min(vals), max(vals)
    if hi <= lo:
        mid = (float(floor) + float(ceiling)) / 2.0
        return [mid] * n
    span = float(ceiling) - float(floor)
    return [float(floor) + ((v - lo) / (hi - lo)) * span for v in vals]


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
