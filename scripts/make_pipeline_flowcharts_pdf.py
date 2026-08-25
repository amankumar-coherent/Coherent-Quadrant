#!/usr/bin/env python3
"""Generate flowchart PDFs for the two pipelines (run_pipeline.py, chatgpt_expand.py).

Market-agnostic — describes the pipeline shape, not any one market's run.
Output:
  docs/pipeline-run_pipeline/run_pipeline_flowchart.pdf
  docs/pipeline-chatgpt_expand/chatgpt_expand_flowchart.pdf
"""
from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[1]

NAVY = colors.HexColor("#0B1F3A")
BLUE = colors.HexColor("#1D4ED8")
TEAL = colors.HexColor("#0D9488")
AMBER = colors.HexColor("#B45309")
LIGHT = colors.HexColor("#F1F5F9")
LINE = colors.HexColor("#CBD5E1")
MUTED = colors.HexColor("#475569")
WHITE = colors.white

PAGE_W, PAGE_H = A4
MARGIN = 16 * mm
CONTENT_W = PAGE_W - 2 * MARGIN


class FlowchartPDF:
    """Minimal vertical box-and-arrow flowchart renderer (reportlab canvas)."""

    def __init__(self, path: Path, title: str, subtitle: str):
        self.c = canvas.Canvas(str(path), pagesize=A4)
        self.title = title
        self.subtitle = subtitle
        self.y = PAGE_H - MARGIN
        self._new_page(first=True)

    def _new_page(self, first: bool = False) -> None:
        if not first:
            self.c.showPage()
        self.y = PAGE_H - MARGIN
        self.c.setFillColor(NAVY)
        self.c.rect(0, PAGE_H - 26 * mm, PAGE_W, 26 * mm, fill=1, stroke=0)
        self.c.setFillColor(WHITE)
        self.c.setFont("Helvetica-Bold", 15)
        self.c.drawString(MARGIN, PAGE_H - 12 * mm, self.title)
        self.c.setFont("Helvetica", 9.5)
        self.c.setFillColor(colors.HexColor("#CBD5E1"))
        self.c.drawString(MARGIN, PAGE_H - 19 * mm, self.subtitle)
        self.y = PAGE_H - 32 * mm

    def _ensure_space(self, needed: float) -> None:
        if self.y - needed < MARGIN + 10 * mm:
            self._new_page()

    def _wrap(self, text: str, font: str, size: float, max_w: float) -> list[str]:
        self.c.setFont(font, size)
        words = text.split()
        lines: list[str] = []
        cur = ""
        for w in words:
            trial = (cur + " " + w).strip()
            if self.c.stringWidth(trial, font, size) <= max_w:
                cur = trial
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        return lines or [""]

    def arrow_down(self, length: float = 6 * mm) -> None:
        self._ensure_space(length + 2 * mm)
        x = PAGE_W / 2
        y0 = self.y
        y1 = self.y - length
        self.c.setStrokeColor(MUTED)
        self.c.setLineWidth(1.3)
        self.c.line(x, y0, x, y1 + 2)
        self.c.setFillColor(MUTED)
        self.c.line(x - 1.6 * mm, y1 + 3.2 * mm, x, y1)
        self.c.line(x + 1.6 * mm, y1 + 3.2 * mm, x, y1)
        self.y = y1

    def step_box(
        self,
        number: str,
        title: str,
        body_lines: list[str],
        *,
        color=BLUE,
        optional: bool = False,
        width_frac: float = 1.0,
    ) -> None:
        """Main pipeline step — numbered header + wrapped body lines."""
        box_w = CONTENT_W * width_frac
        x0 = MARGIN + (CONTENT_W - box_w) / 2
        pad = 3.2 * mm
        header_h = 8 * mm
        line_h = 4.6 * mm
        wrapped: list[str] = []
        for bl in body_lines:
            wrapped.extend(self._wrap(bl, "Helvetica", 8.6, box_w - 2 * pad))
        box_h = header_h + pad + len(wrapped) * line_h + pad
        self._ensure_space(box_h + 4 * mm)
        y_top = self.y
        y_bot = y_top - box_h

        # Header strip
        self.c.setFillColor(LIGHT)
        self.c.setStrokeColor(color)
        self.c.setLineWidth(1.4 if not optional else 0.9)
        if optional:
            self.c.setDash(3, 2)
        else:
            self.c.setDash()
        self.c.roundRect(x0, y_bot, box_w, box_h, 3 * mm, fill=1, stroke=1)
        self.c.setDash()

        self.c.setFillColor(color)
        self.c.rect(x0, y_top - header_h, box_w, header_h, fill=1, stroke=0)
        self.c.setFillColor(WHITE)
        self.c.setFont("Helvetica-Bold", 9.5)
        label = f"{number}  {title}"
        if optional:
            label += "   (optional)"
        self.c.drawString(x0 + pad, y_top - header_h + 2.6 * mm, label)

        self.c.setFillColor(colors.HexColor("#1E293B"))
        self.c.setFont("Helvetica", 8.6)
        ty = y_top - header_h - pad - 3.2 * mm
        for ln in wrapped:
            self.c.drawString(x0 + pad, ty, ln)
            ty -= line_h

        self.y = y_bot

    def sub_box(self, label: str, text: str, *, color=TEAL, indent: float = 8 * mm) -> None:
        """Smaller indented sub-step box under a main step (e.g. 6c, 6d, 2g)."""
        box_w = CONTENT_W - indent
        x0 = MARGIN + indent
        pad = 2.6 * mm
        wrapped = self._wrap(text, "Helvetica", 8.0, box_w - 2 * pad - 16 * mm)
        line_h = 4.1 * mm
        box_h = pad * 2 + len(wrapped) * line_h
        self._ensure_space(box_h + 3 * mm)
        y_top = self.y
        y_bot = y_top - box_h
        self.c.setFillColor(colors.white)
        self.c.setStrokeColor(color)
        self.c.setLineWidth(0.9)
        self.c.roundRect(x0, y_bot, box_w, box_h, 2 * mm, fill=1, stroke=1)
        self.c.setFillColor(color)
        self.c.setFont("Helvetica-Bold", 7.6)
        self.c.drawString(x0 + pad, y_top - pad - 3 * mm, label)
        self.c.setFillColor(colors.HexColor("#334155"))
        self.c.setFont("Helvetica", 8.0)
        ty = y_top - pad - 3 * mm
        tx = x0 + pad + 16 * mm
        for ln in wrapped:
            self.c.drawString(tx, ty, ln)
            ty -= line_h
        self.y = y_bot - 2 * mm

    def note(self, text: str) -> None:
        wrapped = self._wrap(text, "Helvetica-Oblique", 8.0, CONTENT_W)
        self._ensure_space(len(wrapped) * 4 * mm + 4 * mm)
        self.c.setFillColor(MUTED)
        self.c.setFont("Helvetica-Oblique", 8.0)
        for ln in wrapped:
            self.c.drawCentredString(PAGE_W / 2, self.y, ln)
            self.y -= 4 * mm
        self.y -= 2 * mm

    def terminal(self, text: str, *, color=NAVY) -> None:
        pad = 3 * mm
        w = self.c.stringWidth(text, "Helvetica-Bold", 9.5) + 2 * pad + 6 * mm
        x0 = (PAGE_W - w) / 2
        h = 8 * mm
        self._ensure_space(h + 4 * mm)
        y_top = self.y
        self.c.setFillColor(color)
        self.c.roundRect(x0, y_top - h, w, h, h / 2, fill=1, stroke=0)
        self.c.setFillColor(WHITE)
        self.c.setFont("Helvetica-Bold", 9.5)
        self.c.drawCentredString(PAGE_W / 2, y_top - h + 2.6 * mm, text)
        self.y = y_top - h

    def save(self) -> None:
        self.c.showPage()
        self.c.save()


