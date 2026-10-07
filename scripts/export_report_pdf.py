#!/usr/bin/env python3
"""Print a market's interactive Coherent Quadrant report to a paginated PDF.

Layout (nothing market-specific; every label comes from the report itself):
  page 1        cover (market, geography, key figures) + Market Classification
  page 2        contents with page numbers
  next pages    every report section starts on its own page; Quadrant
                Positioning gets a full page with a tall chart
  company pages in Parameter Detail each company starts on a new page with a
                banner header and all 10 parameters (one or two pages)

  first page    branded front cover, if _pipeline/front_cover.pdf (this market)
                or config/front_cover.pdf (every market) exists; its "xxxxxx"
                title slot is filled with the market name, no footer on it
  last page(s)  back cover, if _pipeline/pdf_back_cover.pdf (this market) or
                config/pdf_back_cover.pdf (every market) exists

Interactive parts are opened before printing: every Other Noticeable Player
row, and every parameter's rationale + supporting points for each company.

    .venv\\Scripts\\python.exe scripts\\export_report_pdf.py --market "..." --country global
    .venv\\Scripts\\python.exe scripts\\export_report_pdf.py --html path\\to\\x_report.html
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# Opens the interactive widgets so the printed page shows everything.
EXPAND_JS = r"""
() => {
  const t = document.getElementById('f-toggle');
  if (t && !t.classList.contains('open')) t.click();
  const keys = [...document.querySelectorAll('.axwrap')].map(w => w.getAttribute('data-wrap'));
  for (const key of keys) {
    const sel = () => document.querySelector('.axwrap[data-wrap="' + key + '"]');
    const names = [...sel().querySelectorAll('.pbtn')].map(b => b.getAttribute('data-name'));
    const parts = [];
    for (const n of names) {
      const btn = [...sel().querySelectorAll('.pbtn')].find(b => b.getAttribute('data-name') === n);
      if (!btn.classList.contains('active')) btn.click();
      parts.push('<div class="pdetail">' + sel().querySelector('.pdetail').innerHTML + '</div>');
    }
    sel().querySelector('.axgrid').outerHTML = '<div class="pstack">' + parts.join('') + '</div>';
  }
  return keys.length;
}
"""

# Cover facts come from the page itself (hero line); no date is printed.
COVER_JS = r"""
() => {
  const hero = document.querySelector('.hero');
  if (!hero) return false;
  const line = (hero.querySelector('p') || {}).textContent || '';
  const parts = line.split('·').map(s => s.trim());
  const market = parts[0] || '';
  const geo = parts[1] || '';
  const scope = parts.slice(2).join(' · ');
  hero.innerHTML =
    '<div class="cv-brand">Coherent Quadrant</div>' +
    '<div class="cv-market">' + market + '</div>' +
    '<div class="cv-rule"></div>' +
    '<div class="cv-meta"><span>' + geo + '</span></div>' +
    '<div class="cv-scope">' + scope + '</div>';
  hero.classList.add('cover');
  // Key figures, read from the report's own sections.
  const chartSub = [...document.querySelectorAll('h2 .sub')].map(e => e.textContent)
    .find(t => /on chart/i.test(t)) || '';
  const nums = (chartSub.match(/\d+/g) || []).map(Number);
  const onChart = nums[0], total = nums[1];
  const params = document.querySelectorAll('.pname').length;
  const quads = document.querySelectorAll('.qdef').length;
  const tiles = [[total, 'Companies assessed'], [onChart, 'Companies on the Coherent Quadrant'],
                 [params, 'Scoring parameters'], [quads, 'Quadrants']]
    .filter(t => t[0]).map(t => '<div class="cv-tile"><b>' + t[0] + '</b><span>' + t[1] + '</span></div>').join('');
  const cls = document.querySelector('section.card');
  if (tiles && cls) cls.insertAdjacentHTML('afterend', '<div class="cv-stats">' + tiles + '</div>');
  return true;
}
"""

# Contents page after the cover: every section and every chart company. Each of
# them starts its own page, so the first print is read back for page numbers
# (title = first text on its page) and the second print fills them in.
TOC_JS = r"""
(pages) => {
  const items = [];
  document.querySelectorAll('.cv-toc').forEach(e => e.remove());
  const mark = (el, title, sub) => { items.push({title: title, sub: sub}); };
  const secs = [...document.querySelectorAll('section.card')];
  secs.forEach((sec, i) => {
    if (i === 0) return;                       // classification shares the cover
    const h = sec.querySelector('h2');
    if (!h) return;
    const title = (h.childNodes[0] && h.childNodes[0].textContent || '').trim();
    mark(sec, title, false);
    sec.querySelectorAll('.cblock').forEach(b => {
      const nm = b.querySelector('.chead .nm');
      if (nm) mark(b, nm.textContent.trim(), true);
    });
  });
  const rows = items.map((it, n) =>
    '<div class="' + (it.sub ? 'tc sub' : 'tc') + '"><span class="tt">' + it.title +
    '</span><span class="dots"></span><span class="pg">' + (pages ? (pages[n] || '') : '') +
    '</span></div>').join('');
  const toc = document.createElement('section');
  toc.className = 'card cv-toc';
  toc.innerHTML = '<h2>Contents</h2><div class="tcl">' + rows + '</div>';
  (document.querySelector('.cv-stats') || secs[0]).after(toc);   // after the cover's key figures
  // Screen-only hints ("click a score ...", "on the chart above") mean nothing on paper.
  document.querySelectorAll('h2 .sub').forEach(s => {
    s.textContent = s.textContent.replace(/\s*[··]\s*click[^)]*/i, '')
                                 .replace(/plotted on the chart above/i, 'plotted on the Quadrant Positioning chart');
  });
  return items.map(it => it.title);
}
"""

PRINT_CSS = """
  @page{size:A4;margin:12mm 10mm 14mm}
  body{background:#fff}
  .wrap{max-width:none;padding:0;gap:0;display:block}
  .toggle,.filters,.count,.caret,.pbtn .car,.lead{display:none!important}
  *{-webkit-print-color-adjust:exact;print-color-adjust:exact}

  /* Cover: page 1 opens with a full-width banner; classification follows. */
  .hero.cover{border-radius:0;padding:80px 56px 64px;margin:0 0 30px;min-height:640px;
    display:flex;flex-direction:column;justify-content:flex-end}
  .cv-brand{font-size:1.05rem;font-weight:700;letter-spacing:.32em;text-transform:uppercase;opacity:.85}
  .cv-market{font-size:2.6rem;font-weight:700;line-height:1.15;margin-top:18px;max-width:900px}
  .cv-rule{width:120px;height:5px;background:#52B69A;border-radius:3px;margin:26px 0 18px}
  .cv-meta{display:flex;gap:28px;font-size:1.05rem;font-weight:600}
  .cv-scope{margin-top:10px;font-size:.98rem;opacity:.85;max-width:900px}

  .cv-stats{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-top:28px}
  .cv-tile{border-radius:12px;padding:22px 18px;background:linear-gradient(135deg,#002857 0%,#1A759F 100%);color:#fff}
  .cv-tile b{display:block;font-size:2.3rem;line-height:1.1}
  .cv-tile span{display:block;margin-top:6px;font-size:.9rem;opacity:.85}

  /* Every section starts a page; the one right after the cover stays on it. */
  section.card{break-before:page;border:none;box-shadow:none;border-radius:0;padding:0;margin:0}
  .hero + section.card{break-before:auto}
  h2{font-size:1.55rem;color:#002857;padding-bottom:10px;margin:0 0 20px;
    border-bottom:4px solid #52B69A;break-after:avoid}
  h2 .sub{display:block;font-size:.9rem;font-weight:500;color:#475569;opacity:1;margin-top:4px}

  /* Quadrant Positioning fills its page. */
  .plot{height:1320px}
  .dot b{font-size:.72rem;max-width:150px}
  .qlabel{font-size:.95rem}

  /* One company per page (a long one runs onto a second page). */
  .cblock{break-before:page;border:none;border-radius:0;margin:0}
  .cblock:first-of-type{break-before:auto}
  .chead{background:linear-gradient(135deg,#002857 0%,#1A759F 100%);border-radius:10px;
    padding:18px 22px;margin-bottom:6px;break-after:avoid}
  .chead .nm{color:#fff;font-size:1.3rem}
  .chead .br{color:#cbd5e1}
  .chead .pill{color:#fff}
  .chead .sc{color:#cbd5e1;font-size:.95rem;gap:18px}
  .chead .sc strong{color:#fff;font-size:1.1rem}
  .cbody{padding:12px 0 0;gap:18px}
  .axttl{font-size:.9rem;color:#1A759F;border-bottom:1px solid #e2e8f0;padding-bottom:6px;break-after:avoid}
  .pstack{display:flex;flex-direction:column;gap:10px}
  .pdetail{break-inside:avoid;padding:14px 16px;border-left:4px solid #52B69A}

  /* Contents */
  .tcl{columns:2;column-gap:48px}
  .tc{display:flex;align-items:baseline;gap:6px;break-inside:avoid;font-size:1rem;font-weight:700;
    color:#002857;margin:14px 0 6px}
  .tc.sub{font-size:.9rem;font-weight:400;color:#334155;margin:4px 0 4px 16px}
  .tc .dots{flex:1;border-bottom:1px dotted #94a3b8;transform:translateY(-3px)}
  .tc .pg{min-width:22px;text-align:right;font-variant-numeric:tabular-nums}

  /* Tables: header row repeats on every page, rows never split. */
  thead{display:table-header-group}
  tr,.qdef,.panel,.step,.mix{break-inside:avoid}
  .steps{overflow:visible}
"""


def _footer(market: str) -> str:
    safe = market.replace("&", "&amp;").replace("<", "&lt;")
    return ('<div style="font-size:8px;width:100%;padding:0 10mm;display:flex;'
            'justify-content:space-between;color:#64748b;font-family:Arial,sans-serif">'
            f'<span>Coherent Quadrant &middot; {safe}</span>'
            '<span>Page <span class="pageNumber"></span> of <span class="totalPages"></span></span></div>')


def _title_pages(pdf: Path, titles: list[str]) -> list[str]:
    """Page number of each contents entry in the first print ([] without PyMuPDF).

    Entries are matched in order against the opening text of each page, so a
    company name that also appears in an earlier table is not mistaken for its
    own detail page."""
    try:
        import pymupdf
    except ImportError:
        return []
    import re

    def norm(t: str) -> str:
        return re.sub(r"\s+", " ", t).strip().lower()

    with pymupdf.open(str(pdf)) as doc:
        heads = [norm(pg.get_text())[:400] for pg in doc]
    # The contents page lists every title itself; start matching after it.
    cur = next((i + 1 for i, h in enumerate(heads) if h.startswith("contents")), 0)
    out = []
    for title in titles:
        want = norm(title)
        hit = next((i for i in range(cur, len(heads)) if want and want in heads[i][:len(want) + 120]), None)
        if hit is None:
            out.append("")
            continue
        out.append(str(hit + 1))
        cur = hit
    return out


def _has_pymupdf() -> bool:
    try:
        import pymupdf  # noqa: F401
    except ImportError:
        return False
    return True


def back_cover_for(out_dir: Path) -> Path | None:
    """The page(s) appended after Research Methodology: the market's own
    _pipeline/pdf_back_cover.pdf, else config/pdf_back_cover.pdf for every market."""
    for cand in (Path(out_dir) / "_pipeline" / "pdf_back_cover.pdf", ROOT / "config" / "pdf_back_cover.pdf"):
        if cand.exists():
            return cand
    return None


def front_cover_for(out_dir: Path) -> Path | None:
    """The branded first page: the market's own _pipeline/front_cover.pdf,
    else config/front_cover.pdf for every market."""
    for cand in (Path(out_dir) / "_pipeline" / "front_cover.pdf", ROOT / "config" / "front_cover.pdf"):
        if cand.exists():
            return cand
    return None


def filled_front_cover(path: Path, title: str):
    """The cover page (a one-page PyMuPDF document) with its title placeholder
    ("xxxxxx") replaced by the market name in the same font and colour, and
    any old footer removed. Used by the PDF (as a page) and Word (as an image)."""
    import re

    import pymupdf

    d = pymupdf.open(str(path))
    if d.page_count > 1:
        d.select([0])
    pg = d[0]
    r = pg.rect
    slots = []
    for b in pg.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            for sp in ln["spans"]:
                if re.fullmatch(r"\s*x{3,}\s*", sp["text"], re.I):
                    slots.append(sp)
    pg.add_redact_annot(pymupdf.Rect(0, r.height - 40, r.width, r.height))
    for sp in slots:
        pg.add_redact_annot(pymupdf.Rect(sp["bbox"]))
    pg.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE,
                        graphics=pymupdf.PDF_REDACT_LINE_ART_NONE)
    for sp in slots:
        x0, y0, x1, y1 = sp["bbox"]
        c = sp["color"]
        color = ((c >> 16 & 255) / 255, (c >> 8 & 255) / 255, (c & 255) / 255)
        font = "tibo" if "bold" in sp["font"].lower() else "tiro"
        base = sp["origin"][1]          # the placeholder's own baseline
        mid = (x0 + x1) / 2             # ... and its centre
        room = 2 * min(mid, r.width - mid) - 60
        size = sp["size"]

        def width(t: str) -> float:
            return pymupdf.get_text_length(t, fontname=font, fontsize=size)

        def split(t: str) -> list[str]:
            if width(t) <= room:
                return [t]
            words = t.split()           # two balanced lines, the second ends on the baseline
            best = min(range(1, len(words)), key=lambda k: abs(width(" ".join(words[:k]))
                                                              - width(" ".join(words[k:]))))
            return [" ".join(words[:best]), " ".join(words[best:])]

        lines = split(title)
        while size > 9 and any(width(t) > room for t in lines):
            size -= 1
            lines = split(title)
        lead = size * 1.2
        for k, t in enumerate(lines):
            y = base - (len(lines) - 1 - k) * lead
            pg.insert_text((mid - width(t) / 2, y), t, fontname=font, fontsize=size, color=color)
    return d


def finish(pdf: Path, market: str, back_cover: Path | None, front_cover: Path | None = None) -> int:
    """Put the branded front cover first and the back cover last (their own old
    footers removed), then stamp one footer on every page but the front
    cover, so "Page X of Y" counts both covers -- the same numbering as Word."""
    import pymupdf

    doc = pymupdf.open(str(pdf))
    body = doc.page_count
    if back_cover:
        with pymupdf.open(str(back_cover)) as extra:
            doc.insert_pdf(extra)
        # Remove the cover's own old footer text (a stale "Page N of N");
        # the background artwork is left untouched.
        for pg in list(doc)[body:]:
            r = pg.rect
            pg.add_redact_annot(pymupdf.Rect(0, r.height - 40, r.width, r.height))
            pg.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE,
                                graphics=pymupdf.PDF_REDACT_LINE_ART_NONE)
    if front_cover:
        front = filled_front_cover(front_cover, market)
        doc.insert_pdf(front, start_at=0)
        front.close()
    total = doc.page_count
    grey = (0.39, 0.45, 0.55)
    left = f"Coherent Quadrant · {market}"
    for i, pg in enumerate(doc, 1):
        if front_cover and i == 1:
            continue                      # the branded cover carries no footer
        r = pg.rect
        y = r.height - 20
        pg.insert_text((28, y), left, fontsize=6, fontname="helv", color=grey)
        right = f"Page {i} of {total}"
        w = pymupdf.get_text_length(right, fontname="helv", fontsize=6)
        pg.insert_text((r.width - 28 - w, y), right, fontsize=6, fontname="helv", color=grey)
    doc.save(str(pdf) + ".tmp", garbage=3, deflate=True)
    doc.close()
    Path(str(pdf) + ".tmp").replace(pdf)
    return total


async def export(html: Path, pdf: Path, *, scale: float, stamp: bool = False,
                 page_offset: int = 0) -> tuple[int, str]:
    from patchright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 900})
        await page.goto(html.resolve().as_uri())
        await page.wait_for_timeout(1500)
        panels = await page.evaluate(EXPAND_JS)
        await page.evaluate(COVER_JS)
        await page.add_style_tag(content=PRINT_CSS)
        await page.emulate_media(media="screen")
        titles = await page.evaluate(TOC_JS, None)
        await page.wait_for_timeout(400)
        market = await page.evaluate(
            "() => (document.querySelector('.cv-market') || {}).textContent || ''")
        # With PyMuPDF the footer is stamped afterwards (finish), so the page
        # count includes an appended back cover; otherwise Chrome prints it.
        opts = dict(format="A4", print_background=True, scale=scale, prefer_css_page_size=True,
                    display_header_footer=not stamp, header_template="<span></span>",
                    footer_template=_footer(market))
        await page.pdf(path=str(pdf), **opts)
        # A front cover added afterwards moves every page on by page_offset.
        pages = [str(int(p) + page_offset) if p else "" for p in _title_pages(pdf, titles)]
        if pages:
            # Same layout, page numbers filled in.
            await page.evaluate(TOC_JS, pages)
            await page.wait_for_timeout(200)
            await page.pdf(path=str(pdf), **opts)
        await browser.close()
    return panels, market


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--market")
    ap.add_argument("--country", default="global")
    ap.add_argument("--html", help="report HTML (default: the market's <slug>_report.html)")
    ap.add_argument("--out", help="PDF path (default: next to the HTML, .pdf)")
    ap.add_argument("--scale", type=float, default=0.62)
    args = ap.parse_args()
    if args.html:
        html = Path(args.html)
    elif args.market:
        from vendor_intel.pipeline.web_expand import default_output_dir

        out_dir = Path(default_output_dir(args.market, args.country))
        html = out_dir / f"{out_dir.name}_report.html"
    else:
        ap.error("give --market or --html")
    if not html.exists():
        ap.error(f"report not found: {html}")
    pdf = Path(args.out) if args.out else html.with_suffix(".pdf")
    stamp = _has_pymupdf()
    front = front_cover_for(html.parent) if stamp else None
    panels, market = asyncio.run(export(html, pdf, scale=args.scale, stamp=stamp,
                                        page_offset=1 if front else 0))
    extra = ""
    if stamp:
        cover = back_cover_for(html.parent)
        total = finish(pdf, market, cover, front)
        extra = (f", {total} pages" + (", front cover" if front else "")
                 + (f", back cover {cover.name}" if cover else ""))
    print(f"wrote {pdf} ({panels} axis panels expanded{extra})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
