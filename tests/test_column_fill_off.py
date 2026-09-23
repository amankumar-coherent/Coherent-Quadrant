"""Step 5 (column fill) is off by default.

The report is Brand | Company | Role | Quadrant | X | Y | Overall | Found in.
Discovery already returns headquarters, ownership and website in the same
query that finds the company, so Step 5's remaining work is contact person,
email, LinkedIn and office number — none of which reach the report, at the
cost of a paced query per company.
"""
from __future__ import annotations

import os

from vendor_intel.pipeline import chatgpt_expand as ce


def test_column_fill_is_off_by_default(monkeypatch):
    monkeypatch.delenv("EXPAND_COLUMN_FILL", raising=False)
    assert ce._column_fill_enabled() is False


def test_column_fill_can_be_turned_back_on(monkeypatch):
    for val in ("1", "true", "TRUE", "yes", "on"):
        monkeypatch.setenv("EXPAND_COLUMN_FILL", val)
        assert ce._column_fill_enabled() is True, val


def test_an_explicit_false_stays_off(monkeypatch):
    for val in ("0", "false", "no", "off", ""):
        monkeypatch.setenv("EXPAND_COLUMN_FILL", val)
        assert ce._column_fill_enabled() is False, val


def test_the_skipped_columns_are_not_report_columns():
    """Guard: if a report column ever moved into the unresearched set,
    skipping Step 5 would silently blank it."""
    report = {"Brand", "Company", "Role", "Quadrant", "X", "Y", "Overall", "Found in"}
    skipped = set(ce._UNRESEARCHED_COLUMNS)
    # "Role" is a header name in both, but the report's Role comes from Step 0c
    # (uniform player type), never from column fill.
    assert not (report - {"Role"}) & skipped
