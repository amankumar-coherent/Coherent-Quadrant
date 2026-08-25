"""Coherent Quadrant Streamlit view — chart + explanation cards + company table."""
from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

import streamlit as st

from vendor_intel.quadrant.quadrant_language import build_quadrant_explain

_QUAD_COLORS = {
    "Leaders": "#7CFC00",
    "Challengers": "#7EB6FF",
    "Trailblazers": "#C4B5FD",
    "Emerging Players": "#A7F3D0",
}

_EXPLAIN_CARD_CLASS = {
    "Leaders": "cq-card-leaders",
    "Challengers": "cq-card-challengers",
    "Trailblazers": "cq-card-trailblazers",
    "Emerging Players": "cq-card-emerging",
}

_RATING_DOTS = {
    "very-high": 5,
    "high": 4,
    "average": 3,
    "low": 2,
    "very-low": 1,
}


def quadrant_output_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "output" / "quadrant"


def list_quadrant_jsons() -> list[Path]:
    d = quadrant_output_dir()
    if not d.is_dir():
        return []
    return sorted(d.glob("*_quadrant.json"), key=lambda p: p.stat().st_mtime, reverse=True)


def load_quadrant_payload(source: str | Path | dict[str, Any] | None) -> dict[str, Any] | None:
    if source is None:
        return None
    if isinstance(source, dict):
        if source.get("error") and not source.get("brands"):
            return None
        return source
    path = Path(source)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _esc(s: Any) -> str:
    return html.escape(str(s or ""))


def _score_class(n: int) -> str:
    # X/Y/Overall score badges: always green
    return "cq-score-hi"


def _tier_class(tier: str) -> str:
    t = (tier or "").lower().replace(" ", "")
    if "1" in t:
        return "cq-tier-1"
    if "2" in t:
        return "cq-tier-2"
    return "cq-tier-3"


def _label(b: dict[str, Any]) -> str:
    """Plain brand name — strip any leftover ``(acquired by …)`` from older payloads."""
    import re

    raw = str(b.get("display_name") or b.get("brand") or "").strip()
    return re.sub(
        r"\s*\((?:acquired by|merged into|subsidiary of)\s+[^)]+\)\s*$",
        "",
        raw,
        flags=re.I,
    ).strip() or raw


def _company_col(b: dict[str, Any]) -> str:
    company = str(b.get("company") or "").strip()
    if company:
        return company
    owner = str(b.get("parent_owner") or "").strip()
    if not owner:
        return ""
    mode = str(b.get("company_display_mode") or "").strip().lower()
    if mode == "solution_provider":
        return owner
    return f"(acquired by {owner})"


def _founded_loc(b: dict[str, Any]) -> str:
    loc = str(b.get("founded_location") or "").strip()
    if loc:
        return loc
    founded = str(b.get("founded_in") or "").strip()
    import re

    if founded and not re.fullmatch(r"(19|20)\d{2}", founded):
        return founded
    return str(b.get("hq_location") or "").strip()


def _axis_labels(payload: dict[str, Any]) -> tuple[str, str]:
    labels = (payload.get("criteria") or {}).get("axis_labels") or {}
    return (
        str(labels.get("x") or "Solution Capability"),
        str(labels.get("y") or "Business Strategy"),
    )


def _chart_html(payload: dict[str, Any]) -> str:
    brands = list(payload.get("brands") or [])
    market = _esc(payload.get("market") or "Market")
    x_name, y_name = _axis_labels(payload)
    x_label = f"{x_name.upper()} ( X AXIS ) →"
    y_label = f"{y_name.upper()} ( Y AXIS ) →"
    dots: list[str] = []
    for b in brands:
        left = max(2, min(98, int(b.get("left_pct") or 50)))
        top = max(2, min(98, int(b.get("top_pct") or 50)))
        quad = str(b.get("quadrant") or "Leaders")
        color = _QUAD_COLORS.get(quad, "#7EB6FF")
        name = _esc(_label(b))
        dots.append(
            f'<div class="cq-dot" style="left:{left}%;top:{top}%;--dot:{color}" '
            f'title="{name}">'
            f'<span class="cq-dot-mark"></span>'
            f'<span class="cq-dot-label">{name}</span></div>'
        )
    dots_html = "\n".join(dots)
    return f"""
<div class="cq-wrap">
  <div class="cq-chart-title">Quadrant Positioning — {market}</div>
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
      {dots_html}
    </div>
  </div>
  <div class="cq-x-label">{_esc(x_label)}</div>
</div>
"""


