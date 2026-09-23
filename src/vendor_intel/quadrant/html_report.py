"""Self-contained Coherent Quadrant HTML report (chart + scorecards + company table).

Written next to quadrant JSON after a CLI/pipeline run. Open in any browser — no
Streamlit server required.
"""
from __future__ import annotations

import html
import json
import re
import webbrowser
from pathlib import Path
from typing import Any

from vendor_intel.quadrant.matrix_rollup import NORM_CEILING, NORM_FLOOR
from vendor_intel.quadrant.quadrant_language import (
    build_quadrant_explain,
    quadrant_label,
)

_QUAD_COLORS = {
    "Leaders": "#7CFC00",
    "Challengers": "#7EB6FF",
    "Trailblazers": "#C4B5FD",
    "Emerging Players": "#A7F3D0",
}

_EXPLAIN_CARD_COLOR = {
    "Leaders": "#002857",
    "Challengers": "#1d4ed8",
    "Trailblazers": "#0f766e",
    "Emerging Players": "#3b82f6",
}

_RATING_DOTS = {
    "very-high": 5,
    "high": 4,
    "average": 3,
    "low": 2,
    "very-low": 1,
}

_CSS = """
:root { --ink:#0f172a; --muted:#64748b; --line:#e2e8f0; --navy:#002857;
  /* Single colour for every score marker, in every table. */
  --score-blue:#1e3a8a; }
* { box-sizing: border-box; }
body {
  margin: 0; padding: 0 0 3rem 0;
  font-family: "Segoe UI", system-ui, -apple-system, sans-serif;
  color: var(--ink); background: #f8fafc;
}
.page { max-width: 1180px; margin: 0 auto; padding: 1.5rem 1.25rem; }
.hero {
  background: linear-gradient(135deg, #0f172a 0%, #1e3a5f 50%, #0d9488 100%);
  color: #f8fafc; border-radius: 14px; padding: 1.5rem 1.75rem; margin-bottom: 1.5rem;
}
.hero h1 { margin: 0 0 0.4rem 0; font-size: 1.65rem; letter-spacing: -0.02em; }
.hero p { margin: 0; opacity: 0.9; line-height: 1.45; }
.meta { display: flex; flex-wrap: wrap; gap: 0.75rem; margin: 1rem 0 1.25rem; }
.pill {
  background: #fff; border: 1px solid var(--line); border-radius: 999px;
  padding: 0.35rem 0.85rem; font-size: 0.85rem; font-weight: 600;
}
h2 { font-size: 1.2rem; margin: 1.75rem 0 0.85rem; }
.cq-chart-frame { display: flex; align-items: stretch; gap: 0.5rem; }
.cq-y-label {
  writing-mode: vertical-rl; transform: rotate(180deg);
  font-size: 0.72rem; font-weight: 700; letter-spacing: 0.06em; color: #334155;
  text-align: center; padding: 0.5rem 0;
}
.cq-x-label {
  text-align: center; font-size: 0.72rem; font-weight: 700;
  letter-spacing: 0.06em; color: #334155; margin-top: 0.45rem;
}
.cq-plot {
  position: relative; flex: 1; min-height: 560px; height: 600px;
  background: repeating-linear-gradient(-45deg, #0b1f3a, #0b1f3a 8px, #0d2748 8px, #0d2748 16px);
  border: 2px solid #93c5fd; border-radius: 4px; overflow: hidden;
}
.cq-cross-h, .cq-cross-v { position: absolute; background: rgba(255,255,255,0.35); z-index: 1; }
.cq-cross-h { left: 0; right: 0; top: 50%; height: 1px; }
.cq-cross-v { top: 0; bottom: 0; left: 50%; width: 1px; }
.cq-quad-label {
  position: absolute; z-index: 2; color: rgba(255,255,255,0.85);
  font-size: 0.78rem; font-weight: 600;
}
.cq-tl { top: 10px; left: 12px; } .cq-tr { top: 10px; right: 12px; }
.cq-bl { bottom: 10px; left: 12px; } .cq-br { bottom: 10px; right: 12px; }
.cq-axis-y-max, .cq-axis-y-min, .cq-axis-x-min, .cq-axis-x-max {
  position: absolute; color: rgba(255,255,255,0.55); font-size: 0.7rem; z-index: 2;
}
.cq-axis-y-max { top: 8px; left: 6px; } .cq-axis-y-min { bottom: 8px; left: 6px; }
.cq-axis-x-min { bottom: 4px; left: 28px; } .cq-axis-x-max { bottom: 4px; right: 8px; }
/* Marker is the only positioned center — labels must NOT shift the dot out of its cell */
.cq-dot {
  position: absolute; width: 12px; height: 12px;
  transform: translate(-50%, -50%); z-index: 3;
}
.cq-dot-mark {
  display: block; width: 12px; height: 12px; border-radius: 50%;
  background: var(--dot, #7EB6FF); border: 2px solid #fff;
  box-sizing: border-box;
}
.cq-dot-label {
  position: absolute; top: 50%; transform: translateY(-50%);
  color: #fff; font-size: 0.62rem; font-weight: 600;
  text-shadow: 0 1px 2px rgba(0,0,0,0.75);
  white-space: nowrap; max-width: 88px; overflow: hidden; text-overflow: ellipsis;
  pointer-events: none;
}
.cq-dot.label-right .cq-dot-label { left: 14px; }
.cq-dot.label-left .cq-dot-label { right: 14px; left: auto; }
.cq-dot.label-below .cq-dot-label {
  left: 50%; top: 14px; transform: translate(-50%, 0); max-width: 100px;
}
.cq-dot.label-above .cq-dot-label {
  left: 50%; bottom: 14px; top: auto; transform: translate(-50%, 0); max-width: 100px;
}
/* Keep labels from visually spilling across the 50% crosshairs */
.cq-dot.quad-leaders .cq-dot-label,
.cq-dot.quad-trailblazers .cq-dot-label { max-width: min(110px, 28vw); }
.cq-dot.quad-challengers .cq-dot-label,
.cq-dot.quad-emerging .cq-dot-label { max-width: min(110px, 28vw); }
.cq-explain-grid {
  display: grid; grid-template-columns: repeat(2, 1fr); gap: 0.85rem;
}
@media (max-width: 900px) {
  .cq-explain-grid { grid-template-columns: 1fr; }
  .cq-plot { min-height: 360px; height: 380px; }
}
.cq-explain-card {
  border-radius: 10px; padding: 1rem 1.1rem; color: #fff; min-height: 130px;
}
.cq-explain-card h4 { margin: 0 0 0.35rem; letter-spacing: 0.04em; }
.cq-explain-sub { font-size: 0.78rem; opacity: 0.9; margin-bottom: 0.55rem; font-weight: 600; }
.cq-explain-card p { margin: 0; font-size: 0.88rem; line-height: 1.45; opacity: 0.95; }
.panel {
  background: #fff; border: 1px solid var(--line); border-radius: 12px;
  padding: 1.1rem 1.25rem; margin-bottom: 1.25rem;
}
.table-scroll { overflow-x: auto; }
table.cq {
  width: 100%; border-collapse: collapse; font-size: 0.88rem;
}
table.cq thead th {
  background: var(--navy); color: #fff; text-align: left;
  padding: 0.65rem 0.75rem; font-size: 0.72rem; letter-spacing: 0.03em;
}
table.cq td {
  padding: 0.65rem 0.75rem; border-bottom: 1px solid var(--line); vertical-align: middle;
}
table.cq tr:nth-child(even) td { background: #f1f5f9; }
.cq-tier {
  display: inline-block; padding: 0.2rem 0.55rem; border-radius: 999px;
  font-size: 0.72rem; font-weight: 700; color: #fff;
}
.cq-tier-1 { background: #002857; }
.cq-tier-2 { background: #2563eb; }
.cq-tier-3 { background: #93c5fd; color: #0f172a; }
.cq-score {
  display: inline-flex; align-items: center; justify-content: center;
  width: 2rem; height: 2rem; border-radius: 50%; font-weight: 700;
  font-size: 0.8rem; color: #fff;
}
.cq-score-hi { background: #16a34a; }
.cq-score-mid { background: #ca8a04; }
.cq-score-lo { background: #dc2626; }
.cq-rate-dots { display: inline-flex; gap: 3px; align-items: center; }
.cq-rate-dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
.cq-dot-on { background: #2563eb; }
.cq-dot-off { background: #cbd5e1; }
.scorecard th { white-space: nowrap; font-size: 0.68rem; }
.scorecard td { text-align: center; }
.scorecard td:first-child { text-align: left; font-weight: 600; }
.legend { font-size: 0.8rem; color: #475569; margin: 0 0 0.75rem; }
/* Parameter strength bubble: DIAMETER comes from the score, colour never
   does. The number is always printed next to it — the bubble emphasises,
   it does not replace. */
.cq-bubble { display: inline-block; border-radius: 50%; vertical-align: middle;
  margin-right: 6px; }
/* One colour for every score. Shading by band made a 69 and a 71 look like
   different KINDS of result rather than adjacent numbers; size alone carries
   the magnitude. */
.cq-bub-1 { width: 7px;  height: 7px;  background: var(--score-blue); }
.cq-bub-2 { width: 10px; height: 10px; background: var(--score-blue); }
.cq-bub-3 { width: 13px; height: 13px; background: var(--score-blue); }
.cq-bub-4 { width: 16px; height: 16px; background: var(--score-blue); }
.cq-bub-5 { width: 19px; height: 19px; background: var(--score-blue); }
.cq-bub-num { font-variant-numeric: tabular-nums; font-weight: 600; }
/* Strength column: always 5 circles, small-to-big, filled left-to-right by
   score band -- unlike the single-bubble pattern above, every row shows the
   same 5 fixed sizes so the column reads as one scale regardless of score. */
.cq-strength { display: inline-flex; align-items: center; gap: 4px; margin-right: 6px; }
.cq-sdot {
  display: inline-block; border-radius: 50%; flex: 0 0 auto;
  background: #e2e8f0; border: 1px solid #cbd5e1;
}
.cq-sdot-7  { width: 7px;  height: 7px;  }
.cq-sdot-10 { width: 10px; height: 10px; }
.cq-sdot-13 { width: 13px; height: 13px; }
.cq-sdot-16 { width: 16px; height: 16px; }
.cq-sdot-19 { width: 19px; height: 19px; }
.cq-sdot-on { background: var(--score-blue); border-color: var(--score-blue); }
/* Key takeaways grid: one row per company, one column per parameter, so a
   reader scans down a single column to compare every company on that one
   parameter instead of hunting through a separate block per company. */
.cq-ta td { vertical-align: top; line-height: 1.5; }
.cq-ta td:first-child { white-space: nowrap; font-weight: 600; }
.cq-ta-score-line { font-weight: 700; color: #0f172a; margin-bottom: .25rem; }
/* The scoring rationale: which parts of the parameter's stated measure were
   verified. Set apart from the evidence bullets under it because it
   justifies the NUMBER, where the bullets justify the facts. */
.cq-ta-basis { color: #334155; margin-bottom: .4rem; padding-left: .55rem;
  border-left: 3px solid #cbd5e1; }
/* Evidence as bullets: each stored sentence is a separate finding, so a
   reader can scan them rather than parse one long paragraph. */
.cq-ta-points { margin: 0; padding-left: 1.05rem; }
.cq-ta-points li { margin: 0 0 .3rem; }
.cq-ta-points li:last-child { margin-bottom: 0; }
.cq-param-card th { white-space: nowrap; font-size: 0.68rem; }
.cq-param-card td { vertical-align: top; }
.cq-param-card td:first-child, .cq-param-card td:nth-child(2) { text-align: left; }
.cq-param-card td:first-child { font-weight: 600; }
.cq-axis-tot { background: #f1f5f9; font-weight: 700; }
/* Axis score as a disc; click it to reveal that axis's parameters. Built on
   <details>/<summary> so the report still works opened straight from disk
   with no JavaScript, and stays keyboard-navigable. */
.cq-axis-cell { text-align: left; white-space: nowrap; }
.cq-disc { display: inline-flex; align-items: center; justify-content: center;
  width: 38px; height: 38px; border-radius: 50%; color: #fff;
  font-weight: 700; font-size: 0.82rem; font-variant-numeric: tabular-nums; }
.cq-disc { background: var(--score-blue); }
.cq-pp { display: inline-block; }
.cq-pp-toggle { display: inline-flex; align-items: center; gap: 7px;
  cursor: pointer; list-style: none; }
.cq-pp-toggle::-webkit-details-marker { display: none; }
/* Caret tucked against the RIGHT edge of the disc and pointing back at it,
   so the two read as one control rather than a score with a stray mark
   floating beside it. Rotates down when the row is open. */
.cq-pp-arrow { width: 0; height: 0; border-top: 6px solid transparent;
  border-bottom: 6px solid transparent;
  border-right: 7px solid var(--score-blue);
  transition: transform .15s ease; }
.cq-pp[open] .cq-pp-arrow { transform: rotate(-90deg); }
/* Hover affordance: the disc lifts slightly and the caret darkens, so a
   reader can tell the score is clickable before reading the tooltip. */
.cq-pp-toggle:hover .cq-disc { transform: scale(1.08); }
.cq-pp-toggle:hover .cq-pp-arrow { border-right-color: #0f172a; }
.cq-disc { transition: transform .12s ease; }
/* Keyboard users get the same affordance as a mouse hover. */
.cq-pp-toggle:focus-visible { outline: 2px solid #2563eb; outline-offset: 3px;
  border-radius: 24px; }
.cq-pp-box { margin-top: 8px; padding: 10px 12px; background: #f8fafc;
  border: 1px solid #e2e8f0; border-radius: 8px; min-width: 300px; }
.cq-pp-row { display: flex; justify-content: space-between; gap: 18px;
  padding: 3px 0; font-size: 0.82rem; white-space: normal; }
.cq-pp-row + .cq-pp-row { border-top: 1px solid #eef2f7; }
.cq-pp-name { color: #334155; }
.cq-pp-score { font-weight: 700; font-variant-numeric: tabular-nums;
  color: #1e3a8a; }
.footer { color: var(--muted); font-size: 0.8rem; margin-top: 1.5rem; }
.cq-method-step {
  display: flex; gap: 0.85rem; margin-bottom: 1.1rem; align-items: flex-start;
}
.cq-method-num {
  flex: none; width: 1.9rem; height: 1.9rem; border-radius: 50%;
  background: var(--navy); color: #fff; font-weight: 700; font-size: 0.85rem;
  display: flex; align-items: center; justify-content: center;
}
.cq-method-body h4 { margin: 0 0 0.25rem; font-size: 0.95rem; color: #0f172a; }
.cq-method-body p { margin: 0; font-size: 0.87rem; line-height: 1.5; color: #475569; }
.cq-weight-block { background: #f8fafc; border: 1px solid var(--line); border-radius: 10px; padding: 1rem 1.1rem; }
.cq-weight-block + .cq-weight-block { margin-top: 1rem; }
.cq-weight-title { font-weight: 700; color: #0f172a; margin-bottom: 0.7rem; font-size: 0.95rem; }
.cq-weight-row { display: flex; align-items: center; gap: 0.6rem; margin-bottom: 0.5rem; }
.cq-weight-label { flex: 0 0 42%; font-size: 0.82rem; color: #334155; line-height: 1.3; }
.cq-weight-track { flex: 1; height: 0.65rem; background: #e2e8f0; border-radius: 999px; overflow: hidden; }
.cq-weight-fill { height: 100%; background: linear-gradient(90deg, #0d9488, #002857); border-radius: 999px; }
.cq-weight-pct { flex: 0 0 3rem; text-align: right; font-size: 0.8rem; font-weight: 700; color: #0f172a; }
.cq-formula {
  font-family: "Consolas", "SFMono-Regular", monospace; background: #0f172a; color: #7EB6FF;
  border-radius: 8px; padding: 0.85rem 1rem; font-size: 0.82rem; line-height: 1.7; overflow-x: auto;
}
.cq-norm-scale { display: flex; align-items: center; gap: 0.5rem; margin-top: 0.6rem; }
.cq-norm-track {
  flex: 1; height: 1.4rem; border-radius: 999px; position: relative;
  background: linear-gradient(90deg, #94a3b8 0%, #94a3b8 var(--floor-pct,65%), #0d9488 var(--floor-pct,65%), #002857 100%);
}
.cq-norm-tick {
  position: absolute; top: -1.15rem; font-size: 0.68rem; color: #64748b; transform: translateX(-50%);
}
.cq-flow {
  display: flex; align-items: stretch; gap: 0; flex-wrap: wrap; margin: 1.1rem 0 1.3rem;
}
.cq-flow-step {
  flex: 1 1 150px; min-width: 150px; background: linear-gradient(160deg, #0f172a, #1e3a5f);
  color: #f8fafc; border-radius: 12px; padding: 1rem 1rem 1.1rem; position: relative;
}
.cq-flow-badge {
  width: 1.9rem; height: 1.9rem; border-radius: 50%; background: #0d9488;
  display: flex; align-items: center; justify-content: center; font-weight: 700;
  font-size: 0.85rem; margin-bottom: 0.6rem;
}
.cq-flow-title { font-weight: 700; font-size: 0.88rem; margin-bottom: 0.35rem; letter-spacing: 0.01em; }
.cq-flow-text { font-size: 0.78rem; line-height: 1.45; opacity: 0.88; }
.cq-flow-arrow {
  flex: 0 0 2rem; display: flex; align-items: center; justify-content: center;
  color: #94a3b8; font-size: 1.3rem; font-weight: 700;
}
@media (max-width: 900px) {
  .cq-flow-arrow { flex-basis: 100%; transform: rotate(90deg); padding: 0.2rem 0; }
}
.cq-primary-note {
  background: #f0fdfa; border: 1px solid #99f6e4; border-radius: 10px;
  padding: 0.9rem 1.1rem; font-size: 0.87rem; line-height: 1.55; color: #134e4a; margin-bottom: 1rem;
}
.cq-primary-note strong { color: #0f766e; }
.cq-method-footnote { font-size: 0.82rem; line-height: 1.55; color: #64748b; margin: 0; }
"""


