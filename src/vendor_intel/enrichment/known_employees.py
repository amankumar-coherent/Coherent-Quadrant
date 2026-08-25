"""Passthrough employee-count sanitizer — keep scraped/LLM values as-is."""
from __future__ import annotations

from typing import Any


def sanitize_employees(company: str, current: Any) -> str:
    return str(current or "").strip()
