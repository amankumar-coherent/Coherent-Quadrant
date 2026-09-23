"""X/Y scoring must not crawl. It scores from the company name.

Observed on Silicon Carbide: 152 companies "deep-crawled" at 60 pages each,
every one logging

    [not publicly disclosed] Mode: business
    [enrich] cache hit: not publicly disclosed

because the rows carried the literal placeholder "not publicly disclosed" as
their website. 152 crawls, one shared empty cache entry, and a scorer that
never reads the result: score_company() takes the company NAME and the axis
parameters, nothing else.
"""
from __future__ import annotations

import inspect
import os

from vendor_intel.pipeline import expand_quadrant_score as eqs
from vendor_intel.quadrant import ai_mode_scorer


def test_the_scorer_never_takes_crawled_pages():
    """It scores from the company name, the market, and the one-line
    description discovery already collected — all cheap strings. If this ever
    grows a knowledge-base or crawl argument, the crawl earns its place back;
    until then crawling 60 pages per company feeds nothing."""
    params = set(inspect.signature(ai_mode_scorer.score_company).parameters)
    assert {"company", "x_parameters", "y_parameters"} <= params
    assert not params & {"kb", "knowledge_base", "pages", "crawl", "evidence"}


def test_crawl_is_off_unless_explicitly_asked_for(monkeypatch):
    monkeypatch.delenv("EXPAND_XY_CRAWL", raising=False)
    src = inspect.getsource(eqs)
    assert 'os.getenv("EXPAND_XY_CRAWL")' in src
    assert "not in (" in src.split('os.getenv("EXPAND_XY_CRAWL")')[1][:120], (
        "the flag must be opt-IN: `not in` makes absent mean skip"
    )


def test_no_knowledge_base_is_built_for_scoring():
    """Building a KB cost a crawl per company and fed nothing."""
    src = inspect.getsource(eqs)
    assert "await build_company_kb(" not in src, "KB build must be gone from scoring"
    assert "from vendor_intel.quadrant.company_kb import" not in src


def test_the_placeholder_website_is_not_a_website():
    """The string that caused 152 identical cache hits."""
    assert eqs._filled("not publicly disclosed") == ""
    assert eqs._filled("N/A") == ""
    assert eqs._filled("") == ""
    assert eqs._filled("https://wolfspeed.com") == "https://wolfspeed.com"
