"""Two-stage B2B/B2C + dynamic provider-category classification
(vendor_intel.quadrant.market_relevance) — replaces the old fixed
hardware / software_service / consumer taxonomy.

All LLM calls are mocked (FakeClient below) so these tests are deterministic
and never touch the network — the whole point of the new architecture is
that classification is LLM-driven per market, so pinning behavior against a
live model would be flaky by construction.
"""
from __future__ import annotations

import json

import pytest

import vendor_intel.clients.claude as claude_mod
from vendor_intel.quadrant import market_relevance as mr


class FakeClient:
    """Stands in for ClaudeClient. `stage1` answers the market-analysis call;
    `stage2` (a callable taking the parsed payload) answers the per-batch
    company-role call."""

    available = True

    def __init__(self, stage1: dict, stage2=None):
        self.stage1 = stage1
        self.stage2 = stage2
        self.calls = 0

    def complete_json(self, system, user, model=None, max_tokens=None):
        self.calls += 1
        payload = json.loads(user)
        if "companies" in payload:
            if self.stage2 is None:
                return {"items": []}
            return self.stage2(payload)
        return self.stage1


@pytest.fixture(autouse=True)
def _clear_cache():
    mr._MARKET_ANALYSIS_CACHE.clear()
    yield
    mr._MARKET_ANALYSIS_CACHE.clear()


def _install(client: FakeClient):
    claude_mod.ClaudeClient = client.__class__
    # verify_market_companies() builds ClaudeClient(settings) itself rather
    # than accepting an injected client — patch the class to always hand
    # back this exact fake instance regardless of constructor args.
    claude_mod.ClaudeClient = lambda *a, **k: client


def _role_reply(role_names, in_market=True):
    def _stage2(payload):
        return {
            "items": [
                {
                    "i": c["i"],
                    "in_market": in_market,
                    "roles": [{"type": r, "reason": f"Evidence supports {r}."} for r in role_names],
                }
                for c in payload["companies"]
            ]
        }
    return _stage2


def _row(name: str, note: str = "evidence") -> dict:
    return {"brand": name, "company": name, "ai_overview_note": note}


# --- Classification tests ---------------------------------------------------


def test_b2c_market_resolves_to_brand_marketer():
    client = FakeClient(
        {"market_type": "B2C", "market_definition": "Consumer snack foods.", "market_participants": []},
        _role_reply(["Brand / Marketer"]),
    )
    _install(client)
    kept, stats = mr.verify_market_companies([_row("SnackCo Alpha")], "Potato Chips Market Alpha", settings=object())
    assert stats["market_type"] == "B2C"
    assert kept[0]["commercial_role"] == "Brand / Marketer"
    assert kept[0]["commercial_roles"] == ["Brand / Marketer"]


def test_b2b_manufacturer_only():
    client = FakeClient(
        {
            "market_type": "B2B",
            "market_definition": "Industrial pumps.",
            "market_participants": [
                {"type": "Manufacturer", "definition": "Builds pumps.", "why_relevant": "x"},
                {"type": "Distributor", "definition": "Resells pumps.", "why_relevant": "y"},
            ],
        },
        _role_reply(["Manufacturer"]),
    )
    _install(client)
    kept, stats = mr.verify_market_companies([_row("PumpCo Beta")], "Industrial Pumps Market Beta", settings=object())
    assert stats["market_type"] == "B2B"
    assert kept[0]["commercial_roles"] == ["Manufacturer"]
    assert "produces" in kept[0]["role_reasons"]["Manufacturer"].lower() or "evidence" in kept[0]["role_reasons"]["Manufacturer"].lower()


def test_b2b_solution_provider_role():
    client = FakeClient(
        {
            "market_type": "B2B",
            "market_definition": "Enterprise data platforms.",
            "market_participants": [
                {"type": "Solution Provider", "definition": "Delivers the platform.", "why_relevant": "x"},
            ],
        },
        _role_reply(["Solution Provider"]),
    )
    _install(client)
    kept, _ = mr.verify_market_companies([_row("PlatformCo Gamma")], "Enterprise Data Platforms Market Gamma", settings=object())
    assert kept[0]["commercial_roles"] == ["Solution Provider"]


