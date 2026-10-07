#!/usr/bin/env python3
"""Set each report's X-axis title from the market's own player type.

  Service Provider markets   -> "Service Capability"
  Solution Provider markets  -> "Technology Capability"
  everything else            -> "Product Capability" (unchanged)

The player type is read from the report's own classification
(criteria.relevance.keep_roles, decided at Step 0c), never from a market
name list. Only the displayed title changes: the internal axis key
("Product Strength") in the JSON is untouched, and company evidence text
is never edited (a lower-case "product capability" inside a claim is the
source's wording, not the axis title).

    .\\.venv\\Scripts\\python.exe scripts\\set_x_axis_title.py ^
        --folder "C:\\Users\\me\\Desktop\\Fire Market Quadrant" [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from vendor_intel.quadrant.quadrant_language import (  # noqa: E402
    AXIS_X_TITLE as DEFAULT_TITLE,
    x_axis_title,
)
# Evidence cells hold company text; the title swap must never reach inside them.
_EVIDENCE_CELL = re.compile(r'<td><div class="cq-ta-score-line">.*?</td>', re.S)


def x_title_for(payload: dict) -> str:
    return x_axis_title(payload)


def retitle(html: str, title: str) -> str:
    noun = title.split()[0]  # "Service" / "Technology"
    cells: list[str] = []

    def stash(m: re.Match) -> str:
        cells.append(m.group(0))
        return f"\x00{len(cells) - 1}\x00"

    body = _EVIDENCE_CELL.sub(stash, html)
    for old in (DEFAULT_TITLE, "Service Capability", "Technology Capability"):
        body = body.replace(old, title).replace(old.upper(), title.upper())
    body = re.sub(r"\b(?:product|service|technology) capabilities\b", f"{noun.lower()} capabilities", body)
    # The quadrant cards' own wording ("their product portfolio", "their
    # product proposition") follows the same player type.
    body = _EXPLAIN_GRID.sub(
        lambda m: re.sub(r"\b(?:product|service|technology) (portfolio|proposition|offerings?)\b",
                         lambda w: f"{noun.lower()} {w.group(1)}", m.group(0)), body)
    return re.sub(r"\x00(\d+)\x00", lambda m: cells[int(m.group(1))], body)


_EXPLAIN_GRID = re.compile(r'<div class="cq-explain-grid">.*?</div></div></div>', re.S)
_EXPLAIN_CARD = re.compile(r'<div class="cq-explain-card"[^>]*><h4>(.*?)</h4>'
                           r'<div class="cq-explain-sub">(.*?)</div><p>(.*?)</p></div>', re.S)


def quadrant_definitions(html: str) -> list[dict]:
    """The four "Understanding the Coherent Quadrant" cards exactly as the report shows them."""
    import html as html_lib

    from vendor_intel.quadrant.quadrant_language import QUADRANT_LABELS, QUADRANT_TITLES

    key_by_title = {v: k for k, v in QUADRANT_TITLES.items()}
    out = []
    for title, position, text in _EXPLAIN_CARD.findall(html):
        title = html_lib.unescape(title).strip()
        key = key_by_title.get(title, title)
        out.append({
            "quadrant": key,
            "chart_label": QUADRANT_LABELS.get(key, key),
            "title": title,
            "position": html_lib.unescape(position).strip(),
            "definition": html_lib.unescape(text).strip(),
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--folder", action="append", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    for folder in args.folder:
        for jp in sorted(Path(folder).glob("*_quadrant.json")):
            hp = jp.with_name(jp.name.replace("_quadrant.json", "_report.html"))
            payload = json.loads(jp.read_text(encoding="utf-8"))
            title = x_title_for(payload)
            html = hp.read_text(encoding="utf-8")
            new = retitle(html, title)
            changed = new != html
            # Record what the report displays, so the JSON carries the same
            # axis titles and quadrant definitions a reader of the HTML sees.
            defs = quadrant_definitions(new)
            want = {"axis_titles": {"x": title, "y": "Business Capability"}, "quadrant_definitions": defs}
            json_changed = any(payload.get(k) != v for k, v in want.items())
            payload.update(want)
            print(f"{title:22} html {'changed' if changed else 'unchanged':9} json "
                  f"{'changed' if json_changed else 'unchanged':9} defs={len(defs)} {hp.name}")
            if not args.dry_run:
                if changed:
                    hp.write_text(new, encoding="utf-8")
                if json_changed:
                    jp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
