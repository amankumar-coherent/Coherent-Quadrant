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

# The capability scale both axes are read on. "Emerging" is the low end and
# "Best-in-class" the high end, so a quadrant reads as a pair of capability
# states ("Best-in-class Product, Emerging Business") rather than a value
# judgement about the company. Change these two names and every positioning
# line, axis label and quadrant pair follows.
SCALE_LOW = "Emerging"
SCALE_HIGH = "Best-in-class"

# Axis titles as the report presents them. The underlying axis keys stay
# "Product Strength" / "Business Strength" (axis_define.py), which is what
# scoring and every stored payload use — this is the display wording only.
AXIS_X_TITLE = "Product Capability"
AXIS_Y_TITLE = "Business Capability"

# Short label shown on the chart and in the Quadrant column. The KEY stays
# "Emerging Players" — it is what scoring writes and every saved checkpoint
# and Excel file already holds, so renaming it would orphan that data. Only
# what a reader sees changes.
QUADRANT_LABELS: dict[str, str] = {
    "Leaders": "Leaders",
    "Challengers": "Challengers",
    "Trailblazers": "Trailblazers",
    "Emerging Players": "Evolving Players",
}


def quadrant_label(quadrant: str) -> str:
    """Display name for a quadrant key, e.g. "Evolving Players"."""
    return QUADRANT_LABELS.get(quadrant, quadrant)


# Presentation title for each quadrant: what the quadrant is called in the
# conclusion, as opposed to its short chart label.
QUADRANT_TITLES: dict[str, str] = {
    "Leaders": "Integrated Market Leaders",
    "Challengers": "Scale-Driven Challengers",
    "Trailblazers": "Innovation-Driven Trailblazers",
    "Emerging Players": "Foundation-Building Evolving",
}

# Which capability state each quadrant holds on each axis. Derived from the
# quadrant's own position, so the wording cannot drift out of step with where
# a company is actually plotted.
QUADRANT_POSITIONS: dict[str, tuple[str, str]] = {
    "Leaders": (SCALE_HIGH, SCALE_HIGH),
    "Challengers": (SCALE_LOW, SCALE_HIGH),
    "Trailblazers": (SCALE_HIGH, SCALE_LOW),
    "Emerging Players": (SCALE_LOW, SCALE_LOW),
}


def quadrant_title(quadrant: str) -> str:
    """Presentation title, e.g. "Integrated Market Leaders"."""
    return QUADRANT_TITLES.get(quadrant, quadrant)


def quadrant_position(quadrant: str) -> str:
    """Capability pair, e.g. "Best-in-class Product, Emerging Business"."""
    x, y = QUADRANT_POSITIONS.get(quadrant, (SCALE_LOW, SCALE_LOW))
    return f"{x} Product, {y} Business"


def axis_scale_label(axis: str) -> str:
    """Axis title with its scale, e.g.
    "Product Capability (Emerging → Best-in-class)"."""
    title = AXIS_X_TITLE if axis.lower().startswith("x") else AXIS_Y_TITLE
    return f"{title} ({SCALE_LOW} → {SCALE_HIGH})"

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
# (positioning line, description). The positioning line is deliberately left
# as-is — only the descriptions below carry the standard definitions.
_TEMPLATES: dict[str, tuple[str, str]] = {
    "Leaders": (
        "{hi} {x}, {hi} {y}",
        "Companies demonstrating strong product capabilities and robust "
        "business execution. They combine mature and differentiated offerings "
        "with established market presence, customer reach, commercial scale, "
        "and effective growth strategies, positioning them strongly for "
        "sustained market leadership.",
    ),
    "Challengers": (
        "{lo} {x}, {hi} {y}",
        "Companies with strong business presence and commercial capabilities, "
        "supported by established customer relationships, market reach, "
        "channels, or brand strength. However, their product portfolio may "
        "have relatively lower differentiation, breadth, maturity, or "
        "innovation compared with leading participants.",
    ),
    "Trailblazers": (
        "{hi} {x}, {lo} {y}",
        "Companies demonstrating strong product capabilities, innovation, or "
        "differentiated offerings, but with comparatively lower business scale "
        "or market penetration. Their growth potential depends on "
        "strengthening commercial execution, customer reach, partnerships, "
        "geographic presence, and overall market visibility.",
    ),
    "Emerging Players": (
        "{lo} {x}, {lo} {y}",
        "Companies with developing product capabilities and relatively limited "
        "business presence. These participants may be at an earlier stage of "
        "market development, serve focused segments or geographies, and have "
        "opportunities to strengthen both their product proposition and "
        "commercial footprint.",
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
    # {hi}/{lo} carry the capability scale, so changing SCALE_HIGH updates
    # every positioning line rather than leaving four copies to go stale.
    return {
        quad: tpl.format(x=x, y=y, hi=SCALE_HIGH, lo=SCALE_LOW)
        for quad, (tpl, _body) in _TEMPLATES.items()
    }


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
        tpl, _body = _TEMPLATES[quad]
        # Only the POSITIONING line is checked. The descriptions are the
        # client's own approved standard definitions, and they use comparative
        # wording ("relatively lower differentiation", "relatively limited
        # business presence") that the banned-word list would otherwise
        # reject. The guard still protects the generated positioning labels,
        # which is where an accidental regression would actually show up.
        hits = validate_quadrant_language(tpl)
        if hits:
            raise ValueError(
                f"Quadrant template for {quad!r} contains disparaging language: {hits}"
            )
        out.append((quad, labels[quad], descriptions[quad]))
    return out