def _esc(s: Any) -> str:
    return html.escape(str(s or ""))


def _label(b: dict[str, Any]) -> str:
    """Plain brand name — strip any leftover ``(acquired by …)`` from older payloads."""
    raw = str(b.get("display_name") or b.get("brand") or "").strip()
    name = re.sub(
        r"\s*\((?:acquired by|merged into|subsidiary of)\s+[^)]+\)\s*$",
        "",
        raw,
        flags=re.I,
    ).strip() or raw
    return name


def _chart_label(b: dict[str, Any]) -> str:
    """Short brand-only label so neighbors stay readable; country stays in title."""
    return _label(b)


def _chart_title(b: dict[str, Any]) -> str:
    name = _label(b)
    country = str(b.get("country") or "").strip()
    if country and country.lower() not in {"unknown", "n/a", "-"}:
        return f"{name} ({country})"
    return name


_QUAD_CELL_CSS = {
    # left_lo, left_hi, top_lo, top_hi — keep a clear gap from 50% crosshairs
    "Challengers": (10, 36, 10, 36),
    "Leaders": (64, 90, 10, 36),
    "Emerging Players": (10, 36, 64, 90),
    "Trailblazers": (64, 90, 64, 90),
}


def _clamp_dot_to_quadrant(left: int, top: int, quadrant: str) -> tuple[int, int]:
    lo_l, hi_l, lo_t, hi_t = _QUAD_CELL_CSS.get(quadrant) or (62, 92, 8, 38)
    return max(lo_l, min(hi_l, int(left))), max(lo_t, min(hi_t, int(top)))


