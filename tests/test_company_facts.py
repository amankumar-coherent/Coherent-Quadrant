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


def test_owner_names_splits_joint_owners():
    assert cf.owner_names("TPG and Corpay") == ["TPG and Corpay", "TPG", "Corpay"]
    assert cf.owner_names("Clearlake Capital & TA Associates")[1:] == ["Clearlake Capital", "TA Associates"]
    assert cf.owner_names("Basware") == ["Basware"]
    assert cf.owner_names("") == []


def test_listed_parent_matches_any_listed_co_owner(tmp_path):
    pool = ["AvidXchange, Inc.", "Corpay, Inc.", "Basware Oy", "Redmap Networks Pty Ltd"]
    assert cf.listed_parent("TPG and Corpay", "AvidXchange, Inc.", pool, tmp_path) == "Corpay, Inc."
    assert cf.listed_parent("Basware", "Redmap Networks Pty Ltd", pool, tmp_path) == "Basware Oy"
    # Investment firms not in the list never count; a single name with "&" stays whole.
    assert cf.listed_parent("Clearlake Capital & TA Associates", "Basware Oy", pool, tmp_path) is None
    assert cf.listed_parent("Johnson & Johnson", "X", ["Johnson & Johnson", "X"], tmp_path) == "Johnson & Johnson"
    # Never the company itself.
    assert cf.listed_parent("Corpay", "Corpay, Inc.", pool, tmp_path) is None


def test_listed_groups_joins_parent_with_all_its_units():
    pairs = [{"company": "Redmap", "parent": "Basware"}, {"company": "AP Matching", "parent": "Basware"},
             {"company": "AvidXchange", "parent": "Corpay"}]
    assert sorted(cf.listed_groups(pairs)) == [["AP Matching", "Basware", "Redmap"], ["AvidXchange", "Corpay"]]


def test_resolve_listed_groups_keeps_the_stronger(tmp_path):
    scores = {"Redmap": 70, "Basware": 85, "AvidXchange": 88, "Corpay": 74}
    pairs = [{"company": "Redmap", "parent": "Basware"}, {"company": "AvidXchange", "parent": "Corpay"}]
    out = cf.resolve_listed_groups(tmp_path, pairs, scores.get)
    assert sorted(d["company"] for d in out) == ["Corpay", "Redmap"]
    # The decision is saved: a later re-score does not swap the companies.
    scores.update({"Corpay": 95})
    assert sorted(d["company"] for d in cf.resolve_listed_groups(tmp_path, pairs, scores.get)) == ["Corpay", "Redmap"]


def test_resolve_listed_groups_tie_or_no_score_keeps_parent_and_honours_keep(tmp_path):
    pairs = [{"company": "Unit", "parent": "Parent"}]
    assert [d["company"] for d in cf.resolve_listed_groups(tmp_path / "a", pairs, lambda n: 80)] == ["Unit"]
    assert [d["company"] for d in cf.resolve_listed_groups(tmp_path / "b", pairs, lambda n: None)] == ["Unit"]
    assert cf.resolve_listed_groups(tmp_path / "c", pairs, lambda n: 80, keep={"unit"}) == []


def test_resolve_listed_groups_chart_company_beats_higher_quick_score(tmp_path):
    # The Leader on the chart stays even when its co-owner's quick score is higher.
    pairs = [{"company": "AvidXchange", "parent": "Corpay"}]
    scores = {"AvidXchange": 74, "Corpay": 80}
    out = cf.resolve_listed_groups(tmp_path, pairs, scores.get, on_chart=["AvidXchange"])
    assert [d["company"] for d in out] == ["Corpay"]


