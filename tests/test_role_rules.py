"""Canonical roles, multi-role ranking, and per-industry role scoping."""
from __future__ import annotations

import pytest

from vendor_intel.pipeline.role_rules import (
    allowed_roles,
    filter_by_industry,
    load_rules,
    normalize_role,
    normalize_rows,
    profile_for,
    roles_of,
    sort_multi_role_first,
    split_multi_role,
)


def test_the_rules_file_actually_parses():
    """A missing space after one YAML key silently disabled every rule below."""
    rules = load_rules()
    assert rules.get("profiles"), "profiles missing — the config failed to load"
    assert rules.get("aliases"), "aliases missing — the config failed to load"


# ── normalisation ─────────────────────────────────────────────────────────
@pytest.mark.parametrize("raw,want", [
    ("Distributor", "Distributor"),
    ("distributor", "Distributor"),           # the live casing split
    ("reseller", "Distributor"),
    ("wholesaler", "Distributor"),
    ("raw material supplier", "Supplier"),
    ("EPC Contractor", "System Integrator"),  # three spellings of one role
    ("EPC / Engineering", "System Integrator"),
    ("Engineering firm", "System Integrator"),
    ("brand owner", "Brand"),
    ("software developer", "Solution Developer"),
    ("OEM", "OEM"),
])
def test_normalize_role(raw, want):
    assert normalize_role(raw) == want


def test_unknown_roles_are_kept_not_discarded():
    assert normalize_role("Pyrotechnic Specialist") == "Pyrotechnic Specialist"
    assert normalize_role("") == ""


def test_longest_alias_wins():
    """'raw material supplier' must not be swallowed by the 'supplier' alias."""
    assert normalize_role("raw material supplier") == "Supplier"
    assert normalize_role("component supplier") == "Supplier"


def test_normalize_rows_rewrites_rows_and_segments():
    rows = [{"role": "distributor",
             "multi_segments": [{"section": "S", "role": "reseller"}]}]
    normalize_rows(rows)
    assert rows[0]["role"] == "Distributor"
    assert rows[0]["multi_segments"][0]["role"] == "Distributor"
    assert rows[0]["roles_all"] == ["Distributor"]


# ── industry profiles ─────────────────────────────────────────────────────
@pytest.mark.parametrize("market,profile", [
    ("Industrial Robotics Market", "Robotics & consumer electronics"),
    ("Consumer Electronics Market", "Robotics & consumer electronics"),
    ("Smartphone Market", "Robotics & consumer electronics"),
    ("Cloud Security Software Market", "Technology & software"),
    ("SaaS Analytics Platform Market", "Technology & software"),
    ("Rupture Disc Market", "Full value chain (default)"),
    ("Avocado Oil Market", "Full value chain (default)"),
])
def test_profile_selection(market, profile):
    assert profile_for(market)["name"] == profile


def test_default_profile_allows_everything():
    assert allowed_roles("Rupture Disc Market") is None


def test_robotics_keeps_brands_and_drops_the_supply_chain():
    rows = [
        {"company": "Sony", "role": "Brand"},
        {"company": "LG", "role": "brand owner"},
        {"company": "Foxconn", "role": "contract manufacturer"},
        {"company": "ABC Components", "role": "component supplier"},
        {"company": "BestBuy", "role": "retailer"},
    ]
    kept, dropped = filter_by_industry(rows, "Consumer Electronics Market")
    assert [r["company"] for r in kept] == ["Sony", "LG"]
    assert {r["company"] for r in dropped} == {"Foxconn", "ABC Components", "BestBuy"}
    assert dropped[0]["export_reject"].startswith("role_not_in_scope:")


def test_a_brand_that_also_manufactures_survives_a_brands_only_market():
    """Kept when ANY role is allowed — otherwise every vertically-integrated
    brand would be filtered out of its own report."""
    rows = [{"company": "Samsung", "role": "Manufacturer",
             "multi_segments": [{"section": "Brands", "role": "Brand"},
                                {"section": "Mfg", "role": "Manufacturer"}]}]
    kept, dropped = filter_by_industry(rows, "Consumer Electronics Market")
    assert [r["company"] for r in kept] == ["Samsung"] and dropped == []


