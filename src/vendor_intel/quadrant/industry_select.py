"""Map a market query to one Industry-wise leaf category."""
from __future__ import annotations

import json
import re
from typing import Any

from vendor_intel.quadrant.criteria_catalog import (
    category_keywords,
    find_category,
    get_category_features,
    list_leaf_categories,
)

_FALLBACK = ("Others", "Consumer Goods")

_SYSTEM = """You map a market research topic to exactly ONE industry leaf category.
Return JSON only: {"industry_group": "...", "industry_category": "...", "confidence": 0.0-1.0, "reason": "short"}
industry_category MUST be copied verbatim from the allowed list. Prefer the most specific leaf."""


def _keyword_match(market: str) -> tuple[str, str, float] | None:
    text = (market or "").lower()
    if not text:
        return None
    best: tuple[str, str, float] | None = None
    for cat, kws in category_keywords().items():
        hits = sum(1 for kw in kws if kw in text)
        if hits <= 0:
            continue
        score = hits / max(len(kws), 1)
        # Prefer longer keyword hits
        score += max((len(kw) for kw in kws if kw in text), default=0) / 100.0
        resolved = find_category(cat)
        if not resolved:
            continue
        if best is None or score > best[2]:
            best = (resolved[0], resolved[1], min(0.95, 0.55 + score))
    return best


def select_industry(
    market: str,
    *,
    geography: str = "",
    settings: Any = None,
    client: Any = None,
) -> dict[str, Any]:
    """
    Resolve market → industry features dict with selection metadata.
    Always returns a valid leaf (falls back to Others/Consumer Goods).
    """
    leaves = list_leaf_categories()
    allowed = [{"industry_group": g, "industry_category": c} for g, c in leaves]

    kw = _keyword_match(market)
    if kw and kw[2] >= 0.7:
        group, cat, conf = kw
        feats = get_category_features(group, cat)
        feats.update(
            {
                "selection_method": "keyword",
                "confidence": round(conf, 3),
                "reason": f"keyword match on market={market!r}",
            }
        )
        return feats

    try:
        from vendor_intel.clients.claude import ClaudeClient
        from vendor_intel.config import Settings

        settings = settings or Settings.load()
        client = client or ClaudeClient(settings)
    except Exception:
        client = None
        settings = settings

    if client is not None and getattr(client, "available", False):
        try:
            payload = {
                "market": market,
                "geography": geography or "global",
                "allowed_categories": allowed,
            }
            raw = client.complete_json(
                _SYSTEM,
                json.dumps(payload, ensure_ascii=False),
                model=getattr(settings, "classifier_model", None),
                max_tokens=800,
            )
            if isinstance(raw, dict):
                cat = str(raw.get("industry_category") or "").strip()
                group = str(raw.get("industry_group") or "").strip()
                resolved = find_category(cat)
                if resolved:
                    group, cat = resolved
                elif group and cat:
                    try:
                        get_category_features(group, cat)
                    except KeyError:
                        resolved = None
                        group, cat = "", ""
                if group and cat:
                    feats = get_category_features(group, cat)
                    feats.update(
                        {
                            "selection_method": "llm",
                            "confidence": float(raw.get("confidence") or 0.7),
                            "reason": str(raw.get("reason") or ""),
                        }
                    )
                    return feats
        except Exception as exc:
            print(f"  [quadrant] industry select LLM failed: {exc}", flush=True)

    if kw:
        group, cat, conf = kw
        feats = get_category_features(group, cat)
        feats.update(
            {
                "selection_method": "keyword_fallback",
                "confidence": round(conf, 3),
                "reason": f"keyword fallback for market={market!r}",
            }
        )
        return feats

    # Soft heuristic on tokens
    tokens = set(re.findall(r"[a-z0-9]+", (market or "").lower()))
    for group, cat in leaves:
        cat_tokens = set(re.findall(r"[a-z0-9]+", cat.lower()))
        if tokens & cat_tokens:
            feats = get_category_features(group, cat)
            feats.update(
                {
                    "selection_method": "token_overlap",
                    "confidence": 0.4,
                    "reason": f"token overlap with {cat}",
                }
            )
            return feats

    group, cat = _FALLBACK
    feats = get_category_features(group, cat)
    feats.update(
        {
            "selection_method": "default",
            "confidence": 0.2,
            "reason": f"no match for market={market!r}; defaulted to {cat}",
        }
    )
    return feats