def test_neutral_sources_removes_third_party_names_and_keeps_the_finding():
    f = cf.neutral_sources
    assert f("The company reports 8 lines, according to its corporate profile on Made-in-China.") == \
        "The company reports 8 lines, according to its corporate profile."
    assert f("It offers enteric HPMC capsules, as detailed on IndiaMART.") == \
        "It offers enteric HPMC capsules, according to primary research."
    assert f("Fierce Pharma reported in October 2025 that the company announced a plant.") == \
        "According to primary research, in October 2025, the company announced a plant."
    assert f("The company profile document retrieved from Scribd states that it exports.") == \
        "The company profile document states that it exports."
    assert f("A review by CRISIL indicated growth.") == "A review indicated growth."
    # A real event and a company name are not sources.
    assert f("A partnership formed at CPHI China in Shanghai.") == "A partnership formed at CPHI China in Shanghai."
    assert f("Supplied by Acme Co., Ltd. to clients.") == "Supplied by Acme Co., Ltd. to clients."
    assert cf.neutral_source_label("Made-in-China Supplier Profile") == "Primary research"
    assert cf.neutral_source_label("Company website") == "Company website"


def test_norm_name_folds_accents_and_latin_legal_forms():
    from vendor_intel.pipeline.quadrant_pipeline import dedupe_companies, norm_name
    assert norm_name("Despurifil Ltda") == norm_name("Despurifil") == "despurifil"
    assert norm_name("Indústria X Eireli") == norm_name("Industria X") == "industria x"
    assert norm_name("Ecosan S/A") == "ecosan"
    rows = [{"name": "Despurifil Ltda", "website": "https://despurifil.com.br"},
            {"name": "Despurifil"},
            {"name": "Despurifil Indústria e Comércio Ltda", "website": "despurifil.com.br"}]
    assert len(dedupe_companies(rows)[0]) == 1


def test_buyback_by_own_ceo_is_not_an_owner_label():
    rec = {"acquired": True, "acquirer": "Luis Guilherme Pozzani da Rocha", "year": "2019", "today": "subsidiary",
           "note": "Fluid Brasil was fully acquired by its former CEO, Luis Guilherme Pozzani da Rocha, in 2019."}
    assert cf.owner_entry("Fluid Brasil Ltda.", rec) is None
    real = {"acquired": True, "acquirer": "Mann+Hummel", "year": "2012", "today": "subsidiary",
            "note": "Acquired by Mann+Hummel in 2012."}
    assert cf.owner_entry("Fluid Brasil Ltda.", real)["owner"] == "Mann+Hummel"


def test_division_or_regional_arm_pairs_with_its_listed_group(tmp_path):
    """No acquisition ever happened, yet "Thermo Fisher Scientific Australia" and "MilliporeSigma"
    are not separate competitors of Thermo Fisher / Merck KGaA: the ownership answer's `group`
    pairs them, and resolve_listed_groups keeps one company per group (owner 2026-10-28)."""
    pool = ["Thermo Fisher Scientific Inc.", "Thermo Fisher Scientific Australia Pty Ltd", "Merck KGaA",
            "MilliporeSigma", "Teknova Inc."]
    _write(tmp_path / cf.OWNERSHIP_FILE, {
        "Thermo Fisher Scientific Inc.": {"acquired": False, "group": ""},
        "Thermo Fisher Scientific Australia Pty Ltd": {"acquired": True, "acquirer": "Thermo Fisher Scientific",
                                                       "today": "subsidiary", "group": "Thermo Fisher Scientific"},
        "Merck KGaA": {"acquired": False, "group": ""},
        "MilliporeSigma": {"acquired": False, "group": "Merck KGaA", "note": "Life science business of Merck KGaA."},
        "Teknova Inc.": {"acquired": False, "group": ""},
    })
    pairs = cf.auto_review(tmp_path, pool)["listed_owner"]
    assert {"company": "MilliporeSigma", "parent": "Merck KGaA"} in pairs
    assert {"company": "Thermo Fisher Scientific Australia Pty Ltd",
            "parent": "Thermo Fisher Scientific Inc."} in pairs
    assert not any(p["company"] == "Teknova Inc." for p in pairs)
    # a group answer is never an owner label
    assert not any(o["company"] == "MilliporeSigma" for o in cf.auto_review(tmp_path, pool)["ownership"])