def test_technology_keeps_solution_developers_and_drops_resellers():
    rows = [
        {"company": "Acme Soft", "role": "software developer"},
        {"company": "Integrator Inc", "role": "system integrator"},
        {"company": "Reseller Co", "role": "reseller"},
        {"company": "Box Shifter", "role": "distributor"},
    ]
    kept, dropped = filter_by_industry(rows, "Cloud Security Software Market")
    assert {r["company"] for r in kept} == {"Acme Soft", "Integrator Inc"}
    assert {r["company"] for r in dropped} == {"Reseller Co", "Box Shifter"}


# ── multi-role ranking ────────────────────────────────────────────────────
def test_roles_of_collects_every_segment_role():
    row = {"role": "Brand", "multi_segments": [
        {"section": "A", "role": "Brand"}, {"section": "B", "role": "manufacturer"}]}
    assert roles_of(row) == ["Brand", "Manufacturer"]


def test_multi_role_companies_sort_first():
    rows = [
        {"company": "Zeta Solo", "role": "Manufacturer"},
        {"company": "Alpha Solo", "role": "Manufacturer"},
        {"company": "Multi Co", "role": "Brand", "multi_segments": [
            {"section": "A", "role": "Brand"}, {"section": "B", "role": "Manufacturer"}]},
    ]
    assert [r["company"] for r in sort_multi_role_first(rows)][0] == "Multi Co"


def test_split_multi_role_separates_the_strategic_rows():
    rows = [
        {"company": "Solo", "role": "Manufacturer"},
        {"company": "Multi", "role": "Brand", "multi_segments": [
            {"section": "A", "role": "Brand"}, {"section": "B", "role": "Distributor"}]},
    ]
    multi, single = split_multi_role(rows)
    assert [r["company"] for r in multi] == ["Multi"]
    assert [r["company"] for r in single] == ["Solo"]


def test_one_segment_is_not_multi_role():
    rows = [{"company": "Solo", "role": "Brand",
             "multi_segments": [{"section": "A", "role": "Brand"}]}]
    multi, single = split_multi_role(rows)
    assert multi == [] and len(single) == 1


# ── section canonicalisation ──────────────────────────────────────────────
def test_section_casing_variants_collapse_to_the_common_spelling():
    """A live run printed two headings for one section (42 rows vs 5)."""
    from vendor_intel.pipeline.role_rules import canonicalize_sections

    # distinct dicts — `[{...}] * n` would alias one object 42 times
    rows = ([{"value_chain_section": "Manufacturers of Rupture Discs"} for _ in range(42)]
            + [{"value_chain_section": "Manufacturers of rupture discs"} for _ in range(5)])
    changed = canonicalize_sections(rows)
    assert changed == 5
    assert {r["value_chain_section"] for r in rows} == {"Manufacturers of Rupture Discs"}


def test_section_canonicalisation_reaches_multi_segments():
    from vendor_intel.pipeline.role_rules import canonicalize_sections

    rows = [
        {"value_chain_section": "Distributors of Rupture Discs"},
        {"value_chain_section": "Distributors of Rupture Discs"},
        {"value_chain_section": "distributors of rupture discs",
         "multi_segments": [{"section": "distributors of rupture discs", "role": "Distributor"}]},
    ]
    canonicalize_sections(rows)
    assert rows[2]["multi_segments"][0]["section"] == "Distributors of Rupture Discs"


def test_distinct_sections_are_untouched():
    from vendor_intel.pipeline.role_rules import canonicalize_sections

    rows = [{"value_chain_section": "Manufacturers"}, {"value_chain_section": "Distributors"}]
    assert canonicalize_sections(rows) == 0
