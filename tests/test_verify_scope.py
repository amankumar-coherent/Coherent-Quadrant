"""The market scope must reach VERIFY, not only discovery.

"Advanced Seismic Data Processing" pulls in earthquake-monitoring networks,
structural-engineering ground-motion tools and marine survey hardware: they
share the word "seismic" and serve a different buyer. Discovery was steered
by MARKET_SCOPE but verify saw only the market title, so it had nothing to
reject them with.
"""
from __future__ import annotations

import os

import pytest

from vendor_intel.pipeline import chatgpt_expand as ce
from vendor_intel.quadrant import market_relevance as mr

SCOPE = (
    "Companies that develop or license seismic data PROCESSING software, "
    "algorithms, imaging platforms or related computational solutions used "
    "for SUBSURFACE EXPLORATION in oil, gas and minerals. EXCLUDE earthquake "
    "or structural-engineering seismology, seismic hazard monitoring "
    "networks, and survey acquisition hardware such as sensors and streamers."
)


@pytest.fixture(autouse=True)
def _clean_env():
    old = os.environ.get("MARKET_SCOPE")
    yield
    if old is None:
        os.environ.pop("MARKET_SCOPE", None)
    else:
        os.environ["MARKET_SCOPE"] = old


def test_verify_reads_the_scope(monkeypatch):
    monkeypatch.setenv("MARKET_SCOPE", SCOPE)
    assert ce._market_scope() == " ".join(SCOPE.split())


def test_whitespace_is_flattened(monkeypatch):
    monkeypatch.setenv("MARKET_SCOPE", "  Seismic   processing\n software ")
    assert ce._market_scope() == "Seismic processing software"


def test_no_scope_is_empty(monkeypatch):
    monkeypatch.delenv("MARKET_SCOPE", raising=False)
    assert ce._market_scope() == ""


def test_the_exclusions_are_not_truncated_away(monkeypatch):
    """A 400-char cap silently cut the EXCLUDE clause -- the part that does
    the actual work of keeping adjacent fields out."""
    monkeypatch.setenv("MARKET_SCOPE", SCOPE)
    assert "EXCLUDE" in ce._market_scope()
    assert "acquisition hardware" in ce._market_scope()


def test_discovery_and_verify_see_the_same_scope(monkeypatch):
    """Two different sentences would let discovery look for one thing and
    verify judge against another."""
    monkeypatch.setenv("MARKET_SCOPE", SCOPE)
    assert ce._market_scope() == mr._scope_hint()


def test_a_runaway_scope_is_still_bounded(monkeypatch):
    monkeypatch.setenv("MARKET_SCOPE", "x" * 5000)
    assert len(ce._market_scope()) == 900


# --- the prompt actually carries it ----------------------------------------


def test_the_verify_prompt_states_the_scope_and_how_to_use_it():
    src = (
        __import__("pathlib")
        .Path(ce.__file__)
        .read_text(encoding="utf-8")
    )
    block = src.split("def gpt_verify_market(", 1)[1]
    assert "_scope = _market_scope()" in block, "scope never resolved"
    assert "THIS MARKET COVERS EXACTLY" in block, "scope not in the system prompt"
    assert "Market scope:" in block, "scope not in the user prompt"
    # Stating the scope is not enough; verify must be told what to DO with it.
    assert "in_market=false" in block
