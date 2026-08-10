"""Cooperative cancel flag for long pipeline runs (Stop button in UI)."""
from __future__ import annotations

import threading


class PipelineCancelled(Exception):
    """Raised when the user stops a run midway."""


_cancel = threading.Event()


def clear_cancel() -> None:
    _cancel.clear()


def request_cancel() -> None:
    _cancel.set()


def is_cancelled() -> bool:
    return _cancel.is_set()


def check_cancelled(where: str = "") -> None:
    if _cancel.is_set():
        hint = f" ({where})" if where else ""
        raise PipelineCancelled(f"Stopped by user{hint}.")
