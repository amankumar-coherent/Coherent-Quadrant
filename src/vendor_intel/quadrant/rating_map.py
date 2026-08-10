"""Map matrix scores → CMI ratings, quadrant, tier, chart offsets."""
from __future__ import annotations

from typing import Any, Sequence

from vendor_intel.quadrant.criteria_catalog import load_scoring_weights

QUADRANTS = ("Leaders", "Challengers", "Trailblazers", "Emerging Players")
TIERS = ("Tier 1", "Tier 2", "Tier 3")
RATINGS = ("very-high", "high", "average", "low", "very-low")


def sub_avg_to_rating(sub_avg: float, thresholds: dict[str, float] | None = None) -> str:
    cfg = thresholds or (load_scoring_weights().get("rating_thresholds") or {})
    s = float(sub_avg)
    if s >= float(cfg.get("very_high", 8.5)):
        return "very-high"
    if s >= float(cfg.get("high", 7.0)):
        return "high"
    if s >= float(cfg.get("average", 5.0)):
        return "average"
    if s >= float(cfg.get("low", 3.0)):
        return "low"
    return "very-low"


def overall_to_tier(overall: int | float) -> str:
    """Absolute tier cutoffs on overall 0–100 (legacy / when relative_tier=false)."""
    cfg = load_scoring_weights().get("tier_thresholds") or {}
    o = float(overall)
    if o >= float(cfg.get("tier_1", 85)):
        return "Tier 1"
    if o >= float(cfg.get("tier_2", 70)):
        return "Tier 2"
    return "Tier 3"


