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


def assign_quadrants_absolute_median(
    executions: Sequence[int],
    innovations: Sequence[int],
) -> tuple[list[str], float, float]:
    """Place by cohort median thresholds so labels match axis midlines.

    Leaders: X>=mid_x and Y>=mid_y; Challengers: X<mid_x and Y>=mid_y;
    Trailblazers: X>=mid_x and Y<mid_y; Emerging: X<mid_x and Y<mid_y.

    Prefer this when scores have real spread — half-median equal-sizing can put
    high-X/high-Y brands into Trailblazers and break the chart visually.
    Falls back to half-median when a side would be empty (floor-tied scores).
    """
    n = len(executions)
    if n == 0:
        return [], 50.0, 50.0
    xs = [float(x) for x in executions]
    ys = [float(y) for y in innovations]
    mid_x = _median_floats(xs)
    mid_y = _median_floats(ys)
    left = sum(1 for x in xs if x < mid_x)
    right = sum(1 for x in xs if x >= mid_x)
    below_y = sum(1 for y in ys if y < mid_y)
    above_y = sum(1 for y in ys if y >= mid_y)
    # Both axes must actually split the cohort. A mass tie at the median (e.g.
    # many companies floored to the same minimum score) makes `>= median`
    # true for everyone on that axis, silently emptying two quadrants even
    # though the OTHER axis split fine — checking X alone missed this.
    if left == 0 or right == 0 or below_y == 0 or above_y == 0:
        return assign_quadrants_half_median(executions, innovations)
    quads: list[str] = []
    for x, y in zip(xs, ys):
        high_x = x >= mid_x
        high_y = y >= mid_y
        if high_x and high_y:
            quads.append("Leaders")
        elif not high_x and high_y:
            quads.append("Challengers")
        elif high_x and not high_y:
            quads.append("Trailblazers")
        else:
            quads.append("Emerging Players")
    return quads, mid_x, mid_y


