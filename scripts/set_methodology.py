#!/usr/bin/env python3
"""Replace the Research Methodology panel in finished reports with the
current methodology text, and save the same text into each JSON as
"research_methodology".

Uses html_report.methodology_content(), so existing reports, the JSON and
future pipeline runs all carry identical wording. The X title comes from the
report's own "axis_titles" (Service / Technology / Product Capability).

    .\\.venv\\Scripts\\python.exe scripts\\set_methodology.py ^
        --folder "C:\\Users\\me\\Desktop\\Fire Market Quadrant" [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

_PANEL = re.compile(r'\n?<div class="panel">\s*<h2>Research Methodology</h2>.*?'
                    r'<p class="cq-method-footnote">.*?</p>\s*</div>\n?', re.S)


def main() -> int:
    from vendor_intel.quadrant.html_report import _methodology_panel, methodology_content
    from vendor_intel.quadrant.quadrant_language import AXIS_X_TITLE, AXIS_Y_TITLE

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--folder", action="append", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    for folder in args.folder:
        for jp in sorted(Path(folder).glob("*_quadrant.json")):
            hp = jp.with_name(jp.name.replace("_quadrant.json", "_report.html"))
            payload = json.loads(jp.read_text(encoding="utf-8"))
            titles = payload.get("axis_titles") or {}
            x, y = titles.get("x") or AXIS_X_TITLE, titles.get("y") or AXIS_Y_TITLE
            content = methodology_content(payload, x, y)
            html = hp.read_text(encoding="utf-8")
            if len(_PANEL.findall(html)) != 1:
                print(f"SKIPPED (methodology panel not found exactly once): {hp.name}")
                continue
            new_html = _PANEL.sub(lambda m: _methodology_panel(payload, x, y), html, count=1)
            json_changed = payload.get("research_methodology") != content
            payload["research_methodology"] = content
            print(f"{x:22} html {'changed' if new_html != html else 'same':7} "
                  f"json {'changed' if json_changed else 'same':7} {hp.name}")
            if not args.dry_run:
                if new_html != html:
                    hp.write_text(new_html, encoding="utf-8")
                if json_changed:
                    jp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
