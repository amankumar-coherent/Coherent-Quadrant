"""Quick scorecard (all 5 parameters of an axis in ONE query) and the
5-per-quadrant Top 20 selection built on it."""
from vendor_intel.pipeline.quadrant_pipeline import quadrant_of, select_top_by_quadrant
from vendor_intel.quadrant.ai_mode_scorer import (
    build_axis_scorecard_query,
    parse_axis_scorecard,
)

P = ["Sensor Accuracy", "Wearability", "Regulatory Clearances", "Manufacturing", "Connectivity"]
DEFS = {p: f"how good the company is at {p.lower()}" for p in P}


def test_query_asks_for_every_parameter_in_one_prompt():
    q = build_axis_scorecard_query("Acme", "Product Capability", P, DEFS, market="M")
    assert "Product Capability scorecard" in q and "exactly 5 lines" in q
    assert all(f"{i}. {p} | Score: NN/100" in q for i, p in enumerate(P, 1))


def test_parses_numbered_lines_after_an_echo():
    q = build_axis_scorecard_query("Acme", "Product Capability", P, DEFS, market="M")
    answer = q + "\n" + "\n".join(
        f"{i}. {p} | Score: {70 + i}/100 | reason" for i, p in enumerate(P, 1))
    assert parse_axis_scorecard(answer, P, q) == {p: 70 + i for i, p in enumerate(P, 1)}


def test_parses_a_markdown_table_and_skips_missing():
    answer = ("| Parameter | Score |\n| Sensor Accuracy | 92/100 |\n"
              "| Wearability | 87 out of 100 |\n| Connectivity | 81/100 |")
    got = parse_axis_scorecard(answer, P)
    assert got == {"Sensor Accuracy": 92, "Wearability": 87, "Connectivity": 81}


def test_template_echo_alone_parses_nothing():
    q = build_axis_scorecard_query("Acme", "Product Capability", P, DEFS)
    assert parse_axis_scorecard(q, P) == {}


def test_top20_is_five_per_quadrant():
    # 40 companies spread over all four quadrants
    xy = {}
    for i in range(40):
        x = 80 + (i % 10) if i < 10 or 20 <= i < 30 else 40 + (i % 10)
        y = 80 + (i % 10) if i < 20 else 40 + (i % 10)
        xy[f"c{i:02d}"] = (float(x), float(y))
    top = select_top_by_quadrant(xy, 20)
    assert len(top) == 20
    xs = sorted(v[0] for v in xy.values()); ys = sorted(v[1] for v in xy.values())
    mx, my = (xs[19] + xs[20]) / 2, (ys[19] + ys[20]) / 2
    from collections import Counter
    split = Counter(quadrant_of(*xy[n], mx, my) for n in top)
    assert set(split.values()) == {5} and len(split) == 4


def test_short_quadrant_gives_its_slots_to_best_remaining():
    # no company is high-X/low-Y (Trailblazers empty)
    xy = {f"hi{i}": (90.0 - i, 90.0 - i) for i in range(15)}
    xy.update({f"lo{i}": (40.0 - i, 40.0 - i) for i in range(15)})
    top = select_top_by_quadrant(xy, 20)
    assert len(top) == 20 and len(set(top)) == 20


def test_small_pool_returns_everyone():
    xy = {"a": (80.0, 70.0), "b": (60.0, 96.0)}
    assert select_top_by_quadrant(xy, 20) == ["b", "a"]