def assign_tiers_relative(overalls: Sequence[int | float]) -> list[str]:
    """
    Within-cohort tiers by rank tertiles (highest overall → Tier 1).

    For n=12 → ~4 / 4 / 4. Ties keep stable order by index so placement is
    deterministic. Used when relative_tier (or relative_quadrant) is enabled.
    """
    n = len(overalls)
    if n == 0:
        return []
    order = sorted(range(n), key=lambda i: (-float(overalls[i]), i))
    # ceil(n/3) for Tier 1 and Tier 2 bands
    t1_end = max(1, (n + 2) // 3)
    t2_end = max(t1_end, (2 * n + 2) // 3)
    out = ["Tier 3"] * n
    for rank, idx in enumerate(order):
        if rank < t1_end:
            out[idx] = "Tier 1"
        elif rank < t2_end:
            out[idx] = "Tier 2"
        else:
            out[idx] = "Tier 3"
    return out


def assign_quadrant(execution: int, innovation: int, *, mid: float = 50.0) -> str:
    """
    execution = X (Solution Capability), innovation = Y (Business Strategy).
    Chart: Y up, X right — matches CMI cells:
      Leaders (top-right): high X + high Y
      Challengers (top-left): low X + high Y
      Trailblazers (bottom-right): high X + low Y
      Emerging Players (bottom-left): low X + low Y
    """
    high_x = float(execution) >= mid
    high_y = float(innovation) >= mid
    if high_x and high_y:
        return "Leaders"
    if not high_x and high_y:
        return "Challengers"
    if high_x and not high_y:
        return "Trailblazers"
    return "Emerging Players"


def _median_floats(vals: Sequence[float]) -> float:
    if not vals:
        return 50.0
    s = sorted(float(v) for v in vals)
    n = len(s)
    mid = n // 2
    if n % 2:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2.0


def assign_quadrants_half_median(
    executions: Sequence[int],
    innovations: Sequence[int],
) -> tuple[list[str], float, float]:
    """
    Relative placement that fills all four cells when X≈Y.

    1. Split the cohort at the X median (left = Challengers/Emerging, right = Leaders/Trailblazers).
    2. Within each half, split again at that half's Y median.

    So a brand that is "high capability but lower strategy than other high-X peers"
    lands in Trailblazers, and "high strategy among lower-X peers" lands in Challengers.
    """
    n = len(executions)
    if n == 0:
        return [], 50.0, 50.0
    xs = [float(x) for x in executions]
    ys = [float(y) for y in innovations]
    mid_x = _median_floats(xs)
    mid_y = _median_floats(ys)

    left_idx = [i for i in range(n) if xs[i] < mid_x]
    right_idx = [i for i in range(n) if xs[i] >= mid_x]
    # Degenerate: everyone on one side of X — use global X/Y medians
    if not left_idx or not right_idx:
        quads = []
        for i in range(n):
            high_x = xs[i] >= mid_x
            high_y = ys[i] >= mid_y
            if high_x and high_y:
                quads.append("Leaders")
            elif not high_x and high_y:
                quads.append("Challengers")
            elif high_x and not high_y:
                quads.append("Trailblazers")
            else:
                quads.append("Emerging Players")
        return quads, mid_x, mid_y

    quads = ["Emerging Players"] * n

    def _fill(indices: list[int], *, high_x: bool) -> None:
        if not indices:
            return
        half_ys = [ys[i] for i in indices]
        # If only one brand in the half, put it on the "high Y" side of that half
        if len(indices) == 1:
            i = indices[0]
            quads[i] = "Leaders" if high_x else "Challengers"
            return
        # Rank split, not `y >= median`.
        #
        # A plain median comparison empties a cell whenever the median coincides
        # with a large tie block. Real case: 37 of 66 low-X brands scored Y=40 —
        # the `score_floor` value every unevidenced brand lands on — so the half's
        # median WAS 40, all 37 ties tested `40 >= 40` as high-Y, and Emerging
        # Players came out with zero brands.
        #
        # Sorting by (y, index) and cutting at the halfway rank reduces to the
        # median split when values are distinct, and degrades gracefully when they
        # are not. The old all-equal special case is subsumed by this.
        order = sorted(indices, key=lambda i: (ys[i], i))
        cut = len(order) // 2
        low_set = set(order[:cut])  # lowest-ranked half of this X-half by Y
        for i in indices:
            high_y = i not in low_set
            if high_x and high_y:
                quads[i] = "Leaders"
            elif not high_x and high_y:
                quads[i] = "Challengers"
            elif high_x and not high_y:
                quads[i] = "Trailblazers"
            else:
                quads[i] = "Emerging Players"

    _fill(left_idx, high_x=False)
    _fill(right_idx, high_x=True)
    return quads, mid_x, mid_y


def chart_offsets_for_quadrants(
    executions: Sequence[int],
    innovations: Sequence[int],
    quadrants: Sequence[str],
) -> tuple[list[tuple[int, int]], float, float]:
    """
    Place each brand inside its assigned cell so Challengers / Trailblazers are visible.

    Cell ranges (top_pct, left_pct on full chart; high Y → low top_pct):
      Challengers:     left 8–45,  top 8–45
      Leaders:         left 55–92, top 8–45
      Emerging:        left 8–45,  top 55–92
      Trailblazers:    left 55–92, top 55–92
    """
    n = len(executions)
    if n == 0:
        return [], 50.0, 50.0

    cells = {
        "Challengers": (8.0, 45.0, 8.0, 45.0),       # top_lo, top_hi, left_lo, left_hi
        "Leaders": (8.0, 45.0, 55.0, 92.0),
        "Emerging Players": (55.0, 92.0, 8.0, 45.0),
        "Trailblazers": (55.0, 92.0, 55.0, 92.0),
    }
    # Group indices by quadrant
    groups: dict[str, list[int]] = {k: [] for k in cells}
    for i, q in enumerate(quadrants):
        key = q if q in cells else "Emerging Players"
        groups[key].append(i)

    out: list[tuple[int, int]] = [(50, 50)] * n
    for qname, idxs in groups.items():
        if not idxs:
            continue
        top_lo, top_hi, left_lo, left_hi = cells[qname]
        # Within cell: higher innovation → lower top; higher execution → higher left
        xs = [float(executions[i]) for i in idxs]
        ys = [float(innovations[i]) for i in idxs]
        lefts = _rank_spread(xs, low=left_lo, high=left_hi)
        # rank_spread high value → high number; for top we want high Y → low top
        y_ranks = _rank_spread(ys, low=0.0, high=1.0)
        tops = [top_hi - yr * (top_hi - top_lo) for yr in y_ranks]
        for j, i in enumerate(idxs):
            jitter = ((i * 7) % 11) - 5
            top = int(round(tops[j] + jitter * 0.25))
            left = int(round(lefts[j] + jitter * 0.35))
            top = int(max(top_lo, min(top_hi, top)))
            left = int(max(left_lo, min(left_hi, left)))
            out[i] = (top, left)

    out = _separate_points(out, min_dist=8.0, iters=40)
    # Keep points inside their cell after separation
    for i, q in enumerate(quadrants):
        key = q if q in cells else "Emerging Players"
        top_lo, top_hi, left_lo, left_hi = cells[key]
        t, l = out[i]
        out[i] = (
            int(max(top_lo, min(top_hi, t))),
            int(max(left_lo, min(left_hi, l))),
        )
    return out, 50.0, 50.0


def relative_midpoints(executions: Sequence[int], innovations: Sequence[int]) -> tuple[float, float]:
    """Median-based midpoints so brands spread across quadrants."""
    return _median_floats([float(v) for v in executions]), _median_floats(
        [float(v) for v in innovations]
    )


def _stretch_axis(values: Sequence[float], *, low: float = 12.0, high: float = 88.0) -> list[float]:
    """Min–max stretch one axis onto [low, high] so peers fill the chart."""
    if not values:
        return []
    lo = min(float(v) for v in values)
    hi = max(float(v) for v in values)
    span = hi - lo
    if span < 1e-6:
        mid = (low + high) / 2.0
        return [mid] * len(values)
    out: list[float] = []
    for v in values:
        t = (float(v) - lo) / span
        out.append(low + t * (high - low))
    return out


def _rank_spread(values: Sequence[float], *, low: float = 12.0, high: float = 88.0) -> list[float]:
    """Map values to [low, high] by rank so near-ties still separate on the chart."""
    n = len(values)
    if n == 0:
        return []
    if n == 1:
        return [(low + high) / 2.0]
    order = sorted(range(n), key=lambda i: (float(values[i]), i))
    out = [0.0] * n
    span = high - low
    for rank, idx in enumerate(order):
        out[idx] = low + (rank / (n - 1)) * span
    return out


def chart_offsets_absolute(
    executions: Sequence[int],
    innovations: Sequence[int],
    *,
    stretch: bool = True,
    chart_low: float = 12.0,
    chart_high: float = 88.0,
    mid_x: float | None = None,
    mid_y: float | None = None,
    mode: str = "rank",
) -> tuple[list[tuple[int, int]], float, float]:
    """
    Full-chart top_pct / left_pct (0–100 plane) plus chart midpoints.

    mode=rank (default): space brands evenly by X/Y rank so the chart fills.
    mode=minmax: classic min–max stretch (near-ties stay clustered).
    """
    xs_raw = [float(x) for x in executions]
    ys_raw = [float(y) for y in innovations]
    mx = float(mid_x) if mid_x is not None else 50.0
    my = float(mid_y) if mid_y is not None else 50.0
    mode_l = (mode or "rank").strip().lower()

    def _map_mid_minmax(raw_mid: float, cohort: list[float]) -> float:
        lo = min(cohort)
        hi = max(cohort)
        if hi - lo < 1e-6:
            return (chart_low + chart_high) / 2.0
        return chart_low + (raw_mid - lo) / (hi - lo) * (chart_high - chart_low)

    if stretch and xs_raw:
        if mode_l == "minmax":
            xs = _stretch_axis(xs_raw, low=chart_low, high=chart_high)
            ys = _stretch_axis(ys_raw, low=chart_low, high=chart_high)
            chart_mid_x = _map_mid_minmax(mx, xs_raw)
            chart_mid_y = _map_mid_minmax(my, ys_raw)
        else:
            xs = _rank_spread(xs_raw, low=chart_low, high=chart_high)
            ys = _rank_spread(ys_raw, low=chart_low, high=chart_high)
            # Median of rank-spaced axis ≈ chart center
            chart_mid_x = (chart_low + chart_high) / 2.0
            chart_mid_y = (chart_low + chart_high) / 2.0
    else:
        xs = xs_raw
        ys = ys_raw
        chart_mid_x = mx
        chart_mid_y = my

    out: list[tuple[int, int]] = []
    for i, (x, y) in enumerate(zip(xs, ys)):
        jitter = ((i * 7) % 11) - 5  # -5..5
        left = int(round(x + jitter * 0.45))
        top = int(round(100.0 - y + jitter * 0.35))
        left = max(5, min(95, left))
        top = max(5, min(95, top))
        out.append((top, left))
    out = _separate_points(out, min_dist=9.0, iters=50)
    return out, chart_mid_x, chart_mid_y


def _separate_points(
    coords: list[tuple[int, int]],
    *,
    min_dist: float = 9.0,
    iters: int = 50,
) -> list[tuple[int, int]]:
    """Push overlapping chart points apart so labels/dots don't stack on the diagonal."""
    if len(coords) < 2:
        return coords
    pts = [[float(t), float(l)] for t, l in coords]
    for _ in range(iters):
        for i in range(len(pts)):
            for j in range(i + 1, len(pts)):
                dt = pts[i][0] - pts[j][0]
                dl = pts[i][1] - pts[j][1]
                dist = (dt * dt + dl * dl) ** 0.5
                if dist < 1e-6:
                    dist = 1e-6
                    dt = 1.0
                    dl = 0.0
                if dist >= min_dist:
                    continue
                push = (min_dist - dist) / 2.0
                ux, uy = dt / dist, dl / dist
                pts[i][0] += ux * push
                pts[i][1] += uy * push
                pts[j][0] -= ux * push
                pts[j][1] -= uy * push
        for p in pts:
            p[0] = max(5.0, min(95.0, p[0]))
            p[1] = max(5.0, min(95.0, p[1]))
    return [(int(round(t)), int(round(l))) for t, l in pts]


def inner_cell_offsets(
    execution: int,
    innovation: int,
    quadrant: str,
    *,
    mid_x: float,
    mid_y: float,
    index: int = 0,
) -> tuple[int, int]:
    """
    Legacy within-cell offsets. Prefer chart_offsets_absolute for full-plane scatter.
    """
    # Normalize within the half-plane relative to midpoints
    if quadrant in ("Leaders", "Challengers"):
        y_span = max(100.0 - mid_y, 1.0)
        y_norm = (float(innovation) - mid_y) / y_span
    else:
        y_span = max(mid_y, 1.0)
        y_norm = float(innovation) / y_span

    if quadrant in ("Leaders", "Trailblazers"):
        x_span = max(100.0 - mid_x, 1.0)
        x_norm = (float(execution) - mid_x) / x_span
    else:
        x_span = max(mid_x, 1.0)
        x_norm = float(execution) / x_span

    y_norm = max(0.0, min(1.0, y_norm))
    x_norm = max(0.0, min(1.0, x_norm))

    jitter = ((index * 7) % 11) - 5

    top = int(round(90 - y_norm * 70 + jitter * 0.3))
    left = int(round(10 + x_norm * 70 + jitter * 0.3))
    top = max(10, min(90, top))
    left = max(10, min(90, left))
    return top, left


def brand_color(index: int) -> str:
    colors = list(load_scoring_weights().get("brand_colors") or [])
    if not colors:
        return "#002857"
    return str(colors[index % len(colors)])


def compute_overall(execution: int, innovation: int) -> int:
    return int(round((int(execution) + int(innovation)) / 2.0))
