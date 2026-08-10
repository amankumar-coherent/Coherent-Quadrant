#!/usr/bin/env python3
"""
Vendor Intelligence — Streamlit UI (single clean flow)

Run:
  .venv\\Scripts\\python.exe -m streamlit run app.py
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

import pandas as pd
import streamlit as st

logging.getLogger("streamlit").setLevel(logging.ERROR)

from ui.bootstrap import env_warnings, init_env, load_settings, output_dir
from ui.services import JobRunner, list_result_csvs, pipeline_is_busy
from ui.styles import CUSTOM_CSS
from ui.auth_gate import require_login

st.set_page_config(
    page_title="Vendor Intelligence",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="collapsed",
)

init_env()

st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# --- Auth gate (email OTP + 24h session) ---
_auth_user = require_login()
if not _auth_user:
    st.stop()

if "active_job" not in st.session_state:
    st.session_state.active_job = {"running": False}

JOB_RUNNER = JobRunner("active_job")

DEFAULT_PROFILE = "quality"
DEFAULT_CAP = "broad"
_WIZARD_STEPS = ["Market & Geography", "Market Structure", "Review & Run"]
GEO_HINT = "global · United States · Europe · North America · Latin America · APAC · MENA · India · Germany"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def format_hint(text: str) -> None:
    st.markdown(
        f'<div class="format-hint"><strong>Recommended format:</strong> {text}</div>',
        unsafe_allow_html=True,
    )


def render_hero(title: str, subtitle: str) -> None:
    st.markdown(
        f'<div class="hero"><h1>{title}</h1><p>{subtitle}</p></div>',
        unsafe_allow_html=True,
    )


def metric_card(label: str, value: str) -> None:
    st.markdown(
        f'<div class="metric-card"><div class="label">{label}</div>'
        f'<div class="value">{value}</div></div>',
        unsafe_allow_html=True,
    )


def geography_input(label: str = "Geography", *, key: str | None = None) -> str:
    if key and key not in st.session_state:
        st.session_state[key] = "global"
    kwargs: dict = {
        "label": label,
        "placeholder": "e.g. Global, United States, Europe",
    }
    if key:
        kwargs["key"] = key
    raw = st.text_input(**kwargs)
    format_hint(
        f'Country or region name, or type <code>global</code> for worldwide. Examples: {GEO_HINT}'
    )
    return (raw or "").strip() or "global"


def _parse_sectioned_csv(path: Path) -> tuple[list[tuple[str, list[dict]]], list[str]]:
    import csv

    rows = list(csv.reader(path.open(encoding="utf-8")))
    if not rows:
        return [], []
    header = rows[0]
    sections: list[tuple[str, list[dict]]] = []
    current: list[dict] | None = None
    for r in rows[1:]:
        if not r or not any(str(c).strip() for c in r):
            continue
        first = str(r[0]).strip()
        if first.startswith("==="):
            name = first.strip("= ").rsplit(" (", 1)[0].strip()
            current = []
            sections.append((name, current))
            continue
        if current is None:
            current = []
            sections.append(("Companies", current))
        current.append(dict(zip(header, r)))
    return sections, header


def _download_exports(base: Path, *, key_prefix: str = "dl") -> None:
    xlsx = base.with_suffix(".xlsx")
    docx = base.with_suffix(".docx")
    csv_path = base.with_suffix(".csv") if base.suffix.lower() != ".csv" else base

    d1, d2 = st.columns(2)
    with d1:
        if xlsx.exists():
            st.download_button(
                "⬇ Download Excel",
                xlsx.read_bytes(),
                file_name=xlsx.name,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                width="stretch",
                key=f"{key_prefix}_xlsx",
            )
        elif csv_path.exists():
            st.download_button(
                "⬇ Download Excel (CSV)",
                csv_path.read_bytes(),
                file_name=csv_path.name,
                mime="text/csv",
                width="stretch",
                key=f"{key_prefix}_csv",
            )
    with d2:
        if docx.exists():
            st.download_button(
                "⬇ Download Word",
                docx.read_bytes(),
                file_name=docx.name,
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                width="stretch",
                key=f"{key_prefix}_docx",
            )


def _render_presentation(path: Path, *, key_prefix: str = "pres") -> None:
    sections, _ = _parse_sectioned_csv(path)
    if not sections:
        st.error("Could not read this result file.")
        return

    company_sections = [(n, rows) for n, rows in sections if "not verified" not in n.lower()]
    total = sum(len(rows) for _, rows in company_sections)
    market = (
        (company_sections[0][1][0].get("Industry") if company_sections and company_sections[0][1] else "")
        or path.stem.replace("_", " ").title()
    )

    c1, c2, c3 = st.columns(3)
    with c1:
        metric_card("Market", market)
    with c2:
        metric_card("Companies", str(total))
    with c3:
        metric_card("Segments", str(len(company_sections)))

    _download_exports(path, key_prefix=key_prefix)

    search = st.text_input(
        "Search company",
        "",
        placeholder="Filter by company name…",
        key=f"{key_prefix}_search",
    )
    format_hint("Optional — type part of a company or brand name to filter the tables below.")

    PRES_COLS = ["Company", "Brand", "Functionality", "Summary", "Website"]

    def _section_df(rows: list[dict]) -> pd.DataFrame:
        df = pd.DataFrame(rows)
        if search and not df.empty:
            mask = pd.Series(False, index=df.index)
            for col in ("Company", "Brand", "Functionality", "Summary"):
                if col in df.columns:
                    mask |= df[col].astype(str).str.contains(search, case=False, na=False)
            df = df[mask]
        return df

    for name, rows in sections:
        df = _section_df(rows)
        if df.empty:
            continue
        is_nv = "not verified" in name.lower()
        st.markdown(
            f'<div class="section-head">{name} <span class="count">({len(df)})</span></div>',
            unsafe_allow_html=True,
        )
        if is_nv:
            cols = [c for c in ("Company", "Summary", "Website") if c in df.columns]
            show = df[cols].rename(columns={"Summary": "Why it could not be confirmed"})
        else:
            cols = [c for c in PRES_COLS if c in df.columns]
            show = df[cols] if cols else df
        st.dataframe(
            show,
            width="stretch",
            hide_index=True,
            column_config={
                "Website": st.column_config.LinkColumn(
                    "Website", display_text=r"https?://(?:www\.)?([^/]+)"
                )
            },
        )


def _notice_time_optimization() -> None:
    st.markdown(
        '<div class="notice-banner">'
        "<strong>Time optimization is in progress.</strong> "
        "We’re actively working on making landscape runs faster. "
        "A full market can still take a while today — you can stop a run anytime with "
        "<strong>Stop run</strong>."
        "</div>",
        unsafe_allow_html=True,
    )


# Typical broad run length used only to pace the bar (not a hard cutoff).
_EXPECTED_RUN_SECONDS = 28 * 60  # ~28 minutes


def _pipeline_phase(log: str) -> int:
    """Detect completed/started phase from official pipeline markers only (no false jumps)."""
    low = (log or "").lower()
    phase = 0
    # Match the exact stage lines printed by orchestrator — avoid words like
    # "discovery focused" during Phase 1 that used to jump the bar past 40%.
    if "[pipeline] phase 1" in low or "=== pipeline start ===" in low:
        phase = max(phase, 1)
    if "[pipeline] phase 2" in low:
        phase = max(phase, 2)
    if "[pipeline] phase 3" in low:
        phase = max(phase, 3)
    if "[pipeline] phase 4" in low or "[pipeline] classif" in low:
        phase = max(phase, 4)
    if "[pipeline] csv saved" in low or "[pipeline] xlsx saved" in low or "[pipeline] docx saved" in low:
        phase = max(phase, 5)
    if "[pipeline] total time" in low or "\ndone:" in low:
        phase = max(phase, 5)
    return phase


def _progress_pct(log: str, elapsed: int) -> float:
    """
    Steady progress for a long run:
    - Mostly driven by elapsed / expected duration (smooth, no early leap)
    - Phase markers only nudge within band, never skip to 50%+ in seconds
    """
    # Pure time curve: ~3% after 1 min, ~50% at ~14 min, ~90% near expected end
    time_pct = 1.0 - (2.71828 ** (-elapsed / (_EXPECTED_RUN_SECONDS * 0.85)))
    time_pct = max(0.02, min(time_pct, 0.92))

    phase = _pipeline_phase(log)
    # Soft floors once a real phase starts (small — keeps bar honest early)
    floors = {0: 0.02, 1: 0.04, 2: 0.12, 3: 0.45, 4: 0.68, 5: 0.90}
    # Hard ceilings until later phases — Phase 1/2 can't show as "halfway done"
    ceilings = {0: 0.06, 1: 0.10, 2: 0.48, 3: 0.70, 4: 0.88, 5: 0.96}

    floor = floors.get(phase, 0.02)
    ceiling = ceilings.get(phase, 0.96)
    pct = max(floor, min(time_pct, ceiling))
    return min(pct, 0.96)


def _phase_label(log: str) -> str:
    return {
        0: "Starting…",
        1: "Planning the market…",
        2: "Finding companies…",
        3: "Enriching profiles…",
        4: "Classifying companies…",
        5: "Saving Excel & Word…",
    }.get(_pipeline_phase(log), "Working…")


@st.fragment(run_every=2)
def _live_job_status() -> None:
    job = st.session_state.get("active_job") or {}
    if not (
        job.get("running")
        or job.get("result")
        or job.get("error")
        or job.get("cancelled")
    ):
        return

    # If stop was pressed but the worker is stuck in network I/O, finalize UI after a short wait
    # so the user is not stuck on "Stopping…".
    if (
        job.get("running")
        and job.get("cancel_requested")
        and job.get("cancel_requested_at")
    ):
        waited = time.time() - float(job["cancel_requested_at"])
        if waited >= 8:
            JOB_RUNNER.force_finish_cancelled(st.session_state)
            st.rerun()

    st.markdown("---")
    if job.get("running"):
        st.markdown("### Building your landscape")
        elapsed = int(time.time() - job.get("started_at", time.time()))
        log = job.get("log") or ""
        pct = _progress_pct(log, elapsed)
        label = _phase_label(log)
        left_m = max(0, (_EXPECTED_RUN_SECONDS - elapsed) // 60)
        st.progress(
            pct,
            text=f"{label}  ·  {elapsed // 60}m {elapsed % 60}s elapsed"
            + (f"  ·  ~{left_m}m typically remaining" if left_m > 0 and pct < 0.9 else ""),
        )
        st.caption(f"About {int(pct * 100)}% complete (estimate — time optimization in progress)")
        st.markdown(
            '<div class="notice-banner">'
            "<strong>Time optimization is in progress.</strong> "
            "This can take a while while we build a thorough company landscape. "
            "Your Excel & Word files will appear here when ready."
            "</div>",
            unsafe_allow_html=True,
        )
        if job.get("cancel_requested"):
            st.warning("Stopping the run…")
        elif st.button("⏹ Stop run", type="secondary", key="stop_pipeline_run", width="stretch"):
            JOB_RUNNER.request_stop(st.session_state)
            st.rerun()
    elif job.get("cancelled"):
        st.markdown("### Results")
        st.info("Run stopped. You can start a new market whenever you’re ready.")
    elif job.get("error"):
        st.markdown("### Results")
        st.error(
            "Something went wrong while building this landscape. "
            "Please try again, or contact your admin if it keeps failing."
        )
        st.caption("Technical detail (for support): " + str(job.get("error") or "")[:400])
    elif job.get("result"):
        st.markdown("### Results")
        result = job["result"]
        companies = len(result.get("relevant_companies") or [])
        m1, m2 = st.columns(2)
        m1.metric("Companies in landscape", companies)
        m2.metric("Classified", len(result.get("all_classified") or []))

        csv_path = result.get("_csv_path") or ""
        if csv_path and Path(csv_path).exists():
            st.success("Your landscape is ready — download Excel + Word below.")
            _render_presentation(Path(csv_path), key_prefix="live_pres")
        else:
            st.warning("Run finished but no result file was returned.")

    if not job.get("running") and (job.get("result") or job.get("error") or job.get("cancelled")):
        if st.button("Clear status & start another market", key="clear_job_status"):
            st.session_state.active_job = {
                "running": False,
                "cancelled": False,
                "cancel_requested": False,
            }
            st.session_state.wiz_step = 1
            st.session_state.wiz = {
                "market": "",
                "geography": "global",
                "profile": DEFAULT_PROFILE,
                "cap": DEFAULT_CAP,
            }
            for k in (
                "_wiz_spec",
                "_wiz_spec_for",
                "wiz_brief_text",
                "wiz_brief_edit_box",
                "wiz_sections",
                "wiz_brief_editing",
            ):
                st.session_state.pop(k, None)
            for i in range(16):
                st.session_state.pop(f"wiz_secname_{i}", None)
                st.session_state.pop(f"wiz_seccontent_{i}", None)
            st.rerun()


# ---------------------------------------------------------------------------
# Wizard
# ---------------------------------------------------------------------------
def _wizard_progress(step: int) -> None:
    pills = []
    for i, lbl in enumerate(_WIZARD_STEPS, 1):
        icon = "🔵" if i == step else ("✅" if i < step else "⚪")
        label = f"**Step {i} · {lbl}**" if i == step else f"Step {i} · {lbl}"
        pills.append(f"{icon} {label}")
    st.markdown(" &nbsp;&nbsp; ".join(pills))
    st.divider()


def _wiz_step1_market_geo() -> None:
    st.markdown("### Step 1 — Market & Geography")
    wiz = st.session_state.wiz
    col1, col2 = st.columns([2, 1])
    with col1:
        market = st.text_input(
            "Market",
            value=wiz.get("market", ""),
            placeholder='e.g. "Remote Elderly Health Monitoring Market"',
            key="wiz_market_input",
        )
        format_hint(
            'Plain market title — e.g. <code>Satcom Market</code>, '
            '<code>Waste Oil Market</code>, <code>Bio-based Ethylene Market</code>'
        )
    with col2:
        geo = geography_input("Geography", key="wiz_geo_input")

    if st.button("Next →", type="primary", width="stretch"):
        if not market.strip():
            st.error("Enter a market to continue.")
        else:
            wiz["market"] = market.strip()
            wiz["geography"] = geo
            wiz["profile"] = DEFAULT_PROFILE
            wiz["cap"] = DEFAULT_CAP
            st.session_state.wiz_step = 2
            st.rerun()


_BRIEF_PLACEHOLDER = (
    "FUNCTIONAL ENTITIES IN THE VALUE CHAIN:\n"
    "1. Upstream: … (Function / Core entities / Business model / Market sizing)\n"
    "2. Midstream: …\n"
    "3. Downstream: …\n\n"
    "WHICH ENTITIES TO INCLUDE IN MARKET SIZING: …"
)


def _wiz_back_to_step1() -> None:
    if st.button("← Back", key="wiz_back_1", width="stretch"):
        st.session_state.wiz_step = 1
        st.rerun()


def _wiz_continue_to_review(brief_text: str) -> None:
    st.session_state.wiz["brief"] = (brief_text or "").strip()
    st.session_state.wiz_step = 3
    st.rerun()


def _wiz_step2_brief() -> None:
    wiz = st.session_state.wiz
    st.markdown("### Step 2 — Market structure")
    st.caption(f"Market: **{wiz.get('market', '')}**  ·  {wiz.get('geography', 'global')}")
    st.markdown(
        "What are the different entities in the value chain based on functionality, and which "
        "should be considered for the **market-sizing** activity?"
    )
    st.session_state.setdefault("wiz_brief_text", wiz.get("brief", ""))
    st.session_state.setdefault("wiz_brief_editing", False)

    mode = st.radio(
        "How do you want to provide the market structure?",
        [
            "Write it myself (default)",
            "Generate with AI, then review",
            "Describe it in your own words",
        ],
        key="wiz_brief_mode",
    )
    format_hint(
        "Pick one path: fill section cards yourself, let AI draft a full brief to review, "
        "or paste a free-form overview."
    )

    if mode.startswith("Write"):
        st.session_state.setdefault("wiz_sections", None)
        if st.session_state["wiz_sections"] is None:
            with st.spinner("Drafting the value-chain sections for this market…"):
                from vendor_intel.funnel.brief_interpreter import generate_market_sections

                secs = generate_market_sections(
                    wiz.get("market", ""),
                    wiz.get("geography", "global"),
                    load_settings(DEFAULT_PROFILE),
                )
            st.session_state["wiz_sections"] = secs or [""]
        secs = st.session_state["wiz_sections"]

        st.caption("Edit section names and describe what to profile under each.")
        names: list[str] = []
        contents: list[str] = []
        for i in range(len(secs)):
            nm = st.text_input(f"Section {i + 1} name", value=secs[i], key=f"wiz_secname_{i}")
            format_hint(
                "Value-chain segment name — e.g. <code>Device-Agnostic Platform Providers</code>"
            )
            cont = st.text_area(
                f"What to profile under section {i + 1}",
                key=f"wiz_seccontent_{i}",
                height=110,
                label_visibility="collapsed",
                placeholder=(
                    "Function · core entities (example companies) · business model · "
                    "market-sizing note (include / exclude)…"
                ),
            )
            format_hint(
                "Short bullets: what this segment does, example companies, and "
                "<code>INCLUDE</code> / <code>EXCLUDE</code> for sizing."
            )
            names.append(nm)
            contents.append(cont)

        if st.button("➕ Add a section", key="wiz_sec_add"):
            st.session_state["wiz_sections"] = list(secs) + [""]
            st.rerun()
        if st.button("↻ Re-draft sections with AI", key="wiz_sec_redraft"):
            st.session_state["wiz_sections"] = None
            for i in range(len(secs)):
                st.session_state.pop(f"wiz_secname_{i}", None)
                st.session_state.pop(f"wiz_seccontent_{i}", None)
            st.rerun()

        c1, c2 = st.columns(2)
        with c1:
            _wiz_back_to_step1()
        if c2.button("Next →", type="primary", key="wiz2_next_write", width="stretch"):
            clean = [(n.strip(), c.strip()) for n, c in zip(names, contents) if n.strip()]
            if not clean:
                st.error("Add at least one section name.")
            else:
                lines: list[str] = []
                for n, c in clean:
                    lines.append(n)
                    if c:
                        lines.append(c)
                    lines.append("")
                wiz["brief"] = "\n".join(lines).strip()
                wiz["sections"] = [n for n, _ in clean]
                st.session_state.wiz_step = 3
                st.rerun()
        return

    if mode.startswith("Describe"):
        st.session_state.wiz.pop("sections", None)
        summary = st.text_area(
            "Market overview",
            height=320,
            key="wiz_brief_text",
            placeholder=(
                "e.g. This market covers … Participants range from … through … to …. "
                "For sizing, focus on … while … are counted separately."
            ),
        )
        format_hint(
            "1–3 short paragraphs covering scope, participant types, and sizing include/exclude rules."
        )
        c1, c2 = st.columns(2)
        with c1:
            _wiz_back_to_step1()
        if c2.button("Next →", type="primary", key="wiz2_next_desc", width="stretch"):
            if not (summary or "").strip():
                st.error("Write a short overview to continue.")
            else:
                _wiz_continue_to_review(summary)
        return

    st.session_state.wiz.pop("sections", None)

    if st.button("✨ Generate structure with AI", key="wiz_gen_brief"):
        with st.spinner("Drafting the value-chain structure with AI…"):
            from vendor_intel.funnel.brief_interpreter import generate_market_brief

            txt = generate_market_brief(
                wiz.get("market", ""),
                wiz.get("geography", "global"),
                load_settings(DEFAULT_PROFILE),
            )
        if txt:
            st.session_state["wiz_brief_text"] = txt
            st.session_state["wiz_brief_editing"] = False
            st.rerun()
        else:
            st.warning("Could not generate a draft. Switch to 'Write it myself'.")

    draft = st.session_state.get("wiz_brief_text", "")
    if not draft:
        st.info("Click **✨ Generate structure with AI** to draft the value chain.")
        _wiz_back_to_step1()
        return

    if st.session_state["wiz_brief_editing"]:
        st.session_state.setdefault("wiz_brief_edit_box", draft)
        edited = st.text_area(
            "Market structure brief",
            height=380,
            key="wiz_brief_edit_box",
            placeholder=_BRIEF_PLACEHOLDER,
        )
        format_hint(
            "Numbered functional entities with Function / Core entities / Business model / "
            "Include-exclude sizing notes."
        )
        c1, c2 = st.columns(2)
        with c1:
            _wiz_back_to_step1()
        if c2.button("Save & continue →", type="primary", key="wiz2_save", width="stretch"):
            _wiz_continue_to_review(edited)
    else:
        st.markdown("**AI-generated market structure — review it:**")
        st.text_area(
            "AI draft (read-only)",
            value=draft,
            height=340,
            disabled=True,
            label_visibility="collapsed",
        )
        format_hint("Review the draft, then Edit or Use as-is.")
        c1, c2, c3 = st.columns(3)
        with c1:
            _wiz_back_to_step1()
        if c2.button("✏️ Edit it", key="wiz2_edit", width="stretch"):
            st.session_state["wiz_brief_editing"] = True
            st.session_state["wiz_brief_edit_box"] = draft
            st.rerun()
        if c3.button("✅ Use as-is → continue", type="primary", key="wiz2_useasis", width="stretch"):
            _wiz_continue_to_review(draft)


def _wiz_step3_review_run() -> None:
    wiz = st.session_state.wiz
    job = st.session_state.active_job
    st.markdown("### Step 3 — Review & run")

    c1, c2 = st.columns(2)
    c1.metric("Market", wiz.get("market", "—"))
    c2.metric("Geography", wiz.get("geography", "global"))
    st.caption(
        "Results save as Excel + Word. Runs can take a while while we gather and classify companies — "
        "time optimization is in progress."
    )

    explicit = [s for s in (wiz.get("sections") or []) if str(s).strip()]
    brief = (wiz.get("brief") or "").strip()
    spec: dict | None = None
    if explicit:
        spec = {
            "market": wiz.get("market", ""),
            "geography": wiz.get("geography", "global"),
            "sections": explicit,
            "exclude": [],
            "definition": "",
        }
        st.markdown("**Sections to profile:**")
        for s in explicit:
            st.markdown(f"- {s}")
    elif brief:
        if st.session_state.get("_wiz_spec_for") != brief:
            with st.spinner("Interpreting your market structure…"):
                from vendor_intel.funnel.brief_interpreter import interpret_brief

                st.session_state["_wiz_spec"] = interpret_brief(
                    brief, load_settings(DEFAULT_PROFILE)
                )
                st.session_state["_wiz_spec_for"] = brief
        spec = st.session_state.get("_wiz_spec") or {}
        secs = spec.get("sections") or []
        st.markdown("**Sections to profile:**")
        if secs:
            for s in secs:
                st.markdown(f"- {s}")
        else:
            st.caption("No explicit sections detected — profiling the market generally.")
        defn = str(spec.get("definition") or "").strip()
        if defn:
            st.info(defn)
    else:
        st.caption("No structure brief — running as a plain market query.")

    st.divider()
    b1, b2 = st.columns(2)
    if b1.button("← Back", key="wiz3_back", width="stretch"):
        st.session_state.wiz_step = 2
        st.rerun()
    if b2.button("🚀 Start run", type="primary", key="wiz3_run", width="stretch"):
        if not wiz.get("market"):
            st.error("Market is missing — go back to Step 1.")
        elif job.get("running") or pipeline_is_busy():
            st.warning("A pipeline is already running — wait for it to finish.")
        else:
            if spec:
                scope = {
                    "market": wiz.get("market") or spec.get("market", ""),
                    "geography": wiz.get("geography", "global"),
                    "sections": spec.get("sections") or [],
                    "exclude": spec.get("exclude") or [],
                    "definition": spec.get("definition", "") or (brief if explicit else ""),
                }
                ok = JOB_RUNNER.start(
                    st.session_state,
                    job_type="pipeline",
                    query="",
                    country=scope["geography"],
                    profile=DEFAULT_PROFILE,
                    cap=DEFAULT_CAP,
                    scope=scope,
                )
            else:
                ok = JOB_RUNNER.start(
                    st.session_state,
                    job_type="pipeline",
                    query=wiz.get("market", ""),
                    country=wiz.get("geography", "global"),
                    profile=DEFAULT_PROFILE,
                    cap=DEFAULT_CAP,
                )
            if ok:
                st.rerun()
            else:
                st.warning("Could not start — another pipeline may be running.")


def _past_results_panel() -> None:
    csvs = list_result_csvs()
    if not csvs:
        return
    with st.expander("Saved landscapes", expanded=False):
        names = [p.name for p in csvs]
        selected_name = st.selectbox(
            "Open a previous result",
            names,
            format_func=lambda n: n.replace(".csv", "").replace("_", " ").title(),
            key="past_result_pick",
        )
        format_hint("Optional — reopen a finished run and download Excel / Word again.")
        _render_presentation(output_dir() / selected_name, key_prefix="past_pres")


# ---------------------------------------------------------------------------
# Single page (authenticated)
# ---------------------------------------------------------------------------
# CSS already injected above the auth gate.

render_hero(
    "Vendor Intelligence",
    "Enter a market, define its structure, and get a presentation-ready company landscape "
    "(Excel + Word).",
)
_notice_time_optimization()

for w in env_warnings():
    st.warning(w)

st.session_state.setdefault("wiz_step", 1)
st.session_state.setdefault(
    "wiz",
    {
        "market": "",
        "geography": "global",
        "profile": DEFAULT_PROFILE,
        "cap": DEFAULT_CAP,
    },
)
if not st.session_state.get("_wiz_v2"):
    old = int(st.session_state.get("wiz_step") or 1)
    if old == 3:
        st.session_state.wiz_step = 2
    elif old >= 4:
        st.session_state.wiz_step = 3
    st.session_state["_wiz_v2"] = True

step = max(1, min(3, int(st.session_state.wiz_step)))
st.session_state.wiz_step = step
st.session_state.wiz["profile"] = DEFAULT_PROFILE
st.session_state.wiz["cap"] = DEFAULT_CAP

_wizard_progress(step)
if step == 1:
    _wiz_step1_market_geo()
elif step == 2:
    _wiz_step2_brief()
else:
    _wiz_step3_review_run()

_live_job_status()
_past_results_panel()

st.caption(
    f"Outputs save to `{output_dir().name}/` · Time optimization in progress"
)