def test_same_brand_name_and_group_suffix_pair_with_the_listed_company(tmp_path):
    """The group answer varies ("Sartorius Group", or none); a shared distinctive name does not."""
    pool = ["Avantor Inc.", "Avantor Sciences, Inc.", "Sartorius AG", "Sartorius Stedim Biotech GmbH",
            "Alfa Tecnova, Inc.", "Bio-Rad Laboratories Inc.", "Bio Basic Inc."]
    _write(tmp_path / cf.OWNERSHIP_FILE, {"Sartorius Stedim Biotech GmbH": {"group": "Sartorius Group"}})
    pairs = cf.auto_review(tmp_path, pool)["listed_owner"]
    assert {"company": "Avantor Sciences, Inc.", "parent": "Avantor Inc."} in pairs
    assert {"company": "Sartorius Stedim Biotech GmbH", "parent": "Sartorius AG"} in pairs
    # a short or different first word never links ("Bio" is 3 letters; "Alfa Tecnova" is not "Alfa")
    assert not any(p["company"] in ("Bio Basic Inc.", "Alfa Tecnova, Inc.") for p in pairs)
    assert cf.listed_parent("Sartorius Group", "X", ["Sartorius AG"], tmp_path) == "Sartorius AG"


def test_scope_prompt_rejects_a_product_that_is_only_planned():
    """A planned product is not a product (owner 2026-10-28, Mozambique Fire Insurance):
    "fire insurance which is currently in its product pipeline" was answered core, and the
    company reached the chart on cover it does not yet sell."""
    p = cf.scope_prompt("Fire Insurance Market", "fire policies", own_product_line=True).lower()
    assert "only announced" in p and "pipeline or roadmap" in p
    assert "does not sell yet is not core" in p.replace("does not", "does not")
    # the default main-product test keeps its own wording
    assert "pipeline or roadmap" not in cf.scope_prompt("M", "d").lower()


def test_scope_prompt_sells_in_channel_counts_selling_not_making():
    """A market measured by the SALE of a product through a channel (owner 2026-10-29,
    Japan Fashion E-Commerce). Both maker tests call a marketplace that resells
    "adjacent"; here selling IS the qualifying activity, and the enablers are not."""
    p = cf.scope_prompt("Fashion E-commerce Market", "online sale of apparel",
                        sells_in_channel=True).lower()
    assert "companies that sell" in p
    assert "whether it makes them itself or buys them to resell" in p
    assert "only one category of a much wider assortment" in p
    # the client's exclusions: enablers, offline-only, non-category goods. The enabler
    # test is "who does it sell TO", not "does it let others sell" -- a consumer
    # marketplace lets others sell and is still this market's channel (2026-10-29).
    for kw in ("marketplace software licensed to merchants", "payments", "logistics",
               "only through other channels"):
        assert kw in p, kw
    # the maker tests keep their own wording
    assert "buys them to resell" not in cf.scope_prompt("M", "d", own_product_line=True).lower()
    assert "buys them to resell" not in cf.scope_prompt("M", "d").lower()


def test_sells_in_channel_counts_a_consumer_marketplace_as_the_channel():
    """A marketplace where this market's customers buy IS one of its channels (owner
    2026-10-29, Japan Fashion E-Commerce: Mercari and Enigmo/BUYMA came back "adjacent"
    for "a platform that enables other sellers to sell", and both are Online Fashion
    Marketplaces in the client's own report). The enablers that sell software TO
    merchants and run no storefront stay adjacent."""
    p = cf.scope_prompt("Fashion E-commerce Market", "online sale of apparel",
                        sells_in_channel=True).lower()
    assert "a marketplace where this market's customers themselves buy these products is core" in p
    assert "even when the listings come from third-party shops or private individuals" in p
    # the enabler test is now about who it sells TO, not about "letting others sell"
    assert "it sells tools or services to the companies that do" in p
    assert "runs no storefront or marketplace of its own" in p
    assert "it only lets others sell" not in p


