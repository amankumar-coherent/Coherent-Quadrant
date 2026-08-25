#!/usr/bin/env python3
"""Generate PDF: Coherent Quadrant X/Y/Overall scoring method + worked example."""
from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch, mm
from reportlab.platypus import (
    KeepTogether,
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parents[1]
OUT = (
    ROOT
    / "output"
    / "chatgpt_expand"
    / "Coherent_Quadrant_XY_Overall_Scoring_Guide.pdf"
)

NAVY = colors.HexColor("#0B1F3A")
BLUE = colors.HexColor("#1D4ED8")
LIGHT = colors.HexColor("#F1F5F9")
LINE = colors.HexColor("#CBD5E1")
MUTED = colors.HexColor("#475569")
GREEN = colors.HexColor("#166534")


def _styles():
    base = getSampleStyleSheet()
    styles = {
        "title": ParagraphStyle(
            "title",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=20,
            textColor=NAVY,
            spaceAfter=6,
            alignment=TA_CENTER,
            leading=24,
        ),
        "subtitle": ParagraphStyle(
            "subtitle",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=11,
            textColor=MUTED,
            alignment=TA_CENTER,
            spaceAfter=18,
            leading=14,
        ),
        "h1": ParagraphStyle(
            "h1",
            parent=base["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=14,
            textColor=NAVY,
            spaceBefore=14,
            spaceAfter=8,
            leading=18,
        ),
        "h2": ParagraphStyle(
            "h2",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=12,
            textColor=BLUE,
            spaceBefore=10,
            spaceAfter=6,
            leading=15,
        ),
        "body": ParagraphStyle(
            "body",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=10,
            textColor=colors.HexColor("#0F172A"),
            alignment=TA_JUSTIFY,
            leading=14,
            spaceAfter=6,
        ),
        "bullet": ParagraphStyle(
            "bullet",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=10,
            textColor=colors.HexColor("#0F172A"),
            leading=13,
            leftIndent=4,
        ),
        "formula": ParagraphStyle(
            "formula",
            parent=base["Normal"],
            fontName="Courier",
            fontSize=9.5,
            textColor=NAVY,
            backColor=LIGHT,
            leading=13,
            spaceBefore=4,
            spaceAfter=8,
            leftIndent=8,
            rightIndent=8,
            borderPadding=6,
        ),
        "note": ParagraphStyle(
            "note",
            parent=base["Normal"],
            fontName="Helvetica-Oblique",
            fontSize=9,
            textColor=MUTED,
            leading=12,
            spaceAfter=8,
        ),
        "footer": ParagraphStyle(
            "footer",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8,
            textColor=MUTED,
            alignment=TA_CENTER,
        ),
        "cell": ParagraphStyle(
            "cell",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=11,
            textColor=colors.HexColor("#0F172A"),
        ),
        "cell_b": ParagraphStyle(
            "cell_b",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8.5,
            leading=11,
            textColor=NAVY,
        ),
    }
    return styles


def _table(data, col_widths, header=True):
    t = Table(data, colWidths=col_widths, repeatRows=1 if header else 0)
    style_cmds = [
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#0F172A")),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.4, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("BACKGROUND", (0, 1), (-1, -1), colors.white),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
    ]
    if header:
        style_cmds += [
            ("BACKGROUND", (0, 0), (-1, 0), NAVY),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ]
    t.setStyle(TableStyle(style_cmds))
    return t


def build() -> Path:
    styles = _styles()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(OUT),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title="Coherent Quadrant — How X, Y & Overall Scores Are Calculated",
        author="Coherent Quadrant",
    )
    story = []
    P = lambda t, s="body": Paragraph(t, styles[s])
    H1 = lambda t: Paragraph(t, styles["h1"])
    H2 = lambda t: Paragraph(t, styles["h2"])

    # Cover / intro
    story.append(P("Coherent Quadrant", "title"))
    story.append(
        P(
            "How X, Y and Overall Scores Are Calculated<br/>"
            "Method first, then a worked example (Boehringer Ingelheim — GLP-1 market)",
            "subtitle",
        )
    )
    story.append(
        P(
            "This guide explains the scoring math used in the Coherent Quadrant pipeline. "
            "Part A covers the general method. Part B applies it to one real company."
        )
    )

    # ========== PART A ==========
    story.append(H1("Part A — How scores are calculated"))

    story.append(H2("A1. Market setup (once per market)"))
    story.append(
        P(
            "For each market query (for example Global GLP-1 Receptor Agonist Market), the system:"
        )
    )
    story.append(
        ListFlowable(
            [
                ListItem(
                    Paragraph(
                        "Selects an industry leaf from the criteria catalog "
                        "(e.g. Pharmaceutical, Semiconductors, Packaging, Energy).",
                        styles["bullet"],
                    )
                ),
                ListItem(
                    Paragraph(
                        "Refines market-specific <b>X axis</b> and <b>Y axis</b> titles "
                        "and exactly <b>5 X parameters + 5 Y parameters</b> "
                        "(catalog baseline + optional LLM refine).",
                        styles["bullet"],
                    )
                ),
                ListItem(
                    Paragraph(
                        "Loads feature weights and question weights from "
                        "<font face='Courier'>config/quadrant_scoring_weights.yaml</font>.",
                        styles["bullet"],
                    )
                ),
            ],
            bulletType="1",
            start="1",
            leftIndent=12,
        )
    )
    story.append(Spacer(1, 6))
    story.append(
        P(
            "<b>Default matrix feature weights</b> (used when "
            "<font face='Courier'>use_matrix_slot_weights: true</font>):"
        )
    )
    story.append(
        _table(
            [
                ["Slot", "X weight", "Y weight"],
                ["Parameter 1", "0.30", "0.25"],
                ["Parameter 2", "0.20", "0.25"],
                ["Parameter 3", "0.20", "0.20"],
                ["Parameter 4", "0.15", "0.15"],
                ["Parameter 5", "0.15", "0.15"],
                ["Sum", "1.00", "1.00"],
            ],
            [45 * mm, 45 * mm, 45 * mm],
        )
    )
    story.append(Spacer(1, 8))
    story.append(
        P(
            "Each parameter is normally probed with <b>3 questions</b>, weighted "
            "<b>0.4 / 0.3 / 0.3</b>."
        )
    )

    story.append(H2("A2. Per-company evidence"))
    story.append(
        P(
            "Before scoring, the pipeline builds an evidence packet for the company: "
            "website crawl / smart crawl, optional web search snippets, and landscape "
            "facts (HQ, specialty, key brands, role). The LLM is instructed to score "
            "from this evidence and <b>not invent</b> products, approvals, sales, or "
            "geographies that are not supported."
        )
    )

    story.append(H2("A3. Score each parameter from 1 to 10"))
    story.append(P("<b>Main expand pipeline</b>"))
    story.append(
        P(
            "For every X/Y parameter, the LLM answers three questions (each 1–10). "
            "Those answers are rolled into one parameter score:"
        )
    )
    story.append(
        P(
            "sub_avg = 0.4×q1 + 0.3×q2 + 0.3×q3",
            "formula",
        )
    )
    story.append(P("<b>Deep-rescore path (used for some market rescored runs)</b>"))
    story.append(
        P(
            "The LLM may score each of the five parameters <b>directly</b> (1–10) with "
            "a short rationale and grounding label: <i>supported</i>, <i>partial</i>, "
            "or <i>insufficient</i>. Thin/silent evidence stays mid-low; strong "
            "supported evidence can use the high end of the scale."
        )
    )

    story.append(H2("A4. Roll parameter scores into X and Y (0–100)"))
    story.append(
        P("For each parameter on an axis:")
    )
    story.append(
        P(
            "contribution = feature_weight × (parameter_score / 10)",
            "formula",
        )
    )
    story.append(P("Then sum all five contributions and scale to 0–100:"))
    story.append(
        P(
            "X = round(100 × Σ contributions_X)<br/>"
            "Y = round(100 × Σ contributions_Y)",
            "formula",
        )
    )
    story.append(
        P(
            "Important: X and Y are <b>weighted</b> results, not a simple average of "
            "the five 1–10 scores. The first parameters carry more influence."
        )
    )

    story.append(H2("A5. Overall score"))
    story.append(
        P(
            "Overall = round( (X + Y) / 2 )",
            "formula",
        )
    )
    story.append(
        P(
            "X and Y are equally weighted (50% / 50%). A company can be strong on "
            "capability (X) but weaker commercially (Y), or the reverse."
        )
    )

    story.append(H2("A6. Quadrant placement"))
    story.append(
        P(
            "After the full cohort is scored, the system takes the cohort medians "
            "<b>mid_X</b> and <b>mid_Y</b> (absolute median method):"
        )
    )
    story.append(
        _table(
            [
                ["Condition", "Quadrant"],
                ["X ≥ mid_X and Y ≥ mid_Y", "Leaders"],
                ["X < mid_X and Y ≥ mid_Y", "Challengers"],
                ["X ≥ mid_X and Y < mid_Y", "Trailblazers"],
                ["X < mid_X and Y < mid_Y", "Emerging Players"],
            ],
            [90 * mm, 55 * mm],
        )
    )
    story.append(Spacer(1, 6))
    story.append(
        P(
            "Quadrants are relative to the market peer set. A score of 74 may be "
            "Leaders in one cohort and mid-pack in another, depending on medians.",
            "note",
        )
    )

    story.append(H2("A7. End-to-end flow"))
    story.append(
        P(
            "Market query → industry leaf + 5 X / 5 Y parameters → "
            "company evidence (crawl/search) → LLM scores parameters 1–10 → "
            "weighted rollup → X &amp; Y (0–100) → Overall = (X+Y)/2 → "
            "compare to cohort medians → Quadrant.",
            "formula",
        )
    )

    # ========== PART B ==========
    story.append(PageBreak())
    story.append(H1("Part B — Worked example: Boehringer Ingelheim (GLP-1)"))
    story.append(
        P(
            "Market: <b>Global GLP-1 Receptor Agonist Market</b><br/>"
            "Company: <b>Boehringer Ingelheim</b> (Brand)<br/>"
            "Result: <b>X = 74</b>, <b>Y = 74</b>, <b>Overall = 74</b>, "
            "Quadrant = <b>Leaders</b>"
        )
    )

    story.append(H2("B1. Market axes used for this example"))
    story.append(
        P(
            "<b>X — Therapeutic &amp; Manufacturing Capability</b><br/>"
            "<b>Y — Commercial Reach &amp; Pipeline Strategy</b>"
        )
    )
    story.append(
        _table(
            [
                [
                    Paragraph("<b>#</b>", styles["cell_b"]),
                    Paragraph("<b>X parameter</b>", styles["cell_b"]),
                    Paragraph("<b>w</b>", styles["cell_b"]),
                    Paragraph("<b>Y parameter</b>", styles["cell_b"]),
                    Paragraph("<b>w</b>", styles["cell_b"]),
                ],
                ["1", "Product / Molecule Portfolio", "0.30", "Geographic Market Access", "0.25"],
                [
                    "2",
                    "Therapeutic Coverage & Differentiation",
                    "0.20",
                    "Brand / HCP Reputation",
                    "0.25",
                ],
                [
                    "3",
                    "Innovation & Clinical R&D",
                    "0.20",
                    "Financial Performance",
                    "0.20",
                ],
                [
                    "4",
                    "Manufacturing & Supply Reliability",
                    "0.15",
                    "Pipeline & Indication Roadmap",
                    "0.15",
                ],
                [
                    "5",
                    "Regulatory & Quality Compliance",
                    "0.15",
                    "Partnerships & Business Expansion",
                    "0.15",
                ],
            ],
            [10 * mm, 58 * mm, 14 * mm, 58 * mm, 14 * mm],
        )
    )

    story.append(H2("B2. Evidence available for Boehringer"))
    story.append(
        ListFlowable(
            [
                ListItem(
                    Paragraph(
                        "Partnership with Zealand Pharma on survodutide (GLP-1/glucagon dual agonist).",
                        styles["bullet"],
                    )
                ),
                ListItem(
                    Paragraph(
                        "Late-stage Phase 3 programs in obesity / MASH (public topline path).",
                        styles["bullet"],
                    )
                ),
                ListItem(
                    Paragraph(
                        "Large diversified pharmaceutical company reputation and finances.",
                        styles["bullet"],
                    )
                ),
                ListItem(
                    Paragraph(
                        "Limited evidence in the packet for GLP-1 manufacturing scale or "
                        "already-marketed global GLP-1 commercial footprint → those "
                        "parameters stay mid/low (insufficient).",
                        styles["bullet"],
                    )
                ),
            ],
            bulletType="bullet",
            leftIndent=12,
        )
    )

    story.append(H2("B3. LLM parameter scores (1–10)"))
    story.append(P("<b>X axis — raw feature scores</b>"))
    story.append(
        _table(
            [
                ["Parameter", "Score", "Grounding", "Interpretation"],
                [
                    "Product / Molecule Portfolio",
                    "6",
                    "supported",
                    "Has GLP-1 asset; not a multi-brand franchise like Novo",
                ],
                [
                    "Therapeutic Coverage & Differentiation",
                    "7",
                    "supported",
                    "Dual agonist / MASH angle is differentiated",
                ],
                [
                    "Innovation & Clinical R&D",
                    "8",
                    "supported",
                    "Phase 3 is a strong R&D signal",
                ],
                [
                    "Manufacturing & Supply",
                    "5",
                    "insufficient",
                    "Little GLP-1 manufacturing evidence in packet",
                ],
                [
                    "Regulatory & Quality",
                    "5",
                    "insufficient",
                    "No GLP-1 approval evidenced yet",
                ],
            ],
            [48 * mm, 16 * mm, 24 * mm, 66 * mm],
        )
    )
    story.append(Spacer(1, 8))
    story.append(P("<b>Y axis — raw feature scores</b>"))
    story.append(
        _table(
            [
                ["Parameter", "Score", "Grounding", "Interpretation"],
                [
                    "Geographic Market Access",
                    "4",
                    "insufficient",
                    "No clear marketed GLP-1 geography yet",
                ],
                [
                    "Brand / HCP Reputation",
                    "6",
                    "supported",
                    "Strong pharma brand; not yet a GLP-1 household name",
                ],
                [
                    "Financial Performance",
                    "7",
                    "supported",
                    "Large-company finances supported",
                ],
                [
                    "Pipeline & Indication Roadmap",
                    "8",
                    "supported",
                    "Clear obesity / MASH roadmap",
                ],
                [
                    "Partnerships & Expansion",
                    "7",
                    "supported",
                    "Zealand partnership is real expansion",
                ],
            ],
            [48 * mm, 16 * mm, 24 * mm, 66 * mm],
        )
    )

    story.append(H2("B4. Convert to contributions and X score"))
    story.append(
        P(
            "In that deep-rescore run, supported mid/high scores were lightly stretched "
            "(e.g. 6→7.5, 7→8.5, 8→9.5). Insufficient scores stayed capped near 5. "
            "Then:"
        )
    )
    story.append(
        P(
            "contribution = weight × (score / 10)",
            "formula",
        )
    )
    story.append(
        _table(
            [
                ["#", "Adjusted score", "Weight", "Contribution"],
                ["1 Portfolio", "7.5 → 0.75", "0.30", "0.225"],
                ["2 Coverage", "8.5 → 0.85", "0.20", "0.170"],
                ["3 Innovation", "9.5 → 0.95", "0.20", "0.190"],
                ["4 Manufacturing", "5.0 → 0.50", "0.15", "0.075"],
                ["5 Regulatory", "5.0 → 0.50", "0.15", "0.075"],
                ["Sum", "", "", "0.735"],
            ],
            [42 * mm, 40 * mm, 28 * mm, 35 * mm],
        )
    )
    story.append(Spacer(1, 6))
    story.append(
        P(
            "X = round(0.735 × 100) = <b>74</b>",
            "formula",
        )
    )
    story.append(
        P(
            "Same rollup on Y yields <b>Y = 74</b>. "
            "Note: a naive average of the five raw X scores would be "
            "(6+7+8+5+5)/5 = 6.2 → 62. Weighted scoring (and stretch on supported "
            "evidence) raises the axis to 74 because stronger parameters carry more weight."
        )
    )

    story.append(H2("B5. Overall and quadrant"))
    story.append(
        P(
            "Overall = round( (74 + 74) / 2 ) = <b>74</b>",
            "formula",
        )
    )
    story.append(
        P(
            "For this GLP-1 cohort, medians were about <b>mid_X ≈ 37.5</b> and "
            "<b>mid_Y ≈ 38</b>. Because 74 ≥ 37.5 and 74 ≥ 38, Boehringer is placed in "
            "<b>Leaders</b>."
        )
    )
    story.append(
        _table(
            [
                ["Company", "X", "Y", "Overall", "Quadrant", "Why (short)"],
                [
                    "Novo Nordisk",
                    "100",
                    "100",
                    "100",
                    "Leaders",
                    "Global multi-blockbuster GLP-1 franchise",
                ],
                [
                    "Boehringer",
                    "74",
                    "74",
                    "74",
                    "Leaders",
                    "Strong late-stage pipeline; not yet commercial leader",
                ],
                [
                    "Roche",
                    "64",
                    "71",
                    "68",
                    "Leaders",
                    "Carmot assets / obesity pipeline; still building",
                ],
            ],
            [32 * mm, 14 * mm, 14 * mm, 18 * mm, 22 * mm, 55 * mm],
        )
    )

    story.append(H2("B6. Why 74 — not 90 or 40"))
    story.append(
        _table(
            [
                ["Pulls the score UP", "Pulls the score DOWN"],
                [
                    "Late-stage dual-agonist clinical program",
                    "No marketed blockbuster GLP-1 franchise yet",
                ],
                [
                    "Clear Zealand partnership",
                    "Thin manufacturing / regulatory GLP-1 proof in packet",
                ],
                [
                    "Credible large-pharma finances & brand",
                    "Limited proven geographic GLP-1 commercial reach yet",
                ],
            ],
            [85 * mm, 85 * mm],
        )
    )

    story.append(Spacer(1, 14))
    story.append(
        P(
            "Summary: parameters are market-specific; scores come from evidence; "
            "X/Y are weighted 0–100 rolls; Overall is the midpoint of X and Y; "
            "quadrant is relative to the cohort median.",
            "note",
        )
    )
    story.append(
        P(
            "Generated for Coherent Quadrant · Example market: Global GLP-1 Receptor Agonist",
            "footer",
        )
    )

    def _on_page(canvas, doc_):
        canvas.saveState()
        canvas.setStrokeColor(LINE)
        canvas.setLineWidth(0.5)
        canvas.line(18 * mm, 12 * mm, A4[0] - 18 * mm, 12 * mm)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(MUTED)
        canvas.drawString(18 * mm, 8 * mm, "Coherent Quadrant — Scoring Guide")
        canvas.drawRightString(A4[0] - 18 * mm, 8 * mm, f"Page {doc_.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    return OUT


if __name__ == "__main__":
    path = build()
    print(path)