def test_b2b_service_provider_role():
    client = FakeClient(
        {
            "market_type": "B2B",
            "market_definition": "Industrial equipment maintenance.",
            "market_participants": [
                {"type": "Service Provider", "definition": "Maintains equipment.", "why_relevant": "x"},
            ],
        },
        _role_reply(["Service Provider"]),
    )
    _install(client)
    kept, _ = mr.verify_market_companies([_row("ServiceCo Delta")], "Industrial Maintenance Market Delta", settings=object())
    assert kept[0]["commercial_roles"] == ["Service Provider"]


def test_b2b_manufacturer_plus_solution_provider(monkeypatch):
    # Stage 2 genuinely supports multiple roles per company. The uniform-role
    # collapse (one player type per market) runs AFTER it, so disable it here
    # to assert the classifier itself, not the collapsed landscape.
    monkeypatch.setenv("MARKET_UNIFORM_ROLE", "false")
    client = FakeClient(
        {
            "market_type": "B2B",
            "market_definition": "Industrial water treatment.",
            "market_participants": [
                {"type": "Manufacturer", "definition": "Builds equipment.", "why_relevant": "x"},
                {"type": "Solution Provider", "definition": "Delivers integrated systems.", "why_relevant": "y"},
            ],
        },
        _role_reply(["Manufacturer", "Solution Provider"]),
    )
    _install(client)
    kept, _ = mr.verify_market_companies([_row("WaterTech Epsilon")], "Industrial Water Treatment Epsilon", settings=object())
    assert set(kept[0]["commercial_roles"]) == {"Manufacturer", "Solution Provider"}
    assert kept[0]["commercial_role"] == "Manufacturer"  # primary/first role


def test_b2b_manufacturer_plus_service_provider(monkeypatch):
    monkeypatch.setenv("MARKET_UNIFORM_ROLE", "false")
    client = FakeClient(
        {
            "market_type": "B2B",
            "market_definition": "Industrial filtration.",
            "market_participants": [
                {"type": "Manufacturer", "definition": "Builds filters.", "why_relevant": "x"},
                {"type": "Service Provider", "definition": "Services filters.", "why_relevant": "y"},
            ],
        },
        _role_reply(["Manufacturer", "Service Provider"]),
    )
    _install(client)
    kept, _ = mr.verify_market_companies([_row("FilterCo Zeta")], "Industrial Filtration Market Zeta", settings=object())
    assert set(kept[0]["commercial_roles"]) == {"Manufacturer", "Service Provider"}


def test_b2b_manufacturer_plus_solution_plus_service(monkeypatch):
    monkeypatch.setenv("MARKET_UNIFORM_ROLE", "false")
    client = FakeClient(
        {
            "market_type": "B2B",
            "market_definition": "Industrial automation systems.",
            "market_participants": [
                {"type": "Manufacturer", "definition": "Builds hardware.", "why_relevant": "x"},
                {"type": "Solution Provider", "definition": "Integrates systems.", "why_relevant": "y"},
                {"type": "Service Provider", "definition": "Maintains systems.", "why_relevant": "z"},
            ],
        },
        _role_reply(["Manufacturer", "Solution Provider", "Service Provider"]),
    )
    _install(client)
    kept, _ = mr.verify_market_companies([_row("AutoCo Eta")], "Industrial Automation Systems Market Eta", settings=object())
    assert set(kept[0]["commercial_roles"]) == {"Manufacturer", "Solution Provider", "Service Provider"}


def test_different_markets_produce_different_category_sets():
    mr._MARKET_ANALYSIS_CACHE.clear()
    client_a = FakeClient(
        {
            "market_type": "B2B",
            "market_definition": "Market A.",
            "market_participants": [
                {"type": "Manufacturer", "definition": "d", "why_relevant": "r"},
                {"type": "Distributor", "definition": "d", "why_relevant": "r"},
            ],
        }
    )
    _install(client_a)
    categories_a = mr.expected_roles_for_market("Market A Theta", settings=object())

    client_b = FakeClient(
        {
            "market_type": "B2B",
            "market_definition": "Market B.",
            "market_participants": [
                {"type": "Platform Provider", "definition": "d", "why_relevant": "r"},
                {"type": "Consultant", "definition": "d", "why_relevant": "r"},
                {"type": "Integrator", "definition": "d", "why_relevant": "r"},
            ],
        }
    )
    _install(client_b)
    categories_b = mr.expected_roles_for_market("Market B Iota", settings=object())

    assert categories_a == {"Manufacturer", "Distributor"}
    assert categories_b == {"Platform Provider", "Consultant", "Integrator"}
    assert categories_a != categories_b


