"""Step 7c: figure gaps -> disclosed figure / defensible estimate / gap."""
import json

from vendor_intel.pipeline import estimates as est

GAP = "Based on primary research, the company has not disclosed its exact employee count."
TASK = {"id": "t", "company": "Acme", "parameter": "Scale", "gap": GAP,
        "object": "its exact employee count", "findings": []}
TEXT = "The company reports 4 offices in 3 countries and 40 named enterprise clients."


def _est(**kw):
    r = {"n": 1, "metric": "employee count", "type": "estimated", "value": "approximately 100-150",
         "indicators": [{"fact": "4 offices", "source": "company website"},
                        {"fact": "40 named enterprise clients", "source": "company case studies"}],
         "basis": "its 4 offices and 40 named enterprise clients", "confidence": "high", "remaining": ""}
    r.update(kw)
    return r


def test_estimate_is_labelled_with_range_and_basis():
    d = est.decide(TASK, [_est()], TEXT, min_conf="medium")
    assert d["text"] == ("Based on primary research, the company's employee count can be estimated at approximately "
                         "100–150, derived from its 4 offices and 40 named enterprise clients.")
    rec = d["estimates"][0]
    # two indicators cap the confidence at medium whatever AI Mode claimed
    assert rec["value_type"] == "estimated" and rec["confidence"] == "medium"
    assert rec["source_type"] == "primary_research"


def test_never_a_number_without_a_basis():
    # a basis with no figure at all -> no estimate; a stated basis with figures
    # but no matching published fact -> published at low confidence only
    assert est.decide(TASK, [_est(indicators=[], basis="its strong regional presence")], TEXT) is None
    d = est.decide(TASK, [_est(indicators=[], basis="its 12 offices and 75 clients")], TEXT)
    assert d["estimates"][0]["confidence"] == "low"
    assert est.decide(TASK, [_est(basis="its strong brand")], TEXT) is None
    # modelled-estimate sites are not evidence, even when the report has no other figure
    bad = _est(indicators=[{"fact": "120 employees", "source": "ZoomInfo"},
                           {"fact": "4 offices", "source": "RocketReach profile"}], basis="its 120 employees")
    assert est.decide(TASK, [bad], "") is None
    assert est.decide(TASK, [_est(basis="its 4 offices per ZoomInfo")], TEXT) is None


def test_low_confidence_and_false_precision_not_published():
    one = _est(indicators=[{"fact": "4 offices", "source": "company website"}], basis="its 4 offices")
    assert est.decide(TASK, [one], TEXT, min_conf="medium") is None
    assert est.decide(TASK, [one], TEXT)["estimates"][0]["confidence"] == "low"  # default: low published
    assert est.decide(TASK, [_est(value="127")], TEXT) is None
    assert est.decide(TASK, [_est(value="about 150")], TEXT)["estimates"][0]["estimated_value"] == "150"


def test_disclosed_figure_needs_a_cited_number():
    ok = {"n": 1, "metric": "employee count", "type": "disclosed", "value": "250",
          "indicators": [{"fact": "250 employees", "source": "2025 annual report"}]}
    d = est.decide(TASK, [ok], TEXT)
    assert d["text"] == "Based on primary research, the company reports its employee count as 250."
    assert est.decide(TASK, [{**ok, "value": "300"}], TEXT) is None


def test_insufficient_is_last_fallback_and_proof_gaps_keep_their_sentence():
    d = est.decide(TASK, [{"n": 1, "type": "insufficient", "metric": "employee count"}], TEXT)
    assert d["text"] == ("Based on primary research, the company has not disclosed sufficient information to "
                         "support a reliable quantitative estimate for its employee count.")
    assert est.gap_object(d["text"]) == ""  # not re-asked on the next run
    proof = {**TASK, "object": "independently audited revenue and employee count",
             "gap": "Based on primary research, the company has not disclosed independently audited revenue "
                    "and employee count."}
    assert est.decide(proof, [{"n": 1, "type": "insufficient"}], TEXT) is None
    d = est.decide(proof, [_est()], TEXT)
    assert d["text"].startswith("Based on primary research, the company's employee count can be estimated") and "has not disclosed" not in d["text"]


def test_remaining_gap_reuses_only_the_gaps_words():
    task = {**TASK, "object": "its employee count or third-party audits of its workflow",
            "gap": "Based on primary research, the company has not disclosed its employee count or "
                   "third-party audits of its workflow."}
    d = est.decide(task, [_est(remaining="third-party audits of its workflow")], TEXT)
    assert d["text"].startswith("Based on primary research, the company's employee count can be estimated")
    # the estimate replaces the gap sentence whatever the leftover words are
    d = est.decide(task, [_est(remaining="customer satisfaction surveys")], TEXT)
    assert "has not disclosed" not in d["text"] and "employee count can be estimated" in d["text"]


