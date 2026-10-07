"""Operating-status answers, analyst review exclusions/corrections, chart refill."""
import json

from vendor_intel.pipeline import company_status as cs


def test_only_explicit_non_active_or_review_excludes(tmp_path):
    cs.save_status(tmp_path, {
        "Live Co": {"status": "active", "note": ""},
        "Gone Co Inc.": {"status": "defunct", "note": "Liquidated in 2019."},
    })
    (tmp_path / cs.REVIEW_FILE).write_text(json.dumps(
        {"exclude": [{"company": "Absorbed AS", "reason": "Acquired by Big Co."}]}), encoding="utf-8")
    bad = cs.inactive_companies(tmp_path)
    assert cs.is_inactive("Gone Co", bad)          # legal suffix ignored
    assert cs.is_inactive("Absorbed AS", bad)
    assert not cs.is_inactive("Live Co", bad)
    assert not cs.is_inactive("Never Asked Ltd", bad)   # no answer is not evidence


def test_check_status_parses_and_skips_answered():
    calls = []

    def ask(system, user, label):
        calls.append(user)
        return {"results": [{"name": "B Corp", "operating_status": "acquired",
                             "status_note": "Bought by C.", "successor": "C"}]}

    st = cs.check_status(ask, "M", "", [{"name": "A"}, {"name": "B Corp"}],
                         {"A": {"status": "active"}})
    assert st["B Corp"]["status"] == "acquired" and len(calls) == 1 and '"A"' not in calls[0]


def test_corrections_apply_once_and_report_misses(tmp_path):
    side = tmp_path / "param_detail_prescored_x.json"
    side.write_text(json.dumps({"Mint Seismic": {"y": {"parameters": {"P": {
        "score": 70, "assessed_on": "ok",
        "evidence": [{"claim": 'paper "X in Underground Structures".'}]}}}}}), encoding="utf-8")
    corr = [{"company": "Mint Seismic", "find": "in Underground Structures", "replace": "in Hong Kong"},
            {"company": "Mint Seismic", "find": "not there", "replace": "y"}]
    rows = cs.apply_corrections(tmp_path, corr)
    assert rows[0]["changed"] == 1 and rows[1]["changed"] == 0 and not rows[1]["already_applied"]
    assert "in Hong Kong" in side.read_text(encoding="utf-8")
    again = cs.apply_corrections(tmp_path, corr)
    assert again[0]["changed"] == 0 and again[0]["already_applied"]


def test_refill_keeps_survivors_and_fills_short_quadrant():
    xy = {"L1": (90, 90), "L2": (85, 88), "C1": (20, 90), "T1": (90, 20),
          "E1": (15, 15), "E2": (18, 12), "T2": (80, 30), "C2": (30, 80)}
    top = cs.refill_top_by_quadrant(["L1", "C1", "T1"], xy, 4)
    assert {"L1", "C1", "T1"} <= set(top) and len(top) == 4
    assert "E1" in top  # the Emerging slot goes to that quadrant's best


def test_refill_rebalances_when_median_shift_overfills_a_quadrant():
    # L2 and L1 both sit in Leaders now; with 1 slot per quadrant the weaker
    # Leader leaves and the empty Emerging slot takes its best company.
    xy = {"L1": (90, 90), "L2": (85, 88), "C1": (20, 90), "T1": (90, 20),
          "E1": (15, 15), "E2": (18, 12), "T2": (80, 30), "C2": (30, 80)}
    top = cs.refill_top_by_quadrant(["L1", "L2", "C1", "T1"], xy, 4)
    assert set(top) == {"L1", "C1", "T1", "E1"}
    assert set(cs.refill_top_by_quadrant(top, xy, 4)) == set(top)  # balanced = unchanged


def test_hq_correction_sets_checkpoint_row_once(tmp_path):
    ck = tmp_path / "ckpt.json"
    ck.write_text(json.dumps({"data": {"verified": [
        {"company": "CImaGeo", "headquarters": "Rio de Janeiro, Brazil"}, {"company": "Other"}]}}),
        encoding="utf-8")
    fix = [{"company": "CImaGeo", "headquarters": "Natal, Brazil"}]
    assert cs.apply_hq_corrections(ck, fix)[0]["changed"] == 1
    rows = json.loads(ck.read_text(encoding="utf-8"))["data"]["verified"]
    assert rows[0]["headquarters"] == "Natal, Brazil" and "headquarters" not in rows[1]
    assert cs.apply_hq_corrections(ck, fix)[0]["changed"] == 0


