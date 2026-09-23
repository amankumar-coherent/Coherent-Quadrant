"""discover -> verify -> discover more -> verify ... until --keep verified."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from vendor_intel.pipeline import chatgpt_expand as ce
from vendor_intel.pipeline import web_expand

ROOT = Path(__file__).resolve().parents[1]


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "discover_verify_rounds", ROOT / "scripts" / "discover_verify_rounds.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _row(i: int) -> dict:
    return {"name": f"Company {i:03d} Ltd", "domain": f"company{i:03d}.com"}


@pytest.fixture
def market(tmp_path, monkeypatch):
    ckpt = tmp_path / "chatgpt_checkpoint_batch_all.json"
    start = [_row(i) for i in range(10)]
    ckpt.write_text(json.dumps({"data": {
        "recalled": start, "verified": start[:6], "rejected_mid": start[6:],
        "market_analysis": {"market_type": "B2B", "market_participants": []},
    }}), encoding="utf-8")
    monkeypatch.setattr(web_expand, "default_output_dir", lambda q, c: tmp_path)
    monkeypatch.setattr(ce, "_client", lambda s: None)
    monkeypatch.setattr(ce, "_model", lambda s: "m")
    return ckpt


def _run(mod, monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["x", "--market", "M", *argv])
    return mod.main()


def test_rounds_continue_until_keep_is_reached(market, monkeypatch):
    calls = {"discover": 0, "verified_batches": []}

    def discover(client, model, *, query, family, target, country, ckpt):
        calls["discover"] += 1
        rows = list(ckpt.data("recalled") or [])
        rows += [_row(len(rows) + i) for i in range(target - len(rows))]
        ckpt.state["data"]["recalled"] = rows
        return rows

    def verify(client, model, *, query, family, companies):
        calls["verified_batches"].append([c["name"] for c in companies])
        # Keeps only a quarter -- worse than the 60% the first batch showed,
        # so the first top-up falls short and another round is needed.
        q = len(companies) // 4
        return companies[:q], companies[q:]

    monkeypatch.setattr(ce, "discover_companies_rounds", discover)
    monkeypatch.setattr(ce, "gpt_verify_market", verify)
    mod = _load_script()

    assert _run(mod, monkeypatch, "--keep", "40", "--min-batch", "5") == 0
    data = json.loads(market.read_text(encoding="utf-8"))["data"]
    assert len(data["verified"]) >= 40
    assert calls["discover"] >= 2  # more than one batch was needed
    # Nothing is verified twice: every batch holds only never-seen companies.
    seen = [n for batch in calls["verified_batches"] for n in batch]
    assert len(seen) == len(set(seen))
    assert not {f"Company {i:03d} Ltd" for i in range(10)} & set(seen)


def test_stops_when_discovery_finds_nothing_new(market, monkeypatch):
    monkeypatch.setattr(ce, "discover_companies_rounds",
                        lambda *a, ckpt, **k: list(ckpt.data("recalled") or []))
    monkeypatch.setattr(ce, "gpt_verify_market",
                        lambda *a, **k: pytest.fail("nothing new to verify"))
    mod = _load_script()
    assert _run(mod, monkeypatch, "--keep", "40") == 1


def test_no_rounds_when_already_enough(market, monkeypatch):
    monkeypatch.setattr(ce, "discover_companies_rounds",
                        lambda *a, **k: pytest.fail("must not discover"))
    mod = _load_script()
    assert _run(mod, monkeypatch, "--keep", "5") == 0
