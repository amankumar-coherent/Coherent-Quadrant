import json

from vendor_intel.pipeline import company_facts as cf
from vendor_intel.pipeline import company_status as cs


def _write(path, obj):
    path.write_text(json.dumps(obj), encoding="utf-8")


def test_owner_label_only_for_real_acquisition_still_trading():
    ok = {"acquired": True, "acquirer": "TAQA", "year": "2023", "today": "subsidiary",
          "note": "TAQA acquired the remaining 49% stake from CGG in 2023."}
    assert cf.owner_entry("ARGAS", ok)["owner"] == "TAQA"
    # Set up as a subsidiary is ownership, not an acquisition.
    assert cf.owner_entry("IMC", dict(ok, note="IMC was established in 2016 as a wholly owned "
                                                "subsidiary of AGS, which acquired its assets.")) is None
    assert cf.owner_entry("IMC", dict(ok, note="IMC was established as a subsidiary of AGS.")) is None
    # The buyer is not "acquired"; absorbed companies get no label.
    assert cf.owner_entry("TGS", dict(ok, today="independent")) is None
    assert cf.owner_entry("Echo", dict(ok, today="absorbed")) is None


def test_auto_review_excludes_absorbed_renamed_twin_and_phantom(tmp_path):
    _write(tmp_path / cf.OWNERSHIP_FILE, {
        "Echo Geophysical": {"acquired": True, "acquirer": "SEI", "today": "absorbed",
                             "note": "Acquired by SEI in 2013 and rebranded as Summit Geophysical."},
        "ASIAN Oilfield Services Ltd.": {"acquired": True, "acquirer": "Oilmax", "today": "subsidiary",
                                         "note": "Oilmax acquired a majority stake, later rebranded as Asian Energy Services Ltd."},
        "Asian Energy Services Limited": {"acquired": True, "acquirer": "Oilmax", "today": "subsidiary",
                                          "note": "Acquired by Oilmax in 2016."},
    })
    _write(tmp_path / cf.IDENTITY_FILE, {"HGS": {"exists": "false", "evidence": "Domain belongs to Hundsun."},
                                         "Sterling": {"exists": "true", "operating": "active",
                                                      "website_is_theirs": "false"}})
    pool = ["Echo Geophysical", "ASIAN Oilfield Services Ltd.", "Asian Energy Services Limited", "HGS", "Sterling"]
    rev = cf.auto_review(tmp_path, pool)
    assert {e["company"] for e in rev["exclude"]} == {"Echo Geophysical", "ASIAN Oilfield Services Ltd.", "HGS"}
    assert [e["company"] for e in rev["ownership"]] == ["Asian Energy Services Limited"]


def test_analyst_review_wins_over_automatic(tmp_path):
    _write(tmp_path / cf.AUTO_REVIEW_FILE, {
        "exclude": [{"company": "GeoTek Korea", "reason": "auto"}],
        "ownership": [{"company": "ARGAS", "owner": "Auto Owner"}]})
    _write(tmp_path / cs.REVIEW_FILE, {
        "keep": [{"company": "GeoTek Korea"}],
        "ownership": [{"company": "ARGAS", "owner": "TAQA"}]})
    rev = cs.load_review(tmp_path)
    assert rev["exclude"] == []
    assert [r["owner"] for r in rev["ownership"]] == ["TAQA"]


def test_empty_owner_clears_label(tmp_path):
    ck = tmp_path / "ckpt.json"
    _write(ck, {"data": {"verified": [{"company": "TGS", "parent_owner": "PGS",
                                       "ownership_relation": "acquired_by"}]}})
    cs.apply_ownership_corrections(ck, [{"company": "TGS", "owner": ""}])
    row = json.loads(ck.read_text(encoding="utf-8"))["data"]["verified"][0]
    assert "parent_owner" not in row


def test_tidy_claim_absence_only():
    na = cf.NOT_AVAILABLE
    assert cf.tidy_claim("None available. No specific client projects, named algorithms (such as FWI "
                         "or RTM) could be found in public records.") == na
    assert cf.tidy_claim("No references or case studies exist in corporate literature regarding FWI.") == na
    # A finding after the prefix stays, without the prefix.
    assert cf.tidy_claim("None available. Federal filings reference AUV surveys.") == \
        "Federal filings reference AUV surveys."
    # A reason clause, a contrast or a figure means there is a finding.
    for keep in ("No SLAs could be found, as public documentation confirms Aspen Echos is software.",
                 "No FWI papers exist, but the firm ran 12 PSDM projects.",
                 "EGS emphasizes shallow systems rather than deep exploration algorithms."):
        assert cf.tidy_claim(keep) == keep


