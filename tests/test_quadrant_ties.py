"""Identical scores must land in the same quadrant.

Seen in a shipped report: four wearable-glucometer companies all at X=100
Y=65, two labelled Leaders and two Trailblazers. The rank split cut at n//2,
which lands mid-tie when many companies share a score, so placement came down
to row order — 23 pairs disagreed in that one market.
"""
from __future__ import annotations

from collections import Counter

from vendor_intel.quadrant.rating_map import (
    assign_quadrants_absolute_median,
    assign_quadrants_half_median,
)


def _inconsistent(xs, ys, quads) -> list[tuple]:
    seen: dict[tuple[int, int], str] = {}
    bad = []
    for x, y, q in zip(xs, ys, quads):
        if (x, y) in seen and seen[(x, y)] != q:
            bad.append(((x, y), seen[(x, y)], q))
        seen.setdefault((x, y), q)
    return bad


def test_the_reported_case_is_consistent():
    """Four companies at 100/65, plus a spread either side."""
    xs = [100, 100, 100, 100, 90, 80, 70, 67, 67, 60]
    ys = [65, 65, 65, 65, 70, 75, 65, 65, 65, 80]
    quads, _, _ = assign_quadrants_absolute_median(xs, ys)
    assert _inconsistent(xs, ys, quads) == []


def test_a_heavy_tie_does_not_split_equals():
    """The floor-65 rule puts many companies on the same Y, which is exactly
    when the cut lands mid-tie."""
    xs = [100] * 20 + [67] * 20
    ys = [65] * 40
    quads, _, _ = assign_quadrants_half_median(xs, ys)
    assert _inconsistent(xs, ys, quads) == []


def test_all_four_quadrants_still_fill_with_real_spread():
    """The tie fix must not collapse the split for data that does vary."""
    xs = [60 + (i * 7) % 40 for i in range(60)]
    ys = [60 + (i * 11) % 40 for i in range(60)]
    quads, _, _ = assign_quadrants_half_median(xs, ys)
    assert len(Counter(quads)) == 4


def test_a_cohort_with_one_score_is_not_split():
    """Every company identical: any split would be invented, not measured."""
    xs = [80] * 12
    ys = [70] * 12
    quads, _, _ = assign_quadrants_half_median(xs, ys)
    assert len(set(quads)) == 1


def test_ordering_does_not_change_placement():
    """Shuffling the input must not move a company between quadrants."""
    xs = [100, 100, 90, 90, 80, 80, 70, 70]
    ys = [65, 65, 70, 70, 75, 75, 65, 65]
    q1, _, _ = assign_quadrants_half_median(xs, ys)
    order = [7, 0, 5, 2, 6, 1, 4, 3]
    q2, _, _ = assign_quadrants_half_median([xs[i] for i in order], [ys[i] for i in order])
    assert [q2[order.index(i)] for i in range(len(xs))] == q1


def test_a_clean_boundary_is_left_alone():
    """The cut only moves when it lands inside a run of equal scores."""
    xs = [10, 20, 30, 40]
    ys = [10, 20, 30, 40]
    quads, _, _ = assign_quadrants_half_median(xs, ys)
    assert len(Counter(quads)) == 4
