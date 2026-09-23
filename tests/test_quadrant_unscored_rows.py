"""Quadrant thresholds must ignore UNSCORED rows.

CPaaS shipped with 276 of 287 companies in two quadrants and Trailblazers
completely empty. The 11 unscored rows were being fed into the median as
zeros, dragging both thresholds down until ">= median" was true for nearly
every real company.
"""
from __future__ import annotations

import inspect
from collections import Counter

from vendor_intel.pipeline import expand_quadrant_score as eqs
from vendor_intel.quadrant.rating_map import assign_quadrants_absolute_median


def test_zeros_from_unscored_rows_collapse_the_split():
    """The defect, reproduced: real scores plus a handful of zeros."""
    real = [(80, 70), (75, 68), (90, 85), (70, 66), (85, 80)] * 10
    xs = [x for x, _ in real] + [0] * 11
    ys = [y for _, y in real] + [0] * 11
    quads, _, _ = assign_quadrants_absolute_median(xs, ys)
    counts = Counter(quads[: len(real)])
    assert counts.get("Trailblazers", 0) == 0, "this is the bug being guarded"


def test_dropping_the_zeros_restores_all_four_quadrants():
    """Same scores, zeros removed: the split works again. A real spread is
    used because a handful of repeated pairs ties the median artificially."""
    real = [(65 + (i * 7) % 36, 65 + (i * 5) % 30) for i in range(50)]
    xs = [x for x, _ in real]
    ys = [y for _, y in real]
    quads, _, _ = assign_quadrants_absolute_median(xs, ys)
    counts = Counter(quads)
    assert counts["Trailblazers"] > 0, f"Trailblazers must be reachable: {counts}"
    assert counts["Leaders"] > 0


def test_the_pipeline_filters_to_scored_rows_before_taking_medians():
    src = inspect.getsource(eqs)
    assert "scored_rows = [r for r in rows if _has_xy(r)]" in src
    block = src.split("scored_rows = [r for r in rows if _has_xy(r)]", 1)[1][:400]
    assert "for r in scored_rows" in block, "medians must use the scored rows"


def test_the_cpaas_shape_populates_every_quadrant():
    """Regression on the real exported data shape: 276 scored rows whose Y
    values are floored at 65, which is what emptied Trailblazers."""
    pairs = [(65 + (i % 36), 65 + (i % 12)) for i in range(276)]
    quads, _, _ = assign_quadrants_absolute_median(
        [x for x, _ in pairs], [y for _, y in pairs]
    )
    counts = Counter(quads)
    assert counts["Trailblazers"] > 0, counts
    assert len(counts) == 4, counts
