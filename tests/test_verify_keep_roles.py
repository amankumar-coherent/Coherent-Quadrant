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
