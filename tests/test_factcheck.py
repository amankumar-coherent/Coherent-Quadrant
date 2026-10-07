"""Step 8a: which chart fact-check findings are applied automatically."""
from __future__ import annotations

import json
from pathlib import Path

from vendor_intel.pipeline import factcheck as fc

CLAIM = "The company reports 230 interoperability partners across 100 countries."


def _market(tmp: Path, rows: list[dict], findings: dict) -> Path:
    out = tmp / "m"
    (out / "_pipeline" / "factcheck").mkdir(parents=True)
    brands = []
    for r in rows:
        brands.append({"company": r["company"], "company_key": r["company"], "on_chart": r.get("on_chart", True),
                       "overall": 80, "hq_location": r.get("hq", "Espoo, Finland"),
                       "score_detail": {"x": {"parameters": {"P": {"evidence": [{"claim": c} for c in r["claims"]]}}},
                                        "y": {"parameters": {}}}})
    (out / "m_quadrant.json").write_text(json.dumps({"brands": brands}), encoding="utf-8")
    (out / "_pipeline" / "factcheck" / "findings.json").write_text(json.dumps(findings), encoding="utf-8")
    return out


def _status(**kw) -> dict:
    return {"operating": "active", "scope": "core", "owner": "", "hq": "", **kw}


def _claim(verdict="incorrect", corrected="", source="https://acme.com", note="", claim=CLAIM) -> dict:
    return {"parameter": "P", "claim": claim, "verdict": verdict, "corrected": corrected,
            "source": source, "note": note}


def test_small_fix_from_a_primary_source_is_applied(tmp_path):
    fixed = CLAIM.replace("230", "220")
    out = _market(tmp_path, [{"company": "Acme", "claims": [CLAIM]}],
                  {"Acme": {"status": _status(), "listed_hq": "Espoo, Finland", "claims": [_claim(corrected=fixed)]}})
    review = fc.build_review(out)
    assert review["corrections"] == [{**review["corrections"][0], "find": CLAIM, "replace": fixed}]


def test_directory_or_estimate_sources_are_not_applied(tmp_path):
    fixed = CLAIM.replace("230", "220")
    for src in ("SourceForge profile", "Tracxn company profile", "crunchbase.com/organization/acme"):
        out = _market(tmp_path / src.split()[0], [{"company": "Acme", "claims": [CLAIM]}],
                      {"Acme": {"status": _status(), "claims": [_claim(corrected=fixed, source=src)]}})
        assert fc.build_review(out)["corrections"] == [], src


def test_a_rewrite_or_a_contradicted_figure_is_not_applied(tmp_path):
    rewrite = "Acme was founded in 1985 and sells accounting software in Finland only."
    other = _claim(verdict="correct", claim="Acme lists 230 interoperability partners on its site.")
    out = _market(tmp_path, [{"company": "Acme", "claims": [CLAIM, other["claim"]]}],
                  {"Acme": {"status": _status(), "claims": [_claim(corrected=CLAIM.replace("230", "220")), other]}})
    assert fc.build_review(out)["corrections"] == []          # another check backs "230"
    out2 = _market(tmp_path / "b", [{"company": "Acme", "claims": [CLAIM]}],
                   {"Acme": {"status": _status(), "claims": [_claim(corrected=rewrite)]}})
    assert fc.build_review(out2)["corrections"] == []


def test_a_point_that_belongs_to_another_company_is_removed(tmp_path):
    out = _market(tmp_path, [{"company": "Acme", "claims": [CLAIM]}],
                  {"Acme": {"status": _status(), "claims": [_claim(note="This capability belongs to Other Corp.")]}})
    (c,) = fc.build_review(out)["corrections"]
    assert c["find"] == CLAIM and c["replace"] == ""


def test_status_scope_and_hq_decisions(tmp_path):
    rows = [{"company": n, "claims": []} for n in ("Gone", "Bought", "Side", "Moved")]
    out = _market(tmp_path, rows, {
        "Gone": {"status": _status(operating="liquidated", event="Liquidated in 2025.")},
        "Bought": {"status": _status(operating="acquired_absorbed", event="Acquired in 2025, trades as Bought.")},
        "Side": {"status": _status(scope="adjacent", scope_reason="AP is a minor module.")},
        "Moved": {"status": _status(hq="Austin, United States"), "listed_hq": "Helsinki, Finland"},
    })
    r = fc.build_review(out)
    assert [e["company"] for e in r["exclude"]] == ["Gone"]         # an acquired company that trades stays
    assert [(e["company"], e["scope"]) for e in r["scope"]] == [("Side", "adjacent")]
    assert [e["company"] for e in r["hq"]] == ["Moved"]


def test_same_country_hq_is_left_alone(tmp_path):
    out = _market(tmp_path, [{"company": "Acme", "claims": []}],
                  {"Acme": {"status": _status(hq="Courbevoie, France"), "listed_hq": "Puteaux, France"}})
    assert fc.build_review(out)["hq"] == []


def test_a_decision_stays_after_its_company_leaves_the_chart(tmp_path):
    out = _market(tmp_path, [{"company": "Side", "claims": []}],
                  {"Side": {"status": _status(scope="adjacent")}})
    fc.write_review(out / "_pipeline", fc.build_review(out))
    q = json.loads((out / "m_quadrant.json").read_text(encoding="utf-8"))
    q["brands"][0]["on_chart"] = False
    (out / "m_quadrant.json").write_text(json.dumps(q), encoding="utf-8")
    assert [e["company"] for e in fc.build_review(out)["scope"]] == ["Side"]
    assert fc.write_review(out / "_pipeline", fc.build_review(out)) is False   # stable: no re-run loop


def test_missing_lists_unchecked_chart_companies_by_plain_name(tmp_path):
    out = _market(tmp_path, [{"company": "Acme (acquired by Big Co)", "claims": [CLAIM]},
                             {"company": "Beta", "claims": [CLAIM]}],
                  {"Acme": {"status": _status(), "claims": [_claim(verdict="correct")]}})
    assert fc.missing(out) == ["Beta"]
