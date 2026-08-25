"""Passthrough ownership sanitizer — keep scraped/LLM values as-is."""
from __future__ import annotations

from typing import Any


def sanitize_ownership(company: str, current: Any) -> str:
    return str(current or "").strip()
