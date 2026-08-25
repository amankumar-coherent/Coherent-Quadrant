#!/usr/bin/env python3
"""Open (or regenerate) the Coherent Quadrant HTML UI from a quadrant JSON file.

Examples:
  .venv\\Scripts\\python.exe scripts\\open_quadrant_ui.py
  .venv\\Scripts\\python.exe scripts\\open_quadrant_ui.py --json output/quadrant/organic-milk-market_quadrant.json
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main() -> int:
    from vendor_intel.quadrant.html_report import write_report_from_json

    p = argparse.ArgumentParser(description="Open Coherent Quadrant HTML UI")
    p.add_argument(
        "--json",
        default="",
        help="Path to *_quadrant.json (default: newest under output/quadrant/)",
    )
    p.add_argument("--no-open", action="store_true", help="Write HTML only, do not open browser")
    args = p.parse_args()

    json_path = Path(args.json) if args.json else None
    if json_path is None or not str(args.json).strip():
        folder = ROOT / "output" / "quadrant"
        files = sorted(folder.glob("*_quadrant.json"), key=lambda x: x.stat().st_mtime, reverse=True)
        if not files:
            raise SystemExit(f"No *_quadrant.json found in {folder}")
        json_path = files[0]

    if not json_path.is_file():
        alt = ROOT / json_path
        if alt.is_file():
            json_path = alt
        else:
            raise SystemExit(f"JSON not found: {json_path}")

    html_path = write_report_from_json(json_path, open_browser=not args.no_open)
    print(f"UI: {html_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