def _company_col(b: dict[str, Any]) -> str:
    """Company column as stored — do not reformat; synthesize already applied market mode."""
    company = str(b.get("company") or "").strip()
    if company:
        return company
    owner = str(b.get("parent_owner") or "").strip()
    if not owner:
        return ""
    # Fallback for older payloads without formatted company
    mode = str(b.get("company_display_mode") or "").strip().lower()
    if mode == "solution_provider":
        return owner
    from vendor_intel.quadrant.brand_meta import format_acquired_suffix

    return format_acquired_suffix(
        owner, relation=str(b.get("ownership_relation") or "acquired_by")
    )


def _founded_loc(b: dict[str, Any]) -> str:
    loc = str(b.get("founded_location") or "").strip()
    if loc:
        return loc
    founded = str(b.get("founded_in") or "").strip()
    # Prefer location; skip year-only values
    if founded and not re.fullmatch(r"(19|20)\d{2}", founded):
        return founded
    return str(b.get("hq_location") or "").strip()


def _score_class(n: int) -> str:
    # Company Details X/Y/Overall: always green
    return "cq-score-hi"


def _tier_class(tier: str) -> str:
    t = (tier or "").lower().replace(" ", "")
    if "1" in t:
        return "cq-tier-1"
    if "2" in t:
        return "cq-tier-2"
    return "cq-tier-3"


def _dots(rating: str) -> str:
    filled = _RATING_DOTS.get((rating or "").lower().strip(), 3)
    filled = max(1, min(5, int(filled)))
    parts = [
        f'<span class="cq-rate-dot {"cq-dot-on" if i <= filled else "cq-dot-off"}"></span>'
        for i in range(1, 6)
    ]
    return f'<span class="cq-rate-dots" title="{_esc(rating)}">{"".join(parts)}</span>'


# --- canonical dataset + view model ---------------------------------------
#
# ONE scored-company list feeds every section, so the scorecard, the Top 20
# table, the Top 20 graph and Other Noticeable Players can never disagree.
# The view model is where evidence is dropped: the backend record keeps the
# claims and sources, and nothing downstream of build_view_model can render
# them because they are not in the dict it returns.

# Evidence keys the HTML must never carry. Asserted by the view-model builder
# rather than trusted, so a future field cannot leak by being added upstream.
_EVIDENCE_KEYS = ("evidence", "claim", "source", "sources", "citation", "citations")