def test_tidy_evidence_collapses_per_parameter(tmp_path):
    _write(tmp_path / "param_detail_prescored_a.json", {"Co": {"x": {"parameters": {
        "A": {"evidence": [{"claim": "No case studies exist."}, {"claim": "Filings list AUV work."}]},
        "B": {"evidence": [{"claim": "No price sheets exist."}, {"claim": "No bid data exists."}]}}}}})
    cf.tidy_evidence(tmp_path)
    p = json.loads((tmp_path / "param_detail_prescored_a.json").read_text(encoding="utf-8"))["Co"]["x"]["parameters"]
    assert [e["claim"] for e in p["A"]["evidence"]] == ["Filings list AUV work."]
    assert [e["claim"] for e in p["B"]["evidence"]] == [cf.NOT_AVAILABLE]
    assert not cf.gap_bullets({"brands": [{"brand": "Co", "score_detail": {"x": {"parameters": p}}}]})


def test_citation_leftovers_removed():
    assert cf.tidy_claim("Data from the deepwater Gulf of Mexico [.") == "Data from the deepwater Gulf of Mexico."
    assert cf.tidy_claim("Replaces depth migration workflows. DUG Technology +1") == \
        "Replaces depth migration workflows."
    assert cf.tidy_claim("Uses 4,400+ cores and 480TB of storage.") == "Uses 4,400+ cores and 480TB of storage."


def test_owner_wording_follows_deal_age():
    assert cf.ownership_relation("1998", today_year=2026) == "subsidiary_of"
    assert cf.ownership_relation("2025", today_year=2026) == "acquired_by"
    assert cf.ownership_relation("", today_year=2026) == "subsidiary_of"


def test_old_owner_reads_subsidiary_in_company_column(tmp_path):
    from vendor_intel.pipeline.expand_quadrant_score import _company_column

    ck = tmp_path / "ckpt.json"
    _write(ck, {"data": {"verified": [{"company": "PT Patra Nusa Data"}]}})
    cs.apply_ownership_corrections(ck, [{"company": "PT Patra Nusa Data", "owner": "PT Elnusa Tbk", "year": "1998"}])
    r = json.loads(ck.read_text(encoding="utf-8"))["data"]["verified"][0]
    meta = {k: r[k] for k in ("parent_owner", "ownership_relation", "ownership_confidence")}
    assert _company_column({"Company": "PT Patra Nusa Data", "_meta": meta}) == \
        "PT Patra Nusa Data (subsidiary of PT Elnusa Tbk)"


def test_scope_out_excluded_adjacent_kept_off_chart(tmp_path):
    _write(tmp_path / cf.SCOPE_FILE, {"Echo": {"scope": "adjacent", "reason": "Site-survey acquisition."},
                                      "Nope": {"scope": "out", "reason": "Software reseller."},
                                      "DUG": {"scope": "core", "reason": "Seismic imaging."}})
    rev = cf.auto_review(tmp_path, ["Echo", "Nope", "DUG"])
    assert [e["company"] for e in rev["exclude"]] == ["Nope"]
    assert [e["company"] for e in rev["adjacent"]] == ["Echo"]
    cf.write_auto_review(tmp_path, rev)
    assert cs.chart_ineligible(tmp_path) == {cs.norm_name("Echo")}
    # The analyst can put a company back in scope.
    _write(tmp_path / cs.REVIEW_FILE, {"scope": [{"company": "Echo", "scope": "core"}]})
    assert cs.chart_ineligible(tmp_path) == set()


def test_refill_never_puts_ineligible_company_on_chart():
    xy = {"L1": (90, 90), "L2": (85, 88), "C1": (20, 90), "T1": (90, 20),
          "E1": (15, 15), "E2": (18, 12), "T2": (80, 30), "C2": (30, 80)}
    top = cs.refill_top_by_quadrant(["L1", "C1", "T1"], xy, 4, eligible=lambda n: n != "E1")
    assert "E1" not in top and "E2" in top


