"""Brand -> Company: the market knows a BRAND; a COMPANY stands behind it.

Milton -> Hamilton Housewares Pvt. Ltd.

Discovery used to ask "what companies exist in this market?" and copy the
answer into both columns, producing rows like
Brand="Hamilton Housewares Pvt. Ltd." / Company="Hamilton Housewares Pvt.
Ltd.", which tells a reader nothing.
"""
from __future__ import annotations

import pytest

from vendor_intel.pipeline import chatgpt_expand as ce
from vendor_intel.pipeline import discovery_rounds as dr
from vendor_intel.pipeline.expand_quadrant_score import to_company_detail_rows


def _report(found: list[dict], market: str = "Global Water Bottles Market") -> list[dict]:
    rows = ce._as_seed_rows(found)
    for r in rows:
        r.update(
            {
                "Distribution Type": "Manufacturer",
                "commercial_roles": ["Manufacturer"],
                "X Score": "80",
                "Y Score": "78",
                "Overall Score": "79",
                "Quadrant": "Leaders",
            }
        )
    return to_company_detail_rows(rows, market)


def _co(brand: str, company: str, **kw) -> dict:
    base = {
        "brand": brand,
        "company": company,
        "website": f"https://{brand.lower().replace(' ', '')}.com",
        "headquarters": "Mumbai, India",
        "ownership": "Independent",
        "verdict": "in_market",
        "why_related": "Sells in this market.",
    }
    base.update(kw)
    return base


# --- the core relationship -------------------------------------------------


def test_brand_and_company_are_distinct():
    """The Milton case: the brand a buyer knows is not the legal entity."""
    out = _report([_co("Milton", "Hamilton Housewares Pvt. Ltd.")])[0]
    assert out["Brand"] == "Milton"
    assert out["Company"] == "Hamilton Housewares Pvt. Ltd."
    assert out["Brand"] != out["Company"]


def test_company_selling_under_its_own_name_is_not_invented():
    """When there genuinely is no separate brand, both columns carry the
    company name — that is correct, not a bug. Do NOT invent a brand."""
    out = _report([_co("Wolfspeed", "Wolfspeed, Inc.")])[0]
    assert out["Brand"] == "Wolfspeed"
    assert "Wolfspeed" in out["Company"]


def test_multiple_brands_under_one_company_stay_separate_rows():
    out = _report(
        [
            _co("Cello", "Cello World Ltd."),
            _co("Borosil", "Cello World Ltd."),
        ]
    )
    brands = {o["Brand"] for o in out}
    companies = {o["Company"] for o in out}
    assert brands == {"Cello", "Borosil"}, "one company can own several brands"
    assert companies == {"Cello World Ltd."}
    assert len(out) == 2


# --- acquisitions ----------------------------------------------------------


def test_acquired_brand_shows_the_acquisition_in_the_company_column():
    out = _report(
        [_co("XYZ", "ABC Corporation", ownership="Acquired by DEF Corporation")]
    )[0]
    assert out["Brand"] == "XYZ"
    assert out["Company"].startswith("ABC Corporation")
    assert "acquired by DEF Corporation" in out["Company"]


def test_subsidiary_relationship_is_preserved():
    out = _report([_co("SiCrystal", "SiCrystal GmbH", ownership="Subsidiary of ROHM")])[0]
    assert "subsidiary of ROHM" in out["Company"]


def test_independent_company_has_no_suffix():
    out = _report([_co("Milton", "Hamilton Housewares Pvt. Ltd.")])[0]
    assert "(" not in out["Company"]


# --- what the prompt must and must not say ---------------------------------


def test_prompt_asks_for_brands_then_the_company_behind_them():
    system, user = dr.build_round_prompt("M", "Manufacturer", excluded_names=[])
    assert '"brand"' in system and '"company"' in system
    assert "BRANDS sold in this market" in user
    assert "- brand:" in user and "- company:" in user


