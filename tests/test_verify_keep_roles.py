"""Verify keeps a company whose role IS the market's required player type."""
import pytest

from vendor_intel.pipeline.chatgpt_expand import verify_should_keep


@pytest.mark.parametrize("role", ["Brand / Marketer", "Manufacturer",
                                  "Solution Provider", "Service Provider"])
def test_each_player_type_keeps_its_own_role(role):
    assert verify_should_keep(in_market=True, role=role, builds_or_owns=True,
                              confidence=90, expected_role=role)


@pytest.mark.parametrize("role", ["Distributor", "Reseller", "Media", "Retailer"])
def test_channel_roles_still_dropped_in_a_service_market(role):
    assert not verify_should_keep(in_market=True, role=role, builds_or_owns=True,
                                  confidence=90, expected_role="Service Provider")


def test_low_confidence_still_dropped():
    assert not verify_should_keep(in_market=True, role="Service Provider",
                                  builds_or_owns=True, confidence=50,
                                  expected_role="Service Provider")


@pytest.mark.parametrize("role", ["Retailer", "E-commerce Retailer", "Online Fashion Retailer"])
def test_a_retail_market_keeps_its_own_role_however_it_is_qualified(role):
    """A market whose own players ARE retailers must not drop them as a channel
    (owner 2026-10-29, Japan Fashion E-Commerce: marketplaces and retailers are the
    market). Exact equality alone missed "E-commerce Retailer"."""
    assert verify_should_keep(in_market=True, role=role, builds_or_owns=True,
                              confidence=90, expected_role="Retailer")


def test_a_retail_market_still_drops_the_other_channel_roles():
    for role in ("Distributor", "Reseller", "Wholesaler", "Media"):
        assert not verify_should_keep(in_market=True, role=role, builds_or_owns=True,
                                      confidence=90, expected_role="Retailer"), role


def test_a_maker_market_still_drops_a_contract_manufacturer():
    """The widening is only for a channel role, so "Contract Manufacturer" must not
    slip into a Manufacturer market by containing "Manufacturer"."""
    assert not verify_should_keep(in_market=True, role="Contract Manufacturer",
                                  builds_or_owns=True, confidence=90,
                                  expected_role="Manufacturer")


def test_is_channel_role_names_only_selling_channels():
    from vendor_intel.pipeline.chatgpt_expand import is_channel_role
    for yes in ("Retailer", "Online Marketplace", "E-commerce Retailer", "Distributor"):
        assert is_channel_role(yes), yes
    for no in ("Brand / Marketer", "Manufacturer", "Service Provider", "Solution Provider"):
        assert not is_channel_role(no), no


def test_channel_market_keeps_a_marketplace_the_verifier_labelled_other():
    """The verifier's role enum has no marketplace entry, so it answered "Other" for
    Rakuten, Mercari and Enigmo/BUYMA -- the three marketplaces in the client's own
    report (owner 2026-10-29, Japan Fashion E-Commerce). In a channel market a company
    it confirms is in the market and sells there is a player whatever label it chose."""
    for role in ("Other", "Marketplace", "E-commerce"):
        assert verify_should_keep(in_market=True, role=role, builds_or_owns=True,
                                  confidence=90, expected_role="Retailer"), role
    # A bare "Platform" is NOT kept here: an e-commerce platform vendor is one of this
    # client's excluded types, so that word is left to the scope check to judge.
    assert not verify_should_keep(in_market=True, role="Platform", builds_or_owns=True,
                                  confidence=90, expected_role="Retailer")
    # still fails closed when the verifier did not confirm the business
    assert not verify_should_keep(in_market=False, role="Other", builds_or_owns=True,
                                  confidence=95, expected_role="Retailer")
    assert not verify_should_keep(in_market=True, role="Other", builds_or_owns=False,
                                  confidence=95, expected_role="Retailer")


def test_a_brand_market_still_drops_other():
    assert not verify_should_keep(in_market=True, role="Other", builds_or_owns=True,
                                  confidence=95, expected_role="Brand / Marketer")


def test_channel_market_criteria_ask_who_sells_not_who_makes():
    from vendor_intel.pipeline import chatgpt_expand as ce
    before = dict(ce._DISCOVERY_MARKET)
    try:
        ce.set_discovery_market("B2C", ["Retailer"])
        c = ce.verify_criteria_prompt("Fashion E-commerce Market")
        assert "themselves SELL this market's products" in c
        assert "buy and resell other companies' goods" in c
        assert "whose brand is sold in this market" not in c
        ce.set_discovery_market("B2C", ["Brand / Marketer"])
        b = ce.verify_criteria_prompt("Smart Ring Market")
        assert "whose brand is sold in this market" in b and "themselves SELL" not in b
    finally:
        ce.set_discovery_market(before.get("market_type") or "", before.get("categories") or [])


def test_b2c_brand_market_with_a_selling_scope_test_keeps_the_sellers(monkeypatch):
    """A B2C market is Brand / Marketer (owner's rule, restated 2026-10-29) -- ONE player
    type. Japan Fashion E-Commerce is still measured by the SALE of the goods, so the
    market brief's scope_test, not the role label, lets the marketplaces and retail
    groups the client's report profiles into the same landscape."""
    monkeypatch.setenv("MARKET_SCOPE_TEST", "sells_in_channel")
    for role in ("Brand", "Marketer", "Retailer", "Online Marketplace", "Other"):
        assert verify_should_keep(in_market=True, role=role, builds_or_owns=True,
                                  confidence=90, expected_role="Brand / Marketer"), role
    # selling to the trade is still not selling in this market
    for role in ("Distributor", "Wholesaler", "Reseller", "Media"):
        assert not verify_should_keep(in_market=True, role=role, builds_or_owns=True,
                                      confidence=90, expected_role="Brand / Marketer"), role


def test_a_plain_b2c_brand_market_is_unchanged(monkeypatch):
    """Without the selling scope_test nothing widens: a brand market still drops
    retailers and the catch-all label."""
    monkeypatch.delenv("MARKET_SCOPE_TEST", raising=False)
    for role in ("Retailer", "Other", "Distributor"):
        assert not verify_should_keep(in_market=True, role=role, builds_or_owns=True,
                                      confidence=90, expected_role="Brand / Marketer"), role
    assert verify_should_keep(in_market=True, role="Brand", builds_or_owns=True,
                              confidence=90, expected_role="Brand / Marketer")


def test_selling_scope_test_still_fails_closed(monkeypatch):
    monkeypatch.setenv("MARKET_SCOPE_TEST", "sells_in_channel")
    assert not verify_should_keep(in_market=False, role="Retailer", builds_or_owns=True,
                                  confidence=95, expected_role="Brand / Marketer")
    assert not verify_should_keep(in_market=True, role="Retailer", builds_or_owns=False,
                                  confidence=95, expected_role="Brand / Marketer")
    assert not verify_should_keep(in_market=True, role="Retailer", builds_or_owns=True,
                                  confidence=40, expected_role="Brand / Marketer")
