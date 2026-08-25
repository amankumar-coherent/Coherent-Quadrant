"""Market-agnostic Coherent Quadrant labeling and description layer.

Axis titles and the 10 scoring parameters are already generated per market by
axis_define.py (an LLM refines an industry baseline into market-specific X/Y
titles and parameters). This module only turns those two axis titles into the
four quadrant sub-labels and descriptions — it is the single source of truth
shared by the HTML report (html_report.py) and the Streamlit browser
(ui/quadrant_view.py), replacing what used to be two copies of the same list.

Scoring, thresholds, and quadrant assignment are untouched — this is
presentation-layer wording only.
"""
from __future__ import annotations

QUADRANT_NAMES = ("Leaders", "Challengers", "Trailblazers", "Emerging Players")

# quadrant -> (sub-label template, description).
#
# Sub-label templates use {x}/{y}, filled in with THIS market's own axis
# titles (from axis_define.py) — e.g. "Strong LNG Asset & Operations
# Strength, Strong Commercial & Portfolio Scale" for LNG, "Strong Product &
# Technology Strength, Strong Commercial & Portfolio Scale" for smartwatches.
#
# Descriptions are intentionally left market-agnostic (no axis names, no
# industry nouns) so the same four sentences read naturally across all
# ~1,000 markets instead of leaking one market's vocabulary into another's.
_TEMPLATES: dict[str, tuple[str, str]] = {
    "Leaders": (
        "Strong {x}, Strong {y}",
        "Established, scalable brands with strong capabilities, proven market "
        "adoption, and broad commercial reach.",
    ),
    "Challengers": (
        "Strong {y}, Developing {x}",
        "Brands with strong market reach and commercial presence, while "
        "continuing to expand their capabilities and product depth.",
    ),
    "Trailblazers": (
        "Strong {x}, Focused {y}",
        "Innovative brands with advanced capabilities and differentiated "
        "offerings, with opportunities to broaden their market reach.",
    ),
    "Emerging Players": (
        "Focused {x}, Focused {y}",
        "Focused brands developing specialized capabilities and offerings "
        "around specific applications or customer needs.",
    ),
}

# Used only if a market's axis titles are missing/blank (should not happen in
# normal operation — axis_define.py always returns both).
FALLBACK_X = "Capability & Operations Strength"
FALLBACK_Y = "Commercial & Market Scale"

# Disparaging descriptors the product spec calls out. Checked against our own
# static template wording only (see build_quadrant_explain) — never against a
# market's LLM-authored axis/parameter names, which may legitimately contain
# a word like "low" (e.g. "Low-Carbon Intensity") without describing a
# company as weak.
_BANNED_WORDS = (
    "low",
    "lower",
    "weak",
    "poor",
    "limited",
    "inferior",
    "underdeveloped",
    "small player",
)


def generate_quadrant_labels(x_name: str, y_name: str) -> dict[str, str]:
    """Sub-labels ('Strong X, Developing Y', ...) for each quadrant, using this market's own axis titles."""
    x = (x_name or "").strip() or FALLBACK_X
    y = (y_name or "").strip() or FALLBACK_Y
    return {quad: tpl.format(x=x, y=y) for quad, (tpl, _body) in _TEMPLATES.items()}


def generate_quadrant_descriptions() -> dict[str, str]:
    """Long-form quadrant descriptions, identical across every market by design."""
    return {quad: body for quad, (_tpl, body) in _TEMPLATES.items()}


def validate_quadrant_language(text: str) -> list[str]:
    """Return any banned/disparaging words found in the given text (whole-word match)."""
    words = set(text.lower().replace(",", " ").replace(".", " ").split())
    hits = [w for w in _BANNED_WORDS if w in words]
    if "small player" in text.lower():
        hits.append("small player")
    return hits


def build_quadrant_explain(x_name: str, y_name: str) -> list[tuple[str, str, str]]:
    """Return (quadrant_name, sub_label, description) for all four quadrants, in display order.

    Validates the static template wording (not the market-supplied axis
    names) against the banned-word list on every call, so an accidental
    regression in _TEMPLATES fails loudly instead of shipping disparaging
    copy into a report.
    """
    labels = generate_quadrant_labels(x_name, y_name)
    descriptions = generate_quadrant_descriptions()
    out: list[tuple[str, str, str]] = []
    for quad in QUADRANT_NAMES:
        tpl, body = _TEMPLATES[quad]
        hits = validate_quadrant_language(f"{tpl} {body}")
        if hits:
            raise ValueError(
                f"Quadrant template for {quad!r} contains disparaging language: {hits}"
            )
        out.append((quad, labels[quad], descriptions[quad]))
    return out