def test_to_english_drops_a_local_script_name_that_already_has_its_english():
    """The report is written in English (owner 2026-10-30, Japan Fashion E-Commerce).
    Only the local-script COPY is removed; nothing is translated, so no fact is invented."""
    f = cf.to_english
    assert f("the アシックス公式アプリ (ASICS Official App) adds mobile buying") \
        == "the ASICS Official App adds mobile buying"
    assert f("its Joso Logistics (常総ロジスティクス) facility") == "its Joso Logistics facility"
    assert f('the app "ワコール【公式】" (Wacoal Web Store), enables shopping') \
        == "the app Wacoal Web Store, enables shopping"
    # a citation leftover: the source's own name in kanji, left dangling
    assert f("Not available 株式会社ストライプ +2") == "Not available"


def test_to_english_leaves_english_and_brand_styling_alone():
    f = cf.to_english
    plain = "Fast Retailing sells apparel online in Japan."
    assert f(plain) == plain
    # the katakana middle dot is part of this company's OWN English name
    assert f("SOU・SOU Co., Ltd. sells apparel online.") == "SOU・SOU Co., Ltd. sells apparel online."


def test_to_english_leaves_a_readable_sentence_behind():
    """Removing a local-script name must not leave a dangling comma or double space."""
    f = cf.to_english
    out = f("The company's official mobile application, ワコールウェブストア, provides a reservation service.")
    assert out == "The company's official mobile application provides a reservation service."
    assert f("the Recovery Sandal Slide (25年モデル) and others") == "the Recovery Sandal Slide and others"
    for bad in (" ,", "  ", ", ,"):
        assert bad not in out


def test_page_furniture_is_cut_from_a_supporting_point():
    """A whole search-results dump landed in one bullet (owner 2026-10-30, Japan Fashion
    E-Commerce, Wacoal): the finding, then source chips, app listings and finally
    "Show all Skip to previous prompt". Everything from the first marker on is the
    page, not the finding."""
    t = cf.clean_artifacts("Wacoal acquired Glamorise Foundations, Inc. in 2024. "
                           "Show all Skip to previous prompt")
    assert t == "Wacoal acquired Glamorise Foundations, Inc. in 2024."
    assert "Show all" not in cf.clean_artifacts("A finding. Show all more results")
    assert "People also ask" not in cf.clean_artifacts("A finding. People also ask what?")
    # an ordinary sentence is untouched
    plain = "The company sells apparel online in Japan."
    assert cf.clean_artifacts(plain) == plain


def test_own_product_line_ignores_how_small_the_line_is():
    """A diversified maker qualifies on the line itself, not on its share of revenue
    (owner 2026-10-30, Electrosurgical: FIAB was called adjacent with the reason "makes
    electrosurgical accessories ... but its core lines are respiratory", and accessories
    are named in that market's own product scope)."""
    p = cf.scope_prompt("Electrosurgical Devices Market", "ESUs and accessories",
                        own_product_line=True).lower()
    assert "however small a share of its revenue that line is" in p
    assert "do not answer adjacent because something else is its main business" in p
    assert "accessories, consumables and components count as this market's product" in p


def test_a_four_letter_parent_name_still_pairs_with_its_unit(tmp_path):
    """The shared-name rule needed 5 characters, so a parent whose whole name is one short word
    sat on the chart beside its own unit. 4 catches it; 3 would merge a shared commodity acronym
    with an unrelated company, so the floor stays above it (owner 2026-10-30)."""
    pool = ["Dell Inc.", "Dell Technologies Inc.", "Lion Corporation", "Lion Korea Corporation",
            "LNG Limited", "LNG Terminal Stade GmbH", "Kirwan Surgical Products, LLC"]
    _write(tmp_path / cf.OWNERSHIP_FILE, {n: {"acquired": False, "group": ""} for n in pool})
    pairs = cf.auto_review(tmp_path, pool)["listed_owner"]
    assert {"company": "Dell Technologies Inc.", "parent": "Dell Inc."} in pairs
    assert {"company": "Lion Korea Corporation", "parent": "Lion Corporation"} in pairs
    # "LNG" is the commodity, not the owner
    assert not any(p["parent"] == "LNG Limited" for p in pairs)
    assert not any(p["company"] == "Kirwan Surgical Products, LLC" for p in pairs)
