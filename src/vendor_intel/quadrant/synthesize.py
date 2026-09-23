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
from vendor_intel.quadrant.brand_meta import (
    brand_display_fields,
    company_display_mode,
    extract_founded_year,
    plain_brand_name,
)
from vendor_intel.quadrant.company_kb import build_company_kb
from vendor_intel.quadrant.criteria_catalog import feature_weights_for, load_scoring_weights
from vendor_intel.quadrant.industry_select import select_industry
from vendor_intel.quadrant.matrix_rollup import (
    feature_contribution,
    normalize_scores_proportionally,
    scale_to_100,
    weighted_question_average,
)
from vendor_intel.quadrant.qa_scorer import score_company_features_async
from vendor_intel.quadrant.question_gen import generate_questions
from vendor_intel.quadrant.value_chain_filter import filter_direct_operators
from vendor_intel.quadrant.rating_map import (
    brand_color,
    chart_offsets_absolute,
    chart_offsets_for_quadrants,
    compute_overall,
    inner_cell_offsets,
    assign_quadrants_absolute_median,
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


def _commercial_filter(rows: list[dict[str, Any]], *, market: str = "") -> list[dict[str, Any]]:
    """Keep only companies a buyer actually chooses between.

    A quadrant compares competitors, so the supply chain behind them — contract
    manufacturers, material suppliers, pure resellers — does not belong on it even
    though it belongs in the landscape report.

    Roles:
    - Food / CPG (avocado oil, etc.): Brand, Marketer
    - Technology: Solution Developer
    Controlled by QUADRANT_ROLES (comma-separated); empty uses market-aware defaults;
    "all" scores every company.
    """
    import os

    raw = (os.getenv("QUADRANT_ROLES") or "").strip()
    if raw.lower() == "all":
        return rows
    if raw:
        keep = {r.strip() for r in raw.split(",") if r.strip()}
    else:
        try:
            from vendor_intel.quadrant.market_relevance import expected_roles_for_market

            keep = expected_roles_for_market(market)
        except Exception:
            keep = set()
    if not keep:
        return rows
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
            f"- scoring all instead (run relevance / brand-owner pass first)",
            flush=True,
        )
        return rows
    print(
        f"  [quadrant] role filter {sorted(keep)}: {len(filtered)} of {len(rows)} companies",
        flush=True,
    )
    return filtered


def _pick_companies(
    rows: list[dict[str, Any]], max_n: int, *, market: str = ""
) -> list[dict[str, Any]]:
    """Best-quality relevant rows, deduped by name. ``max_n <= 0`` scores everything."""
    rows = _commercial_filter(rows, market=market)
    scored = []
    for r in rows:
        if not r.get("is_relevant", True):
            continue
        if r.get("in_market") is False:
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


async def _kb_text_for_filter(row: dict[str, Any], *, market: str, settings: Settings) -> str:
    """Flatten a company's KB chunks to plain text for the operator-segment classifier."""
    kb = await build_company_kb(row, market=market, settings=settings, do_search=False)
    chunks = kb.get("chunks") or []
    return " ".join(str(c.get("text") or "") for c in chunks)[:3000]


_QUADRANT_ORDER = ("Leaders", "Challengers", "Trailblazers", "Emerging Players")