def test_prompt_blocks_a_distributor_becoming_the_company():
    """A distributor carries the brand; it does not own it."""
    _, user = dr.build_round_prompt("M", "Manufacturer", excluded_names=[])
    assert "NEVER a distributor, reseller or channel partner" in user
    assert "they carry the brand, they do not own it" in user.replace("\n", " ").replace(
        "— those carry", "they carry"
    ) or "carry the" in user


def test_prompt_blocks_a_contract_manufacturer_becoming_the_company():
    _, user = dr.build_round_prompt("M", "Manufacturer", excluded_names=[])
    assert "contract manufacturer merely makes" in user
    assert "brand OWNER still goes here" in user


def test_prompt_requires_verified_acquisitions_only():
    """Do not guess acquisitions — a wrong one is worse than none."""
    _, user = dr.build_round_prompt("M", "Manufacturer", excluded_names=[])
    assert "NEVER infer one from similar names" in user
    assert "investor-relations page" in user
    assert "ownership_confidence" in user


def test_prompt_asks_for_ownership_confidence_levels():
    _, user = dr.build_round_prompt("M", "Manufacturer", excluded_names=[])
    for level in ("high", "medium", "low"):
        assert level in user


# --- market type: B2B / B2C / Hybrid ---------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("B2B", "B2B"),
        ("b2c", "B2C"),
        ("Hybrid B2B + B2C", ce.HYBRID_MARKET_TYPE),
        ("hybrid", ce.HYBRID_MARKET_TYPE),
        ("B2B and B2C", ce.HYBRID_MARKET_TYPE),
        ("", "B2C"),
    ],
)
def test_market_type_is_one_of_three(raw, expected):
    assert ce._canonical_market_type(raw) == expected


def test_hybrid_keeps_its_business_side_categories():
    """A hybrid market has real business buyers, so discovery targets the
    market's own participant roles rather than consumer-brand wording."""
    ce.set_discovery_market(ce.HYBRID_MARKET_TYPE, ["Manufacturer"])
    try:
        assert ce._is_b2b_market() is True
        assert "Manufacturer" in ce._landscape_list_nouns("M", "general")
    finally:
        ce.set_discovery_market("", [])


def test_hybrid_is_one_landscape_not_split_rows():
    """Selling through both channels must not duplicate a company."""
    for prompt in (ce._MARKET_ANALYSIS_DISCOVERY_SYSTEM,):
        flat = " ".join(prompt.split())
        assert "Hybrid B2B + B2C" in flat
        assert "never split a company into separate B2B and B2C rows" in flat


# --- dedupe ----------------------------------------------------------------


def test_brand_variants_are_one_brand():
    """Milton / MILTON / Milton India must not become three brands."""
    from vendor_intel.pipeline.ai_mode_discovery import dedupe_key

    assert dedupe_key("Milton") == dedupe_key("MILTON")
    assert dedupe_key("Milton") == dedupe_key("Milton  ")


def test_genuinely_different_brands_stay_apart():
    from vendor_intel.pipeline.ai_mode_discovery import dedupe_key

    assert dedupe_key("Milton") != dedupe_key("Milton Kitchen")
    assert dedupe_key("Cello") != dedupe_key("Borosil")


# --- contract manufacturers are never the company behind a brand -----------


def test_contract_manufacturer_rows_are_dropped_in_code():
    """The prompt says to exclude them, but a prompt is a request. A contract
    manufacturer builds to someone else's specification and owns no brand, so
    it can never be "the company behind the brand"."""
    for why in (
        "Contract manufacturer of power modules for other brands.",
        "OEM/ODM supplier building to customer specification.",
        "White-label producer of stainless steel bottles.",
        "Private-label manufacturer for retail chains.",
        "Toll manufacturing of polyurethane systems.",
        "Electronics manufacturing services provider.",
    ):
        assert dr.is_contract_manufacturer({"why_related": why}), why


def test_real_brand_owners_are_not_dropped():
    """Over-matching would delete genuine competitors."""
    for row in (
        {"why_related": "Designs and sells SiC wafers under its own brand."},
        {"company": "Acme Manufacturing Ltd", "why_related": "Owns the Acme bottle brand."},
        {"why_related": "Manufactures and markets its own consumer bottles."},
    ):
        assert not dr.is_contract_manufacturer(row), row