def _explain_html(x_name: str, y_name: str) -> str:
    cards = []
    for title, sub, body in build_quadrant_explain(x_name, y_name):
        cls = _EXPLAIN_CARD_CLASS[title]
        cards.append(
            f'<div class="cq-explain-card {cls}">'
            f"<h4>{_esc(title)}</h4>"
            f'<div class="cq-explain-sub">{_esc(sub)}</div>'
            f"<p>{_esc(body)}</p></div>"
        )
    return (
        '<div class="cq-explain">'
        "<h3>Understanding the Coherent Quadrant — What Each Position Means</h3>"
        f'<div class="cq-explain-grid">{"".join(cards)}</div></div>'
    )


def _dots_html(rating: str) -> str:
    filled = _RATING_DOTS.get((rating or "").lower().strip(), 3)
    filled = max(1, min(5, int(filled)))
    parts = []
    for i in range(1, 6):
        cls = "cq-dot-on" if i <= filled else "cq-dot-off"
        parts.append(f'<span class="cq-rate-dot {cls}"></span>')
    return f'<span class="cq-rate-dots" title="{_esc(rating)}">{"".join(parts)}</span>'


def _scorecard_axis_html(
    payload: dict[str, Any],
    *,
    axis: str,
    title: str,
    which: str = "x",
) -> str:
    """Build market-specific X/Y scorecard table with 5-dot ratings."""
    criteria = payload.get("criteria") or {}
    axis_key = "x_axis" if which == "x" else "y_axis"
    features = list(criteria.get(axis_key) or [])
    brands = list(payload.get("brands") or [])
    scorecard = list(payload.get("scorecard") or [])

    # rating lookup: (brand_plain, criterion) -> rating
    by_key: dict[tuple[str, str], str] = {}
    for row in scorecard:
        row_axis = str(row.get("axis") or "")
        if row_axis and row_axis != axis:
            continue
        b = str(row.get("brand") or "").strip().lower()
        c = str(row.get("criterion") or "").strip().lower()
        by_key[(b, c)] = str(row.get("rating") or "average")

    if not features:
        # Infer feature order from scorecard rows for this axis
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

    head_cols = "".join(f"<th>{_esc(f)}</th>" for f in features)
    head_cols += "<th>OVERALL</th>"

    body_rows: list[str] = []
    for i, b in enumerate(brands):
        zebra = "cq-row-alt" if i % 2 else ""
        label = _label(b)
        brand_key = str(b.get("brand") or label).strip().lower()
        cells = [f"<td>{_esc(label)}</td>"]
        ratings_for_overall: list[int] = []
        for feat in features:
            rating = by_key.get((brand_key, feat.lower()), "")
            if not rating:
                # try display_name key
                rating = by_key.get((_label(b).lower(), feat.lower()), "average")
            ratings_for_overall.append(_RATING_DOTS.get(rating, 3))
            cells.append(f"<td>{_dots_html(rating or 'average')}</td>")
        # Overall column: average of feature dots → nearest rating label
        avg = sum(ratings_for_overall) / max(len(ratings_for_overall), 1)
        overall_dots = int(round(avg))
        overall_rating = {
            5: "very-high",
            4: "high",
            3: "average",
            2: "low",
            1: "very-low",
        }.get(max(1, min(5, overall_dots)), "average")
        # Prefer axis score from brand row when available
        if which == "x" and b.get("execution") is not None:
            # Map 0-100 roughly onto 1-5 for display consistency with screenshot Overall col
            ex = int(b.get("execution") or 0)
            overall_rating = (
                "very-high" if ex >= 85 else
                "high" if ex >= 70 else
                "average" if ex >= 50 else
                "low" if ex >= 35 else
                "very-low"
            )
        elif which == "y" and b.get("innovation") is not None:
            inn = int(b.get("innovation") or 0)
            overall_rating = (
                "very-high" if inn >= 85 else
                "high" if inn >= 70 else
                "average" if inn >= 50 else
                "low" if inn >= 35 else
                "very-low"
            )
        cells.append(f"<td>{_dots_html(overall_rating)}</td>")
        body_rows.append(f'<tr class="{zebra}">{"".join(cells)}</tr>')

    legend = (
        '<div class="cq-score-legend">'
        "<span>Rating:</span>"
        f"{_dots_html('very-high')} Very High &nbsp; "
        f"{_dots_html('high')} High &nbsp; "
        f"{_dots_html('average')} Average &nbsp; "
        f"{_dots_html('low')} Low &nbsp; "
        f"{_dots_html('very-low')} Very Low"
        "</div>"
    )

    return f"""
<div class="cq-table-wrap cq-scorecard-wrap">
  <h3>{_esc(title)}</h3>
  {legend}
  <div class="cq-table-scroll">
  <table class="cq-table cq-scorecard">
    <thead>
      <tr>
        <th>BRAND</th>
        {head_cols}
      </tr>
    </thead>
    <tbody>
      {"".join(body_rows)}
    </tbody>
  </table>
  </div>
</div>
"""


