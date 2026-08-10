"""Coherent Quadrant — matrix rollup, industry select, schema, KB grounding."""
from __future__ import annotations

from vendor_intel.quadrant.criteria_catalog import (
    get_category_features,
    list_leaf_categories,
    load_industry_catalog,
)
from vendor_intel.quadrant.industry_select import select_industry
from vendor_intel.quadrant.matrix_rollup import (
    feature_contribution,
    rollup_axis,
    scale_to_100,
    weighted_question_average,
)
from vendor_intel.quadrant.qa_scorer import answer_question
from vendor_intel.quadrant.rating_map import (
    assign_quadrant,
    assign_quadrants_half_median,
    assign_tiers_relative,
    overall_to_tier,
    sub_avg_to_rating,
)
from vendor_intel.quadrant.schema import CoherentQuadrantPayload, QuadrantBrand, ScorecardRow


def test_catalog_loads_medical_devices():
    cats = list_leaf_categories()
    assert ("Healthcare", "Medical Devices") in cats
    feats = get_category_features("Healthcare", "Medical Devices")
    assert len(feats["x"]) == 5
    assert len(feats["y"]) == 5
    assert "Regulatory & Quality Compliance" in feats["x"]
    assert "Geographic Expansion" in feats["y"]


def test_industry_select_dental_to_medical_devices():
    sel = select_industry("Africa dental equipment market")
    assert sel["industry_category"] == "Medical Devices"
    assert sel["industry_group"] == "Healthcare"


def test_industry_select_organic_milk_to_food():
    sel = select_industry("Organic milk market brand positioning")
    assert sel["industry_category"] == "Food and Beverages"


def test_weighted_question_average_vendor1_solution_portfolio():
    # Vendor Evaluation Matrix: scores 7, 5, 6 with weights 0.3, 0.3, 0.4 → 6.0
    avg = weighted_question_average([7, 5, 6], [0.3, 0.3, 0.4])
    assert abs(avg - 6.0) < 1e-9
    contrib = feature_contribution(0.3, avg)
    assert abs(contrib - 0.18) < 1e-9


def test_rollup_matches_vendor1_solution_capability():
    """Reproduce Vendor 1 X-axis overall 0.5275 from Solution Capability sheet."""
    # Feature weights from Criteria sheet
    feature_weights = [0.30, 0.20, 0.20, 0.15, 0.15]
    # Question scores + weights from Solution Capability sheet (Vendor 1)
    q_scores = [
        [7, 5, 6],   # Solution Portfolio → 6.0 → 0.18
        [4, 3, 3],   # Innovation → 3.4 → 0.068
        [4, 5, 7],   # Flexibility → 5.2 → 0.104
        [7, 6, 4],   # Scalability → 5.8 → 0.087
        [8, 5, 4],   # Support → 5.9 → 0.0885
    ]
    q_weights = [
        [0.4, 0.3, 0.3] if False else [0.3, 0.3, 0.4],  # portfolio uses 0.3/0.3/0.4
        [0.4, 0.3, 0.3],
        [0.4, 0.3, 0.3],
        [0.4, 0.3, 0.3],
        [0.4, 0.3, 0.3],
    ]
    # Fix portfolio weights explicitly
    q_weights[0] = [0.3, 0.3, 0.4]

    result = rollup_axis(
        feature_weights=feature_weights,
        feature_question_scores=q_scores,
        question_weights=q_weights,
    )
    assert abs(result["axis_overall"] - 0.5275) < 1e-3
    assert result["score_0_100"] == scale_to_100(0.5275)