def build_run_pipeline_pdf(out_path: Path) -> None:
    fc = FlowchartPDF(
        out_path,
        "run_pipeline.py — Vendor Intelligence Pipeline",
        "Quality market-landscape pipeline. Works for ANY market — replace <Market> with your query.",
    )
    fc.terminal('START: python run_pipeline.py --industry "<Market>" --country <global|Country> --live', color=TEAL)
    fc.arrow_down()

    fc.step_box(
        "1",
        "Phase 1 — Query Plan",
        [
            "LLM interprets the market query into a structured search plan: value-chain "
            "sections/segments to profile, geography scope, and search prompt seeds.",
        ],
        color=BLUE,
    )
    fc.arrow_down()

    fc.step_box(
        "2",
        "Phase 2 — Discovery + Entity Gate",
        [
            "Search-driven candidate discovery (web search, directories, AI Overview) across "
            "the value-chain sections. Drops geo-artifact / placeholder names (e.g. '<Country> "
            f"<Market>') and obvious duplicates before enrichment.",
        ],
        color=BLUE,
    )
    fc.arrow_down()

    fc.step_box(
        "3",
        "Phase 3 — Enrichment",
        [
            "Crawls each candidate's website (smart_crawl / SSC) to extract facts: HQ location, "
            "founded year, revenue, YoY growth, product/service description, ownership.",
        ],
        color=BLUE,
    )
    fc.arrow_down()

    fc.step_box(
        "4",
        "Phase 4 — Classification (Quality)",
        [
            "LLM scores each company's relevance/confidence/quality for this market and tags a "
            "commercial_role (Brand, Marketer, Manufacturer, Solution Provider, etc.) from the "
            "enrichment evidence.",
        ],
        color=BLUE,
    )
    fc.arrow_down()

    fc.step_box(
        "5",
        "Export Filter + Save Landscape",
        [
            "Keeps rows clearing confidence/quality gates, scoped by config/industry_role_rules.yaml "
            "(per-market-family role allow-list) and the row cap (target: 1000 companies, global "
            "and regional runs). Writes CSV + Excel (.xlsx) + Word (.docx).",
        ],
        color=BLUE,
    )
    fc.arrow_down()

    fc.step_box(
        "6",
        "Coherent Quadrant Synthesis (synthesize_quadrant)",
        [
            "Takes the exported landscape rows and scores them on the Coherent Quadrant. "
            "Sub-steps below run in this order:",
        ],
        color=NAVY,
    )
    fc.sub_box(
        "6a",
        "Select Industry Catalog — matches the market to an industry_group / "
        "industry_category baseline (config/quadrant_industry_criteria.yaml).",
    )
    fc.sub_box(
        "6b",
        "Define Market Axes — LLM refines the baseline into 5 X + 5 Y scoring parameters "
        "specific to THIS market. Axis TITLES are fixed for every market: "
        "X = 'Product Strength', Y = 'Business Strategy'. The 5 parameters under each "
        "axis change per market (axis_define.py).",
    )
    fc.sub_box(
        "6c",
        "Market Relevance / Player-Type Filter — LLM classifies the market as hardware / "
        "software_service / consumer, then keeps ONLY the matching role: hardware -> "
        "Manufacturer only; software_service -> Solution Developer / Service Provider / "
        "System Integrator only; consumer -> Brand / Marketer only "
        "(market_relevance.py).",
        color=AMBER,
    )
    fc.sub_box(
        "6d",
        "Value-Chain Operator Filter — drops distributors/traders/resellers with no "
        "operational control, and collapses parent/subsidiary duplicates to one row "
        "(value_chain_filter.py).",
    )
    fc.sub_box(
        "6e",
        "Generate Scoring Questions — LLM writes 3 evidence-based questions per X/Y "
        "parameter (question_gen.py).",
    )
    fc.sub_box(
        "6f",
        "Score Each Company — builds a knowledge base from the enrichment evidence "
        "snapshot, then LLM answers the scoring questions per company (qa_scorer.py).",
    )
    fc.sub_box(
        "6g",
        "Normalize + Assign Quadrant — proportional score normalization across the "
        "population, then assigns Leaders / Challengers / Trailblazers / Emerging "
        "Players and a chart position (matrix_rollup.py, rating_map.py).",
    )
    fc.sub_box(
        "6h",
        "Build Chart + Table — chart shows ~20 brands split evenly across the four "
        "quadrants; Company Details table lists up to 1000 scored rows. Company column "
        "is never blank: shows the company's own name, plus '(acquired by Parent)' when "
        "owned (brand_meta.py).",
    )
    fc.arrow_down()

    fc.step_box(
        "7",
        "Write Outputs",
        [
            "Quadrant JSON + Companies CSV + self-contained HTML report "
            "(output/quadrant/<market>_report.html) — chart, scorecards, Company Details "
            "table, and Market Scoring Parameters / Parameter Definitions panels.",
        ],
        color=BLUE,
    )
    fc.arrow_down()

    fc.terminal("END: CSV + XLSX + DOCX (landscape) + Quadrant JSON/CSV/HTML (chart)", color=NAVY)
    fc.note(
        "Every LLM decision above (axis parameters, player-type, relevance, role, scoring) is "
        "re-run per market at call time — nothing here is hardcoded to one market."
    )
    fc.save()


