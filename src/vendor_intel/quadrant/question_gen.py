"""LLM generates market-specific evaluation questions per industry feature."""
from __future__ import annotations

import json
from typing import Any

from vendor_intel.clients.claude import ClaudeClient
from vendor_intel.config import Settings
from vendor_intel.quadrant.criteria_catalog import load_scoring_weights
from vendor_intel.quadrant.schema import FeatureQuestions, QuestionItem

_SYSTEM = """You write vendor-evaluation questions for a Coherent Quadrant scorecard.
For EACH feature, write exactly N questions tailored to the given market and industry category.
Questions must be answerable from a company's public website, filings, news, or product pages.
Return JSON only:
{
  "features": [
    {
      "feature": "exact feature name from input",
      "axis": "Solution Capability" or "Business Strategy",
      "questions": [
        {"text": "question?", "weight": 0.4},
        {"text": "question?", "weight": 0.3},
        {"text": "question?", "weight": 0.3}
      ]
    }
  ]
}
Rules:
- Use the EXACT feature names and axis labels from the input.
- Weights per feature must sum to 1.0 (prefer 0.4/0.3/0.3).
- Do NOT copy generic ICT template wording; make questions market-specific.
- Keep each question under 140 characters."""


def _default_questions(
    feature: str,
    axis: str,
    market: str,
    weights: list[float],
) -> FeatureQuestions:
    m = market or "this market"
    templates = [
        f"How strong is the vendor's capability on '{feature}' for {m}?",
        f"What public evidence shows excellence in '{feature}' within {m}?",
        f"How does the vendor compare to peers on '{feature}' in {m}?",
    ]
    n = len(weights)
    items = [
        QuestionItem(text=templates[i % len(templates)], weight=float(weights[i]))
        for i in range(n)
    ]
    return FeatureQuestions(feature=feature, axis=axis, items=items)  # type: ignore[arg-type]


def _normalize_feature_block(
    block: dict[str, Any],
    *,
    feature: str,
    axis: str,
    default_weights: list[float],
    n: int,
) -> FeatureQuestions:
    raw_qs = block.get("questions") or block.get("items") or []
    items: list[QuestionItem] = []
    for i, q in enumerate(raw_qs[:n]):
        if isinstance(q, str):
            items.append(QuestionItem(text=q.strip(), weight=float(default_weights[i])))
            continue
        if not isinstance(q, dict):
            continue
        text = str(q.get("text") or q.get("question") or "").strip()
        if not text:
            continue
        w = q.get("weight")
        try:
            w_f = float(w) if w is not None else float(default_weights[min(i, len(default_weights) - 1)])
        except (TypeError, ValueError):
            w_f = float(default_weights[min(i, len(default_weights) - 1)])
        items.append(QuestionItem(text=text, weight=w_f))
    while len(items) < n:
        items.append(
            QuestionItem(
                text=f"How well does the vendor perform on '{feature}'?",
                weight=float(default_weights[len(items)]),
            )
        )
    items = items[:n]
    total = sum(it.weight for it in items) or 1.0
    items = [QuestionItem(text=it.text, weight=round(it.weight / total, 4)) for it in items]
    return FeatureQuestions(feature=feature, axis=axis, items=items)  # type: ignore[arg-type]


def generate_questions(
    *,
    market: str,
    geography: str,
    industry_group: str,
    industry_category: str,
    x_features: list[str],
    y_features: list[str],
    axis_x: str = "Solution Capability",
    axis_y: str = "Business Strategy",
    settings: Settings | None = None,
    client: ClaudeClient | None = None,
) -> list[FeatureQuestions]:
    settings = settings or Settings.load()
    cfg = load_scoring_weights()
    n = int(cfg.get("questions_per_feature") or 3)
    default_w = [float(x) for x in (cfg.get("default_question_weights") or [0.4, 0.3, 0.3])]
    while len(default_w) < n:
        default_w.append(1.0 / n)
    default_w = default_w[:n]
    tw = sum(default_w) or 1.0
    default_w = [w / tw for w in default_w]

    feature_specs = (
        [{"feature": f, "axis": axis_x} for f in x_features]
        + [{"feature": f, "axis": axis_y} for f in y_features]
    )

    client = client or ClaudeClient(settings)
    by_key: dict[tuple[str, str], FeatureQuestions] = {}

    if client.available:
        try:
            user = {
                "market": market,
                "geography": geography or "global",
                "industry_group": industry_group,
                "industry_category": industry_category,
                "N": n,
                "features": feature_specs,
            }
            raw = client.complete_json(
                _SYSTEM,
                json.dumps(user, ensure_ascii=False),
                model=getattr(settings, "classifier_model", None),
                max_tokens=4096,
            )
            blocks = []
            if isinstance(raw, dict):
                blocks = raw.get("features") or raw.get("questions") or []
            elif isinstance(raw, list):
                blocks = raw
            for block in blocks:
                if not isinstance(block, dict):
                    continue
                feat = str(block.get("feature") or "").strip()
                axis = str(block.get("axis") or "").strip()
                if not feat:
                    continue
                if axis not in (axis_x, axis_y):
                    # infer from feature lists
                    axis = axis_x if feat in x_features else axis_y
                by_key[(feat, axis)] = _normalize_feature_block(
                    block,
                    feature=feat,
                    axis=axis,
                    default_weights=default_w,
                    n=n,
                )
        except Exception as exc:
            print(f"  [quadrant] question gen LLM failed: {exc}", flush=True)

    out: list[FeatureQuestions] = []
    for spec in feature_specs:
        feat = spec["feature"]
        axis = spec["axis"]
        q = by_key.get((feat, axis))
        if q is None:
            q = _default_questions(feat, axis, market, default_w)
        out.append(q)
    return out
