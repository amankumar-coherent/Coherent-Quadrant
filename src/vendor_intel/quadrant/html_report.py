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

from vendor_intel.quadrant.quadrant_language import build_quadrant_explain

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
:root { --ink:#0f172a; --muted:#64748b; --line:#e2e8f0; --navy:#002857; }
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
.footer { color: var(--muted); font-size: 0.8rem; margin-top: 1.5rem; }
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


def _axis_labels(payload: dict[str, Any]) -> tuple[str, str]:
    labels = (payload.get("criteria") or {}).get("axis_labels") or {}
    x_name = str(labels.get("x") or "Solution Capability")
    y_name = str(labels.get("y") or "Business Strategy")
    return x_name, y_name


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
        mix_bits.append(f"<strong>{_esc(q)}</strong>: {_esc(countries)}")
    mix_html = (
        f'<div class="cq-country-mix" style="margin-top:.75rem;font-size:.82rem;color:#475569;line-height:1.45">'
        f'<div style="font-weight:600;margin-bottom:.25rem">Countries on chart (by quadrant)</div>'
        + " · ".join(mix_bits)
        + "</div>"
        if mix_bits
        else ""
    )
    x_name, y_name = _axis_labels(payload)
    x_label = f"{x_name.upper()} ( X AXIS ) →"
    y_label = f"{y_name.upper()} ( Y AXIS ) →"
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
      <div class="cq-quad-label cq-bl">Emerging Players</div>
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
    for title, sub, body in build_quadrant_explain(x_name, y_name):
        color = _EXPLAIN_CARD_COLOR[title]
        cards.append(
            f'<div class="cq-explain-card" style="background:{color}">'
            f"<h4>{_esc(title)}</h4>"
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
          <th>{_esc(x_hdr)}</th><th>{_esc(y_hdr)}</th><th>OVERALL</th>
          <th>FOUND IN</th>
        </tr>
      </thead>
      <tbody>{"".join(rows) or '<tr><td colspan="8">No brands</td></tr>'}</tbody>
    </table>
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


def render_quadrant_html(payload: dict[str, Any]) -> str:
    """Return a full HTML document for the quadrant payload."""
    market = str(payload.get("market") or "Market")
    geo = str(payload.get("geography") or "global")
    n = len(payload.get("brands") or [])
    x_name, y_name = _axis_labels(payload)

    body = (
        f'<div class="hero"><h1>Coherent Quadrant</h1>'
        f"<p>{_esc(market)} · {_esc(geo)} · {n} brands scored on "
        f"{_esc(x_name)} (X) and {_esc(y_name)} (Y)</p></div>"
        f'<div class="meta">'
        f'<span class="pill">Market: {_esc(market)}</span>'
        f'<span class="pill">Geography: {_esc(geo)}</span>'
        f'<span class="pill">Brands: {n}</span>'
        f'<span class="pill">{_esc(payload.get("industry_category") or "")}</span>'
        f'<span class="pill">X: {_esc(x_name)}</span>'
        f'<span class="pill">Y: {_esc(y_name)}</span>'
        f"</div>"
        + _parameters_panel(payload, x_name, y_name)
        + _chart(payload)
        + _explain(x_name, y_name)
        + _companies(payload, x_name=x_name, y_name=y_name)
        + _parameter_definitions_panel(payload, x_name, y_name)
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