def all_scored_companies(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """The canonical company list, ranked exactly as the payload ordered it.

    Ranking and Top 20 selection are the pipeline's, not this module's — the
    report only reads `on_chart`, which scoring already set.
    """
    return list(payload.get("brands") or [])


def split_top20(
    companies: list[dict[str, Any]], limit: int = 20
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(top20, others) from one list, with no company in both and none lost.

    Membership follows the `on_chart` flag the pipeline already set, so the
    table and the graph plot the same companies. When that flag is missing
    (older payloads) the first `limit` rows stand in, which is what the chart
    itself falls back to.
    """
    flagged = [c for c in companies if c.get("on_chart") is True]
    top = flagged[:limit] if flagged else companies[:limit]
    top_ids = {id(c) for c in top}
    others = [c for c in companies if id(c) not in top_ids]
    return top, others


def _bubble(score: int) -> str:
    """Strength bubble sized from the score itself — never randomised.

    Five steps so the size is readable at a glance; the number is always
    rendered beside it, so the bubble adds emphasis rather than replacing
    information.
    """
    n = max(0, min(100, int(score or 0)))
    cls = _bubble_class(n)
    return (
        f'<span class="cq-bubble {cls}" title="{n}"></span>'
        f'<span class="cq-bub-num">{n}</span>'
    )


def build_view_model(
    company: dict[str, Any], x_params: list[str], y_params: list[str]
) -> dict[str, Any]:
    """Backend record -> the ONLY fields the HTML may render.

    Evidence is excluded here, deliberately and by construction: the returned
    dict holds scores and labels, so a template cannot print a claim or a
    source URL even by accident. `_assert_no_evidence` makes that a checked
    guarantee rather than a convention.
    """
    detail = company.get("score_detail") or {}

    def _params(axis_key: str, names: list[str]) -> dict[str, int | None]:
        stored = ((detail.get(axis_key) or {}).get("parameters")) or {}
        # Dynamic by design: whatever this market's axis configuration names,
        # in its own order. Nothing is hardcoded to X1/X2/X3.
        return {
            name: (stored.get(name) or {}).get("score")
            for name in names
        }

    view = {
        "brand": _label(company),
        "company": _company_col(company),
        "hq": _founded_loc(company),
        "role": str(company.get("commercial_role") or company.get("company_function") or ""),
        "quadrant": str(company.get("quadrant") or ""),
        "x_score": _int_or_none(company.get("execution")),
        "y_score": _int_or_none(company.get("innovation")),
        "overall_score": _int_or_none(company.get("overall")),
        "x_parameters": _params("x", x_params),
        "y_parameters": _params("y", y_params),
    }
    _assert_no_evidence(view)
    return view


def _int_or_none(value: Any) -> int | None:
    text = str(value or "").strip()
    if not text or text in ("—", "-"):
        return None
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


def _assert_no_evidence(view: dict[str, Any]) -> None:
    """Fail loudly if an evidence field ever reaches the view model.

    Requirement 6 is that the renderer cannot show evidence. A silent filter
    would drift the first time someone adds a field upstream; this turns that
    into an immediate error instead of a leaked source URL in a client report.
    """
    for key in view:
        if str(key).lower() in _EVIDENCE_KEYS:
            raise ValueError(f"evidence field {key!r} must not reach the HTML view model")


def _axis_labels(payload: dict[str, Any]) -> tuple[str, str]:
    """Axis titles as the REPORT presents them — FIXED for every market.

    X is always Product Capability and Y always Business Capability; only the
    5 parameters under each axis change per market. Whatever title a saved
    payload carries (an old market-specific one such as "Service Delivery
    Capability", or the internal "Product Strength" key) is ignored here.
    """
    from vendor_intel.quadrant.quadrant_language import AXIS_X_TITLE, AXIS_Y_TITLE

    return AXIS_X_TITLE, AXIS_Y_TITLE


def _label_side(quad: str, left: int, top: int) -> str:
    """Point labels outward within the quadrant — never toward the crosshairs."""
    # Near the horizontal midline → stack vertically away from the line
    if quad in ("Leaders", "Challengers") and top >= 32:
        return "label-above"
    if quad in ("Trailblazers", "Emerging Players") and top <= 68:
        return "label-below"
    # Otherwise point toward the outer vertical edge (away from 50%)
    if quad in ("Leaders", "Trailblazers"):
        return "label-right" if left < 80 else "label-left"
    return "label-left" if left > 20 else "label-right"


def _chart(payload: dict[str, Any]) -> str:
    all_brands = list(payload.get("brands") or [])
    # Graph: only top 20 chart brands (on_chart); fall back to first 20 if flag missing
    brands = [b for b in all_brands if b.get("on_chart") is True]
    if not brands:
        brands = all_brands[:20]
    dots = []
    for b in brands:
        # Hard clamp into the quadrant cell (never sit on / across the 50% cross)
        left, top = _clamp_dot_to_quadrant(
            int(b.get("left_pct") or 50),
            int(b.get("top_pct") or 50),
            str(b.get("quadrant") or "Leaders"),
        )
        quad = str(b.get("quadrant") or "Leaders")
        color = _QUAD_COLORS.get(quad, "#7EB6FF")
        name = _esc(_chart_label(b))
        title = _esc(_chart_title(b))
        side = _label_side(quad, left, top)
        qclass = {
            "Leaders": "quad-leaders",
            "Challengers": "quad-challengers",
            "Trailblazers": "quad-trailblazers",
            "Emerging Players": "quad-emerging",
        }.get(quad, "quad-leaders")
        dots.append(
            f'<div class="cq-dot {side} {qclass}" style="left:{left}%;top:{top}%;--dot:{color}" title="{title}">'
            f'<span class="cq-dot-mark"></span><span class="cq-dot-label">{name}</span></div>'
        )
    n_chart = len(brands)
    n_table = len(all_brands)
    # Country mix shown on chart, per quadrant
    from collections import Counter

    by_q: dict[str, Counter[str]] = {}
    for b in brands:
        q = str(b.get("quadrant") or "Leaders")
        c = str(b.get("country") or "Unknown").strip() or "Unknown"
        by_q.setdefault(q, Counter())[c] += 1
    mix_bits = []
    for q in ("Leaders", "Challengers", "Trailblazers", "Emerging Players"):
        ctr = by_q.get(q) or Counter()
        if not ctr:
            continue
        countries = ", ".join(f"{c}×{n}" for c, n in ctr.most_common(6))
        mix_bits.append(f"<strong>{_esc(quadrant_label(q))}</strong>: {_esc(countries)}")
    mix_html = (
        f'<div class="cq-country-mix" style="margin-top:.75rem;font-size:.82rem;color:#475569;line-height:1.45">'
        f'<div style="font-weight:600;margin-bottom:.25rem">Countries on chart (by quadrant)</div>'
        + " · ".join(mix_bits)
        + "</div>"
        if mix_bits
        else ""
    )
    x_name, y_name = _axis_labels(payload)
    # Name the scale on the axis itself, so a reader knows which end is which
    # without hunting for the legend.
    from vendor_intel.quadrant.quadrant_language import SCALE_HIGH, SCALE_LOW

    scale = f"{SCALE_LOW.upper()} → {SCALE_HIGH.upper()}"
    x_label = f"{x_name.upper()} ( X AXIS ) · {scale} →"
    y_label = f"{y_name.upper()} ( Y AXIS ) · {scale} →"
    return f"""
<div class="panel">
  <h2>Quadrant Positioning <span style="font-weight:500;font-size:0.85rem;opacity:.75">
  ({n_chart} on chart · {n_table} in table · ~equal per quadrant · country-diverse)</span></h2>
  <div class="cq-chart-frame">
    <div class="cq-y-label">{_esc(y_label)}</div>
    <div class="cq-plot">
      <div class="cq-axis-y-max">100</div>
      <div class="cq-axis-y-min">0</div>
      <div class="cq-axis-x-min">0</div>
      <div class="cq-axis-x-max">100</div>
      <div class="cq-quad-label cq-tl">Challengers</div>
      <div class="cq-quad-label cq-tr">Leaders</div>
      <div class="cq-quad-label cq-bl">{_esc(quadrant_label("Emerging Players"))}</div>
      <div class="cq-quad-label cq-br">Trailblazers</div>
      <div class="cq-cross-h"></div>
      <div class="cq-cross-v"></div>
      {"".join(dots)}
    </div>
  </div>
  <div class="cq-x-label">{_esc(x_label)}</div>
  {mix_html}
</div>
"""


def _explain(x_name: str, y_name: str) -> str:
    cards = []
    from vendor_intel.quadrant.quadrant_language import quadrant_title

    for title, sub, body in build_quadrant_explain(x_name, y_name):
        color = _EXPLAIN_CARD_COLOR[title]
        # Chart label stays short ("Leaders"); the card carries the full
        # presentation title ("Integrated Market Leaders") so the conclusion
        # and the plot use the same vocabulary.
        cards.append(
            f'<div class="cq-explain-card" style="background:{color}">'
            f"<h4>{_esc(quadrant_title(title))}</h4>"
            f'<div class="cq-explain-sub">{_esc(sub)}</div>'
            f"<p>{_esc(body)}</p></div>"
        )
    return (
        '<div class="panel"><h2>Understanding the Coherent Quadrant</h2>'
        f'<div class="cq-explain-grid">{"".join(cards)}</div></div>'
    )


def _score_from_axis(value: int) -> str:
    if value >= 85:
        return "very-high"
    if value >= 70:
        return "high"
    if value >= 50:
        return "average"
    if value >= 35:
        return "low"
    return "very-low"


def _scorecard(
    payload: dict[str, Any],
    *,
    axis: str,
    title: str,
    which: str = "x",
) -> str:
    criteria = payload.get("criteria") or {}
    features = list(criteria.get("x_axis" if which == "x" else "y_axis") or [])
    brands = list(payload.get("brands") or [])
    # Scorecards only for brands on the chart
    brands = [b for b in brands if b.get("on_chart") is not False][:20]
    scorecard = list(payload.get("scorecard") or [])
    by_key: dict[tuple[str, str], str] = {}
    for row in scorecard:
        row_axis = str(row.get("axis") or "")
        if row_axis and row_axis != axis:
            continue
        by_key[
            (str(row.get("brand") or "").strip().lower(), str(row.get("criterion") or "").strip().lower())
        ] = str(row.get("rating") or "average")

    if not features:
        seen: list[str] = []
        for row in scorecard:
            row_axis = str(row.get("axis") or "")
            if row_axis and row_axis != axis:
                continue
            feat = str(row.get("criterion") or "").strip()
            if feat and feat not in seen:
                seen.append(feat)
        features = seen
    if not features or not brands:
        return ""

    head = "".join(f"<th>{_esc(f)}</th>" for f in features) + "<th>OVERALL</th>"
    rows = []
    for b in brands:
        label = _label(b)
        brand_key = str(b.get("brand") or label).strip().lower()
        cells = [f"<td>{_esc(label)}</td>"]
        for feat in features:
            rating = by_key.get((brand_key, feat.lower())) or by_key.get(
                (label.lower(), feat.lower()), "average"
            )
            cells.append(f"<td>{_dots(rating)}</td>")
        overall_src = int(
            b.get("execution") if which == "x" else b.get("innovation") or 0
        )
        cells.append(f"<td>{_dots(_score_from_axis(overall_src))}</td>")
        rows.append(f"<tr>{''.join(cells)}</tr>")

    legend = (
        '<div class="legend">Rating: '
        f"{_dots('very-high')} Very High &nbsp; {_dots('high')} High &nbsp; "
        f"{_dots('average')} Average &nbsp; {_dots('low')} Low &nbsp; "
        f"{_dots('very-low')} Very Low</div>"
    )
    return f"""
<div class="panel">
  <h2>{_esc(title)}</h2>
  {legend}
  <div class="table-scroll">
    <table class="cq scorecard">
      <thead><tr><th>BRAND</th>{head}</tr></thead>
      <tbody>{"".join(rows)}</tbody>
    </table>
  </div>
</div>
"""


def _companies(payload: dict[str, Any], x_name: str = "X", y_name: str = "Y") -> str:
    brands = list(payload.get("brands") or [])
    x_hdr = f"X ({x_name})"
    y_hdr = f"Y ({y_name})"
    rows = []
    for b in brands:
        ex = int(b.get("execution") or 0)
        inn = int(b.get("innovation") or 0)
        overall = int(b.get("overall") or 0)
        on_chart = b.get("on_chart")
        # Unscored table-only rows: show blank scores instead of 0
        if on_chart is False and ex == 0 and inn == 0 and overall == 0:
            ex_html = inn_html = ov_html = "—"
            quad = ""
        else:
            ex_html = f'<span class="cq-score {_score_class(ex)}">{ex}</span>'
            inn_html = f'<span class="cq-score {_score_class(inn)}">{inn}</span>'
            ov_html = f'<span class="cq-score {_score_class(overall)}">{overall}</span>'
            quad = str(b.get("quadrant") or "")
        role = str(
            b.get("commercial_role")
            or b.get("company_function")
            or ""
        ).strip()
        rows.append(
            "<tr>"
            f"<td>{_esc(_label(b))}</td>"
            f"<td>{_esc(_company_col(b))}</td>"
            f"<td>{_esc(role)}</td>"
            f"<td>{_esc(quad)}</td>"
            f"<td>{ex_html}</td>"
            f"<td>{inn_html}</td>"
            f"<td>{ov_html}</td>"
            f"<td>{_esc(_founded_loc(b))}</td>"
            "</tr>"
        )
    return f"""
<div class="panel">
  <h2>Company Details <span style="font-weight:500;font-size:0.85rem;opacity:.75">
  ({len(brands)} rows)</span></h2>
  <div class="table-scroll">
    <table class="cq">
      <thead>
        <tr>
          <th>BRAND</th><th>COMPANY</th><th>ROLE</th><th>QUADRANT</th>
          <th>{_esc(x_hdr)}</th><th>{_esc(y_hdr)}</th><th>OVERALL SCORE</th>
          <th>HQ</th>
        </tr>
      </thead>
      <tbody>{"".join(rows) or '<tr><td colspan="8">No brands</td></tr>'}</tbody>
    </table>
  </div>
</div>
"""


def _axis_parameters(payload: dict[str, Any]) -> tuple[list[str], list[str]]:
    """This market's X and Y parameter names, in configuration order."""
    criteria = payload.get("criteria") or {}
    x = [str(p).strip() for p in (criteria.get("x_axis") or []) if str(p).strip()]
    y = [str(p).strip() for p in (criteria.get("y_axis") or []) if str(p).strip()]
    return x, y


def _disc_score(value: int | None) -> str:
    """A score as the same fixed-size disc X/Y cells use, with no dropdown.

    _axis_cell wraps this same disc markup in a <details> toggle because it
    has per-parameter rows to reveal underneath. Overall Score has no
    parameter breakdown of its own, so it renders just the disc — same
    size, same font, same fill colour as X and Y — without a caret that
    would open onto nothing.
    """
    if value is None:
        return "—"
    n = max(0, min(100, int(value)))
    return f'<span class="cq-disc {_bubble_class(n)}">{n}</span>'


def _axis_cell(
    uid: str,
    score: int | None,
    scores_by_param: dict[str, int | None],
    order: list[str],
) -> str:
    """One axis score as a clickable disc that reveals its parameters.

    Built with <details>/<summary> rather than JavaScript: the report is a
    standalone file opened straight from disk, and native disclosure keeps it
    keyboard-accessible, printable and working with scripts disabled.

    A company with no parameter detail renders as a plain score, because an
    arrow that opens an empty box is worse than no arrow.
    """
    if score is None:
        return "<td>—</td>"

    rows = [
        f'<div class="cq-pp-row"><span class="cq-pp-name">{_esc(name)}</span>'
        f'<span class="cq-pp-score">{scores_by_param[name]}</span></div>'
        for name in order
        if scores_by_param.get(name) is not None
    ]
    disc = f'<span class="cq-disc {_bubble_class(score)}">{score}</span>'
    if not rows:
        return f'<td class="cq-axis-cell">{disc}</td>'

    # The arrow follows the disc, and `title` gives a native hover tooltip —
    # no JavaScript, so it survives being opened straight from disk.
    return (
        '<td class="cq-axis-cell">'
        f'<details class="cq-pp" id="pp-{uid}">'
        '<summary class="cq-pp-toggle" title="Click a score for the breakdown">'
        f'{disc}<span class="cq-pp-arrow"></span></summary>'
        f'<div class="cq-pp-box">{"".join(rows)}</div>'
        "</details></td>"
    )


def _bubble_class(score: int) -> str:
    """Bubble strength band for a score — shared by the disc and the dot."""
    n = max(0, min(100, int(score or 0)))
    if n >= 85:
        return "cq-bub-5"
    if n >= 70:
        return "cq-bub-4"
    if n >= 50:
        return "cq-bub-3"
    if n >= 30:
        return "cq-bub-2"
    return "cq-bub-1"


# [label](url "title") -> label. The URL belongs in the JSON, not the report.
_MD_LINK = re.compile(r"\[([^\]]+)\]\(\s*<?https?://[^)]*\)")
# A link pasted without Markdown around it.
_BARE_URL = re.compile(r"<?https?://\S+>?")


def _first_sentence(text: str, limit: int = 420) -> str:
    """One sentence of takeaway, not the whole evidence paragraph.

    The stored claim often runs several sentences with sources and asides.
    The JSON keeps all of it; the report shows the first sentence, which is
    where the specific finding lives ("N-type TOPCon cells reach 22.5%
    module efficiency"). Falls back to a clean truncation when the claim has
    no sentence break.

    The limit is a runaway guard, not the normal path: across the four scored
    markets the longest real first sentence is 494 characters and 97% are
    under 360, so 420 keeps almost every takeaway a complete sentence rather
    than cutting it mid-clause.
    """
    flat = " ".join(str(text or "").split())
    if not flat:
        return ""
    # Claims sometimes arrive with the source inline as a Markdown link. Keep
    # the label, drop the URL: the report shows the finding, and the full
    # record including the link stays in the scores JSON.
    flat = _MD_LINK.sub(r"\1", flat)
    flat = _BARE_URL.sub("", flat)
    flat = " ".join(flat.replace("()", "").split())
    # Split on . ! ? followed by a space + capital, so "22.5% efficiency" and
    # "Co., Ltd." do not end the sentence early.
    match = re.search(r"(?<=[.!?])\s+(?=[A-Z(])", flat)
    first = flat[: match.start()] if match else flat
    if len(first) > limit:
        cut = first[:limit].rsplit(" ", 1)[0]
        return cut.rstrip(",;:") + "…"
    return first


def _strip_links(text: str) -> str:
    """Markdown link -> its label; bare URL removed."""
    out = _MD_LINK.sub(r"\1", str(text or ""))
    out = _BARE_URL.sub("", out)
    return " ".join(out.replace("()", "").split())


def _sentences(text: str) -> list[str]:
    """Split an evidence claim into its sentences.

    The stored claim routinely runs 400-600 characters across two or three
    sentences, each carrying a different fact -- a capacity figure, then the
    contract it supports, then the source. Showing only the first discards
    the rest of the evidence text, which is precisely the reasoning a client
    needs to see behind a score.

    Decimals and abbreviations must not end a sentence: "1.5 Mt" and
    "Co., Ltd." are split points only if the following token starts a new
    sentence (space + capital).
    """
    flat = _strip_links(text)
    if not flat:
        return []
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z(])", flat)
    return [p.strip() for p in parts if p.strip()]


def _evidence_bullets(evidence: list[dict[str, Any]]) -> str:
    """Every stored sentence across all evidence entries, as list items.

    Source URLs are deliberately dropped -- they stay in the scores JSON.
    What reaches the report is the reasoning, not the link. Duplicate
    sentences (the same fact cited twice) are shown once.
    """
    items: list[str] = []
    seen: set[str] = set()
    for entry in evidence or []:
        for sentence in _sentences((entry or {}).get("claim")):
            key = sentence.lower()
            if key in seen:
                continue
            seen.add(key)
            items.append(f"<li>{_esc(sentence)}</li>")
    if not items:
        return ""
    return f'<ul class="cq-ta-points">{"".join(items)}</ul>'


def _positioning_note(
    view: dict[str, Any], x_name: str, y_name: str
) -> str:
    """One line stating WHY this company sits where it does.

    The per-parameter bullets explain each score; this says what the two
    axis scores add up to, which is the question a client actually asks
    about a quadrant chart.
    """
    x, y, quad = view.get("x_score"), view.get("y_score"), view.get("quadrant")
    if x is None or y is None or not quad:
        return ""
    from vendor_intel.quadrant.quadrant_language import (
        quadrant_label,
        quadrant_position,
    )

    return (
        '<p class="cq-ta-note">Positioned in '
        f'<strong>{_esc(quadrant_label(quad))}</strong> on '
        f"{_esc(x_name)} {x}/100 and {_esc(y_name)} {y}/100 — "
        f"{_esc(quadrant_position(quad).lower())}. "
        "The parameter evidence below is what those two scores are built "
        "from.</p>"
    )


def _takeaways_grid(
    views: list[dict[str, Any]],
    companies: list[dict[str, Any]],
    params: list[str],
    axis_key: str,
    *,
    title: str,
    note: str,
) -> str:
    """One row per company, one column per parameter, cell = its takeaway.

    A reader comparing companies on a single parameter needs to scan down
    one column, not hunt through a separate block per company. Each cell
    leads with the score itself, then lists every stored evidence sentence
    as its own bullet, framed as the reasoning BEHIND that score ("Scored
    70/100 — why:") rather than a bare list of facts -- the score and its
    justification read together, without opening
    chatgpt_xy_scores_batch_all.json.
    """
    if not views or not params:
        return ""

    rows = []
    for view, company in zip(views, companies):
        detail = company.get("score_detail") or {}
        stored = ((detail.get(axis_key) or {}).get("parameters")) or {}
        company_name = _esc(view["company"] or view["brand"])
        cells = []
        has_any = False
        for name in params:
            entry = stored.get(name) or {}
            score = entry.get("score")
            evidence = entry.get("evidence") or []
            bullets = _evidence_bullets(evidence)
            basis = str(entry.get("assessed_on") or "").strip()
            if score is None and not bullets and not basis:
                cells.append("<td>—</td>")
                continue
            has_any = True
            head = (
                f'<div class="cq-ta-score-line">Scored {int(score)}/100 — why:</div>'
                if score is not None else ""
            )
            # The scoring rationale comes FIRST and the findings under it:
            # this line says which parts of the parameter's stated measure
            # were actually verified, which is what justifies the number.
            # The Evidence bullets are the facts it was drawn from.
            basis_html = (
                f'<div class="cq-ta-basis">{_esc(basis)}</div>' if basis else ""
            )
            cells.append(f"<td>{head}{basis_html}{bullets or ''}</td>")
        if has_any:
            rows.append(f"<tr><td>{company_name}</td>{''.join(cells)}</tr>")

    if not rows:
        return ""
    head = "".join(f"<th>{_esc(p)}</th>" for p in params)
    return f"""
<div class="panel">
  <h2>{_esc(title)} <span style="font-weight:500;font-size:0.85rem;opacity:.75">
  ({_esc(note)})</span></h2>
  <div class="table-scroll">
    <table class="cq cq-ta">
      <thead><tr><th>Company</th>{head}</tr></thead>
      <tbody>{"".join(rows)}</tbody>
    </table>
  </div>
</div>
"""


def _strength_table(
    views: list[dict[str, Any]],
    title: str,
    note: str,
    *,
    overrides: dict[str, int] | None = None,
) -> str:
    """Brand | Company | HQ | Role | Strength.

    The long tail does not need four numeric columns: at 159 rows the scores
    read as noise rather than a ranking. A 5-circle strength rating conveys
    the same standing at a glance, and the exact figures remain one section
    up in the scorecard for anyone who wants them.

    overrides: {company name: filled-dot count} from the market's own axes
    spec (payload["strength_fill_overrides"]) -- a per-market display
    override, never baked into this module for one specific market.
    """
    if not views:
        return ""
    overrides = overrides or {}
    scored = [v["overall_score"] for v in views if v["overall_score"] is not None]
    # This table's OWN min/max, not the fixed 65-100 normalization range --
    # see _strength_fill_count's docstring for why a tightly-clustered long
    # tail needs this to spread across all 5 fill levels.
    floor = min(scored) if scored else 65
    ceiling = max(scored) if scored else 100

    def _fill_for(v: dict[str, Any]) -> int:
        overall = v["overall_score"]
        if overall is None:
            return 0
        n = max(0, min(100, int(overall)))
        return overrides.get(
            v["company"], _strength_fill_count(n, floor=floor, ceiling=ceiling)
        )

    # 5-filled rows first, then 4, then 3... ties broken by the raw Overall
    # score so the ordering within one fill level still reads high-to-low.
    views = sorted(
        views,
        key=lambda v: (_fill_for(v), v["overall_score"] if v["overall_score"] is not None else -1),
        reverse=True,
    )
    rows = []
    for v in views:
        overall = v["overall_score"]
        strength = (
            _strength_bubble(
                overall, floor=floor, ceiling=ceiling,
                override=overrides.get(v["company"]),
            )
            if overall is not None else "—"
        )
        rows.append(
            "<tr>"
            f"<td>{_esc(v['brand'])}</td>"
            f"<td>{_esc(v['company'])}</td>"
            f"<td>{_esc(v['hq'])}</td>"
            f"<td>{_esc(v['role'])}</td>"
            f"<td>{strength}</td>"
            "</tr>"
        )
    return f"""
<div class="panel">
  <h2>{_esc(title)} <span style="font-weight:500;font-size:0.85rem;opacity:.75">
  ({_esc(note)})</span></h2>
  <div class="table-scroll">
    <table class="cq">
      <thead>
        <tr><th>BRAND</th><th>COMPANY</th><th>HQ</th><th>ROLE</th><th>STRENGTH</th></tr>
      </thead>
      <tbody>{"".join(rows)}</tbody>
    </table>
  </div>
</div>
"""


_STRENGTH_SIZES = (7, 10, 13, 16, 19)  # px, matches .cq-bub-1..5


def _strength_fill_count(score: int, *, floor: int = 65, ceiling: int = 100) -> int:
    """How many of the 5 strength dots (out of 5) a score fills.

    Overall scores here are floor-normalized so every one already lands in
    [floor, ceiling] (see normalize_row_score_floor) -- reusing
    _bubble_class's raw 0-100 bands (>=85, >=70, >=50, >=30) against a score
    that can never go below 65 only ever reaches its top 2 of 5 bands,
    which is why the vast majority of companies were rendering all 5 dots
    filled regardless of real standing. This splits the [floor, ceiling]
    range into 5 even bands instead, so all 5 fill levels are actually
    used and the column keeps differentiating companies near the top of
    the range.

    floor/ceiling default to the fixed 65-100 normalization range, but
    _strength_table passes the CURRENT table's own min/max instead: a long
    tail whose real scores cluster in, say, 65-82 would otherwise have 80%
    of its rows landing in the bottom 1-2 bands of the fixed 65-100 scale
    (confirmed live on Wearable Glucometer's 167-row Other Noticeable
    Player table) even though there is real spread to show within that
    narrower cluster.
    """
    n = max(floor, min(ceiling, int(score or floor)))
    span = max(1, ceiling - floor)
    step = span / 5.0
    band = int((n - floor) // step)
    return max(1, min(5, band + 1))


def _strength_bubble(
    score: int, *, floor: int = 65, ceiling: int = 100,
    override: int | None = None,
) -> str:
    """Overall score as 5 FIXED circles, small-to-big, filled by score band.

    All 5 circles are always drawn at the same 5 sizes in the same order --
    the column reads as one consistent scale no matter how many rows there
    are. How many of the 5 (counting from the smallest) are filled/coloured
    comes from _strength_fill_count, banded against [floor, ceiling] --
    _strength_table passes the CURRENT table's own min/max score so a
    tightly-clustered long tail still spreads across all 5 fill levels
    (see _strength_fill_count's docstring). No number is printed beside
    the dots here and there is no hover tooltip -- this column is the filled
    bubbles alone. The score itself stays in the saved JSON ("overall").
    """
    n = max(0, min(100, int(score or 0)))
    filled = (
        max(1, min(5, int(override))) if override
        else _strength_fill_count(n, floor=floor, ceiling=ceiling)
    )
    dots = "".join(
        f'<span class="cq-sdot cq-sdot-{size}'
        f'{" cq-sdot-on" if i <= filled else ""}"></span>'
        for i, size in enumerate(_STRENGTH_SIZES, 1)
    )
    return f'<span class="cq-strength">{dots}</span>'


def _ranked_table(
    views: list[dict[str, Any]],
    title: str,
    note: str,
    x_name: str,
    y_name: str,
    *,
    x_params: list[str] | None = None,
    y_params: list[str] | None = None,
    uid: str = "t",
) -> str:
    """Brand | Company | HQ | Role | Quadrant | X | Y | Overall score.

    X and Y are expandable discs when the parameter lists are supplied —
    the same control as the scorecard, so a reader who wants the breakdown
    does not have to scroll back up to a different table to find it.
    Overall Score always renders as that same fixed-size disc (never a
    dropdown, since it has no parameters of its own to reveal), so the
    three score columns read as one consistent visual scale rather than
    Overall looking like a smaller, different kind of number.
    """
    if not views:
        return ""
    rows = []
    for i, v in enumerate(views):
        if x_params and y_params:
            x_cell = _axis_cell(f"{uid}x{i}", v["x_score"], v["x_parameters"], x_params)
            y_cell = _axis_cell(f"{uid}y{i}", v["y_score"], v["y_parameters"], y_params)
        else:
            x_cell = f"<td>{_disc_score(v['x_score'])}</td>"
            y_cell = f"<td>{_disc_score(v['y_score'])}</td>"
        rows.append(
            "<tr>"
            f"<td>{_esc(v['brand'])}</td>"
            f"<td>{_esc(v['company'])}</td>"
            # HQ sits beside the company it belongs to — at the far right it
            # was separated from its name by four score columns.
            f"<td>{_esc(v['hq'])}</td>"
            f"<td>{_esc(v['role'])}</td>"
            f"<td>{_esc(quadrant_label(v['quadrant']))}</td>"
            f"{x_cell}"
            f"{y_cell}"
            f"<td>{_disc_score(v['overall_score'])}</td>"
            "</tr>"
        )
    return f"""
<div class="panel">
  <h2>{_esc(title)} <span style="font-weight:500;font-size:0.85rem;opacity:.75">
  ({_esc(note)})</span></h2>
  <div class="table-scroll">
    <table class="cq">
      <thead>
        <tr>
          <th>BRAND</th><th>COMPANY</th><th>HQ</th><th>ROLE</th><th>QUADRANT</th>
          <th>{_esc(f"X ({x_name})")}</th><th>{_esc(f"Y ({y_name})")}</th>
          <th>OVERALL SCORE</th>
        </tr>
      </thead>
      <tbody>{"".join(rows)}</tbody>
    </table>
  </div>
</div>
"""


def _top20_and_others(payload: dict[str, Any], x_name: str, y_name: str) -> tuple[str, str]:
    """Chart table and Other Noticeable Player, from one split.

    The same `split_top20` result also decides what the graph plots, so the
    table and the chart cannot drift apart.
    """
    x_params, y_params = _axis_parameters(payload)
    companies = all_scored_companies(payload)
    top, others = split_top20(companies)
    top_views = [build_view_model(c, x_params, y_params) for c in top]
    # Table order only — chart membership and the quadrant split above both
    # read from `top`/`top_views` before this sort, so plotting is unaffected.
    top_views.sort(key=lambda v: v["overall_score"], reverse=True)
    other_views = [build_view_model(c, x_params, y_params) for c in others]
    # Name the selection rule. These are 5 per quadrant, picked for the
    # clearest separation from the midlines — NOT the 20 highest scores, so
    # a company in Other Noticeable Player can out-score the lowest entry
    # here. Saying so keeps the title from implying a ranking.
    from collections import Counter

    per_quad = Counter(
        quadrant_label(v["quadrant"]) for v in top_views if v["quadrant"]
    )
    spread = " · ".join(f"{q} {n}" for q, n in sorted(per_quad.items())) or "all quadrants"
    return (
        _ranked_table(
            top_views,
            "Top 20 Companies",
            f"the {len(top_views)} companies plotted on the chart above · "
            f"{spread} · click a score for the breakdown",
            x_name, y_name,
            # Same expandable discs as the scorecard. `uid` keeps the
            # <details> ids distinct from the scorecard's, or the two tables
            # would share toggle state.
            x_params=x_params, y_params=y_params, uid="t20",
        ),
        # Hidden entirely when every company made the Top 20 (<= 20 total).
        # Strength bubble instead of four numeric columns — see
        # _strength_table for why the long tail reads better that way.
        _strength_table(
            other_views, "Other Noticeable Player", f"{len(other_views)} companies",
            overrides=payload.get("strength_fill_overrides") or {},
        ),
    )


def _market_classification_panel(payload: dict[str, Any]) -> str:
    """Market / Market Type / Provider Categories, each WITH the reasoning
    behind it.

    market_type_reason and player_type_reason explain a call a reader would
    otherwise have to take on faith: why this market is B2B vs B2C, and why
    its companies were compared as Solution Providers rather than, say,
    Service Providers or Manufacturers. Both come from the same market
    analysis pass that decided the classification -- showing the number
    without the reasoning was the earlier design; this is the reversal of
    that, at the user's request.
    """
    rel = (payload.get("criteria") or {}).get("relevance") or {}
    market_type = str(rel.get("market_type") or "").strip()
    if not market_type:
        return ""
    definition = str(rel.get("market_definition") or "").strip()
    type_reason = str(rel.get("market_type_reason") or "").strip()
    categories = [str(c).strip() for c in (rel.get("keep_roles") or []) if str(c).strip()]
    cat_html = "".join(f"<li>{_esc(c)}</li>" for c in categories)
    player_reason = str(rel.get("player_type_reason") or "").strip()
    market = str(payload.get("market") or "this market")
    return f"""
<div class="panel">
  <h2>Market Classification</h2>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem">
    <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:1rem 1.1rem">
      <div style="font-weight:700;color:#0f172a;margin-bottom:.35rem">Market</div>
      <div style="color:#334155;font-size:.92rem;margin-bottom:.75rem">{_esc(market)}</div>
      <div style="font-weight:700;color:#0f172a;margin-bottom:.35rem">Market Type</div>
      <div style="color:#334155;font-size:.92rem">{_esc(market_type)}{f" &mdash; {_esc(definition)}" if definition else ""}</div>
      {f'<div style="color:#64748b;font-size:.84rem;margin-top:.4rem">{_esc(type_reason)}</div>' if type_reason else ""}
    </div>
    <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:1rem 1.1rem">
      <div style="font-weight:700;color:#0f172a;margin-bottom:.5rem">Provider Categories in this Market</div>
      <ol style="margin:0;padding-left:1.2rem;line-height:1.6;color:#334155">{cat_html or '<li>Brand/Marketer</li>'}</ol>
      {f'<div style="color:#64748b;font-size:.84rem;margin-top:.6rem">{_esc(player_reason)}</div>' if player_reason else ""}
    </div>
  </div>
</div>
"""


def _parameters_panel(payload: dict[str, Any], x_name: str, y_name: str) -> str:
    """Show the market-specific 5 X + 5 Y scoring parameters used for this report."""
    crit = payload.get("criteria") or {}
    x_feats = list(crit.get("x_axis") or [])
    y_feats = list(crit.get("y_axis") or [])
    if not x_feats and not y_feats:
        return ""
    x_lis = "".join(f"<li>{_esc(f)}</li>" for f in x_feats)
    y_lis = "".join(f"<li>{_esc(f)}</li>" for f in y_feats)
    return f"""
<div class="panel">
  <h2>Market Scoring Parameters</h2>
  <p style="margin:0 0 1rem 0;color:#64748b;font-size:.92rem;line-height:1.45">
    X and Y axes and these 10 parameters are defined for
    <strong>{_esc(str(payload.get('market') or 'this market'))}</strong>
    and used to calculate company scores below.
  </p>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem">
    <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:1rem 1.1rem">
      <div style="font-weight:700;color:#0f172a;margin-bottom:.5rem">X — {_esc(x_name)}</div>
      <ol style="margin:0;padding-left:1.2rem;line-height:1.55;color:#334155">{x_lis or '<li>—</li>'}</ol>
    </div>
    <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:1rem 1.1rem">
      <div style="font-weight:700;color:#0f172a;margin-bottom:.5rem">Y — {_esc(y_name)}</div>
      <ol style="margin:0;padding-left:1.2rem;line-height:1.55;color:#334155">{y_lis or '<li>—</li>'}</ol>
    </div>
  </div>
</div>
"""


def _parameter_definitions_panel(
    payload: dict[str, Any], x_name: str, y_name: str
) -> str:
    """End-of-report LLM definitions for each market scoring parameter."""
    crit = payload.get("criteria") or {}
    defs = crit.get("parameter_definitions") or {}
    x_feats = list(crit.get("x_axis") or [])
    y_feats = list(crit.get("y_axis") or [])
    x_defs = defs.get("x") if isinstance(defs, dict) else {}
    y_defs = defs.get("y") if isinstance(defs, dict) else {}
    if not isinstance(x_defs, dict):
        x_defs = {}
    if not isinstance(y_defs, dict):
        y_defs = {}
    if not x_feats and not y_feats:
        return ""

    def _items(feats: list[str], dmap: dict[str, Any]) -> str:
        blocks = []
        for f in feats:
            expl = str(dmap.get(f) or "").strip()
            if not expl:
                # case-insensitive fallback
                for k, v in dmap.items():
                    if str(k).strip().lower() == f.lower():
                        expl = str(v or "").strip()
                        break
            if not expl:
                expl = "Definition pending for this market parameter."
            blocks.append(
                f'<div style="margin:0 0 .85rem 0">'
                f'<div style="font-weight:700;color:#0f172a;margin-bottom:.2rem">{_esc(f)}</div>'
                f'<div style="color:#475569;line-height:1.5;font-size:.92rem">{_esc(expl)}</div>'
                f"</div>"
            )
        return "".join(blocks) or "<div>—</div>"

    market = str(payload.get("market") or "this market")
    return f"""
<div class="panel">
  <h2>Parameter Definitions</h2>
  <p style="margin:0 0 1rem 0;color:#64748b;font-size:.92rem;line-height:1.45">
    What each scoring parameter means for
    <strong>{_esc(market)}</strong>
    (generated for this market — not a fixed template).
  </p>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:1.25rem">
    <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:1rem 1.1rem">
      <div style="font-weight:700;color:#0f172a;margin-bottom:.75rem;font-size:1.02rem">
        X — {_esc(x_name)}
      </div>
      {_items(x_feats, x_defs)}
    </div>
    <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:1rem 1.1rem">
      <div style="font-weight:700;color:#0f172a;margin-bottom:.75rem;font-size:1.02rem">
        Y — {_esc(y_name)}
      </div>
      {_items(y_feats, y_defs)}
    </div>
  </div>
</div>
"""


def _methodology_panel(payload: dict[str, Any], x_name: str, y_name: str) -> str:
    """Research methodology as a market-research-firm-style flow diagram +
    narrative: how the quadrant was independently derived, what counts as
    primary vs. secondary research, and how the two feed into the score."""
    crit = payload.get("criteria") or {}
    x_feats = list(crit.get("x_axis") or [])
    y_feats = list(crit.get("y_axis") or [])
    market = str(payload.get("market") or "this market")
    n_brands = len(payload.get("brands") or [])
    floor, ceiling = int(NORM_FLOOR), int(NORM_CEILING)

    flow = [
        ("Secondary Research", "Desk research and analyst market recall combined with live web search build the initial universe of candidate companies active in this market."),
        ("Screening &amp; Verification", "Each candidate checked against this market's inclusion criteria and correct commercial role; off-market, reseller, and media names removed."),
        ("Primary Research", "Each verified company's own website is reviewed directly for firsthand company information on product portfolio, scale, and positioning."),
        ("Data Triangulation", "Website evidence cross-checked against search-derived signals so no score rests on a single source."),
        ("Quantitative Scoring", f"Structured 1&ndash;10 scoring across weighted features rolls up into the {_esc(x_name)} (X) and {_esc(y_name)} (Y) axis scores."),
        ("Normalization &amp; Validation", f"Scores rescaled across this market's full population ({floor}&ndash;{ceiling}) and quadrant boundaries validated against the median distribution."),
    ]
    flow_cards = []
    for i, (title, text) in enumerate(flow, 1):
        flow_cards.append(
            f'<div class="cq-flow-step"><div class="cq-flow-badge">{i}</div>'
            f'<div class="cq-flow-title">{title}</div><div class="cq-flow-text">{text}</div></div>'
        )
        if i < len(flow):
            flow_cards.append('<div class="cq-flow-arrow">&rarr;</div>')
    flow_html = f'<div class="cq-flow">{"".join(flow_cards)}</div>'

    footnote = (
        f'<p class="cq-method-footnote">Scoring inputs: {_esc(x_name)} (X) is weighted across '
        f"{len(x_feats)} features ({_esc(', '.join(x_feats))}); {_esc(y_name)} (Y) across "
        f"{len(y_feats)} features ({_esc(', '.join(y_feats))}). Each feature is scored on 3 "
        f"structured questions, rolled into an axis score, then normalized within {_esc(market)}'s "
        f"own {n_brands}-company population to a {floor}&ndash;{ceiling} range &mdash; preserving "
        "relative ranking without any company reading as disproportionately weak in isolation."
        "</p>"
    )

    return f"""
<div class="panel">
  <h2>Research Methodology</h2>
  <p style="margin:0 0 1.25rem 0;color:#64748b;font-size:.92rem;line-height:1.5">
    This quadrant was independently compiled using a structured, evidence-based research methodology
    &mdash; not a survey or vendor self-submission. The flow below shows how secondary and primary
    research combine into each company's final score.
  </p>
  {flow_html}
  {footnote}
</div>
"""


def _player_type_label(payload: dict[str, Any], *, plural: bool = True) -> str:
    """What this market's companies actually ARE -- "manufacturers" was
    hardcoded regardless of market, so a software market (Solution Provider)
    or a consumer brand market (Brand/Marketer) still read "115
    manufacturers scored on...". Derived from the most common
    commercial_role across the companies, since that is set once per market
    by the same relevance pass that decided who qualifies.
    """
    roles = [
        str(b.get("commercial_role") or b.get("company_function") or "").strip()
        for b in (payload.get("brands") or [])
    ]
    roles = [r for r in roles if r]
    if not roles:
        return "companies" if plural else "company"
    from collections import Counter

    label = Counter(roles).most_common(1)[0][0]
    if not plural:
        return label
    # "Solution Provider" -> "Solution Providers"; "Brand / Marketer" is
    # left as-is rather than guessing which half of the slash to pluralise.
    if "/" in label:
        return label
    return label if label.endswith("s") else f"{label}s"


def render_quadrant_html(payload: dict[str, Any]) -> str:
    """Return a full HTML document for the quadrant payload."""
    market = str(payload.get("market") or "Market")
    geo = str(payload.get("geography") or "global")
    n = len(payload.get("brands") or [])
    player_label = _player_type_label(payload)
    x_name, y_name = _axis_labels(payload)
    top20_table, others_table = _top20_and_others(payload, x_name, y_name)
    # Takeaways cover the SAME charted companies as the Top 20 table, built
    # from one split so the two sections can never list different firms.
    _x_params, _y_params = _axis_parameters(payload)
    _charted, _ = split_top20(all_scored_companies(payload))
    _charted_views = [build_view_model(c, _x_params, _y_params) for c in _charted]
    takeaways_table = (
        _takeaways_grid(
            _charted_views, _charted, _x_params, "x",
            title="Table A — X-Axis Parameters",
            note=f"key takeaway per {_esc(x_name)} parameter for the "
                 f"{len(_charted)} companies on the chart",
        )
        + _takeaways_grid(
            _charted_views, _charted, _y_params, "y",
            title="Table B — Y-Axis Parameters",
            note=f"key takeaway per {_esc(y_name)} parameter for the "
                 f"{len(_charted)} companies on the chart",
        )
    )
    body = (
        f'<div class="hero"><h1>Coherent Quadrant</h1>'
        f"<p>{_esc(market)} · {_esc(geo)} · {n} {_esc(player_label)} scored on "
        f"{_esc(x_name)} (X) and {_esc(y_name)} (Y)</p></div>"
        f'<div class="meta">'
        f'<span class="pill">Market: {_esc(market)}</span>'
        f'<span class="pill">Geography: {_esc(geo)}</span>'
        f'<span class="pill">{_esc(player_label.capitalize())}: {n}</span>'
        + (
            f'<span class="pill">{_esc(payload["industry_category"])}</span>'
            if str(payload.get("industry_category") or "").strip() else ""
        )
        + f'<span class="pill">X: {_esc(x_name)}</span>'
        f'<span class="pill">Y: {_esc(y_name)}</span>'
        f"</div>"
        # Scorecard first (requirement 4), then Top 20 table immediately
        # above the graph it shares a dataset with, then the remainder.
        # Market Classification and the scoring parameters come FIRST: they
        # define the axes and the 10 parameters, so a reader meets them
        # before the scorecard that is built from them.
        + _market_classification_panel(payload)
        + _parameters_panel(payload, x_name, y_name)
        # The Company Parameter Scorecard is gone. Its expandable score discs
        # now live in the Top 20 table, so the breakdown is where a reader is
        # already looking. Per-parameter scores for every company remain in
        # chatgpt_xy_scores_batch_all.json — the HTML shows the charted 20.
        + _chart(payload)
        # Definitions directly under the chart they explain, so a reader meets
        # "Innovation-Driven Trailblazers" while that corner is still on
        # screen — then the companies plotted there, then everyone else.
        + _explain(x_name, y_name)
        + top20_table
        + takeaways_table
        + others_table
        # Company Details is gone: Top 20 + Other Noticeable Player already
        # list every company with the same columns, so it was a third copy of
        # the same rows. `_companies` is kept for the Streamlit view, which
        # still renders it.
        + _parameter_definitions_panel(payload, x_name, y_name)
        + _methodology_panel(payload, x_name, y_name)
        + '<p class="footer">Generated by Coherent Quadrant · open this file after a terminal run</p>'
    )
    return (
        "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\"/>"
        f"<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"/>"
        f"<title>Coherent Quadrant — {_esc(market)}</title>"
        f"<style>{_CSS}</style></head><body><div class=\"page\">{body}</div></body></html>"
    )


def write_quadrant_html_report(
    payload: dict[str, Any],
    path: str | Path,
    *,
    open_browser: bool = False,
) -> str:
    """Write HTML report to ``path``; optionally open in the default browser."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_quadrant_html(payload), encoding="utf-8")
    if open_browser:
        open_quadrant_report(out)
    return str(out.resolve())


def open_quadrant_report(path: str | Path) -> None:
    """Open a local HTML report in the default browser."""
    p = Path(path).resolve()
    webbrowser.open(p.as_uri())


def write_report_from_json(
    json_path: str | Path,
    *,
    open_browser: bool = True,
    html_path: str | Path | None = None,
) -> str:
    """Load a quadrant JSON file and write/open the HTML report."""
    jp = Path(json_path)
    payload = json.loads(jp.read_text(encoding="utf-8"))
    hp = Path(html_path) if html_path else jp.with_name(jp.name.replace("_quadrant.json", "_report.html"))
    if hp == jp:
        hp = jp.with_suffix(".html")
    return write_quadrant_html_report(payload, hp, open_browser=open_browser)
