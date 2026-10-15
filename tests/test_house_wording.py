"""Report house wording (owner 2026-10-15): 'As per our findings', estimates read '... is ...'."""
from vendor_intel.pipeline.house_wording import apply, to_house, to_legacy


def test_worded_estimate_reads_as_a_finding():
    src = ("Based on primary research, the company's contracted healthcare networks and formulary listings "
           "can be estimated as extensive across both public and private sectors, based on its client base.")
    assert to_house(src) == ("As per our findings, the company's contracted healthcare networks and formulary "
                             "listings is extensive across both public and private sectors, based on its client base.")


def test_gap_numeric_and_attribution():
    assert to_house("Based on primary research, the company has not disclosed its yield.") == \
        "As per our findings, the company has not disclosed its yield."
    assert to_house("The company's revenue can be estimated at approximately USD 5-8 million, derived from x.") == \
        "The company's revenue is approximately USD 5-8 million, derived from x."
    assert to_house("It won a tender, according to primary research.") == "It won a tender, as per our findings."
    assert to_house("No change here.") == "No change here."


def test_apply_walks_a_payload_and_legacy_maps_back():
    out = apply({"brands": [{"assessed_on": "Based on primary research, the company has not disclosed X."}],
                 "n": 3})
    assert out["brands"][0]["assessed_on"].startswith("As per our findings,") and out["n"] == 3
    assert to_legacy("It won a tender, as per our findings.") == "It won a tender, according to primary research."
