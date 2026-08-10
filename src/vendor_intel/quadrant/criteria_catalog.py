"""Load industry-wise X/Y criteria and scoring weights from config YAML."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

AXIS_X = "Solution Capability"
AXIS_Y = "Business Strategy"


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _config_path(name: str) -> Path:
    return _project_root() / "config" / name


@lru_cache(maxsize=1)
def load_industry_catalog() -> dict[str, Any]:
    path = _config_path("quadrant_industry_criteria.yaml")
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@lru_cache(maxsize=1)
def load_scoring_weights() -> dict[str, Any]:
    path = _config_path("quadrant_scoring_weights.yaml")
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def list_leaf_categories() -> list[tuple[str, str]]:
    """Return [(group, category), ...] for every leaf."""
    catalog = load_industry_catalog()
    out: list[tuple[str, str]] = []
    for group, cats in (catalog.get("groups") or {}).items():
        if not isinstance(cats, dict):
            continue
        for cat in cats:
            out.append((str(group), str(cat)))
    return out


def get_category_features(group: str, category: str) -> dict[str, Any]:
    """Return {group, category, x: [...], y: [...], axis_x, axis_y}."""
    catalog = load_industry_catalog()
    groups = catalog.get("groups") or {}
    g = groups.get(group) or {}
    row = g.get(category)
    if not isinstance(row, dict):
        raise KeyError(f"Unknown industry category: {group}/{category}")
    labels = catalog.get("axis_labels") or {}
    return {
        "industry_group": group,
        "industry_category": category,
        "x": list(row.get("x") or []),
        "y": list(row.get("y") or []),
        "axis_x": str(labels.get("x") or AXIS_X),
        "axis_y": str(labels.get("y") or AXIS_Y),
    }


def find_category(category: str) -> tuple[str, str] | None:
    """Resolve leaf category name → (group, category), case-insensitive."""
    needle = (category or "").strip().lower()
    if not needle:
        return None
    for group, cat in list_leaf_categories():
        if cat.lower() == needle:
            return group, cat
    return None


def feature_weights_for(axis: str, n: int) -> list[float]:
    """Return n feature weights for axis 'x' or 'y' (normalized to sum 1)."""
    cfg = load_scoring_weights()
    use_matrix = bool(cfg.get("use_matrix_slot_weights"))
    key = "matrix_slot_weights" if use_matrix else "default_feature_weights"
    slots = list((cfg.get(key) or {}).get(axis) or [])
    if len(slots) < n:
        slots = [1.0 / max(n, 1)] * n
    else:
        slots = [float(x) for x in slots[:n]]
    total = sum(slots) or 1.0
    return [s / total for s in slots]


def category_keywords() -> dict[str, list[str]]:
    catalog = load_industry_catalog()
    raw = catalog.get("category_keywords") or {}
    return {str(k): [str(x).lower() for x in (v or [])] for k, v in raw.items()}
