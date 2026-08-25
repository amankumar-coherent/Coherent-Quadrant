"""Clean Google AI Overview markdown via DeepSeek — keep meaningful sentences only."""
from __future__ import annotations

import json
import os
import re
from typing import Any

_SYSTEM = """You clean Google AI Overview text for market research.

Return JSON only:
{"sentences":["meaningful sentence 1","..."],"summary":"2-4 sentence factual summary"}

Rules:
- Keep ONLY factual, meaningful sentences about companies, brands, products, ownership,
  locations, certifications, market position, or numbers.
- Drop navigation chrome, disclaimers, "AI Overview", "Show more", feedback prompts,
  ads, unrelated boilerplate, and repeated filler.
- Do NOT invent facts. If the source is empty or useless, return empty sentences.
- Prefer short clear sentences. Preserve proper names and numbers exactly.
- Max 25 sentences. Summary must only use facts from those sentences.
"""


def overview_clean_enabled() -> bool:
    return (os.getenv("AI_OVERVIEW_DEEPSEEK_CLEAN") or "true").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _heuristic_clean(markdown: str, *, max_chars: int = 6000) -> str:
    """Fallback when LLM unavailable: strip obvious chrome, keep content lines."""
    text = (markdown or "").strip()
    if not text:
        return ""
    drop = re.compile(
        r"(?i)^(ai overview|show more|see more|feedback|people also ask|"
        r"related questions|was this helpful|sign in|advertisement)\b"
    )
    lines: list[str] = []
    for line in text.splitlines():
        s = line.strip().lstrip("#*-• ").strip()
        if len(s) < 25:
            continue
        if drop.match(s):
            continue
        if s.count("http") > 3:
            continue
        lines.append(s)
    # Also split long paragraphs into sentences
    blob = " ".join(lines) if lines else text
    parts = re.split(r"(?<=[.!?])\s+", blob)
    kept = [p.strip() for p in parts if len(p.strip()) >= 40]
    out = " ".join(kept[:40]) if kept else blob
    return out[:max_chars].strip()


def clean_overview_markdown(
    markdown: str,
    *,
    settings: Any = None,
    query: str = "",
    max_chars: int = 6000,
) -> str:
    """
    Use DeepSeek (via ClaudeClient / LLM_PROVIDER) to extract meaningful sentences.

    Falls back to heuristic cleaning when LLM is unavailable.
    """
    raw = (markdown or "").strip()
    if not raw:
        return ""
    if not overview_clean_enabled():
        return raw[:max_chars]

    try:
        from vendor_intel.clients.claude import ClaudeClient
        from vendor_intel.config import Settings

        settings = settings or Settings.load()
        client = ClaudeClient(settings)
        if not getattr(client, "available", False):
            return _heuristic_clean(raw, max_chars=max_chars)

        user = json.dumps(
            {
                "query": query,
                "ai_overview_raw": raw[:9000],
            },
            ensure_ascii=False,
        )
        result = client.complete_json(_SYSTEM, user, max_tokens=1800)
        if not isinstance(result, dict):
            return _heuristic_clean(raw, max_chars=max_chars)

        sentences = [
            str(s).strip()
            for s in (result.get("sentences") or [])
            if str(s).strip()
        ]
        summary = str(result.get("summary") or "").strip()
        parts: list[str] = []
        if summary:
            parts.append(summary)
        parts.extend(sentences)
        cleaned = "\n".join(parts).strip()
        if len(cleaned) < 40:
            return _heuristic_clean(raw, max_chars=max_chars)
        return cleaned[:max_chars]
    except Exception as exc:
        print(f"  [overview-clean] DeepSeek clean failed: {exc} — heuristic", flush=True)
        return _heuristic_clean(raw, max_chars=max_chars)
