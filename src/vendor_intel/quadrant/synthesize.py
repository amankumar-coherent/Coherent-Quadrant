"""Orchestrate industry-aware Coherent Quadrant synthesis → CMI JSON."""
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from vendor_intel.clients.claude import ClaudeClient
from vendor_intel.config import Settings
from vendor_intel.quadrant.company_kb import build_company_kb
from vendor_intel.quadrant.criteria_catalog import feature_weights_for, load_scoring_weights
from vendor_intel.quadrant.industry_select import select_industry
from vendor_intel.quadrant.matrix_rollup import (
    feature_contribution,
    scale_to_100,
    weighted_question_average,
)
from vendor_intel.quadrant.qa_scorer import score_company_features_async
from vendor_intel.quadrant.question_gen import generate_questions
from vendor_intel.quadrant.rating_map import (
    brand_color,
    chart_offsets_absolute,
    chart_offsets_for_quadrants,
    compute_overall,
    inner_cell_offsets,
    assign_quadrants_half_median,
    assign_tiers_relative,
    overall_to_tier,
    relative_midpoints,
    sub_avg_to_rating,
)
from vendor_intel.quadrant.schema import (
    CoherentQuadrantPayload,
    EvidenceItem,
    FeatureScoreDetail,
    FeatureQuestions,
    QuadrantBrand,
    ScorecardRow,
)