def _select_chart_balanced(
    quadrants: list[str], overalls: list[int], chart_n: int
) -> list[int]:
    """Pick chart_n row indices split ~evenly across the four quadrants.

    Within each quadrant, keeps the highest-overall brands first (same
    ranking rule as before) — only the "top N overall" step is now scoped per
    quadrant instead of across the whole cohort, so a quadrant that happens to
    score lower overall isn't crowded off the chart entirely.
    """
    groups: dict[str, list[int]] = {q: [] for q in _QUADRANT_ORDER}
    for i, q in enumerate(quadrants):
        groups.setdefault(q if q in groups else "Emerging Players", []).append(i)

    per_quad, remainder = divmod(max(0, chart_n), len(_QUADRANT_ORDER))
    picked: list[int] = []
    leftover: list[int] = []
    for qi, q in enumerate(_QUADRANT_ORDER):
        idxs = sorted(groups.get(q, []), key=lambda i: overalls[i], reverse=True)
        take = per_quad + (1 if qi < remainder else 0)
        picked.extend(idxs[:take])
        leftover.extend(idxs[take:])

    # A quadrant with fewer members than its share leaves the target short —
    # top up from the remaining highest-overall brands (any quadrant) so the
    # chart still shows chart_n brands when the cohort allows it.
    if len(picked) < chart_n:
        leftover.sort(key=lambda i: overalls[i], reverse=True)
        picked.extend(leftover[: chart_n - len(picked)])
    return picked


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
    row: dict[str, Any],
    kb: dict[str, Any],
    feature_results: list[dict[str, Any]],
    x_feats: list[str],
    y_feats: list[str],
    axis_x: str,
    axis_y: str,
    x_weights: list[float],
    y_weights: list[float],
    market: str = "",
    industry_group: str = "",
    industry_category: str = "",
    display_mode: str | None = None,
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

    # Raw axis scores (0-100). Population-level proportional normalization
    # (65-100, min-max scoped to this market's full company list) happens
    # once in synthesize_quadrant() after every brand in this run has been
    # scored — see normalize_scores_proportionally() there. Not applied here
    # per-brand: the population isn't complete yet at this point.
    execution = scale_to_100(sum(x_contribs))
    innovation = scale_to_100(sum(y_contribs))
    revenue = str(kb.get("revenue") or "")
    yoy = str(kb.get("yoy_growth") or "")
    if display_mode is None:
        display_mode = company_display_mode(
            market, industry_group=industry_group, industry_category=industry_category,
        )
    display_name, company_col, founded_location = brand_display_fields(
        row,
        market=market,
        industry_group=industry_group,
        industry_category=industry_category,
        mode=display_mode,
    )
    founded_year = extract_founded_year(row, kb=kb)
    if not founded_location:
        founded_location = str(row.get("founded_location") or row.get("hq_location") or "").strip()
    hq_location = str(row.get("hq_location") or "").strip()
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
    if founded_year:
        evidence.append(
            EvidenceItem(
                brand=brand,
                field="founded_year",
                status="retrieved",
                snippet=founded_year,
                method="kb_extract",
            )
        )
    if founded_location:
        evidence.append(
            EvidenceItem(
                brand=brand,
                field="founded_location",
                status="retrieved",
                snippet=founded_location,
                method="kb_extract",
            )
        )

    brand_row = {
        "brand": brand,
        # Chart / Brand column: plain name only (no "acquired by")
        "display_name": display_name or brand,
        # Company column: market-aware (provider name OR "(acquired by …)")
        "company": company_col,
        "company_display_mode": display_mode,
        # "Founded in" column shows location (not year)
        "founded_in": founded_location,
        "founded_location": founded_location,
        "hq_location": hq_location,
        "founded_year": founded_year,
        "execution": execution,
        "innovation": innovation,
        "revenue": revenue,
        "yoy_growth": yoy,
        "top_strength": _top_strength(feature_results),
        "commercial_role": str(row.get("commercial_role") or "").strip(),
        "company_function": str(row.get("company_function") or "").strip(),
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
    industry_group: str = "",
    industry_category: str = "",
) -> tuple[
    dict[str, Any],
    list[FeatureScoreDetail],
    list[ScorecardRow],
    list[EvidenceItem],
]:
    brand = plain_brand_name(row)
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
    display_mode = company_display_mode(
        market, industry_group=industry_group, industry_category=industry_category,
        settings=settings, client=client,
    )
    return _rollup_brand_scores(
        brand=brand,
        idx=idx,
        row=row,
        kb=kb,
        feature_results=feature_results,
        x_feats=x_feats,
        y_feats=y_feats,
        axis_x=axis_x,
        axis_y=axis_y,
        x_weights=x_weights,
        y_weights=y_weights,
        market=market,
        industry_group=industry_group,
        industry_category=industry_category,
        display_mode=display_mode,
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
    # Chart = top 15–20 scored brands; table can list many more (200+)
    _chart = getattr(settings, "quadrant_chart_companies", None)
    if _chart is None:
        _chart = getattr(settings, "quadrant_max_companies", None)
    if _chart is None:
        _chart = cfg.get("max_companies", 20)
    chart_n = max(1, min(int(_chart), 20))

    _table = getattr(settings, "quadrant_table_companies", None)
    if _table is None:
        _table = cfg.get("table_companies", 1000)
    table_n = max(chart_n, min(int(_table), 1000))
    score_all = bool(getattr(settings, "quadrant_score_all_table", True))
    # Score every table row when enabled; chart still shows top chart_n by overall
    max_n = table_n if score_all else chart_n

    industry = select_industry(market, geography=geography, settings=settings)
    from vendor_intel.quadrant.axis_define import define_market_axes

    industry = define_market_axes(
        market, industry, geography=geography, settings=settings
    )

    # Drop geo artifacts / off-market; tag Brand|Marketer (food) or Solution Developer (tech)
    try:
        from vendor_intel.quadrant.market_relevance import verify_market_companies

        companies, rel_stats = verify_market_companies(
            list(companies or []),
            market,
            settings=settings,
            industry_group=str(industry.get("industry_group") or ""),
            industry_category=str(industry.get("industry_category") or ""),
        )
        query_context = dict(query_context or {})
        query_context["relevance_stats"] = rel_stats
    except Exception as exc:
        print(f"  [quadrant] relevance filter skipped: {exc}", flush=True)

    x_feats = list(industry.get("x") or [])
    y_feats = list(industry.get("y") or [])
    axis_x = str(industry.get("axis_x") or "Product Strength")
    axis_y = str(industry.get("axis_y") or "Business Strategy")
    x_weights = feature_weights_for("x", len(x_feats))
    y_weights = feature_weights_for("y", len(y_feats))

    print(
        f"  [quadrant] industry={industry.get('industry_group')}/"
        f"{industry.get('industry_category')} "
        f"({industry.get('selection_method')}, conf={industry.get('confidence')}) "
        f"axes={axis_x!r} / {axis_y!r} "
        f"({industry.get('axis_definition_method') or 'catalog'})",
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

    table_rows = _pick_companies(companies, table_n, market=market)

    # Value-chain segment filter: keep only companies that directly operate the
    # capability this market's X-axis parameters describe (drops distributors,
    # traders/marketers, shippers, buyers/importers, and diversified investors
    # with no operational control), and collapse obvious parent/subsidiary
    # duplicates (a producer and its own trading arm, a parent and its owned
    # terminal) down to one representative row. Reuses each company's existing
    # KB text — no new web search.
    if bool(getattr(settings, "quadrant_operator_filter", True)) and table_rows:
        try:
            kb_texts = await asyncio.gather(
                *[_kb_text_for_filter(row, market=market, settings=settings) for row in table_rows]
            )
            before_n = len(table_rows)
            table_rows = await filter_direct_operators(
                table_rows,
                market=market,
                x_feats=x_feats,
                kb_texts=list(kb_texts),
                client=client,
                model=getattr(settings, "classifier_model", None),
            )
            print(
                f"  [quadrant] operator filter: {before_n} -> {len(table_rows)} "
                "direct-operator companies (segment filter + family dedup)",
                flush=True,
            )
        except Exception as exc:
            print(f"  [quadrant] operator filter skipped: {exc}", flush=True)

    selected = table_rows if score_all else _pick_companies(table_rows, chart_n, market=market)
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
        f"(score_all_table={score_all}, chart_cap={chart_n}, table≤{table_n}) · "
        f"concurrency={conc}, qa_batch={batch_mode}",
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
            industry_group=str(industry.get("industry_group") or ""),
            industry_category=str(industry.get("industry_category") or ""),
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

    # Proportional normalization — the complete scoring population for this
    # market (every brand that just finished scoring above) is available
    # now, for the first time. Scoped to THIS market only: X/Y criteria are
    # LLM-defined per market (axis_define.py), so one market's raw scores
    # are never on the same scale as another's — normalizing across markets
    # would be comparing unrelated criteria. Each of up to ~10,000 market
    # runs calls this independently on its own brand_rows; no cross-run
    # state, no shared min/max, so concurrent market runs can't interfere
    # with each other's normalization.
    if brand_rows:
        raw_execs = [b["execution"] for b in brand_rows]
        raw_innovs = [b["innovation"] for b in brand_rows]
        norm_execs = normalize_scores_proportionally(raw_execs)
        norm_innovs = normalize_scores_proportionally(raw_innovs)
        for b, nx, ny in zip(brand_rows, norm_execs, norm_innovs):
            b["execution"] = int(round(nx))
            b["innovation"] = int(round(ny))

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
        quad_labels, mid_x, mid_y = assign_quadrants_absolute_median(execs, innovs)
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
                display_name=str(b.get("display_name") or b["brand"]),
                company=str(b.get("company") or ""),
                founded_in=str(b.get("founded_in") or b.get("founded_location") or ""),
                founded_location=str(b.get("founded_location") or b.get("founded_in") or ""),
                hq_location=str(b.get("hq_location") or ""),
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
                on_chart=True,  # set below after ranking
                commercial_role=str(b.get("commercial_role") or ""),
                company_function=str(b.get("company_function") or ""),
            )
        )

    # Graph shows chart_n brands split evenly across the four quadrants (top by
    # overall within each quadrant), so the chart never skews toward whichever
    # quadrant happens to have the highest overall scores. Every scored row
    # keeps its real X/Y/quadrant in the table regardless of chart membership.
    if brands:
        chart_indices = _select_chart_balanced(
            [b.quadrant for b in brands],
            [b.overall for b in brands],
            chart_n,
        )
        chart_set = set(chart_indices)
        chart_quads = [brands[i].quadrant for i in chart_indices]
        chart_execs = [brands[i].execution for i in chart_indices]
        chart_innovs = [brands[i].innovation for i in chart_indices]
        if chart_execs:
            # Quadrant label is NOT recomputed here — it stays the brand's true,
            # full-cohort quadrant. Only the on-chart x/y placement (position
            # within that quadrant's cell) is derived from the chart subset.
            c_coords, chart_mid_x, chart_mid_y = chart_offsets_for_quadrants(
                chart_execs, chart_innovs, chart_quads
            )
            for local_i, bi in enumerate(chart_indices):
                brands[bi] = brands[bi].model_copy(
                    update={
                        "on_chart": True,
                        "top_pct": c_coords[local_i][0],
                        "left_pct": c_coords[local_i][1],
                    }
                )
        for bi, b in enumerate(brands):
            if bi not in chart_set:
                brands[bi] = b.model_copy(update={"on_chart": False})

    # Append remaining table brands only when we did not score the full table
    scored_keys = {str(b.brand).strip().lower() for b in brands}
    ig = str(industry.get("industry_group") or "")
    ic = str(industry.get("industry_category") or "")
    if not score_all:
        remaining_mode = company_display_mode(
            market, industry_group=ig, industry_category=ic, settings=settings, client=client
        )
        for ri, row in enumerate(table_rows):
            name = plain_brand_name(row)
            if not name or name.lower() in scored_keys:
                continue
            display_name, company_col, founded_location = brand_display_fields(
                row, market=market, industry_group=ig, industry_category=ic, mode=remaining_mode
            )
            brands.append(
                QuadrantBrand(
                    brand=name,
                    display_name=display_name or name,
                    company=company_col,
                    founded_in=founded_location or str(row.get("founded_location") or ""),
                    founded_location=founded_location or str(row.get("founded_location") or ""),
                    hq_location=str(row.get("hq_location") or ""),
                    quadrant="Emerging Players",  # type: ignore[arg-type]
                    execution=0,
                    innovation=0,
                    top_pct=50,
                    left_pct=50,
                    color=brand_color(1000 + ri),
                    tier="Tier 3",  # type: ignore[arg-type]
                    overall=0,
                    on_chart=False,
                )
            )
            scored_keys.add(name.lower())

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
            "parameter_definitions": industry.get("parameter_definitions")
            or {"x": {}, "y": {}},
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
            "chart_brand_count": sum(1 for b in brands if b.on_chart),
            "table_brand_count": len(brands),
            "chart_cap": chart_n,
            "table_cap": table_n,
            "score_all_table": score_all,
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
        slug = _slug(market)
        out_path = str(out_dir / f"{slug}_quadrant.json")
        Path(out_path).write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        q_path = out_dir / f"{slug}_questions.json"
        q_path.write_text(
            json.dumps([q.model_dump() for q in questions], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        csv_path = _write_companies_csv(out_dir / f"{slug}_companies.csv", brands)
        html_path = ""
        try:
            from vendor_intel.quadrant.html_report import write_quadrant_html_report

            html_path = write_quadrant_html_report(
                result, out_dir / f"{slug}_report.html", open_browser=False
            )
        except Exception as exc:
            print(f"  [quadrant] HTML report skipped: {exc}", flush=True)
        result["output_path"] = out_path
        result["questions_path"] = str(q_path)
        result["companies_csv_path"] = csv_path
        if html_path:
            result["html_report_path"] = html_path
        print(f"  [quadrant] wrote {out_path}", flush=True)
        if csv_path:
            print(f"  [quadrant] wrote {csv_path}", flush=True)
        if html_path:
            print(f"  [quadrant] wrote {html_path}", flush=True)

    return result


def _write_companies_csv(path: Path, brands: list[QuadrantBrand]) -> str:
    """Export Brand | Company | Quadrant | X | Y | Overall | Founded in (location)."""
    import csv

    try:
        with path.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(
                [
                    "Brand",
                    "Company",
                    "Quadrant",
                    "X",
                    "Y",
                    "Overall",
                    "Founded in",
                ]
            )
            for b in brands:
                w.writerow(
                    [
                        b.display_name or b.brand,
                        b.company or "",
                        b.quadrant,
                        b.execution,
                        b.innovation,
                        b.overall,
                        b.founded_location or b.founded_in or "",
                    ]
                )
        return str(path)
    except Exception as exc:
        print(f"  [quadrant] CSV export skipped: {exc}", flush=True)
        return ""