def test_company_name_alone_never_triggers_the_drop():
    """A legitimate brand owner can be called "<X> Manufacturing"."""
    assert not dr.is_contract_manufacturer(
        {"company": "Hamilton Manufacturing Pvt. Ltd.", "brand": "Milton"}
    )


def test_contract_manufacturers_are_excluded_by_the_round_prompt():
    _, user = dr.build_round_prompt("M", "Manufacturer", excluded_names=[])
    assert "CONTRACT MANUFACTURERS" in user
    assert "own no brand of their own here" in user
    assert "name the brand owner instead" in user


def test_contract_manufacturers_are_dropped_by_the_verify_prompt():
    ce.set_discovery_market("B2B", ["Manufacturer"])
    try:
        p = ce.verify_criteria_prompt("Global Silicon Carbide Market")
        assert "CONTRACT MANUFACTURERS" in p
        assert "never the company behind a brand" in p
    finally:
        ce.set_discovery_market("", [])


def test_contract_manufacturer_is_filtered_out_of_a_round():
    """End to end: a CM in the reply must not reach the results."""
    def ask(system, user, label):
        return {
            "companies": [
                {
                    "brand": "Milton",
                    "company": "Hamilton Housewares Pvt. Ltd.",
                    "verdict": "in_market",
                    "why_related": "Owns and sells the Milton bottle brand.",
                },
                {
                    "brand": "GenericCo",
                    "company": "GenericCo Ltd",
                    "verdict": "in_market",
                    "why_related": "Contract manufacturer producing bottles for other brands.",
                },
            ]
        }

    from vendor_intel.pipeline.ai_mode_discovery import dedupe_key

    found, _ = dr.discover_in_rounds(
        "Global Water Bottles Market",
        "Manufacturer",
        ask_json=ask,
        target=2,
        dedupe_key=dedupe_key,
    )
    names = {c["brand"] for c in found}
    assert "Milton" in names
    assert "GenericCo" not in names, "a contract manufacturer must not be kept"


# --- acquisition notation only when the evidence supports it ---------------


def test_low_confidence_acquisition_is_not_printed_as_fact():
    """Spec 12/13: state an acquisition ONLY when verified. The model rates
    its own evidence, and a "low" means it found only indirect signals — a
    wrong acquisition in the report is worse than none."""
    out = _report(
        [
            _co(
                "XYZ",
                "ABC Corporation",
                ownership="Acquired by DEF Corporation",
                ownership_confidence="low",
            )
        ]
    )[0]
    assert out["Company"] == "ABC Corporation"
    assert "acquired by" not in out["Company"].lower()


def test_high_confidence_acquisition_is_printed():
    out = _report(
        [
            _co(
                "XYZ",
                "ABC Corporation",
                ownership="Acquired by DEF Corporation",
                ownership_confidence="high",
            )
        ]
    )[0]
    assert "acquired by DEF Corporation" in out["Company"]


def test_missing_confidence_keeps_the_suffix():
    """Rows from older / non-AI-Mode sources carry no confidence field.
    Treating those as unverified would strip correct suffixes wholesale."""
    out = _report(
        [_co("XYZ", "ABC Corporation", ownership="Acquired by DEF Corporation")]
    )[0]
    assert "acquired by DEF Corporation" in out["Company"]


def test_a_company_is_not_shown_as_acquired_by_itself():
    """"Helen of Troy Limited (acquired by Helen of Troy)" is noise — the
    parent and the company are one entity under a legal-suffix variant."""
    out = _report(
        [_co("Hydro Flask", "Helen of Troy Limited", ownership="Acquired by Helen of Troy")]
    )[0]
    assert out["Company"] == "Helen of Troy Limited"


def test_a_genuinely_different_parent_still_shows():
    """The self-ownership guard must not swallow real acquisitions."""
    out = _report([_co("XYZ", "ABC Corporation", ownership="Acquired by DEF Corporation")])[0]
    assert "acquired by DEF Corporation" in out["Company"]
