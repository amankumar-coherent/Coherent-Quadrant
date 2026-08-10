"""Brand owners vs the supply chain behind them.

The classifier assigns value-chain roles only: a live run labelled 82 companies
`Manufacturer` and zero as `Brand`, so a quadrant filtered to brands matched 1 of
122. Commercial role is a separate question and gets its own pass.
"""
from __future__ import annotations

from vendor_intel.pipeline.brand_owner import (
    classify,
    commercial_roles,
    filter_to_commercial,
)


class _Client:
    """Returns a fixed commercial_role for every company in the batch."""

    available = True

    def __init__(self, role="Brand", confidence=0.9):
        self.role, self.confidence, self.calls = role, confidence, 0

    def complete_json(self, _sys, user, **k):
        self.calls += 1
        import json as _json

        idxs = [_json.loads(line)["i"] for line in user.splitlines() if line.startswith("{")]
        return {"items": [{"i": i, "commercial_role": self.role,
                           "confidence": self.confidence} for i in idxs]}


def _rows(n=3):
    return [{"company": f"Co{i}", "role": "Manufacturer",
             "company_summary": "Makes finished rupture discs."} for i in range(n)]


# ── classification ────────────────────────────────────────────────────────
def test_classify_tags_rows():
    rows = _rows(3)
    assert classify(rows, "M", client=_Client("Brand")) == 3
    assert all(r["commercial_role"] == "Brand" for r in rows)


def test_low_confidence_is_not_applied():
    rows = _rows(2)
    assert classify(rows, "M", client=_Client("Brand", confidence=0.2)) == 0
    assert "commercial_role" not in rows[0]


def test_empty_role_means_supply_chain_not_a_tag():
    rows = _rows(2)
    classify(rows, "M", client=_Client(""))
    assert "commercial_role" not in rows[0]


def test_no_llm_tags_nothing():
    rows = _rows(2)
    assert classify(rows, "M", client=None, settings=None) == 0


def test_batching_covers_every_row():
    rows = _rows(25)
    client = _Client("Brand")
    assert classify(rows, "M", client=client, batch_size=10) == 25
    assert client.calls == 3


def test_a_failing_batch_does_not_lose_the_others():
    class Flaky(_Client):
        def complete_json(self, s, u, **k):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("timeout")
            return super().complete_json(s, u, **k)

    rows = _rows(20)
    assert classify(rows, "M", client=Flaky(), batch_size=10) == 10


def test_classify_uses_the_unannotated_name():
    """After an ownership annotation the name carries "(acquired by X)"."""
    captured = {}

    class Capture(_Client):
        def complete_json(self, s, u, **k):
            captured["user"] = u
            return super().complete_json(s, u, **k)

    classify([{"company": "Oseco (acquired by Halma plc)", "company_raw": "Oseco",
               "company_summary": "x"}], "M", client=Capture())
    assert '"Oseco"' in captured["user"]


# ── commercial roles ──────────────────────────────────────────────────────
def test_commercial_roles_combines_both_sources():
    assert commercial_roles({"commercial_role": "Brand"}) == {"Brand"}
    assert commercial_roles({"role": "Brand"}) == {"Brand"}
    assert commercial_roles({"role": "Manufacturer"}) == set()
    assert commercial_roles({"role": "Manufacturer", "commercial_role": "Brand"}) == {"Brand"}


def test_value_chain_roles_alone_are_not_commercial():
    for role in ("Manufacturer", "Distributor", "Supplier", "System Integrator"):
        assert commercial_roles({"role": role}) == set()


# ── filtering ─────────────────────────────────────────────────────────────
def test_filter_keeps_brands_and_drops_the_supply_chain():
    rows = [
        {"company": "Fike", "role": "Manufacturer", "commercial_role": "Brand"},
        {"company": "ATI Metals", "role": "Supplier"},
        {"company": "Acme Soft", "role": "Manufacturer", "commercial_role": "Solution Developer"},
        {"company": "Contract Co", "role": "Manufacturer"},
    ]
    kept, dropped = filter_to_commercial(rows)
    assert [r["company"] for r in kept] == ["Fike", "Acme Soft"]
    assert [r["company"] for r in dropped] == ["ATI Metals", "Contract Co"]


def test_filter_respects_a_custom_keep_set():
    rows = [{"company": "A", "commercial_role": "Brand"},
            {"company": "B", "commercial_role": "Solution Developer"}]
    kept, _ = filter_to_commercial(rows, keep={"Solution Developer"})
    assert [r["company"] for r in kept] == ["B"]


# ── the quadrant-side guard ───────────────────────────────────────────────
def test_quadrant_falls_back_rather_than_scoring_nothing(monkeypatch):
    """An empty quadrant hides the real problem — nothing was tagged a Brand."""
    from vendor_intel.quadrant.synthesize import _commercial_filter

    monkeypatch.setenv("QUADRANT_ROLES", "Brand")
    rows = [{"company": "A", "role": "Manufacturer"}, {"company": "B", "role": "Supplier"}]
    assert _commercial_filter(rows) == rows, "must not return an empty cohort"


def test_quadrant_filter_applies_when_tags_exist(monkeypatch):
    from vendor_intel.quadrant.synthesize import _commercial_filter

    monkeypatch.setenv("QUADRANT_ROLES", "Brand")
    rows = [{"company": "A", "commercial_role": "Brand"}, {"company": "B", "role": "Supplier"}]
    assert [r["company"] for r in _commercial_filter(rows)] == ["A"]


def test_quadrant_filter_off_by_default(monkeypatch):
    from vendor_intel.quadrant.synthesize import _commercial_filter

    monkeypatch.delenv("QUADRANT_ROLES", raising=False)
    rows = [{"company": "A", "role": "Supplier"}]
    assert _commercial_filter(rows) == rows

    monkeypatch.setenv("QUADRANT_ROLES", "all")
    assert _commercial_filter(rows) == rows
