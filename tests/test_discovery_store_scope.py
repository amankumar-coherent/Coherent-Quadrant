"""The cross-run discovery store must not leak between countries.

Regression: the store was keyed on market alone, so in a region run the USA pass
persisted its companies and the Canada pass re-injected all of them as
candidates. Country N processed ~N times the work (USA 214 -> Canada 405 on a
real run) and spent its budget re-judging the previous country's companies.
"""
from __future__ import annotations

import pytest

from vendor_intel.pipeline.discovery_store import (
    _store_path,
    load_discovered,
    save_discovered,
)


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    """Point _project_root() at a temp dir so tests never touch output/."""
    import vendor_intel.config as cfg

    monkeypatch.setattr(cfg, "_project_root", lambda: tmp_path)
    return tmp_path


def _rows(*names):
    return [{"name": n, "domain": f"{n.lower().replace(' ', '')}.com"} for n in names]


def test_countries_get_separate_store_files():
    usa = _store_path("Rupture Disc Market", "USA")
    canada = _store_path("Rupture Disc Market", "Canada")
    assert usa != canada
    assert usa.name == "rupture_disc_market__usa.json"
    assert canada.name == "rupture_disc_market__canada.json"


def test_saving_one_country_does_not_leak_into_another():
    save_discovered("Rupture Disc Market", _rows("Fike", "ZOOK"), "USA")
    assert {r["name"] for r in load_discovered("Rupture Disc Market", "USA")} == {"Fike", "ZOOK"}
    assert load_discovered("Rupture Disc Market", "Canada") == []


def test_each_country_accumulates_independently():
    """Cumulative coverage still works — just per country."""
    save_discovered("Rupture Disc Market", _rows("Fike"), "USA")
    save_discovered("Rupture Disc Market", _rows("ZOOK"), "USA")
    save_discovered("Rupture Disc Market", _rows("Spartan Controls"), "Canada")

    assert {r["name"] for r in load_discovered("Rupture Disc Market", "USA")} == {"Fike", "ZOOK"}
    assert {r["name"] for r in load_discovered("Rupture Disc Market", "Canada")} == {"Spartan Controls"}


def test_save_reloads_its_own_scope_not_the_global_one():
    """save_discovered() merges the existing store in; it must read the same scope."""
    save_discovered("Rupture Disc Market", _rows("GlobalCo"), "")        # global scope
    save_discovered("Rupture Disc Market", _rows("CanadaCo"), "Canada")

    canada = {r["name"] for r in load_discovered("Rupture Disc Market", "Canada")}
    assert canada == {"CanadaCo"}, "the global store bled into Canada"


def test_blank_geography_is_the_global_scope():
    assert _store_path("M", "").name == "m__global.json"
    assert _store_path("M", "global").name == "m__global.json"
    assert _store_path("M").name == "m__global.json"


def test_different_markets_still_separate():
    save_discovered("Rupture Disc Market", _rows("Fike"), "USA")
    assert load_discovered("Avocado Oil Market", "USA") == []


def test_payload_records_its_geography(_isolated_store):
    import json

    save_discovered("Rupture Disc Market", _rows("Fike"), "Canada")
    data = json.loads(_store_path("Rupture Disc Market", "Canada").read_text(encoding="utf-8"))
    assert data["geography"] == "Canada"
