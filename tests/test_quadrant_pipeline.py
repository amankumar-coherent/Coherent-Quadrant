import json

from vendor_intel.pipeline.quadrant_pipeline import (
    dedupe_companies,
    domain_of,
    evidence_gaps,
    load_evidence,
    rank_score,
)

X = ["a", "b"]
Y = ["c", "d"]


def _p(score, reason="why"):
    return {"score": score, "evidence": [{"claim": "x"}], "assessed_on": reason}


def test_domain_of_registrable_and_platform():
    assert domain_of("https://shop.goodflip.in") == "goodflip.in"
    assert domain_of("www.acme.co.uk/about") == "acme.co.uk"
    assert domain_of("https://www.linkedin.com/company/acme") == ""
    assert domain_of("Not publicly disclosed") == ""


def test_dedupe_merges_shared_domain_and_name_variants():
    verified = [
        {"Company": "Abbott Laboratories", "Website": "https://www.abbott.com"},
        {"Company": "Abbott Diabetes Care Inc.", "Website": "abbott.com",
         "Headquarters": "Alameda, USA"},
        {"Company": "Alertgy Inc.", "Website": ""},
        {"Company": "Alertgy, Inc.", "Website": ""},
        {"Company": "Dexcom, Inc.", "Website": "dexcom.com"},
    ]
    reps, groups = dedupe_companies(verified, prefer={"Abbott Laboratories"})
    assert sorted(reps) == ["Abbott Laboratories", "Alertgy Inc.", "Dexcom, Inc."]
    assert groups["Abbott Laboratories"] == ["Abbott Diabetes Care Inc.", "Abbott Laboratories"]


def test_dedupe_never_merges_on_a_platform_domain():
    verified = [
        {"Company": "Acme Sensors", "Website": "https://linkedin.com/company/acme"},
        {"Company": "Zeta Devices", "Website": "https://linkedin.com/company/zeta"},
    ]
    reps, _ = dedupe_companies(verified)
    assert len(reps) == 2


def test_gaps_split_missing_from_missing_reasoning():
    ev = {"Co": {"x": {"a": _p(80), "b": _p(70, reason="")}, "y": {"c": _p(60)}}}
    gaps = evidence_gaps(ev, ["Co", "New"], X, Y)
    assert gaps["Co"] == {"missing": ["d"], "no_reasoning": ["b"]}
    assert gaps["New"]["missing"] == X + Y


def test_load_evidence_prefers_copy_with_reasoning(tmp_path):
    (tmp_path / "param_detail_prescored_a.json").write_text(json.dumps(
        {"Co": {"x": {"parameters": {"a": {"score": 90, "evidence": []}}}, "y": {}}}))
    (tmp_path / "param_detail_prescored_b.json").write_text(json.dumps(
        {"Co": {"x": {"parameters": {"a": _p(88)}}, "y": {}}}))
    ev = load_evidence(tmp_path)
    assert ev["Co"]["x"]["a"]["score"] == 88
    assert ev["Co"]["x"]["a"]["assessed_on"] == "why"


def test_rank_prefers_full_evidence_then_overall_only():
    ev = {"Full": {"x": {"a": _p(80), "b": _p(60)}, "y": {"c": _p(90), "d": _p(70)}}}
    overall = {"Tail": {"overall": 55}}
    assert rank_score("Full", ev, overall, X, Y) == 75
    assert rank_score("Tail", ev, overall, X, Y) == 55
    assert rank_score("Nothing", ev, overall, X, Y) is None