def build_chatgpt_expand_pdf(out_path: Path) -> None:
    fc = FlowchartPDF(
        out_path,
        "chatgpt_expand.py — ChatGPT/DeepSeek Expand Pipeline",
        "Landscape discovery + Coherent Quadrant, one script. Works for ANY market.",
    )
    fc.terminal(
        'START: python scripts/run_chatgpt_expand.py --query "<Market>" --country <global|Country> --fresh',
        color=TEAL,
    )
    fc.arrow_down()

    fc.step_box(
        "1/6",
        "ChatGPT Recall",
        [
            "Asks the LLM (paged, ~35 companies/page) to list companies it already knows in "
            "this market — cheap first pass before any live web search.",
        ],
        color=BLUE,
    )
    fc.arrow_down()

    fc.step_box(
        "2/6",
        "OpenAI SDK Web Search — Find Companies",
        [
            "Live web_search tool calls discover companies not in the LLM's own knowledge. "
            "Includes sub-step 2g below.",
        ],
        color=BLUE,
    )
    fc.sub_box(
        "2g",
        "Google AI List Discover (optional) — queries the local Google AI Overview scraper "
        "backend (http://127.0.0.1:15561, Chrome extension relay) for company-list-style "
        "AI Overviews, LLM-extracts company names from the scraped text. Needs the backend "
        "running + GOOGLE_AI_SCRAPER_ENABLED=true, else silently skipped.",
        color=AMBER,
    )
    fc.arrow_down()

    fc.step_box(
        "3/6",
        "DDGS / SearXNG Harvest + Extract",
        ["Optional supplementary search-engine harvest, LLM-extracts company names from results."],
        color=BLUE,
        optional=True,
    )
    fc.arrow_down()

    fc.step_box(
        "4/6",
        "ChatGPT Verify (mid)",
        [
            "LLM checks each candidate against strict market-fit criteria (verify_criteria_prompt) "
            "and drops resellers/media/associations/geo-junk before the expensive fill step.",
        ],
        color=BLUE,
    )
    fc.arrow_down()

    fc.step_box(
        "5/6",
        "Fill Gaps to Target",
        ["Two-part fill, run in order, until the target row count is reached:"],
        color=BLUE,
    )
    fc.sub_box(
        "5a",
        "Search-stack fill — Google AI + DDGS + SearXNG + Exa + Wikipedia + Owler "
        "(default fill_backend=search).",
    )
    fc.sub_box("5b", "OpenAI SDK residual fill — LLM fills remaining gaps directly.")
    fc.arrow_down()

    fc.step_box(
        "6/6",
        "ChatGPT Final Verify + Trim to Target",
        [
            "Final market-fit pass on the merged candidate set, then trims to the target row "
            "count (default 1000), ranked by data confidence.",
        ],
        color=BLUE,
    )
    fc.arrow_down()

    fc.step_box(
        "6c",
        "Coherent Quadrant X / Y / Overall Scoring",
        ["Runs the SAME scoring machinery as synthesize.py, in this order:"],
        color=NAVY,
    )
    fc.sub_box(
        "6c.1",
        "Player-Type Filter — classify_player_type() decides hardware / software_service / "
        "consumer for this market, then DROPS every row whose role does not match: hardware "
        "-> Manufacturer only; software_service -> Solution Developer / Service Provider / "
        "System Integrator only; consumer -> Brand / Marketer only. This filtered set is what "
        "everything downstream (scoring, Excel, Quadrant chart) is built from.",
        color=AMBER,
    )
    fc.sub_box(
        "6c.2",
        "Define Market Axes — same fixed axis titles as run_pipeline.py: X = 'Product "
        "Strength', Y = 'Business Strategy', with 5 market-specific parameters per axis.",
    )
    fc.sub_box(
        "6c.3",
        "Deep Crawl + Score — smart_crawl each surviving company, then LLM answers the "
        "generated scoring questions per company; computes X / Y / Overall and assigns "
        "quadrant by absolute median split.",
    )
    fc.arrow_down()

    fc.step_box(
        "6d",
        "Company Details Mapping",
        [
            "Builds the Brand | Company | Role | Quadrant | X | Y | Overall | Found-in table via "
            "brand_display_fields() — Company column is never blank: shows the company's own "
            "name, plus '(acquired by Parent)' when owned.",
        ],
        color=BLUE,
    )
    fc.arrow_down()

    fc.step_box(
        "7",
        "Write Final Outputs",
        [
            "Writes the final Excel (landscape) and the HTML/CSV Quadrant report — BOTH built "
            "from the same player-type-filtered row set from step 6c.1, so a hardware market's "
            "Excel and chart are Manufacturer-only end to end.",
        ],
        color=BLUE,
    )
    fc.arrow_down()

    fc.terminal("END: Final Excel (landscape) + Quadrant JSON/CSV/HTML (chart)", color=NAVY)
    fc.note(
        "Every step is checkpointed (ExpandCheckpoint) — re-running without --fresh resumes "
        "from the last completed step instead of starting over."
    )
    fc.save()


def main() -> None:
    run_dir = ROOT / "docs" / "pipeline-run_pipeline"
    chatgpt_dir = ROOT / "docs" / "pipeline-chatgpt_expand"
    run_dir.mkdir(parents=True, exist_ok=True)
    chatgpt_dir.mkdir(parents=True, exist_ok=True)

    run_pdf = run_dir / "run_pipeline_flowchart.pdf"
    chatgpt_pdf = chatgpt_dir / "chatgpt_expand_flowchart.pdf"

    build_run_pipeline_pdf(run_pdf)
    build_chatgpt_expand_pdf(chatgpt_pdf)

    print(f"wrote {run_pdf}")
    print(f"wrote {chatgpt_pdf}")


if __name__ == "__main__":
    main()