def test_legacy_brand_shown_under_current_name(tmp_path):
    from vendor_intel.pipeline.expand_quadrant_score import _brand_column, _company_column

    _write(tmp_path / cf.OWNERSHIP_FILE, {"Schlumberger Technology Corporation": {
        "acquired": False, "today": "independent", "current_name": "SLB", "brand_status": "legacy"}})
    rev = cf.auto_review(tmp_path, ["Schlumberger Technology Corporation"])
    assert rev["display"][0]["current_name"] == "SLB"
    ck = tmp_path / "ckpt.json"
    _write(ck, {"data": {"verified": [{"company": "Schlumberger Technology Corporation",
                                       "brand_name": "WesternGeco"}]}})
    cs.apply_display_corrections(ck, rev["display"])
    r = json.loads(ck.read_text(encoding="utf-8"))["data"]["verified"][0]
    row = {"Company": "Schlumberger Technology Corporation", "Brand": "WesternGeco",
           "_meta": {k: r[k] for k in ("current_company", "brand_label")}}
    assert _company_column(row) == "SLB"
    assert _brand_column(row) == "SLB (WesternGeco legacy)"


def test_employee_review_bullets_removed(tmp_path):
    _write(tmp_path / "param_detail_prescored_a.json", {"Co": {"y": {"parameters": {
        "Customer Feedback": {"evidence": [{"claim": "Glassdoor shows a 4.2 employee rating."},
                                           {"claim": "Repeat contracts with Aramco since 2019."}]},
        "Peer Standing": {"evidence": [{"claim": "Rated 4.0 on AmbitionBox by staff."}]}}}}})
    cf.tidy_evidence(tmp_path)
    p = json.loads((tmp_path / "param_detail_prescored_a.json").read_text(encoding="utf-8"))["Co"]["y"]["parameters"]
    assert [e["claim"] for e in p["Customer Feedback"]["evidence"]] == ["Repeat contracts with Aramco since 2019."]
    assert [e["claim"] for e in p["Peer Standing"]["evidence"]] == [cf.NOT_AVAILABLE]
    assert cf.cites_employee_reviews("Indeed, the firm grew.") is False


def test_buyer_is_never_removed_or_labelled():
    ctrack = {"acquired": True, "acquirer": "Ctrack", "year": "2024", "today": "absorbed",
              "note": "The fleet management division under the previous name Inseego UK Limited was acquired by Ctrack in 2024."}
    mi = {"acquired": True, "acquirer": "Moving Intelligence", "today": "absorbed",
          "note": "Dutch firm Moving Intelligence acquired Phantom Tracking Systems in 2021."}
    bought = {"acquired": True, "acquirer": "Smith System", "today": "absorbed",
              "note": "Brightmile was acquired by Smith System in 2025 and rebranded as 5Keys Engage."}
    assert cf.is_buyer("Ctrack UK Limited", ctrack) and cf.is_buyer("Moving Intelligence Ltd", mi)
    assert not cf.is_buyer("Brightmile", bought)


def test_research_publisher_bullets_removed(tmp_path):
    _write(tmp_path / "param_detail_prescored_a.json", {"Co": {"y": {"parameters": {
        "Market Share": {"evidence": [{"claim": "Grand View Research identifies Co as a key player."},
                                      {"claim": "Co tracks 40,000 UK vehicles."}]}}}}})
    cf.tidy_evidence(tmp_path)
    p = json.loads((tmp_path / "param_detail_prescored_a.json").read_text(encoding="utf-8"))
    assert [e["claim"] for e in p["Co"]["y"]["parameters"]["Market Share"]["evidence"]] == \
        ["Co tracks 40,000 UK vehicles."]


def test_name_variant_is_not_a_legacy_brand(tmp_path):
    _write(tmp_path / cf.OWNERSHIP_FILE, {"Ctrack UK Limited": {
        "acquired": False, "today": "independent", "current_name": "Ctrack", "brand_status": "legacy"}})
    assert cf.auto_review(tmp_path, ["Ctrack UK Limited"])["display"] == []
    ck = tmp_path / "ckpt.json"
    _write(ck, {"data": {"verified": [{"company": "Ctrack UK Limited", "current_company": "Ctrack",
                                       "brand_label": "Ctrack (Ctrack legacy)"}]}})
    cs.apply_display_corrections(ck, [])          # stale display from an earlier run is cleared
    row = json.loads(ck.read_text(encoding="utf-8"))["data"]["verified"][0]
    assert "brand_label" not in row and "current_company" not in row


def test_markdown_links_flattened():
    assert cf.tidy_claim("Listed according to [UK Find a Tender](Stotles) records.") == \
        "Listed according to UK Find a Tender (Stotles) records."
    assert cf.tidy_claim("See [the case study](https://example.com/x) for details.") == \
        "See the case study for details."


def test_chip_after_not_available_removed():
    assert cf.tidy_claim("Not available Webfleet +1") == cf.NOT_AVAILABLE