def test_bare_or_renamed_answers_are_kept_and_flagged(tmp_path):
    cs.save_status(tmp_path, {
        "Bare Co": {"status": "defunct", "note": ""},
        "Old Name Ltd": {"status": "renamed", "note": "Renamed in 2020.", "successor": "New Name Ltd"},
        "Gone Co": {"status": "exited", "note": "Left the market in 2021."},
    })
    bad = cs.inactive_companies(tmp_path)
    assert not cs.is_inactive("Bare Co", bad) and not cs.is_inactive("Old Name Ltd", bad)
    assert cs.is_inactive("Gone Co", bad)
    flagged = cs.status_needs_review(tmp_path)
    assert set(flagged) == {"Bare Co", "Old Name Ltd"} and "New Name Ltd" in flagged["Old Name Ltd"]


def test_empty_replace_of_whole_claim_removes_the_bullet(tmp_path):
    side = tmp_path / "param_detail_prescored_x.json"
    side.write_text(json.dumps({"PND": {"x": {"parameters": {"P": {
        "score": 70, "assessed_on": "why",
        "evidence": [{"claim": "Unsupported study."}, {"claim": "Kept finding."}]}}}}}), encoding="utf-8")
    cs.apply_corrections(tmp_path, [{"company": "PND", "find": "Unsupported study.", "replace": ""}])
    ev = json.loads(side.read_text(encoding="utf-8"))["PND"]["x"]["parameters"]["P"]["evidence"]
    assert ev == [{"claim": "Kept finding."}]


def test_ownership_review_labels_company_column(tmp_path):
    from vendor_intel.pipeline.expand_quadrant_score import _company_column

    ck = tmp_path / "ckpt.json"
    ck.write_text(json.dumps({"data": {"verified": [{"company": "ARGAS", "ownership": "Independent",
                                                     "ownership_confidence": "low"}]}}), encoding="utf-8")
    fix = [{"company": "ARGAS", "owner": "TAQA", "year": str(__import__("datetime").date.today().year)},
           {"company": "Missing Co", "owner": "X"}]
    rows = cs.apply_ownership_corrections(ck, fix)
    assert rows[0]["changed"] and rows[0]["matched"] and not rows[1]["matched"]
    r = json.loads(ck.read_text(encoding="utf-8"))["data"]["verified"][0]
    assert r["parent_owner"] == "TAQA" and r["ownership_confidence"] == "high"
    assert not cs.apply_ownership_corrections(ck, fix)[0]["changed"]  # idempotent
    meta = {k: r[k] for k in ("parent_owner", "ownership_relation", "ownership_confidence")}
    assert _company_column({"Company": "ARGAS", "_meta": meta}) == "ARGAS (acquired by TAQA)"
    assert _company_column({"Company": "ARGAS", "_meta": {}}) == "ARGAS"


def test_wording_collapses_gap_bullets_to_one_not_available(tmp_path):
    side = tmp_path / "param_detail_prescored_x.json"
    side.write_text(json.dumps({"Echo": {"x": {"parameters": {"Quality": {"evidence": [
        {"claim": "None available. No projects could be found in public records."},
        {"claim": "No documented case studies mention FWI leadership."},
        {"claim": "Federal filings reference AUV surveys."}]}}}}}), encoding="utf-8")
    mapping = {"None available. No projects could be found in public records.": "Not available",
               "No documented case studies mention FWI leadership.": "Not available"}
    assert cs.apply_wording(tmp_path, mapping) == 2
    ev = json.loads(side.read_text(encoding="utf-8"))["Echo"]["x"]["parameters"]["Quality"]["evidence"]
    # A real finding exists, so no "Not available" beside it.
    assert [e["claim"] for e in ev] == ["Federal filings reference AUV surveys."]


def test_wording_keeps_one_not_available_when_nothing_was_found(tmp_path):
    side = tmp_path / "param_detail_prescored_x.json"
    side.write_text(json.dumps({"Echo": {"y": {"parameters": {"Cost": {"evidence": [
        {"claim": "No price sheets exist."}, {"claim": "No bid references exist."}]}}}}}),
        encoding="utf-8")
    cs.apply_wording(tmp_path, {"No price sheets exist.": "Not available",
                                "No bid references exist.": "Not available"})
    ev = json.loads(side.read_text(encoding="utf-8"))["Echo"]["y"]["parameters"]["Cost"]["evidence"]
    assert [e["claim"] for e in ev] == ["Not available"]