def assign_quadrants_half_median(
    executions: Sequence[int],
    innovations: Sequence[int],
) -> tuple[list[str], float, float]:
    """
    Relative placement that always fills all four cells (no empty quadrant).

    1. Rank-split the cohort on X (lowest half → Challengers/Emerging;
       highest half → Leaders/Trailblazers). Rank split — not ``x >= median`` —
       so score-floor ties (everyone at 52) still produce a left and right half.
    2. Within each X-half, rank-split again on Y.

    Hardcoding quadrant labels is never used; placement is always relative to
    the cohort being scored.
    """
    n = len(executions)
    if n == 0:
        return [], 50.0, 50.0
    xs = [float(x) for x in executions]
    ys = [float(y) for y in innovations]
    mid_x = _median_floats(xs)
    mid_y = _median_floats(ys)

    # Rank-split on X first. A plain ``x < median`` empties the left half when
    # min(X) == median (common after score_floor / thin-KB runs — every brand
    # lands on the same X). Sorting by (x, y, index) and cutting at n//2 always
    # yields both halves; ties degrade gracefully via stable index order.
    order_x = sorted(range(n), key=lambda i: (xs[i], ys[i], i))
    cut_x = n // 2
    left_idx = order_x[:cut_x]
    right_idx = order_x[cut_x:]

    quads = ["Emerging Players"] * n

    def _fill(indices: list[int], *, high_x: bool) -> None:
        if not indices:
            return
        # Single brand in a half → put on the high-Y side of that half
        if len(indices) == 1:
            i = indices[0]
            quads[i] = "Leaders" if high_x else "Challengers"
            return
        # Rank split on Y (same rationale as X — median ties must not empty a cell)
        order = sorted(indices, key=lambda i: (ys[i], xs[i], i))
        cut = len(order) // 2
        low_set = set(order[:cut])
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
      Challengers:     left 12–38,  top 12–38
      Leaders:         left 62–88,  top 12–38
      Emerging:        left 12–38,  top 62–88
      Trailblazers:    left 62–88,  top 62–88
    """
    n = len(executions)
    if n == 0:
        return [], 50.0, 50.0

    cells = {
        # Keep a clear gap from the 50% crosshairs so dots never sit on the lines
        # or look centered between quadrants (top_lo, top_hi, left_lo, left_hi)
        "Challengers": (10.0, 36.0, 10.0, 36.0),
        "Leaders": (10.0, 36.0, 64.0, 90.0),
        "Emerging Players": (64.0, 90.0, 10.0, 36.0),
        "Trailblazers": (64.0, 90.0, 64.0, 90.0),
    }
    # Group indices by quadrant
    groups: dict[str, list[int]] = {k: [] for k in cells}
    for i, q in enumerate(quadrants):
        key = q if q in cells else "Emerging Players"
        groups[key].append(i)

    out: list[tuple[int, int]] = [(50, 50)] * n
    bounds: list[tuple[float, float, float, float]] = [(5.0, 95.0, 5.0, 95.0)] * n
    for qname, idxs in groups.items():
        if not idxs:
            continue
        top_lo, top_hi, left_lo, left_hi = cells[qname]
        # Within cell: higher innovation → lower top; higher execution → higher left
        xs = [float(executions[i]) for i in idxs]
        ys = [float(innovations[i]) for i in idxs]
        # Inset rank spread so separation has room before hitting cell walls
        pad = 2.0 if len(idxs) >= 4 else 1.0
        lefts = _rank_spread(xs, low=left_lo + pad, high=left_hi - pad)
        y_ranks = _rank_spread(ys, low=0.0, high=1.0)
        tops = [
            (top_hi - pad) - yr * ((top_hi - pad) - (top_lo + pad)) for yr in y_ranks
        ]
        for j, i in enumerate(idxs):
            # Stronger deterministic offset so near-tied scores don't start stacked
            jitter_t = (((i * 11) % 13) - 6) * 0.55
            jitter_l = (((i * 17) % 13) - 6) * 0.55
            top = int(round(tops[j] + jitter_t))
            left = int(round(lefts[j] + jitter_l))
            top = int(max(top_lo, min(top_hi, top)))
            left = int(max(left_lo, min(left_hi, left)))
            out[i] = (top, left)
            bounds[i] = (top_lo, top_hi, left_lo, left_hi)

    # Stronger separation so ~5 brands/cell stay visually spaced
    out = _separate_points(out, min_dist=15.0, iters=120, bounds=bounds)

    # If a cell still has clustered points (common with near-tied scores),
    # snap that cell onto a staggered grid ordered by overall strength.
    for qname, idxs in groups.items():
        if len(idxs) < 2:
            continue
        top_lo, top_hi, left_lo, left_hi = cells[qname]
        min_pair = 999.0
        for a in range(len(idxs)):
            for b in range(a + 1, len(idxs)):
                i, j = idxs[a], idxs[b]
                dt = out[i][0] - out[j][0]
                dl = out[i][1] - out[j][1]
                min_pair = min(min_pair, (dt * dt + dl * dl) ** 0.5)
        if min_pair >= 13.0:
            continue
        ranked = sorted(
            idxs,
            key=lambda i: (
                -(float(innovations[i]) + float(executions[i])),
                -float(innovations[i]),
                -float(executions[i]),
                i,
            ),
        )
        k = len(ranked)
        # Staggered slots in normalized cell space (row-major with offset)
        slots: list[tuple[float, float]] = []
        if k == 2:
            slots = [(0.28, 0.30), (0.72, 0.70)]
        elif k == 3:
            slots = [(0.22, 0.28), (0.50, 0.72), (0.78, 0.35)]
        elif k == 4:
            slots = [(0.22, 0.25), (0.22, 0.75), (0.78, 0.25), (0.78, 0.75)]
        else:
            # 5+: two columns with vertical stagger
            cols = 2
            rows_n = (k + cols - 1) // cols
            for r in range(rows_n):
                for c in range(cols):
                    idx_slot = r * cols + c
                    if idx_slot >= k:
                        break
                    yn = (r + 0.5) / rows_n
                    xn = 0.28 if c == 0 else 0.72
                    if r % 2 == 1:
                        xn = 0.22 if c == 0 else 0.78
                    slots.append((yn, xn))
        for slot_i, i in enumerate(ranked):
            yn, xn = slots[slot_i]
            top = top_lo + yn * (top_hi - top_lo)
            left = left_lo + xn * (left_hi - left_lo)
            out[i] = (int(round(top)), int(round(left)))

    # Keep points inside their cell after separation / grid snap
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
    bounds: list[tuple[float, float, float, float]] | None = None,
) -> list[tuple[int, int]]:
    """Push overlapping chart points apart so labels/dots don't stack on the diagonal.

    If ``bounds`` is provided (top_lo, top_hi, left_lo, left_hi per point), each
    point is clamped to its own quadrant cell every iteration so separation never
    pushes a brand into another quadrant.
    """
    if len(coords) < 2:
        return coords
    pts = [[float(t), float(l)] for t, l in coords]

    def _clamp(i: int) -> None:
        if bounds and i < len(bounds):
            top_lo, top_hi, left_lo, left_hi = bounds[i]
            pts[i][0] = max(top_lo, min(top_hi, pts[i][0]))
            pts[i][1] = max(left_lo, min(left_hi, pts[i][1]))
        else:
            pts[i][0] = max(5.0, min(95.0, pts[i][0]))
            pts[i][1] = max(5.0, min(95.0, pts[i][1]))

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
        for i in range(len(pts)):
            _clamp(i)
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