def test_rollup_matches_vendor1_business_excellence():
    """Reproduce Vendor 1 Y-axis overall ~0.649 from Business Excellence sheet."""
    feature_weights = [0.25, 0.25, 0.20, 0.15, 0.15]
    # Sheet order: Industry Expertise, Global Presence, Market Reputation, GTM, Financial
    # But Criteria sheet order is: Industry Expertise, Global Presence, GTM, Market Reputation, Financial
    # Vendor Rating Y header: Industry Expertise | Global Presence | GTM | Market Reputation | Financial
    # Looking at Business Excellence sheet row order vs Vendor Rating...
    # BE sheet: Expertise, Global, Market Reputation, GTM, Financial
    # Vendor Rating Y: Expertise 0.1625, Global 0.1475, GTM 0.15, MarketRep 0.081, Financial 0.108
    # Wait - Vendor Rating columns: Industry Expertise || Global Presence & Reach || GTM Strategy || Market Reputation || Financial
    # Contributions: 0.1625, 0.1475, 0.15, 0.081, 0.108 → sum 0.649
    # But BE sheet order has Market Reputation before GTM with contribs 0.15 and 0.081
    # Looking at BE sheet again:
    # Expertise → 6.5 * 0.25 = 0.1625
    # Global → 5.9 * 0.25 = 0.1475
    # Market Reputation → 7.5 * 0.20 = 0.15  (feature weight 0.2 in sheet row 13)
    # GTM → 5.4 * 0.15 = 0.081
    # Financial → 7.2 * 0.15 = 0.108
    # So sheet uses Market Reputation weight 0.20 and GTM 0.15 — opposite of Criteria sheet labels!
    # Criteria said: GTM 0.20, Market Reputation 0.15
    # The Solution/Business sheets' blank "weight" rows are the source of truth for rollup demo.
    feature_weights = [0.25, 0.25, 0.20, 0.15, 0.15]  # Expertise, Global, MarketRep, GTM, Financial
    q_scores = [
        [8, 3, 8],  # Expertise → 6.5
        [8, 7, 2],  # Global → 5.9
        [6, 8, 9],  # Market Reputation → 7.5
        [3, 8, 6],  # GTM → 5.4
        [9, 3, 9],  # Financial → 7.2
    ]
    q_weights = [[0.4, 0.3, 0.3]] * 5
    result = rollup_axis(
        feature_weights=feature_weights,
        feature_question_scores=q_scores,
        question_weights=q_weights,
    )
    assert abs(result["axis_overall"] - 0.649) < 1e-3


def test_rating_and_quadrant_mapping():
    assert sub_avg_to_rating(9.0) == "very-high"
    assert sub_avg_to_rating(7.5) == "high"
    assert sub_avg_to_rating(5.5) == "average"
    assert sub_avg_to_rating(3.5) == "low"
    assert sub_avg_to_rating(1.0) == "very-low"
    assert assign_quadrant(80, 80) == "Leaders"
    assert assign_quadrant(80, 20) == "Trailblazers"
    assert assign_quadrant(20, 80) == "Challengers"
    assert assign_quadrant(20, 20) == "Emerging Players"
    assert overall_to_tier(90) == "Tier 1"
    assert overall_to_tier(75) == "Tier 2"
    assert overall_to_tier(50) == "Tier 3"


def test_assign_quadrants_half_median_fills_all_four():
    # Correlated X≈Y cohort — global median would only fill Leaders + Emerging
    xs = [45, 47, 49, 51, 51, 65, 74, 75, 84, 85, 90, 45]
    ys = [41, 46, 47, 44, 55, 63, 77, 73, 79, 84, 86, 43]
    quads, mid_x, mid_y = assign_quadrants_half_median(xs, ys)
    assert mid_x > 0 and mid_y > 0
    assert "Leaders" in quads
    assert "Emerging Players" in quads
    assert "Challengers" in quads
    assert "Trailblazers" in quads

    # 12 brands → 4 / 4 / 4 by overall rank
    overalls = [60, 59, 57, 55, 54, 54, 52, 51, 50, 44, 42, 42]
    tiers = assign_tiers_relative(overalls)
    assert tiers.count("Tier 1") == 4
    assert tiers.count("Tier 2") == 4
    assert tiers.count("Tier 3") == 4
    assert tiers[0] == "Tier 1"  # highest
    assert tiers[-1] == "Tier 3"  # lowest


def test_chart_offsets_stretch_spreads_cohort():
    from vendor_intel.quadrant.rating_map import chart_offsets_absolute

    xs = [45, 47, 51, 65, 74, 75, 84, 85, 90]
    ys = [41, 46, 44, 63, 77, 73, 79, 84, 86]
    coords, mx, my = chart_offsets_absolute(
        xs, ys, stretch=True, mid_x=65, mid_y=63, mode="rank"
    )
    lefts = [c[1] for c in coords]
    tops = [c[0] for c in coords]
    assert max(lefts) - min(lefts) >= 60
    assert max(tops) - min(tops) >= 50
    assert lefts[-1] > lefts[0]
    assert tops[-1] < tops[0]
    assert abs(mx - 50) < 1 or 40 <= mx <= 60
    assert 40 <= my <= 60