def test_apply_rewrites_sidecars_once(tmp_path):
    side = {"Acme": {"x": {"parameters": {"Scale": {"score": 70, "evidence": [{"claim": TEXT}],
                                                    "assessed_on": f"The rating rests on its footprint. {GAP}"}}},
                     "y": {"parameters": {}}}}
    (tmp_path / "param_detail_prescored_a.json").write_text(json.dumps(side), encoding="utf-8")
    tid = est.task_id("Acme", "Scale", GAP)
    work = tmp_path / "_pipeline" / est.EST_DIR
    work.mkdir(parents=True)
    (work / est.ANSWERS).write_text(json.dumps({tid: {"results": [_est()], "asks": 1}}), encoding="utf-8")
    assert est.apply_estimates(tmp_path)["estimated"] == 1
    v = json.loads((tmp_path / "param_detail_prescored_a.json").read_text(encoding="utf-8"))["Acme"]["x"][
        "parameters"]["Scale"]
    assert "employee count can be estimated at approximately 100–150" in v["assessed_on"]
    assert "has not disclosed" not in v["assessed_on"] and len(v["estimates"]) == 1
    est.apply_estimates(tmp_path)  # second run: nothing left to replace
    v2 = json.loads((tmp_path / "param_detail_prescored_a.json").read_text(encoding="utf-8"))["Acme"]["x"][
        "parameters"]["Scale"]
    assert v2 == v
    assert est.verify_report([{"company": "Acme", "score_detail": {"x": {"parameters": {"Scale": v}}}}]) == []


ANSWER = """Calculation: ...
1 | annual revenue | estimated | $180–220 million | its 6,500 customers, 1,350 employees and 220 million invoices a year | Basware website | confidence high
2 | market share | estimated | 6–8% | its revenue against a global AP automation market size of $3.41 billion | press release | confidence high
2 | competitive win rate | insufficient | None | not published | newsroom | confidence low
"""
FACTS = [{"fact": "over 6,500 customers", "year": "2026", "source": "company website"},
         {"fact": "over 1,350 employees", "year": "2026", "source": "company website"},
         {"fact": "220 million invoices processed in 2023", "year": "2023", "source": "press release"}]


def test_plain_answer_parsed_and_judged():
    blocks = est.parse_blocks(ANSWER)
    assert [(b["n"], b["type"]) for b in blocks] == [(1, "estimated"), (2, "estimated"), (2, "insufficient")]
    rev = {**TASK, "object": "its annual revenue"}
    d = est.decide(rev, [est.to_result(b, FACTS) for b in blocks if b["n"] == 1], "")
    assert d["text"] == ("Based on primary research, the company's annual revenue can be estimated at approximately "
                         "$180–220 million, derived from its 6,500 customers, 1,350 employees and 220 million "
                         "invoices a year.")
    assert d["estimates"][0]["confidence"] == "high"
    share = {**TASK, "object": "its exact market share or competitive win rates"}
    d = est.decide(share, [est.to_result(b, FACTS) for b in blocks if b["n"] == 2], "")
    assert "market share can be estimated at approximately 6–8%" in d["text"]


def test_plain_answer_partly_estimated_keeps_the_gap():
    task = {**TASK, "object": "its annual revenue or growth rates",
            "gap": "Based on primary research, the company has not disclosed its annual revenue or growth rates."}
    blocks = est.parse_blocks(ANSWER.replace("2 | market share | estimated", "1 | growth rate | insufficient"))
    d = est.decide(task, [est.to_result(b, FACTS) for b in blocks if b["n"] == 1], "")
    assert d["text"].startswith("Based on primary research, the company's annual revenue can be estimated")


def test_market_share_estimated_and_values_read_cleanly():
    share = {**TASK, "object": "its market share",
             "gap": "Based on primary research, the company has not disclosed its market share."}
    d = est.decide(share, [_est(metric="market share", value="3-6%")], TEXT)
    assert "Based on primary research, the company's market share can be estimated at approximately 3–6%" in d["text"]
    assert est.clean_value("$180 million - $210 million", True) == "$180–210 million"
    assert est.clean_value("3% - 6% globally (higher in Europe)", True) == "3–6%"
    assert est.clean_value("€210M – €240M", True) == "€210–240M"


