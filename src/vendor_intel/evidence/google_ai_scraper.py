"""HTTP client for the local Google AI Overview scraper (port 15551).

Talks to the pasted ``google-ai-scraper`` FastAPI relay::

    GET http://127.0.0.1:15551/ask?q=...&close_thread=1

Requires:
  1. Scraper server running (``google-ai-scraper-main/.../server``)
  2. Its Chrome extension loaded and connected
"""
from __future__ import annotations

import os
from typing import Any

import httpx

DEFAULT_URL = "http://127.0.0.1:15551"
DEFAULT_TIMEOUT = 120.0


def scraper_base_url() -> str:
    return (
        os.getenv("GOOGLE_AI_SCRAPER_URL")
        or os.getenv("GOOGLE_AI_SCRAPER_BASE_URL")
        or DEFAULT_URL
    ).rstrip("/")


def scraper_enabled() -> bool:
    return (os.getenv("GOOGLE_AI_SCRAPER_ENABLED") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def scraper_timeout() -> float:
    try:
        return float(os.getenv("GOOGLE_AI_SCRAPER_TIMEOUT") or DEFAULT_TIMEOUT)
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT


def health() -> dict[str, Any]:
    """Return /health JSON or ``{"ok": False, "error": ...}``."""
    url = f"{scraper_base_url()}/health"
    try:
        with httpx.Client(timeout=5.0) as client:
            r = client.get(url)
            r.raise_for_status()
            data = r.json()
            if isinstance(data, dict):
                data.setdefault("ok", True)
                return data
            return {"ok": True, "raw": data}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "url": url}


def ask(
    question: str,
    *,
    close_thread: bool = True,
    mode: str = "pro",
    timeout: float | None = None,
) -> dict[str, Any]:
    """
    Ask one question via the Google AI scraper.

    Returns dict with ``markdown``, ``citations``, ``error``, ``query``.
    """
    q = (question or "").strip()
    if not q:
        return {"markdown": "", "citations": [], "error": "empty_question", "query": ""}

    params = {"q": q, "close_thread": "1" if close_thread else "0", "mode": mode or "pro"}
    url = f"{scraper_base_url()}/ask"
    try:
        with httpx.Client(timeout=timeout or scraper_timeout()) as client:
            r = client.get(url, params=params)
            if r.status_code >= 400:
                return {
                    "markdown": "",
                    "citations": [],
                    "error": f"http_{r.status_code}: {(r.text or '')[:240]}",
                    "query": q,
                }
            data = r.json() if r.content else {}
            if not isinstance(data, dict):
                return {"markdown": "", "citations": [], "error": "bad_json", "query": q}
            md = str(data.get("markdown") or "")
            # DeepSeek (LLM_PROVIDER) cleans AI Overview → meaningful sentences only
            if md.strip() and (os.getenv("AI_OVERVIEW_DEEPSEEK_CLEAN") or "true").strip().lower() in (
                "1",
                "true",
                "yes",
                "on",
                "",
            ):
                try:
                    from vendor_intel.evidence.overview_clean import clean_overview_markdown

                    cleaned = clean_overview_markdown(md, query=q)
                    if cleaned.strip():
                        md = cleaned
                except Exception as exc:
                    print(f"  [google-ai] overview clean skipped: {exc}", flush=True)
            return {
                "query": data.get("query") or q,
                "query_id": data.get("query_id") or "",
                "markdown": md,
                "citations": list(data.get("citations") or []),
                "ai_overview_missing": bool(data.get("ai_overview_missing")),
                "error": str(data.get("error") or ""),
                "source": "google_ai_scraper",
            }
    except Exception as exc:
        return {
            "markdown": "",
            "citations": [],
            "error": str(exc),
            "query": q,
            "source": "google_ai_scraper",
        }