def test_foreign_branch_excluded_in_single_country_run(tmp_path):
    _write(tmp_path / cf.HQ_FILE, {
        "Transpoco Limited": {"hq": "Dublin, Ireland", "in_country": "false", "evidence": "Global HQ in Dublin."},
        "Cubo Solutions Limited": {"hq": "Manchester, United Kingdom", "in_country": "true"},
        "Unknown Co": {"hq": "", "in_country": "unknown"}})
    pool = ["Transpoco Limited", "Cubo Solutions Limited", "Unknown Co"]
    assert [e["company"] for e in cf.auto_review(tmp_path, pool, country="united kingdom")["exclude"]] == ["Transpoco Limited"]
    assert cf.auto_review(tmp_path, pool)["exclude"] == []          # global run: not applied


def test_footnote_markers_and_raw_links_are_removed():
    from vendor_intel.pipeline.company_facts import clean_artifacts
    assert clean_artifacts("It had 83,000 vehicles [1.23, 1.26].") == "It had 83,000 vehicles."
    assert clean_artifacts("Clients include Stannah and VPS [https://fleetservicegb.co.uk/].") == \
        "Clients include Stannah and VPS."
    assert clean_artifacts("according to the Prolius Official Profile (https://www.prolius.com/about).") == \
        "according to the Prolius Official Profile."
    # a real bracketed note stays
    assert clean_artifacts("Revenue rose (to £84.0m) in 2025.") == "Revenue rose (to £84.0m) in 2025."


def test_modelled_estimate_sites_are_not_evidence():
    from vendor_intel.pipeline.company_facts import cites_estimate_site
    assert cites_estimate_site("An annual revenue estimate of $600,000, as reported by RocketReach.")
    assert not cites_estimate_site("Companies House accounts report turnover of £2.1m.")


def test_scope_prompt_applies_main_product_test():
    from vendor_intel.pipeline.company_facts import scope_prompt
    p = scope_prompt("Any Market", "definition")
    assert "main product" in p and "add-on" in p
    assert "If unsure, answer core" not in p


def test_invalid_source_bullets_dropped_before_gap_fill(tmp_path):
    import json
    from vendor_intel.pipeline.company_facts import drop_invalid_sources
    side = tmp_path / "param_detail_prescored_x.json"
    side.write_text(json.dumps({"Acme": {"x": {"parameters": {}}, "y": {"parameters": {
        "Revenue": {"score": 60, "assessed_on": "a", "evidence": [
            {"claim": "Revenue of 7,697,444 according to GlobalDatabase.com."}]},
        "Partners": {"score": 70, "assessed_on": "b", "evidence": [
            {"claim": "Raised funding, as tracked by Tracxn."}, {"claim": "Partner of Geotab."}]}}}}}),
        encoding="utf-8")
    assert drop_invalid_sources(tmp_path) == 2
    y = json.loads(side.read_text(encoding="utf-8"))["Acme"]["y"]["parameters"]
    assert y["Revenue"]["evidence"] == []          # empty -> step 5 re-asks it
    assert y["Partners"]["evidence"] == [{"claim": "Partner of Geotab."}]


def test_bare_source_chip_after_last_sentence_removed():
    from vendor_intel.pipeline.company_facts import clean_artifacts
    assert clean_artifacts("It has not disclosed profitability figures. Tracxn") == \
        "It has not disclosed profitability figures."
    assert clean_artifacts("Revenue rose 12%. Quartix Technologies Plc") == "Revenue rose 12%."
    s = "The company serves UK fleets. It won the 2025 award."
    assert clean_artifacts(s) == s


def test_source_chip_between_sentences_removed():
    from vendor_intel.pipeline.company_facts import clean_artifacts
    assert clean_artifacts("It has regional prominence. Grand View Research +2 Based on primary research, "
                           "the company has not disclosed its share.") == \
        "It has regional prominence. Based on primary research, the company has not disclosed its share."


def test_area_shard_splits_countries(monkeypatch):
    from vendor_intel.pipeline.geo_rotation import all_countries_by_coverage, area_shard
    countries = all_countries_by_coverage([])
    monkeypatch.setenv("GEO_AREA_SHARD", "1/4")
    a = area_shard(countries)
    monkeypatch.setenv("GEO_AREA_SHARD", "2/4")
    b = area_shard(countries)
    assert a and b and not set(a) & set(b)
    monkeypatch.delenv("GEO_AREA_SHARD")
    assert area_shard(countries) == countries
