"""Row-level proportional floor normalization (normalize_row_score_floor).

Every row is normalized independently of every other row — no population
min/max, no global shift. See matrix_rollup.normalize_row_score_floor.
"""
from __future__ import annotations

from vendor_intel.quadrant.matrix_rollup import normalize_row_score_floor
from vendor_intel.quadrant.rating_map import compute_overall


def test_both_below_floor_scaled_proportionally():
    x, y = normalize_row_score_floor(50, 40)
    assert round(x, 2) == 81.25
    assert round(y, 2) == 65.0


def test_only_x_below_floor_raised_to_floor():
    x, y = normalize_row_score_floor(52, 78)
    assert x == 65
    assert y == 78


def test_only_y_below_floor_raised_to_floor():
    x, y = normalize_row_score_floor(72, 48)
    assert x == 72
    assert y == 65


def test_both_exactly_at_floor_unchanged():
    x, y = normalize_row_score_floor(65, 65)
    assert x == 65
    assert y == 65


def test_both_above_floor_unchanged():
    x, y = normalize_row_score_floor(80, 90)
    assert x == 80
    assert y == 90


def test_never_scaled_above_ceiling():
    x, y = normalize_row_score_floor(1, 1)
    assert x <= 100
    assert y <= 100


def test_overall_recomputed_after_normalization_not_before():
    # Overall must come from the NORMALIZED X/Y via the existing formula,
    # never max(original_overall, 65).
    x_raw, y_raw = 50, 40
    x_norm, y_norm = normalize_row_score_floor(x_raw, y_raw)
    overall = compute_overall(int(round(x_norm)), int(round(y_norm)))
    original_overall = compute_overall(x_raw, y_raw)
    assert overall == compute_overall(81, 65)  # from the normalized pair
    assert overall != max(original_overall, 65) or overall == compute_overall(81, 65)
    assert overall >= 65


def test_100_independent_rows_each_normalized_on_its_own():
    rows = [(45, 40), (70, 60), (80, 90)] + [(i % 60 + 1, (i * 3) % 60 + 1) for i in range(97)]
    assert len(rows) == 100

    results = [normalize_row_score_floor(x, y) for x, y in rows]

    # Company C (80, 90) must be untouched regardless of how bad Company A's
    # (45, 40) score was — no population-wide shift, no cross-row coupling.
    assert results[2] == (80, 90)

    # Company A (45, 40): both below floor -> proportional scale, lower one
    # lands exactly on the floor.
    ax, ay = results[0]
    assert min(round(ax, 6), round(ay, 6)) == 65.0

    # Company B (70, 60): only Y below floor -> only Y raised.
    bx, by = results[1]
    assert bx == 70
    assert by == 65

    # Every row's result must be independently derivable from that row
    # alone — recomputing one row directly must match the batch result.
    for (x, y), (nx, ny) in zip(rows, results):
        assert normalize_row_score_floor(x, y) == (nx, ny)


def test_row_never_influenced_by_other_rows_in_same_batch():
    # Same two rows, computed alone vs. alongside a very different third row
    # — results must be identical either way.
    alone = normalize_row_score_floor(50, 40)
    with_others = [
        normalize_row_score_floor(50, 40),
        normalize_row_score_floor(10, 5),
        normalize_row_score_floor(99, 99),
    ][0]
    assert alone == with_others
