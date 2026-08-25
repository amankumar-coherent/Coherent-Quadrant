"""Passthrough channel-field sanitizer (electrical-distributor registry not used here)."""
from __future__ import annotations

from typing import Any


def apply_known_channel_fields_to_row(row: dict[str, Any]) -> dict[str, Any]:
    return dict(row)
