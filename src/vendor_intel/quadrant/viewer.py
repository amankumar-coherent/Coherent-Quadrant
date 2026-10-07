"""Interactive Coherent Quadrant report (the design the owner signed off on).

The page is one self-contained HTML file: the market's quadrant.json is
embedded in a <script type="application/json"> block and rendered in the
browser (chart, Top 20 with score breakdowns, Other Noticeable Player table
with search/filter, per-parameter evidence, methodology). Nothing in the
template is market-specific; every label comes from the payload.
"""
from __future__ import annotations

import json
from pathlib import Path

from vendor_intel.quadrant.quadrant_language import AXIS_Y_TITLE, x_axis_title

TEMPLATE = Path(__file__).with_name("templates") / "quadrant_viewer.html"
PLACEHOLDER = "__QUADRANT_DATA__"


def render_viewer(payload: dict) -> str:
    data = dict(payload)
    crit = dict(data.get("criteria") or {})
    # The internal keys stay "Product Strength"/"Business Strength"; the page
    # shows the Capability titles chosen by player type.
    titles = data.get("axis_titles") or {"x": x_axis_title(data), "y": AXIS_Y_TITLE}
    crit["axis_labels"] = {"x": titles["x"], "y": titles["y"]}
    data["criteria"] = crit
    # "</" inside a JSON string would close the script element early.
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = TEMPLATE.read_text(encoding="utf-8")
    if html.count(PLACEHOLDER) != 1:
        raise RuntimeError(f"{TEMPLATE} must contain {PLACEHOLDER} exactly once")
    return _inline_assets(html).replace(PLACEHOLDER, blob)


_MIME = {".png": "image/png", ".webp": "image/webp", ".avif": "image/avif", ".svg": "image/svg+xml"}


def _inline_assets(html: str) -> str:
    """Embed the brand images as data URIs so the report is one offline file."""
    import base64
    import re

    def sub(m: re.Match) -> str:
        f = TEMPLATE.parent / "assets" / m.group(1)
        mime = _MIME.get(f.suffix.lower(), "application/octet-stream")
        return f"data:{mime};base64," + base64.b64encode(f.read_bytes()).decode("ascii")

    return re.sub(r"__ASSET:([\w.\-]+)__", sub, html)


def write_viewer(payload: dict, path: Path) -> Path:
    path = Path(path)
    path.write_text(render_viewer(payload), encoding="utf-8")
    return path
