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


def normalize_cohort_to_band(
    values: Sequence[float],
    *,
    floor: float = NORM_FLOOR,
    ceiling: float = NORM_CEILING,
) -> list[float]:
    """Map one axis's raw scores onto [floor, ceiling], preserving ORDER.

    Why this exists, and why the row-level floor scaling below is not enough:

    ``normalize_row_score_floor`` scales a row so its SMALLER value lands on
    the floor, then caps at 100. Once the cap bites, the ratio it set out to
    preserve is gone — raw 12/38 and raw 5/20 both come out as exactly
    65/100. So the weakest companies in a market were being shown a perfect
    score, and 64 of 230 Silicon Carbide rows carried a 100.

    Three goals conflict: land on the floor, preserve the ratio, and cap at
    100. This keeps the floor and the cap and gives up the per-row ratio,
    because rank order across the cohort is what a quadrant chart actually
    reads. The weakest company sits at 65, the strongest at 100, and nobody
    is inflated past the companies that genuinely beat them.

    A cohort with no spread (every score identical) maps to the floor rather
    than dividing by zero.
    """
    raw = [float(v) for v in values]
    if not raw:
        return []
    lo, hi = min(raw), max(raw)
    if hi <= lo:
        return [floor for _ in raw]
    span = hi - lo
    width = ceiling - floor
    return [floor + (v - lo) / span * width for v in raw]


def normalize_row_score_floor(
    x: float, y: float, *, floor: float = NORM_FLOOR, ceiling: float = NORM_CEILING
) -> tuple[float, float]:
    """Row-level proportional floor normalization for one company's X/Y pair.

    Every row is transformed independently of every other row — there is no
    population min/max here, deliberately, unlike normalize_scores_proportionally
    above. A company's score never changes because of what any other company
    scored.

    Rule:
    - If both x and y are already >= floor: unchanged.
    - If both are below floor: scale both by the SAME factor so the ratio
      between x and y is preserved (a company proportionally stronger on one
      axis stays proportionally stronger after scaling). The factor is
      `min(floor / lower, ceiling / upper)` — capped by whichever bound
      would be hit first, so the stronger axis is never pushed past
      `ceiling` by a much weaker partner axis (the earlier bug here: scaling
      derived purely from the weaker axis could send the stronger axis past
      100, and once THAT got clamped the ratio was lost anyway — e.g. a
      raw 94.4 that happened to be the strongest score in the whole cohort
      showing as a flat 100, indistinguishable from every other company that
      also hit the ceiling).
    - If only one is below floor: raise just that one to `floor`; the axis
      that already qualified is left untouched (never scaled down).

    Note this does not force EVERY axis to land at exactly `floor` or above
    in every case: when the two raw scores are far apart, capping the
    stronger axis at `ceiling` can still leave the weaker one under `floor`
    (e.g. raw 61.2/36.0 -> 100.0/58.8) — the ratio is kept exact rather than
    topping the weaker axis up the rest of the way, which would break that
    ratio for the sake of a number that is already close to it.
    """
    fx, fy = float(x), float(y)
    if fx >= floor and fy >= floor:
        return fx, fy
    if fx < floor and fy < floor:
        lower = min(fx, fy)
        upper = max(fx, fy)
        if lower <= 0:
            return floor, floor
        scale = min(floor / lower, ceiling / upper)
        return (fx * scale, fy * scale)
    # exactly one is below floor — raise only that one
    return (floor if fx < floor else fx, floor if fy < floor else fy)


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
