"""Custom CSS for the Vendor Intelligence Streamlit app."""

CUSTOM_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,400;0,9..40,500;0,9..40,600;0,9..40,700;1,9..40,400&family=JetBrains+Mono:wght@400;500&display=swap');

html, body, [class*="css"] {
    font-family: 'DM Sans', system-ui, sans-serif;
}

.hero {
    background: linear-gradient(135deg, #0f172a 0%, #1e3a5f 45%, #0d9488 100%);
    border-radius: 16px;
    padding: 2rem 2.25rem;
    margin-bottom: 1.5rem;
    color: #f8fafc;
    box-shadow: 0 20px 40px rgba(15, 23, 42, 0.25);
}
.hero h1 {
    font-size: 2rem;
    font-weight: 700;
    margin: 0 0 0.5rem 0;
    letter-spacing: -0.02em;
}
.hero p {
    margin: 0;
    opacity: 0.9;
    font-size: 1.05rem;
    line-height: 1.5;
}
.metric-card {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
    padding: 1.1rem 1.25rem;
    box-shadow: 0 4px 12px rgba(15, 23, 42, 0.06);
}
.metric-card .label {
    font-size: 0.78rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: #64748b;
    font-weight: 600;
}
.metric-card .value {
    font-size: 1.75rem;
    font-weight: 700;
    color: #0f172a;
    margin-top: 0.25rem;
}
.phase-pill {
    display: inline-block;
    background: #f0fdfa;
    color: #0f766e;
    border: 1px solid #99f6e4;
    border-radius: 999px;
    padding: 0.25rem 0.75rem;
    font-size: 0.8rem;
    font-weight: 600;
    margin-right: 0.35rem;
    margin-bottom: 0.35rem;
}
.section-head {
    font-size: 1.15rem;
    font-weight: 700;
    color: #0f172a;
    background: linear-gradient(90deg, #f0fdfa 0%, #ffffff 100%);
    border-left: 4px solid #0d9488;
    border-radius: 0 8px 8px 0;
    padding: 0.55rem 0.9rem;
    margin: 1.4rem 0 0.5rem 0;
}
.section-head .count {
    color: #0d9488;
    font-weight: 600;
    font-size: 0.95rem;
}
.status-ok { color: #059669; font-weight: 600; }
.status-warn { color: #d97706; font-weight: 600; }
.status-fail { color: #dc2626; font-weight: 600; }
.log-box {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.78rem;
    background: #0f172a;
    color: #e2e8f0;
    border-radius: 10px;
    padding: 1rem;
    max-height: 420px;
    overflow-y: auto;
    white-space: pre-wrap;
    line-height: 1.45;
}
.sidebar-brand {
    font-size: 1.1rem;
    font-weight: 700;
    color: #0f172a;
    padding: 0.5rem 0 1rem 0;
    border-bottom: 2px solid #0d9488;
    margin-bottom: 1rem;
}
.result-card {
    border-left: 4px solid #0d9488;
    background: #f8fafc;
    border-radius: 0 10px 10px 0;
    padding: 0.85rem 1rem;
    margin-bottom: 0.5rem;
}
div[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #f8fafc 0%, #f1f5f9 100%);
}
.stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #0d9488, #0f766e);
    border: none;
    font-weight: 600;
}
.stButton > button[kind="primary"]:hover {
    background: linear-gradient(135deg, #14b8a6, #0d9488);
    border: none;
}
.format-hint {
    display: block;
    margin: -0.35rem 0 0.85rem 0;
    padding: 0.45rem 0.75rem;
    background: #f0fdfa;
    border: 1px dashed #99f6e4;
    border-radius: 8px;
    color: #0f766e;
    font-size: 0.82rem;
    line-height: 1.4;
}
.format-hint strong {
    color: #0f766e;
}
.notice-banner {
    background: #fffbeb;
    border: 1px solid #fcd34d;
    border-left: 4px solid #f59e0b;
    border-radius: 10px;
    padding: 0.85rem 1.1rem;
    margin: 0 0 1.25rem 0;
    color: #78350f;
    font-size: 0.95rem;
    line-height: 1.45;
}
.notice-banner strong {
    color: #92400e;
}
.status-steps {
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
    padding: 1rem 1.25rem;
    margin: 0.75rem 0 1rem 0;
}
.status-step {
    display: flex;
    align-items: flex-start;
    gap: 0.65rem;
    padding: 0.4rem 0;
    font-size: 0.98rem;
    color: #64748b;
}
.status-step.active {
    color: #0f172a;
    font-weight: 600;
}
.status-step.done {
    color: #0f766e;
}
.status-step .icon {
    width: 1.4rem;
    text-align: center;
    flex-shrink: 0;
}
.status-current {
    margin-top: 0.65rem;
    padding: 0.65rem 0.85rem;
    background: #f0fdfa;
    border: 1px solid #99f6e4;
    border-radius: 8px;
    color: #0f766e;
    font-weight: 600;
}

/* —— Coherent Quadrant chart + table —— */
.cq-wrap { margin: 1rem 0 1.5rem 0; }
.cq-chart-title {
    font-size: 1.15rem;
    font-weight: 700;
    color: #0f172a;
    margin-bottom: 0.75rem;
}
.cq-chart-frame {
    display: flex;
    align-items: stretch;
    gap: 0.5rem;
}
.cq-y-label {
    writing-mode: vertical-rl;
    transform: rotate(180deg);
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.06em;
    color: #334155;
    text-align: center;
    padding: 0.5rem 0;
}
.cq-x-label {
    text-align: center;
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.06em;
    color: #334155;
    margin-top: 0.45rem;
}
.cq-plot {
    position: relative;
    flex: 1;
    min-height: 480px;
    height: 520px;
    background:
        repeating-linear-gradient(
            -45deg,
            #0b1f3a,
            #0b1f3a 8px,
            #0d2748 8px,
            #0d2748 16px
        );
    border: 2px solid #93c5fd;
    border-radius: 4px;
    overflow: hidden;
}
.cq-cross-h, .cq-cross-v {
    position: absolute;
    background: rgba(255,255,255,0.35);
    z-index: 1;
}
.cq-cross-h { left: 0; right: 0; top: 50%; height: 1px; }
.cq-cross-v { top: 0; bottom: 0; left: 50%; width: 1px; }
.cq-quad-label {
    position: absolute;
    z-index: 2;
    color: rgba(255,255,255,0.85);
    font-size: 0.78rem;
    font-weight: 600;
    letter-spacing: 0.02em;
}
.cq-tl { top: 10px; left: 12px; }
.cq-tr { top: 10px; right: 12px; }
.cq-bl { bottom: 10px; left: 12px; }
.cq-br { bottom: 10px; right: 12px; }
.cq-axis-y-max, .cq-axis-y-min, .cq-axis-x-min, .cq-axis-x-max {
    position: absolute;
    color: rgba(255,255,255,0.55);
    font-size: 0.7rem;
    z-index: 2;
}
.cq-axis-y-max { top: 8px; left: 6px; }
.cq-axis-y-min { bottom: 8px; left: 6px; }
.cq-axis-x-min { bottom: 4px; left: 28px; }
.cq-axis-x-max { bottom: 4px; right: 8px; }
.cq-dot {
    position: absolute;
    transform: translate(-50%, -50%);
    z-index: 3;
    display: flex;
    align-items: center;
    gap: 6px;
    white-space: nowrap;
}
.cq-dot-mark {
    width: 12px;
    height: 12px;
    border-radius: 50%;
    background: var(--dot, #7EB6FF);
    border: 2px solid #fff;
    flex-shrink: 0;
}
.cq-dot-label {
    color: #fff;
    font-size: 0.72rem;
    font-weight: 600;
    text-shadow: 0 1px 2px rgba(0,0,0,0.65);
}
.cq-explain { margin: 1.75rem 0; }
.cq-explain h3 {
    font-size: 1.15rem;
    font-weight: 700;
    color: #0f172a;
    margin: 0 0 1rem 0;
}
.cq-explain-grid {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 0.85rem;
}
@media (max-width: 900px) {
    .cq-explain-grid { grid-template-columns: 1fr; }
    .cq-plot { min-height: 360px; height: 380px; }
}
.cq-explain-card {
    border-radius: 10px;
    padding: 1rem 1.1rem;
    color: #fff;
    min-height: 140px;
}
.cq-explain-card h4 {
    margin: 0 0 0.35rem 0;
    font-size: 1rem;
    letter-spacing: 0.04em;
}
.cq-explain-sub {
    font-size: 0.78rem;
    opacity: 0.9;
    margin-bottom: 0.55rem;
    font-weight: 600;
}
.cq-explain-card p {
    margin: 0;
    font-size: 0.88rem;
    line-height: 1.45;
    opacity: 0.95;
}
.cq-card-leaders { background: #002857; }
.cq-card-challengers { background: #1d4ed8; }
.cq-card-trailblazers { background: #0f766e; }
.cq-card-emerging { background: #3b82f6; }
.cq-table-wrap { margin: 1.5rem 0 2rem 0; }
.cq-table-wrap h3 {
    font-size: 1.15rem;
    font-weight: 700;
    color: #0f172a;
    margin: 0 0 0.75rem 0;
}
.cq-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.88rem;
}
.cq-table thead th {
    background: #002857;
    color: #fff;
    text-align: left;
    padding: 0.65rem 0.75rem;
    font-weight: 600;
    letter-spacing: 0.03em;
    font-size: 0.75rem;
}
.cq-table td {
    padding: 0.65rem 0.75rem;
    border-bottom: 1px solid #e2e8f0;
    color: #0f172a;
    vertical-align: middle;
}
.cq-row-alt td { background: #f1f5f9; }
.cq-tier {
    display: inline-block;
    padding: 0.2rem 0.55rem;
    border-radius: 999px;
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.04em;
    color: #fff;
}
.cq-tier-1 { background: #002857; }
.cq-tier-2 { background: #2563eb; }
.cq-tier-3 { background: #93c5fd; color: #0f172a; }
.cq-score {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 2rem;
    height: 2rem;
    border-radius: 50%;
    font-weight: 700;
    font-size: 0.8rem;
    color: #fff;
}
.cq-score-hi { background: #16a34a; }
.cq-score-mid { background: #d97706; }
.cq-score-lo { background: #dc2626; }
.cq-scorecard-wrap { margin-top: 1.75rem; }
.cq-score-legend {
    font-size: 0.8rem;
    color: #475569;
    margin: 0 0 0.75rem 0;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.35rem 0.5rem;
}
.cq-table-scroll { overflow-x: auto; }
.cq-rate-dots {
    display: inline-flex;
    gap: 3px;
    align-items: center;
}
.cq-rate-dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    display: inline-block;
}
.cq-dot-on { background: #2563eb; }
.cq-dot-off { background: #cbd5e1; }
.cq-scorecard th { white-space: nowrap; font-size: 0.68rem; }
.cq-scorecard td { text-align: center; }
.cq-scorecard td:first-child { text-align: left; font-weight: 600; }
</style>
"""