def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _slug(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")
    return s[:80] or "market"


def _commercial_filter(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only companies a buyer actually chooses between.

    A quadrant compares competitors, so the supply chain behind them — contract
    manufacturers, material suppliers, pure resellers — does not belong on it even
    though it belongs in the landscape report. Controlled by QUADRANT_ROLES
    (comma-separated); empty or "all" scores every company.
    """
    import os

    raw = (os.getenv("QUADRANT_ROLES") or "").strip()
    if not raw or raw.lower() == "all":
        return rows
    keep = {r.strip() for r in raw.split(",") if r.strip()}
    try:
        from vendor_intel.pipeline.brand_owner import commercial_roles
    except Exception:
        return rows
    filtered = [r for r in rows if commercial_roles(r) & keep]
    if not filtered:
        # Never hand back an empty cohort because a market has no brand tags —
        # an empty quadrant is worse than an unfiltered one, and it hides the
        # real problem (nothing was classified as a Brand).
        print(
            f"  [quadrant] QUADRANT_ROLES={sorted(keep)} matched 0 of {len(rows)} companies "
            f"- scoring all instead (run the brand-owner pass to populate commercial_role)",
            flush=True,
        )
        return rows
    print(
        f"  [quadrant] role filter {sorted(keep)}: {len(filtered)} of {len(rows)} companies",
        flush=True,
    )
    return filtered


def _pick_companies(rows: list[dict[str, Any]], max_n: int) -> list[dict[str, Any]]:
    """Best-quality relevant rows, deduped by name. ``max_n <= 0`` scores everything."""
    rows = _commercial_filter(rows)
    scored = []
    for r in rows:
        if not r.get("is_relevant", True):
            continue
        name = str(r.get("company") or r.get("brand") or "").strip()
        if not name:
            continue
        q = float(r.get("quality_score") or r.get("confidence") or 0)
        scored.append((q, name.lower(), r))
    scored.sort(key=lambda x: (-x[0], x[1]))
    # dedupe by name
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for _, key, r in scored:
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
        if max_n > 0 and len(out) >= max_n:
            break
    return out


def _top_strength(feature_results: list[dict[str, Any]]) -> str:
    best_text = ""
    best_score = -1.0
    for fr in feature_results:
        for ans in fr.get("answers") or []:
            sc = float(getattr(ans, "score", 0) or 0)
            grounding = getattr(ans, "grounding", "")
            if grounding == "insufficient":
                continue
            if sc > best_score and getattr(ans, "answer", ""):
                best_score = sc
                best_text = str(ans.answer).strip()
    return best_text[:200]


def _rollup_brand_scores(
    *,
    brand: str,
    idx: int,
    kb: dict[str, Any],
    feature_results: list[dict[str, Any]],
    x_feats: list[str],
    y_feats: list[str],
    axis_x: str,
    axis_y: str,
    x_weights: list[float],
    y_weights: list[float],
) -> tuple[
    dict[str, Any],
    list[FeatureScoreDetail],
    list[ScorecardRow],
    list[EvidenceItem],
]:
    x_map = {f: i for i, f in enumerate(x_feats)}
    y_map = {f: i for i, f in enumerate(y_feats)}
    x_contribs = [0.0] * len(x_feats)
    y_contribs = [0.0] * len(y_feats)
    score_detail: list[FeatureScoreDetail] = []
    scorecard: list[ScorecardRow] = []

    for fr in feature_results:
        feat = fr["feature"]
        axis = fr["axis"]
        sub = weighted_question_average(fr["scores"], fr["weights"])
        if feat in x_map and axis == axis_x:
            i = x_map[feat]
            x_contribs[i] = feature_contribution(x_weights[i], sub)
            rating = sub_avg_to_rating(sub)
            score_detail.append(
                FeatureScoreDetail(
                    brand=brand,
                    feature=feat,
                    axis=axis_x,  # type: ignore[arg-type]
                    sub_avg=round(sub, 4),
                    contribution=round(x_contribs[i], 6),
                    rating=rating,  # type: ignore[arg-type]
                    answers=fr["answers"],
                )
            )
            notes = ""
            for a in fr["answers"]:
                if a.grounding == "supported" and a.answer:
                    notes = a.answer[:160]
                    break
            scorecard.append(
                ScorecardRow(
                    brand=brand,
                    axis=axis_x,  # type: ignore[arg-type]
                    criterion=feat,
                    rating=rating,  # type: ignore[arg-type]
                    notes=notes,
                )
            )
        elif feat in y_map:
            i = y_map[feat]
            y_contribs[i] = feature_contribution(y_weights[i], sub)
            rating = sub_avg_to_rating(sub)
            score_detail.append(
                FeatureScoreDetail(
                    brand=brand,
                    feature=feat,
                    axis=axis_y,  # type: ignore[arg-type]
                    sub_avg=round(sub, 4),
                    contribution=round(y_contribs[i], 6),
                    rating=rating,  # type: ignore[arg-type]
                    answers=fr["answers"],
                )
            )
            notes = ""
            for a in fr["answers"]:
                if a.grounding == "supported" and a.answer:
                    notes = a.answer[:160]
                    break
            scorecard.append(
                ScorecardRow(
                    brand=brand,
                    axis=axis_y,  # type: ignore[arg-type]
                    criterion=feat,
                    rating=rating,  # type: ignore[arg-type]
                    notes=notes,
                )
            )

    execution = scale_to_100(sum(x_contribs))
    innovation = scale_to_100(sum(y_contribs))
    revenue = str(kb.get("revenue") or "")
    yoy = str(kb.get("yoy_growth") or "")
    evidence: list[EvidenceItem] = []
    if revenue:
        evidence.append(
            EvidenceItem(
                brand=brand,
                field="revenue",
                status="retrieved",
                snippet=revenue,
                method="kb_extract",
            )
        )
    else:
        evidence.append(
            EvidenceItem(brand=brand, field="revenue", status="unknown", method="kb_extract")
        )
    if yoy:
        evidence.append(
            EvidenceItem(
                brand=brand,
                field="yoy_growth",
                status="retrieved",
                snippet=yoy,
                method="kb_extract",
            )
        )
    else:
        evidence.append(
            EvidenceItem(brand=brand, field="yoy_growth", status="unknown", method="kb_extract")
        )

    brand_row = {
        "brand": brand,
        "execution": execution,
        "innovation": innovation,
        "revenue": revenue,
        "yoy_growth": yoy,
        "top_strength": _top_strength(feature_results),
        "index": idx,
    }
    return brand_row, score_detail, scorecard, evidence


async def _score_one_brand(
    *,
    idx: int,
    row: dict[str, Any],
    market: str,
    questions: list[FeatureQuestions],
    settings: Settings,
    client: ClaudeClient,
    batch_mode: str,
    x_feats: list[str],
    y_feats: list[str],
    axis_x: str,
    axis_y: str,
    x_weights: list[float],
    y_weights: list[float],
    sem: asyncio.Semaphore,
) -> tuple[
    dict[str, Any],
    list[FeatureScoreDetail],
    list[ScorecardRow],
    list[EvidenceItem],
]:
    brand = str(row.get("company") or row.get("brand") or "").strip()
    async with sem:
        print(f"  [quadrant] scoring brand {idx + 1}: {brand[:50]}", flush=True)
        kb = await build_company_kb(row, market=market, settings=settings, do_search=False)
        feature_results = await score_company_features_async(
            kb,
            questions,
            settings=settings,
            client=client,
            batch_mode=batch_mode,
        )
    return _rollup_brand_scores(
        brand=brand,
        idx=idx,
        kb=kb,
        feature_results=feature_results,
        x_feats=x_feats,
        y_feats=y_feats,
        axis_x=axis_x,
        axis_y=axis_y,
        x_weights=x_weights,
        y_weights=y_weights,
    )


async def synthesize_quadrant(
    companies: list[dict[str, Any]],
    *,
    query_context: dict[str, Any] | None = None,
    scope: dict[str, Any] | None = None,
    settings: Settings | None = None,
    write_output: bool = True,
) -> dict[str, Any]:
    """
    Build CMI-shaped coherent quadrant JSON for exported landscape companies.
    """
    settings = settings or Settings.load()
    if not getattr(settings, "quadrant_enabled", True):
        return {}

    query_context = query_context or {}
    scope = scope or {}
    # Prefer the operator's own market string over the pipeline's normalised
    # search topic: it keys the AI Overview cache (shared with discovery), names
    # the output file, and reads better in the JSON and on the chart.
    from vendor_intel.evidence.ai_overview import resolve_market_key

    market = resolve_market_key(query_context, scope) or "market"
    geography = str(
        scope.get("geography")
        or (scope.get("geographies") or [None])[0]
        or query_context.get("country")
        or "global"
    ).strip()

    cfg = load_scoring_weights()
    # An explicit 0 means "score every relevant brand" and must not fall through to
    # the YAML default, so this cannot use `or`-chaining.
    _max = getattr(settings, "quadrant_max_companies", None)
    if _max is None:
        _max = cfg.get("max_companies", 12)
    max_n = int(_max)

    industry = select_industry(market, geography=geography, settings=settings)
    x_feats = list(industry.get("x") or [])
    y_feats = list(industry.get("y") or [])
    axis_x = str(industry.get("axis_x") or "Solution Capability")
    axis_y = str(industry.get("axis_y") or "Business Strategy")
    x_weights = feature_weights_for("x", len(x_feats))
    y_weights = feature_weights_for("y", len(y_feats))

    print(
        f"  [quadrant] industry={industry.get('industry_group')}/"
        f"{industry.get('industry_category')} "
        f"({industry.get('selection_method')}, conf={industry.get('confidence')})",
        flush=True,
    )

    client = ClaudeClient(settings)
    questions = generate_questions(
        market=market,
        geography=geography,
        industry_group=str(industry.get("industry_group") or ""),
        industry_category=str(industry.get("industry_category") or ""),
        x_features=x_feats,
        y_features=y_feats,
        axis_x=axis_x,
        axis_y=axis_y,
        settings=settings,
        client=client,
    )

    selected = _pick_companies(companies, max_n)
    conc = int(
        getattr(settings, "quadrant_brand_concurrency", 0)
        or cfg.get("brand_concurrency")
        or 6
    )
    conc = max(1, min(conc, 16))
    batch_mode = str(
        getattr(settings, "quadrant_qa_batch_mode", None)
        or cfg.get("qa_batch_mode")
        or "company"
    ).strip().lower()
    print(
        f"  [quadrant] scoring {len(selected)} brands "
        f"(concurrency={conc}, qa_batch={batch_mode})",
        flush=True,
    )

    sem = asyncio.Semaphore(conc)
    tasks = [
        _score_one_brand(
            idx=idx,
            row=row,
            market=market,
            questions=questions,
            settings=settings,
            client=client,
            batch_mode=batch_mode,
            x_feats=x_feats,
            y_feats=y_feats,
            axis_x=axis_x,
            axis_y=axis_y,
            x_weights=x_weights,
            y_weights=y_weights,
            sem=sem,
        )
        for idx, row in enumerate(selected)
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    brand_rows: list[dict[str, Any]] = []
    score_detail: list[FeatureScoreDetail] = []
    scorecard: list[ScorecardRow] = []
    evidence: list[EvidenceItem] = []
    for idx, res in enumerate(results):
        if isinstance(res, BaseException):
            name = str(
                (selected[idx].get("company") or selected[idx].get("brand") or "")
            ).strip()
            print(f"  [quadrant] brand failed ({name[:40]}): {res}", flush=True)
            continue
        brow, sd, sc, ev = res
        brand_rows.append(brow)
        score_detail.extend(sd)
        scorecard.extend(sc)
        evidence.extend(ev)

    # Relative quadrant placement (median midpoints) + optional relative tiers
    relative = bool(cfg.get("relative_quadrant", True))
    relative_tier = bool(cfg.get("relative_tier", relative))
    execs = [b["execution"] for b in brand_rows]
    innovs = [b["innovation"] for b in brand_rows]
    if relative and brand_rows:
        mid_x, mid_y = relative_midpoints(execs, innovs)
    else:
        mid = float(cfg.get("axis_midpoint") or 50)
        mid_x = mid_y = mid

    overalls = [
        compute_overall(b["execution"], b["innovation"]) for b in brand_rows
    ]
    if relative_tier and brand_rows:
        tier_labels = assign_tiers_relative(overalls)
    else:
        tier_labels = [overall_to_tier(o) for o in overalls]

    brands: list[QuadrantBrand] = []
    fill_mode = str(cfg.get("quadrant_fill_mode") or "half_median").strip().lower()
    if fill_mode in ("half_median", "half", "fill"):
        quad_labels, mid_x, mid_y = assign_quadrants_half_median(execs, innovs)
        chart_coords, chart_mid_x, chart_mid_y = chart_offsets_for_quadrants(
            execs, innovs, quad_labels
        )
    else:
        quad_labels = []
        for b in brand_rows:
            high_x = b["execution"] >= mid_x
            high_y = b["innovation"] >= mid_y
            if high_x and high_y:
                quad_labels.append("Leaders")
            elif not high_x and high_y:
                quad_labels.append("Challengers")
            elif high_x and not high_y:
                quad_labels.append("Trailblazers")
            else:
                quad_labels.append("Emerging Players")
        chart_stretch = bool(cfg.get("chart_stretch", True))
        chart_coords, chart_mid_x, chart_mid_y = chart_offsets_absolute(
            execs,
            innovs,
            stretch=chart_stretch,
            chart_low=float(cfg.get("chart_low") or 12),
            chart_high=float(cfg.get("chart_high") or 88),
            mid_x=mid_x,
            mid_y=mid_y,
            mode=str(cfg.get("chart_placement") or "rank"),
        )

    for bi, b in enumerate(brand_rows):
        overall = overalls[bi]
        top, left = chart_coords[bi]
        brands.append(
            QuadrantBrand(
                brand=b["brand"],
                quadrant=quad_labels[bi],  # type: ignore[arg-type]
                execution=b["execution"],
                innovation=b["innovation"],
                top_pct=top,
                left_pct=left,
                color=brand_color(int(b["index"])),
                tier=tier_labels[bi],  # type: ignore[arg-type]
                overall=overall,
                revenue=b["revenue"],
                yoy_growth=b["yoy_growth"],
                top_strength=b["top_strength"],
            )
        )

    weights_payload = {
        "x": {feat: round(w, 4) for feat, w in zip(x_feats, x_weights)},
        "y": {feat: round(w, 4) for feat, w in zip(y_feats, y_weights)},
    }
    payload = CoherentQuadrantPayload(
        market=market,
        geography=geography,
        industry_group=str(industry.get("industry_group") or ""),
        industry_category=str(industry.get("industry_category") or ""),
        criteria={
            "x_axis": x_feats,
            "y_axis": y_feats,
            "weights": weights_payload,
            "axis_labels": {"x": axis_x, "y": axis_y},
            "midpoints": {"x": round(chart_mid_x, 2), "y": round(chart_mid_y, 2)},
            "score_midpoints": {"x": round(mid_x, 2), "y": round(mid_y, 2)},
        },
        questions=questions,
        brands=brands,
        scorecard=scorecard,
        score_detail=score_detail,
        evidence=evidence,
        meta={
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "selection": {
                "method": industry.get("selection_method"),
                "confidence": industry.get("confidence"),
                "reason": industry.get("reason"),
            },
            "brand_count": len(brands),
            "kb_source": "pipeline_evidence_snapshot",
            "quadrant_web_search": False,
            "brand_concurrency": conc,
            "qa_batch_mode": batch_mode,
        },
    )
    result = payload.to_cmi_dict()

    out_path = ""
    if write_output:
        out_dir = _project_root() / "output" / "quadrant"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = str(out_dir / f"{_slug(market)}_quadrant.json")
        Path(out_path).write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        q_path = out_dir / f"{_slug(market)}_questions.json"
        q_path.write_text(
            json.dumps([q.model_dump() for q in questions], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        result["output_path"] = out_path
        result["questions_path"] = str(q_path)
        print(f"  [quadrant] wrote {out_path}", flush=True)

    return result