def test_schema_cmi_enums():
    brand = QuadrantBrand(
        brand="Acme",
        quadrant="Leaders",
        execution=89,
        innovation=92,
        tier="Tier 1",
        overall=91,
        revenue="$1.18 B",
        yoy_growth="+11.4%",
        top_strength="Trust",
    )
    row = ScorecardRow(
        brand="Acme",
        axis="Solution Capability",
        criterion="Product Portfolio Breadth",
        rating="high",
    )
    payload = CoherentQuadrantPayload(
        market="dental equipment",
        industry_category="Medical Devices",
        brands=[brand],
        scorecard=[row],
    )
    d = payload.to_cmi_dict()
    assert d["schema_version"] == "cmi-quadrant-v1"
    assert d["brands"][0]["quadrant"] == "Leaders"
    assert d["scorecard"][0]["rating"] == "high"


def test_empty_kb_uses_model_knowledge_floor():
    """Thin KB must not force scores of 1–2; heuristic floors to mid-band."""
    ans = answer_question(
        "Does the vendor hold FDA certification?",
        0.4,
        {"brand": "EmptyCo", "domain": "", "chunks": []},
    )
    assert ans.grounding in ("insufficient", "model_knowledge", "partial")
    assert ans.score >= 4


def test_clamp_does_not_cap_model_knowledge_high_scores():
    from vendor_intel.quadrant.qa_scorer import _clamp_answer_fields

    ans = _clamp_answer_fields(
        question="Portfolio breadth?",
        weight=0.4,
        raw={
            "score": 9,
            "answer": "Global flagship brand with full portfolio.",
            "grounding": "model_knowledge",
            "evidence_snippets": ["Known premium smartphone OEM"],
        },
        score_floor=4,
        allow_model_knowledge=True,
    )
    assert ans.score == 9
    assert ans.grounding == "model_knowledge"


def test_clamp_floors_low_scores_when_kb_missing():
    from vendor_intel.quadrant.qa_scorer import _clamp_answer_fields

    ans = _clamp_answer_fields(
        question="Portfolio breadth?",
        weight=0.4,
        raw={"score": 2, "answer": "No KB", "grounding": "insufficient"},
        score_floor=4,
        allow_model_knowledge=True,
    )
    assert ans.score >= 4


def test_catalog_yaml_has_all_groups():
    catalog = load_industry_catalog()
    groups = catalog.get("groups") or {}
    assert "Healthcare" in groups
    assert "Chemical and Materials" in groups
    assert "ICT, Automation, Semiconductor" in groups
    assert "Others" in groups
    assert "Food and Beverages" in groups["Others"]


# ── half-median tie handling ──────────────────────────────────────────────
def test_all_four_cells_fill_when_the_median_sits_on_a_tie_block():
    """Regression: Emerging Players came out empty on a real 134-brand run.

    37 of the 66 low-X brands scored Y=40 — the score_floor value every
    unevidenced brand lands on. The half's median WAS 40, so all 37 ties passed
    `y >= median` into the high-Y cell and the low-Y cell got nothing.
    """
    from vendor_intel.quadrant.rating_map import assign_quadrants_half_median

    execs = [40] * 66 + [70] * 68             # a clean low/high X split
    innovs = ([40] * 37 + list(range(41, 70))) + ([60] * 34 + list(range(61, 95)))
    quads, _, _ = assign_quadrants_half_median(execs, innovs)

    from collections import Counter
    counts = Counter(quads)
    for cell in ("Leaders", "Trailblazers", "Challengers", "Emerging Players"):
        assert counts[cell] > 0, f"{cell} is empty: {dict(counts)}"


def test_rank_split_matches_median_split_on_distinct_values():
    """With no ties the new rank split must reproduce the old median behaviour."""
    from vendor_intel.quadrant.rating_map import assign_quadrants_half_median

    execs = [10, 20, 80, 90]
    innovs = [10, 90, 10, 90]
    quads, _, _ = assign_quadrants_half_median(execs, innovs)
    assert quads == ["Emerging Players", "Challengers", "Trailblazers", "Leaders"]


def test_each_half_splits_evenly():
    from collections import Counter

    from vendor_intel.quadrant.rating_map import assign_quadrants_half_median

    execs = [40] * 50 + [70] * 50
    innovs = [40] * 100                      # every Y identical — the hardest case
    quads, _, _ = assign_quadrants_half_median(execs, innovs)
    c = Counter(quads)
    assert c["Challengers"] == c["Emerging Players"] == 25
    assert c["Leaders"] == c["Trailblazers"] == 25