def test_contract_manufacturer_never_present():
    client = FakeClient(
        {
            "market_type": "B2B",
            "market_definition": "Consumer electronics assembly.",
            # Even if the model tries to hand back "Contract Manufacturer",
            # analyze_market() must strip it — it is never a default/global
            # category.
            "market_participants": [
                {"type": "Contract Manufacturer", "definition": "d", "why_relevant": "r"},
                {"type": "Manufacturer", "definition": "d", "why_relevant": "r"},
            ],
        }
    )
    _install(client)
    categories = mr.expected_roles_for_market("Consumer Electronics Assembly Kappa", settings=object())
    assert "Contract Manufacturer" not in categories
    assert categories == {"Manufacturer"}


def test_no_hardware_software_classification_dimension():
    """The new module must not expose a hardware/software/consumer taxonomy
    anywhere in its public surface."""
    banned = {"classify_player_type", "_PLAYER_TYPE_SYSTEM", "_PLAYER_TYPE_KEYWORDS", "_ROLES_BY_PLAYER_TYPE"}
    present = banned & set(dir(mr))
    assert not present, f"hardware/software-style symbols still present: {present}"

    client = FakeClient(
        {
            "market_type": "B2B",
            "market_definition": "Any market.",
            "market_participants": [{"type": "Manufacturer", "definition": "d", "why_relevant": "r"}],
        }
    )
    _install(client)
    analysis = mr.analyze_market("Any Market Lambda", settings=object())
    blob = json.dumps(analysis).lower()
    assert "hardware" not in blob
    assert "software" not in blob


def test_reasons_are_internal_not_exposed_via_html_helper():
    """role_reasons must exist for audit purposes but the HTML layer must
    never be handed them as a per-role explanation to render."""
    client = FakeClient(
        {
            "market_type": "B2B",
            "market_definition": "d",
            "market_participants": [{"type": "Manufacturer", "definition": "d", "why_relevant": "r"}],
        },
        _role_reply(["Manufacturer"]),
    )
    _install(client)
    kept, _ = mr.verify_market_companies([_row("ReasonCo Mu")], "Reason Market Mu", settings=object())
    assert "role_reasons" in kept[0]
    assert kept[0]["role_reasons"]["Manufacturer"]
    # commercial_role / commercial_roles are what the HTML table renders —
    # confirm they contain only type names, never reason text.
    assert kept[0]["role_reasons"]["Manufacturer"] not in kept[0]["commercial_role"]


def test_landscape_is_one_player_type_by_default():
    """With the uniform-role default ON, a market whose companies classify
    differently still yields a single peer group in the landscape."""
    client = FakeClient(
        {
            "market_type": "B2B",
            "market_definition": "Industrial pumps.",
            "market_participants": [
                {"type": "Manufacturer", "definition": "Builds pumps.", "why_relevant": "x"},
                {"type": "Distributor", "definition": "Resells pumps.", "why_relevant": "y"},
            ],
        },
        # Two manufacturers, one distributor -> Manufacturer dominates.
        lambda payload: {
            "items": [
                {
                    "i": c["i"],
                    "in_market": True,
                    "roles": [
                        {
                            "type": "Distributor" if c["i"] == 2 else "Manufacturer",
                            "reason": "evidence",
                        }
                    ],
                }
                for c in payload["companies"]
            ]
        },
    )
    _install(client)
    kept, stats = mr.verify_market_companies(
        [_row("PumpCo A"), _row("PumpCo B"), _row("ResellCo C")],
        "Industrial Pumps Market Uniform",
        settings=object(),
    )
    roles = {r["commercial_role"] for r in kept}
    assert len(roles) == 1, f"landscape must be one player type, got {roles}"
    assert stats["uniform_role"] == "Manufacturer"
    assert all(len(r["commercial_roles"]) == 1 for r in kept)