def test_summary_lines_go_to_the_gap_they_name():
    tasks = [{**TASK, "object": "its average contract value"}, {**TASK, "object": "its annual recurring revenue"}]
    blocks = [{"n": 1, "metric": "contract value"}, {"n": 2, "metric": "throughput"},
              {"n": 3, "metric": "annual recurring revenue (ARR)"}]
    got = est.assign_blocks(blocks, tasks)
    assert [b["metric"] for b in got[0]] == ["contract value"]
    assert [b["metric"] for b in got[1]] == ["annual recurring revenue (ARR)"]


def test_splits_and_performance_figures_estimated():
    split = {**TASK, "object": "the regional break-down of revenue"}
    r = _est(metric="regional break-down of revenue", value="35% Nordics / 40% Rest of Europe / 25% Americas & APAC")
    d = est.decide(split, [r], TEXT)
    assert "can be estimated at approximately 35% Nordics, 40% Rest of Europe and 25% Americas and APAC" in d["text"]
    rate = {**TASK, "object": "its touchless processing rate"}
    assert "touchless processing rate can be estimated at approximately 60–90%" in est.decide(
        rate, [_est(metric="touchless processing rate", value="60-90%")], TEXT)["text"]
    assert est.clean_value("59", True) == "" and est.clean_value("€100–166.67 million", True) == ""


def test_worded_estimate_for_a_gap_that_is_not_a_number():
    gap = ("Based on primary research, the company has not disclosed independent, third-party verified "
           "performance data validating these processing turnaround metrics across its entire customer base.")
    task = {**TASK, "gap": gap, "object": est.gap_object(gap)}
    answer = """...
1 | processing turnaround performance | fast for most approvals, in line with leading vendors | its conditional routing rules, mobile approvals and exception handling | company website | confidence medium
"""
    blocks = est.parse_worded(answer)
    rec = est.judge_worded(blocks[0], task)
    assert est.after_gap(gap, [rec]) == ("Based on primary research, the company's processing turnaround performance can be "
                                         "estimated as fast for most approvals, in line with leading vendors, based "
                                         "on its conditional routing rules, mobile approvals and exception handling.")
    # in words only, with a basis, never "unknown", never a research firm
    assert est.judge_worded({**blocks[0], "value": "about 2 days"}, task) is None
    assert est.judge_worded({**blocks[0], "value": "unknown"}, task) is None
    assert est.judge_worded({**blocks[0], "basis": ""}, task) is None
    assert est.judge_worded({**blocks[0], "sources": "MarketsandMarkets report"}, task) is None


def test_worded_estimate_rejects_non_estimates_and_keeps_figures_in_basis():
    gap = "Based on primary research, the company has not disclosed independent data on its turnaround."
    task = {**TASK, "gap": gap, "object": est.gap_object(gap)}
    r = {"n": 1, "metric": "turnaround", "type": "worded", "value": "completely unavailable for customers",
         "basis": "its over three thousand total global customers", "sources": "website", "confidence": "low"}
    assert est.judge_worded(r, task) is None
    ok = est.judge_worded({**r, "value": "fast for most approvals"}, task)
    assert ok["basis"] == "its over 3,000 total global customers"
import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _numeric_on(monkeypatch, request):
    """The numeric-estimate rules are tested with the switch on; the words-only default has its own test."""
    if "words_only_default" not in request.node.name:
        monkeypatch.setenv("QUADRANT_NUMERIC_ESTIMATES", "1")


def test_words_only_default_no_numeric_range(monkeypatch):
    monkeypatch.delenv("QUADRANT_NUMERIC_ESTIMATES", raising=False)
    assert not est.numeric_estimates_enabled()
    assert est.decide(TASK, [_est()], TEXT) is None  # a range is never published
    gap = "Based on primary research, the company has not disclosed its exact first-pass extraction accuracy rates."
    task = {**TASK, "gap": gap, "object": est.gap_object(gap)}
    blk = {"n": 1, "metric": "first-pass extraction accuracy rates", "type": "worded", "value": "high",
           "basis": "its 6,500 customers", "sources": "website", "confidence": "medium"}
    rec = est.judge_worded(blk, task)
    assert est.after_gap(gap, [rec]).endswith(
        "Based on primary research, the company's first-pass extraction accuracy rates can be estimated as high, "
        "based on its 6,500 customers.")
    assert est.judge_worded({**blk, "value": "85-96.5%"}, task) is None


def test_tone_step_leaves_estimate_sentences_alone():
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from primary_research_wording import to_primary

    t = ("The rating rests on its footprint. Based on primary research, the company's published data can be "
         "estimated as no evidence of limits, based on its 6,500 customers.")
    assert to_primary(t) == t