def _scorecards_html(payload: dict[str, Any]) -> str:
    x_name, y_name = _axis_labels(payload)
    x_html = _scorecard_axis_html(
        payload, axis=x_name, title=f"{x_name} Scorecard", which="x"
    )
    y_html = _scorecard_axis_html(
        payload, axis=y_name, title=f"{y_name} Scorecard", which="y"
    )
    if not x_html and not y_html:
        return ""
    return x_html + y_html


def _table_html(payload: dict[str, Any]) -> str:
    brands = list(payload.get("brands") or [])
    x_name, y_name = _axis_labels(payload)
    rows: list[str] = []
    for i, b in enumerate(brands):
        zebra = "cq-row-alt" if i % 2 else ""
        ex = int(b.get("execution") or 0)
        inn = int(b.get("innovation") or 0)
        overall = int(b.get("overall") or 0)
        rows.append(
            f'<tr class="{zebra}">'
            f"<td>{_esc(_label(b))}</td>"
            f"<td>{_esc(_company_col(b))}</td>"
            f"<td>{_esc(b.get('quadrant') or '')}</td>"
            f'<td><span class="cq-score {_score_class(ex)}">{ex}</span></td>'
            f'<td><span class="cq-score {_score_class(inn)}">{inn}</span></td>'
            f'<td><span class="cq-score {_score_class(overall)}">{overall}</span></td>'
            f"<td>{_esc(_founded_loc(b))}</td>"
            f"</tr>"
        )
    body = "\n".join(rows) or '<tr><td colspan="7">No brands scored.</td></tr>'
    return f"""
<div class="cq-table-wrap">
  <h3>Company Details</h3>
  <table class="cq-table">
    <thead>
      <tr>
        <th>BRAND</th>
        <th>COMPANY</th>
        <th>QUADRANT</th>
        <th>{_esc(x_name)} (X)</th>
        <th>{_esc(y_name)} (Y)</th>
        <th>OVERALL</th>
        <th>FOUNDED IN</th>
      </tr>
    </thead>
    <tbody>
      {body}
    </tbody>
  </table>
</div>
"""


def render_quadrant_payload(payload: dict[str, Any], *, key_prefix: str = "cq") -> None:
    """Render chart + cards + table for a coherent_quadrant payload."""
    if not payload or not payload.get("brands"):
        st.info("No Coherent Quadrant brands to show yet.")
        return

    market = payload.get("market") or "Market"
    geo = payload.get("geography") or ""
    n = len(payload.get("brands") or [])
    c1, c2, c3 = st.columns(3)
    c1.metric("Market", str(market)[:40])
    c2.metric("Geography", str(geo)[:30] or "global")
    c3.metric("Brands on chart", n)

    st.markdown(_chart_html(payload), unsafe_allow_html=True)
    st.markdown(_explain_html(*_axis_labels(payload)), unsafe_allow_html=True)
    st.markdown(_table_html(payload), unsafe_allow_html=True)

    csv_hint = payload.get("companies_csv_path") or ""
    out = payload.get("output_path") or ""
    if out and Path(out).is_file():
        st.download_button(
            "Download quadrant JSON",
            Path(out).read_bytes(),
            file_name=Path(out).name,
            mime="application/json",
            key=f"{key_prefix}_json_dl",
        )
    elif payload.get("brands"):
        st.download_button(
            "Download quadrant JSON",
            json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
            file_name=f"{str(market).lower().replace(' ', '-')}_quadrant.json",
            mime="application/json",
            key=f"{key_prefix}_json_inline",
        )
    if csv_hint and Path(csv_hint).is_file():
        st.download_button(
            "Download companies CSV",
            Path(csv_hint).read_bytes(),
            file_name=Path(csv_hint).name,
            mime="text/csv",
            key=f"{key_prefix}_csv_dl",
        )


def render_quadrant_browser() -> None:
    """Sidebar/expander: open any saved output/quadrant/*_quadrant.json."""
    files = list_quadrant_jsons()
    with st.expander("Coherent Quadrant — saved charts", expanded=bool(files)):
        if not files:
            st.caption(
                "No quadrant JSON yet. Run: "
                "`scripts/run_quadrant_market.py --industry \"Your Market\"`"
            )
            return
        names = [p.name for p in files]
        pick = st.selectbox(
            "Open a quadrant result",
            names,
            key="cq_past_pick",
        )
        path = quadrant_output_dir() / pick
        payload = load_quadrant_payload(path)
        if payload:
            # Attach path for download buttons
            payload = {**payload, "output_path": str(path)}
            csv_sib = path.with_name(path.name.replace("_quadrant.json", "_companies.csv"))
            if csv_sib.is_file():
                payload["companies_csv_path"] = str(csv_sib)
            render_quadrant_payload(payload, key_prefix="cq_past")
