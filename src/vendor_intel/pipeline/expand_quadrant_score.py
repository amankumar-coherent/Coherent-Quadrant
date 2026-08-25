"""Score ChatGPT-expand rows with the same X/Y/overall math as Coherent Quadrant.

X = Solution Capability (5 industry features, weighted)
Y = Business Strategy (5 industry features, weighted)
Overall = round((X + Y) / 2)

Feature lists come from config/quadrant_industry_criteria.yaml.
Weights come from config/quadrant_scoring_weights.yaml (matrix_slot_weights).
Each feature is scored 1–10 on 3 questions (weights 0.4 / 0.3 / 0.3), then:

  sub_avg       = Σ(question_weight × score)
  contribution  = feature_weight × (sub_avg / 10)
  axis_0_100    = round(Σ(contributions) × 100)
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Any
from urllib.parse import urlparse

from vendor_intel.config import Settings
from vendor_intel.quadrant.criteria_catalog import feature_weights_for, load_scoring_weights
from vendor_intel.quadrant.industry_select import select_industry
from vendor_intel.quadrant.matrix_rollup import feature_contribution, scale_to_100, weighted_question_average
from vendor_intel.quadrant.question_gen import generate_questions
from vendor_intel.quadrant.rating_map import (
    assign_quadrants_absolute_median,
    compute_overall,
    sub_avg_to_rating,
)

SCORE_COLUMNS = (
    "X Score",
    "Y Score",
    "Overall Score",
    "Quadrant",
    "Industry Category",
)

# User-requested Company Details table (Brand | Company | Quadrant | X | Y | Overall | Found in)
# Role is included so Brand/Marketer vs Solution Provider is visible in the same sheet.
DETAIL_COLUMNS = (
    "Brand",
    "Company",
    "Role",
    "Quadrant",
    "X",
    "Y",
    "Overall",
    "Found in",
)


def _log(msg: str) -> None:
    print(msg, flush=True)


def _domain(website: str) -> str:
    raw = (website or "").strip()
    if not raw:
        return ""
    try:
        host = urlparse(raw if "://" in raw else f"https://{raw}").netloc.lower()
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return ""


_EMPTY = frozenset(
    {
        "",
        "n/a",
        "na",
        "none",
        "-",
        "—",
        "not publicly disclosed",
        "unknown",
    }
)


def _filled(val: Any) -> str:
    s = str(val or "").strip()
    if not s or s.lower() in _EMPTY:
        return ""
    return s


def kb_from_landscape_row(row: dict[str, Any]) -> dict[str, Any]:
    """Excel columns only — used when crawl is skipped or fails."""
    parts: list[str] = []
    for key, val in row.items():
        if key in SCORE_COLUMNS or str(key).startswith("_"):
            continue
        s = _filled(val)
        if s:
            parts.append(f"{key}: {s}")
    text = "\n".join(parts)
    name = str(row.get("Company") or "").strip()
    website = str(row.get("Website") or "").strip()
    return {
        "brand": name,
        "domain": _domain(website),
        "chunks": [{"source_url": website, "text": text or f"{name} {website}"}],
        "revenue": "",
        "yoy_growth": "",
    }


def _scoring_row(row: dict[str, str]) -> dict[str, Any]:
    """Shape a landscape Excel row for build_company_kb + smart_crawl."""
    name = str(row.get("Company") or "").strip()
    website = str(row.get("Website") or "").strip()
    summary_bits = [
        _filled(row.get("Summary")),
        _filled(row.get("Specialty Focus")),
        _filled(row.get("Core Categories")),
        _filled(row.get("Key Brands Represented")),
        _filled(row.get("Operational Presence")),
        _filled(row.get("Headquarters")),
    ]
    return {
        "company": name,
        "brand": name,
        "website": website,
        "domain": _domain(website),
        "summary": " | ".join(b for b in summary_bits if b),
        "company_summary": _filled(row.get("Summary")),
        "key_products": _filled(row.get("Core Categories")),
        "role_description": _filled(row.get("Distribution Type")),
        "evidence_snapshot": row.get("_evidence_snapshot"),
    }


def _backfill_from_snapshot(row: dict[str, str], snap: dict[str, Any]) -> None:
    """Fill empty landscape cells from crawl INTEL when Google AI left them blank."""
    data = snap.get("data") if isinstance(snap.get("data"), dict) else {}
    company = data.get("company") if isinstance(data.get("company"), dict) else {}
    location = data.get("location") if isinstance(data.get("location"), dict) else {}
    financials = data.get("financials") if isinstance(data.get("financials"), dict) else {}
    intel = data.get("intel") if isinstance(data.get("intel"), dict) else {}

    fy = str(company.get("founded_year") or company.get("founded") or "").strip()
    if fy and not _filled(row.get("Founded")):
        row["Founded"] = fy
    hq = str(location.get("headquarters") or "").strip()
    if hq and not _filled(row.get("Headquarters")):
        row["Headquarters"] = hq
    emp = str(financials.get("employee_count") or "").strip()
    if emp and not _filled(row.get("Employees")):
        row["Employees"] = emp
    summ = str(intel.get("summary") or "").strip()
    if summ and not _filled(row.get("Summary")):
        row["Summary"] = summ[:500]


async def _deep_crawl_rows(
    rows: list[dict[str, str]],
    *,
    country: str,
    settings: Settings,
) -> dict[str, int]:
    """smart_crawl every company (business mode) and attach evidence_snapshot."""
    from vendor_intel.enrichment.smart_enrichment import clear_enrichment_cache, enrich_companies
    from vendor_intel.pipeline.chatgpt_env import apply_chatgpt_expand_env
    from vendor_intel.quadrant.snapshot import build_evidence_snapshot

    apply_chatgpt_expand_env()
    batch: list[dict[str, str]] = []
    for row in rows:
        name = str(row.get("Company") or "").strip()
        dom = _domain(str(row.get("Website") or ""))
        if name and dom:
            batch.append({"name": name, "domain": dom})
    stats = {
        "crawled": 0,
        "ok": 0,
        "fail": 0,
        "skipped_no_domain": len(rows) - len(batch),
    }
    if not batch:
        return stats

    crawl_mode = (
        str(getattr(settings, "quadrant_crawl_mode", None) or "business").strip() or "business"
    )
    max_pages = int(getattr(settings, "quadrant_crawl_max_pages", 0) or 60)
    concurrent = int(os.getenv("EXPAND_XY_CRAWL_CONCURRENT") or "6")
    _log(
        f"  [xy] deep-crawling {len(batch)} companies "
        f"(smart_crawl mode={crawl_mode}, max_pages={max_pages}, concurrent={concurrent})"
    )
    clear_enrichment_cache()
    enriched = await enrich_companies(
        batch,
        limit=len(batch),
        max_concurrent=max(1, min(concurrent, 8)),
        country=country,
        use_ssc=False,
        crawl_mode=crawl_mode,
        max_pages=max_pages,
    )
    stats["crawled"] = len(batch)
    for row in rows:
        name = str(row.get("Company") or "").strip()
        dom = _domain(str(row.get("Website") or ""))
        smart = enriched.get(name) or enriched.get(dom)
        if not isinstance(smart, dict) or smart.get("error"):
            stats["fail"] += 1
            continue
        score_row = _scoring_row(row)
        snap = build_evidence_snapshot(smart, score_row, score_row)
        row["_evidence_snapshot"] = snap
        _backfill_from_snapshot(row, snap)
        stats["ok"] += 1
    _log(
        f"  [xy] crawl done: ok={stats['ok']} fail={stats['fail']} "
        f"no_domain={stats['skipped_no_domain']}"
    )
    return stats


def _axis_score(
    feature_results: list[dict[str, Any]],
    features: list[str],
    weights: list[float],
    axis_label: str,
) -> tuple[int, list[dict[str, Any]]]:
    contribs = [0.0] * len(features)
    detail: list[dict[str, Any]] = []
    fmap = {f: i for i, f in enumerate(features)}
    for fr in feature_results:
        feat = str(fr.get("feature") or "")
        if feat not in fmap:
            continue
        i = fmap[feat]
        sub = weighted_question_average(fr.get("scores") or [], fr.get("weights") or [])
        contribs[i] = feature_contribution(weights[i], sub)
        detail.append(
            {
                "feature": feat,
                "axis": axis_label,
                "weight": round(float(weights[i]), 4),
                "sub_avg": round(sub, 4),
                "contribution": round(contribs[i], 6),
                "rating": sub_avg_to_rating(sub),
            }
        )
    return scale_to_100(sum(contribs)), detail


def _filter_rows_by_player_type(
    rows: list[dict[str, str]],
    query: str,
    *,
    industry_group: str,
    industry_category: str,
    settings: Settings,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Drop companies whose role doesn't match this market's player type.

    Same gate synthesize_quadrant() applies via market_relevance.py
    (hardware -> Manufacturer only; software / system-integration ->
    Solution Developer / Service Provider / System Integrator only; else
    -> Brand / Marketer only) — run here too so the chatgpt_expand report
    reflects it without a separate manual "run_quadrant_from_chatgpt_
    checkpoint.py" step.
    """
    from vendor_intel.quadrant.brand_meta import plain_brand_name
    from vendor_intel.quadrant.market_relevance import verify_market_companies

    if not rows:
        return rows, {}

    adapted = [
        {
            "company": (company := str(r.get("Company") or "").strip()),
            "company_raw": company,
            "brand": company,
            "ai_overview_note": str(r.get("Summary") or r.get("Specialty Focus") or "").strip(),
            "summary": str(r.get("Summary") or "").strip(),
        }
        for r in rows
    ]

    kept, stats = verify_market_companies(
        adapted,
        query,
        settings=settings,
        industry_group=industry_group,
        industry_category=industry_category,
    )
    role_by_key = {
        re.sub(r"[^a-z0-9]", "", plain_brand_name(r).lower()): r.get("commercial_role")
        for r in kept
    }
    filtered: list[dict[str, str]] = []
    for r in rows:
        key = re.sub(r"[^a-z0-9]", "", plain_brand_name(str(r.get("Company") or "")).lower())
        role = role_by_key.get(key)
        if not role:
            continue
        r["Distribution Type"] = role
        r["Role"] = role
        filtered.append(r)
    _log(
        f"  [xy] player-type filter ({stats.get('player_type')}): "
        f"{len(rows)} -> {len(filtered)} companies (roles={stats.get('keep_roles')})"
    )
    return filtered, stats


async def score_expand_rows(
    rows: list[dict[str, str]],
    query: str,
    *,
    country: str = "global",
    concurrent: int = 4,
    ckpt: Any = None,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Attach X/Y/overall/quadrant using Coherent Quadrant criteria + rollup."""
    if not rows:
        return rows, {"scored": 0}

    def _has_xy(row: dict[str, Any]) -> bool:
        return bool(str(row.get("X Score") or "").strip()) and bool(
            str(row.get("Y Score") or "").strip()
        )

    def _slim(row: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in row.items() if not str(k).startswith("_")}

    if ckpt:
        prior = {
            str(r.get("Company") or "").strip().lower(): r
            for r in (ckpt.data("xy_partial") or [])
            if isinstance(r, dict) and r.get("Company")
        }
        for row in rows:
            key = str(row.get("Company") or "").strip().lower()
            old = prior.get(key)
            if old and _has_xy(old) and not _has_xy(row):
                for col in SCORE_COLUMNS:
                    if old.get(col):
                        row[col] = old[col]

    settings = Settings.load()
    industry = select_industry(query, geography=country, settings=settings)
    from vendor_intel.quadrant.axis_define import define_market_axes

    industry = define_market_axes(
        query, industry, geography=country, settings=settings
    )
    x_feats = list(industry.get("x") or [])
    y_feats = list(industry.get("y") or [])
    axis_x = str(industry.get("axis_x") or "Solution Capability")
    axis_y = str(industry.get("axis_y") or "Business Strategy")
    group = str(industry.get("industry_group") or "")
    category = str(industry.get("industry_category") or "")

    rows, relevance_stats = _filter_rows_by_player_type(
        rows, query, industry_group=group, industry_category=category, settings=settings,
    )
    if not rows:
        _log("  [xy] player-type filter dropped every row — nothing left to score")
        return rows, {"scored": 0, "relevance": relevance_stats}

    x_weights = feature_weights_for("x", len(x_feats))
    y_weights = feature_weights_for("y", len(y_feats))
    cfg = load_scoring_weights()
    q_weights = [float(w) for w in (cfg.get("default_question_weights") or [0.4, 0.3, 0.3])]

    _log(
        f"  [xy] industry={group}/{category} "
        f"axis_def={industry.get('axis_definition_method') or 'catalog'} | "
        f"X={axis_x} {x_feats} | Y={axis_y} {y_feats}"
    )
    _log(
        f"  [xy] weights X={ [round(w, 2) for w in x_weights] } "
        f"Y={ [round(w, 2) for w in y_weights] } "
        f"questions/feature={cfg.get('questions_per_feature') or 3} {q_weights} "
        f"| overall=(X+Y)/2"
    )

    from vendor_intel.clients.claude import ClaudeClient
    from vendor_intel.quadrant.company_kb import build_company_kb, kb_text_blob
    from vendor_intel.quadrant.qa_scorer import score_company_features_async

    skip_crawl = (os.getenv("EXPAND_XY_SKIP_CRAWL") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    crawl_stats: dict[str, int] = {"crawled": 0, "ok": 0, "fail": 0, "skipped_no_domain": 0}
    need_score = [r for r in rows if not _has_xy(r)]
    if skip_crawl:
        _log("  [xy] crawl SKIPPED (EXPAND_XY_SKIP_CRAWL)")
        if ckpt:
            ckpt.bump("6c_xy", "6c_crawl", note="crawl skipped")
    elif not need_score:
        _log("  [xy] crawl SKIPPED (all rows already scored in checkpoint)")
        if ckpt:
            ckpt.bump("6c_xy", "6c_crawl", note="crawl skipped — already scored")
    else:
        if ckpt:
            ckpt.begin("6c_xy", "6c_crawl", note=f"begin crawl {len(need_score)} companies")
        crawl_stats = await _deep_crawl_rows(need_score, country=country, settings=settings)
        if ckpt:
            ckpt.bump(
                "6c_xy",
                "6c_crawl",
                progress={"xy_crawled": crawl_stats.get("ok", 0)},
                note=f"crawl done ok={crawl_stats.get('ok')}",
            )

    client = ClaudeClient(settings)
    questions = generate_questions(
        market=query,
        geography=country,
        industry_group=group,
        industry_category=category,
        x_features=x_feats,
        y_features=y_feats,
        axis_x=axis_x,
        axis_y=axis_y,
        settings=settings,
        client=client,
    )

    sem = asyncio.Semaphore(max(1, int(os.getenv("EXPAND_XY_CONCURRENT") or concurrent)))
    meta: list[dict[str, Any]] = [{} for _ in rows]
    lock = asyncio.Lock()
    scored_n = sum(1 for r in rows if _has_xy(r))
    if ckpt:
        ckpt.begin(
            "6c_xy",
            "6c_score",
            note=f"begin score {len(need_score)} remaining / {len(rows)} total",
        )

    async def _one(i: int, row: dict[str, str]) -> None:
        nonlocal scored_n
        if _has_xy(row):
            meta[i] = {
                "company": row.get("Company"),
                "x": int(str(row.get("X Score") or 0) or 0),
                "y": int(str(row.get("Y Score") or 0) or 0),
                "overall": int(str(row.get("Overall Score") or 0) or 0),
                "kb_chars": 0,
                "crawled": False,
                "resumed": True,
            }
            return
        async with sem:
            name = str(row.get("Company") or "")[:50]
            _log(f"    → [xy] score {i + 1}/{len(rows)} {name}")
            score_row = _scoring_row(row)
            try:
                kb = await build_company_kb(
                    score_row, market=query, settings=settings, do_search=False
                )
            except Exception:
                kb = kb_from_landscape_row(row)
            kb_chars = len(kb_text_blob(kb, max_chars=24000))
            if kb_chars < 200:
                excel_kb = kb_from_landscape_row(row)
                kb["chunks"] = list(excel_kb.get("chunks") or []) + list(kb.get("chunks") or [])
                kb_chars = len(kb_text_blob(kb, max_chars=24000))
            try:
                feature_results = await score_company_features_async(
                    kb,
                    questions,
                    settings=settings,
                    client=client,
                    batch_mode="company",
                )
            except Exception as exc:
                _log(f"    → [xy] fail {name}: {type(exc).__name__}: {exc}")
                feature_results = []
            x_score, x_detail = _axis_score(feature_results, x_feats, x_weights, axis_x)
            y_score, y_detail = _axis_score(feature_results, y_feats, y_weights, axis_y)
            overall = compute_overall(x_score, y_score)
            meta[i] = {
                "company": row.get("Company"),
                "x": x_score,
                "y": y_score,
                "overall": overall,
                "kb_chars": kb_chars,
                "crawled": bool(row.get("_evidence_snapshot")),
                "x_features": x_detail,
                "y_features": y_detail,
            }
            row["X Score"] = str(x_score)
            row["Y Score"] = str(y_score)
            row["Overall Score"] = str(overall)
            row["Industry Category"] = f"{group} / {category}"
            async with lock:
                scored_n += 1
                if ckpt:
                    ckpt.bump(
                        "6c_xy",
                        f"6c.{i + 1}",
                        progress={"xy_scored": scored_n, "xy_total": len(rows)},
                        xy_partial=[_slim(r) for r in rows if _has_xy(r)],
                        note=f"scored {scored_n}/{len(rows)} {name}",
                    )

    await asyncio.gather(*[_one(i, r) for i, r in enumerate(rows)])

    if ckpt:
        ckpt.begin("6c_xy", "6c_quadrant", note="begin quadrant assignment")

    xs = [int(r.get("X Score") or 0) for r in rows]
    ys = [int(r.get("Y Score") or 0) for r in rows]
    quads, mid_x, mid_y = assign_quadrants_absolute_median(xs, ys)
    for r, q in zip(rows, quads):
        r["Quadrant"] = q
        key = str(r.get("Company") or "")
        for m in meta:
            if m.get("company") == key:
                m["quadrant"] = q
                break

    if ckpt:
        ckpt.bump(
            "6c_xy",
            "6c_quadrant",
            xy_partial=[_slim(r) for r in rows],
            note="quadrants assigned",
        )

    audit = {
        "industry_group": group,
        "industry_category": category,
        "axis_x": axis_x,
        "axis_y": axis_y,
        "axis_definition_method": industry.get("axis_definition_method") or "catalog",
        "axis_definition_reason": industry.get("axis_definition_reason") or "",
        "parameter_definitions": industry.get("parameter_definitions") or {"x": {}, "y": {}},
        "x_features": x_feats,
        "y_features": y_feats,
        "x_feature_weights": [round(w, 4) for w in x_weights],
        "y_feature_weights": [round(w, 4) for w in y_weights],
        "question_weights": q_weights,
        "overall_formula": "(X + Y) / 2",
        "quadrant_mid_x": mid_x,
        "quadrant_mid_y": mid_y,
        "scored": len(rows),
        "crawl": crawl_stats,
        "rows": meta,
        "relevance": relevance_stats,
    }
    return rows, audit


def _int_score(val: Any) -> int:
    raw = str(val or "").strip()
    if not raw:
        return 0
    token = raw.split()[0]
    try:
        return int(round(float(token or 0)))
    except (TypeError, ValueError):
        return 0


_QUAD_ORDER = ("Leaders", "Challengers", "Trailblazers", "Emerging Players")


def country_from_hq(hq: str) -> str:
    """Best-effort country token from a Headquarters string."""
    text = str(hq or "").strip()
    if not text or text.lower() in {"not publicly disclosed", "n/a", "unknown", "-"}:
        return "Unknown"
    # Prefer last comma segment: "Zurich, Switzerland" / "Evansville, IN, USA"
    parts = [p.strip() for p in text.split(",") if p.strip()]
    if not parts:
        return "Unknown"
    last = parts[-1]
    # US state abbreviations → United States when previous looks like a city/state
    us_states = {
        "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga", "hi", "id", "il",
        "in", "ia", "ks", "ky", "la", "me", "md", "ma", "mi", "mn", "ms", "mo", "mt",
        "ne", "nv", "nh", "nj", "nm", "ny", "nc", "nd", "oh", "ok", "or", "pa", "ri",
        "sc", "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv", "wi", "wy", "dc",
    }
    low = last.lower().rstrip(".")
    if low in {"usa", "u.s.", "u.s.a.", "us", "united states", "united states of america"}:
        return "United States"
    if low in {"uk", "u.k.", "united kingdom", "england", "scotland", "wales"}:
        return "United Kingdom"
    if low in us_states or (len(low) == 2 and low.isalpha() and low in us_states):
        return "United States"
    # Strip trailing postal codes
    last = re.sub(r"\b\d{4,6}\b", "", last).strip(" -")
    return last or "Unknown"


def select_chart_rows_by_quadrant_country(
    detail_rows: list[dict[str, Any]],
    *,
    chart_n: int = 20,
) -> list[dict[str, Any]]:
    """Pick chart companies so each quadrant is filled and countries are diversified.

    Within each quadrant, prefer brands with clearer High/Lower separation vs cohort
    medians (official Coherent criteria), then Overall — so chart exemplars are not
    stacked on the midlines.
    """
    chart_n = max(4, int(chart_n or 20))
    per_quad = max(1, chart_n // 4)
    # leftover slots (e.g. chart_n=18 → 4+4+5+5) go to Leaders then Challengers…
    leftover = chart_n - per_quad * 4

    xs_all = [_int_score(r.get("X")) for r in detail_rows]
    ys_all = [_int_score(r.get("Y")) for r in detail_rows]
    mid_x = sorted(xs_all)[len(xs_all) // 2] if xs_all else 50
    mid_y = sorted(ys_all)[len(ys_all) // 2] if ys_all else 50

    by_quad: dict[str, list[dict[str, Any]]] = {q: [] for q in _QUAD_ORDER}
    for row in detail_rows:
        q = str(row.get("Quadrant") or "").strip() or "Emerging Players"
        if q not in by_quad:
            by_quad[q] = []
        by_quad[q].append(row)

    selected: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _key(row: dict[str, Any]) -> str:
        return str(row.get("Brand") or row.get("Company") or "").strip().lower()

    def _clear_level_key(row: dict[str, Any], quad: str) -> tuple[float, float]:
        """Prefer clearer High/Lower margins per Coherent criteria, then Overall."""
        x = _int_score(row.get("X"))
        y = _int_score(row.get("Y"))
        o = _int_score(row.get("Overall"))
        if quad == "Leaders":
            # High P&P + High GTM — maximize the weaker High margin
            return (-min(x - mid_x, y - mid_y), -o)
        if quad == "Challengers":
            # Lower P&P + High GTM
            return (-min(mid_x - x, y - mid_y), -o)
        if quad == "Trailblazers":
            # High P&P + Lower GTM
            return (-min(x - mid_x, mid_y - y), -o)
        # Emerging: Lower + Lower — keep recognizable names via Overall first
        return (-o, -min(mid_x - x, mid_y - y))

    for qi, quad in enumerate(_QUAD_ORDER):
        want = per_quad + (1 if qi < leftover else 0)
        pool = sorted(
            by_quad.get(quad) or [],
            key=lambda r, q=quad: _clear_level_key(r, q),
        )
        # country -> remaining rows (already level-clarity sorted)
        buckets: dict[str, list[dict[str, Any]]] = {}
        order: list[str] = []
        for row in pool:
            meta = row.get("_meta") if isinstance(row.get("_meta"), dict) else {}
            ctry = country_from_hq(
                str(
                    meta.get("hq_location")
                    or row.get("Headquarters")
                    or row.get("Found in")
                    or ""
                )
            )
            if ctry not in buckets:
                buckets[ctry] = []
                order.append(ctry)
            buckets[ctry].append(row)

        picked = 0
        # Round-robin countries so one country does not fill the quadrant
        while picked < want and any(buckets.values()):
            progress = False
            for ctry in list(order):
                if picked >= want:
                    break
                bucket = buckets.get(ctry) or []
                while bucket:
                    row = bucket.pop(0)
                    k = _key(row)
                    if not k or k in seen:
                        continue
                    seen.add(k)
                    selected.append(row)
                    picked += 1
                    progress = True
                    break
                if not bucket and ctry in buckets:
                    buckets.pop(ctry, None)
            if not progress:
                break

        # Fill remaining slots from this quadrant if countries exhausted early
        if picked < want:
            for row in pool:
                if picked >= want:
                    break
                k = _key(row)
                if not k or k in seen:
                    continue
                seen.add(k)
                selected.append(row)
                picked += 1

    # If some quadrants were empty, top up from leftover high-Overall rows
    if len(selected) < chart_n:
        for row in sorted(detail_rows, key=lambda r: -_int_score(r.get("Overall"))):
            if len(selected) >= chart_n:
                break
            k = _key(row)
            if not k or k in seen:
                continue
            seen.add(k)
            selected.append(row)

    return selected


def _landscape_to_brand_row(
    row: dict[str, Any], query: str, audit: dict[str, Any] | None
) -> tuple[dict[str, Any], str, str]:
    """Map a filled landscape Excel row onto brand_display_fields inputs."""
    from vendor_intel.quadrant.brand_meta import extract_founded_year

    name = str(row.get("Company") or row.get("Brand") or "").strip()
    ownership = str(row.get("Ownership") or row.get("parent") or "").strip()
    founded = str(row.get("Founded") or row.get("Founded in") or "").strip()
    hq = str(row.get("Headquarters") or "").strip()
    role = str(row.get("Distribution Type") or row.get("Role") or "").strip()
    if not role or role.strip().lower() in {
        "brand / marketer",
        "brand/marketer",
        "brand and marketer",
    }:
        from vendor_intel.pipeline.role_split import normalize_role_label
        from vendor_intel.quadrant.market_relevance import classify_player_type

        player_type = classify_player_type(
            query,
            industry_group=str((audit or {}).get("industry_group") or ""),
            industry_category=str((audit or {}).get("industry_category") or ""),
        )
        if player_type == "hardware":
            role = "Manufacturer"
        elif player_type == "software_service":
            role = "Solution Provider"
        else:
            role = normalize_role_label(
                role or "Brand",
                query=query,
                company=name,
                brand=name,
            )
    else:
        from vendor_intel.pipeline.role_split import normalize_role_label

        role = normalize_role_label(role, query=query, company=name, brand=name)
    meta: dict[str, Any] = {
        "company": name,
        "company_raw": name,
        "brand": name,
        "parent": ownership,
        "parent_or_independent": ownership,
        "parent_owner": str(row.get("parent_owner") or "").strip(),
        "ownership_relation": str(row.get("ownership_relation") or "").strip(),
        "founded_in": founded,
        "founded_year": founded,
        "hq_location": hq,
        "founded_location": hq,
        "evidence_snapshot": row.get("_evidence_snapshot"),
        "commercial_role": role,
        "legal_name": name,
    }
    year = extract_founded_year(meta) or founded
    if year and not hq:
        meta["founded_location"] = ""
    return meta, year, role


def to_company_detail_rows(
    rows: list[dict[str, Any]],
    query: str,
    audit: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Brand | Company | Role | Quadrant | X | Y | Overall | Found in (location).

    Company column uses brand_display_fields: ``(acquired by Parent)`` for
    consumer/brand markets, parent/provider name for tech solution providers.
    ``Found in`` is HQ / founding location — never the year.
    Sorted by Overall descending.
    """
    from vendor_intel.quadrant.brand_meta import brand_display_fields

    audit = audit or {}
    group = str(audit.get("industry_group") or "")
    category = str(audit.get("industry_category") or "")
    out: list[dict[str, Any]] = []
    for row in rows:
        meta, _year, role = _landscape_to_brand_row(row, query, audit)
        brand, company_col, founded_loc = brand_display_fields(
            meta,
            market=query,
            industry_group=group,
            industry_category=category,
        )
        # Location only (HQ / founded place) — never prefer year; prefer City, Country
        from vendor_intel.enrichment.hq_city_country import (
            is_city_country,
            normalize_city_country,
        )

        found_in = (
            founded_loc
            or str(meta.get("hq_location") or "").strip()
            or str(row.get("Headquarters") or "").strip()
            or str(row.get("Founded location") or row.get("Found in") or "").strip()
        )
        # If legacy cell still holds a bare year, drop it
        if found_in.isdigit() and len(found_in) == 4:
            found_in = str(meta.get("hq_location") or row.get("Headquarters") or "").strip()
        found_in = normalize_city_country(found_in) or (
            found_in if is_city_country(found_in) else ""
        )
        x = _int_score(row.get("X Score") or row.get("X"))
        y = _int_score(row.get("Y Score") or row.get("Y"))
        overall = _int_score(row.get("Overall Score") or row.get("Overall"))
        if not overall and (x or y):
            overall = int(round((x + y) / 2.0))
        out.append(
            {
                "Brand": brand,
                "Company": company_col or brand,
                "Role": role,
                "Quadrant": str(row.get("Quadrant") or "").strip(),
                "X": x,
                "Y": y,
                "Overall": overall,
                "Found in": found_in,
                "_meta": meta,
            }
        )
    out.sort(key=lambda r: (-int(r.get("Overall") or 0), str(r.get("Brand") or "")))
    return out


def build_expand_quadrant_payload(
    detail_rows: list[dict[str, Any]],
    query: str,
    *,
    country: str = "global",
    audit: dict[str, Any] | None = None,
    chart_n: int = 20,
) -> dict[str, Any]:
    """JSON payload for the Coherent Quadrant HTML report (graph = top 20)."""
    from vendor_intel.quadrant.rating_map import (
        assign_tiers_relative,
        brand_color,
        chart_offsets_for_quadrants,
    )

    audit = audit or {}
    chart_n = max(1, int(chart_n or 20))
    brands: list[dict[str, Any]] = []
    # Chart: ~equal per quadrant + country diversity (not global top-N → all Leaders)
    chart_slice = select_chart_rows_by_quadrant_country(detail_rows, chart_n=chart_n)
    chart_keys = {
        str(r.get("Brand") or r.get("Company") or "").strip().lower() for r in chart_slice
    }
    execs = [_int_score(r.get("X")) for r in chart_slice]
    innovs = [_int_score(r.get("Y")) for r in chart_slice]
    quads = [str(r.get("Quadrant") or "Emerging Players") for r in chart_slice]
    coords: list[tuple[int, int]] = [(50, 50)] * len(chart_slice)
    if chart_slice:
        coords, _, _ = chart_offsets_for_quadrants(execs, innovs, quads)
    overalls = [_int_score(r.get("Overall")) for r in chart_slice]
    tiers = assign_tiers_relative(overalls) if overalls else []
    coord_by_key = {
        str(r.get("Brand") or r.get("Company") or "").strip().lower(): (
            coords[i] if i < len(coords) else (50, 50),
            tiers[i] if i < len(tiers) else "Tier 3",
            i,
        )
        for i, r in enumerate(chart_slice)
    }

    for i, row in enumerate(detail_rows):
        key = str(row.get("Brand") or row.get("Company") or "").strip().lower()
        on_chart = key in chart_keys
        top, left = (50, 50)
        tier = "Tier 3"
        color_i = i
        if on_chart and key in coord_by_key:
            (top, left), tier, color_i = coord_by_key[key]
        meta = row.get("_meta") if isinstance(row.get("_meta"), dict) else {}
        hq = str(meta.get("hq_location") or row.get("Headquarters") or "")
        brands.append(
            {
                "brand": row.get("Brand") or "",
                "display_name": row.get("Brand") or "",
                "company": row.get("Company") or "",
                "commercial_role": row.get("Role") or "",
                "founded_in": row.get("Found in") or row.get("Founded in") or "",
                "founded_location": row.get("Found in")
                or row.get("Founded in")
                or str(meta.get("hq_location") or ""),
                "hq_location": hq,
                "country": country_from_hq(hq),
                "quadrant": row.get("Quadrant") or "",
                "execution": _int_score(row.get("X")),
                "innovation": _int_score(row.get("Y")),
                "overall": _int_score(row.get("Overall")),
                "tier": tier,
                "top_pct": top,
                "left_pct": left,
                "color": brand_color(color_i),
                "on_chart": on_chart,
                "company_display_mode": "",
            }
        )

    scorecard: list[dict[str, Any]] = []
    axis_x = str(audit.get("axis_x") or "Solution Capability")
    axis_y = str(audit.get("axis_y") or "Business Strategy")
    by_name = {
        str(m.get("company") or "").strip().lower(): m
        for m in (audit.get("rows") or [])
        if isinstance(m, dict)
    }
    for row in chart_slice:
        key = str(row.get("Brand") or "").strip().lower()
        m = by_name.get(key) or {}
        for feat in m.get("x_features") or []:
            scorecard.append(
                {
                    "brand": row.get("Brand"),
                    "axis": axis_x,
                    "criterion": feat.get("feature"),
                    "rating": feat.get("rating") or "average",
                }
            )
        for feat in m.get("y_features") or []:
            scorecard.append(
                {
                    "brand": row.get("Brand"),
                    "axis": axis_y,
                    "criterion": feat.get("feature"),
                    "rating": feat.get("rating") or "average",
                }
            )

    return {
        "schema_version": "cmi-quadrant-v1",
        "market": query,
        "geography": country,
        "industry_group": audit.get("industry_group") or "",
        "industry_category": audit.get("industry_category") or "",
        "criteria": {
            "axis_labels": {"x": axis_x, "y": axis_y},
            "x_axis": list(audit.get("x_features") or []),
            "y_axis": list(audit.get("y_features") or []),
            "parameter_definitions": audit.get("parameter_definitions")
            or {"x": {}, "y": {}},
            "midpoints": {
                "x": audit.get("quadrant_mid_x") or 50,
                "y": audit.get("quadrant_mid_y") or 50,
            },
        },
        "brands": brands,
        "scorecard": scorecard,
        "chart_brand_count": min(chart_n, len(detail_rows)),
    }


def export_expand_quadrant_outputs(
    out_dir: Any,
    detail_rows: list[dict[str, Any]],
    query: str,
    *,
    country: str = "global",
    audit: dict[str, Any] | None = None,
    chart_n: int = 20,
) -> dict[str, str]:
    """Write CSV + HTML next to the FINAL Excel (same columns as Company Details)."""
    import csv
    from pathlib import Path

    from vendor_intel.quadrant.html_report import write_quadrant_html_report

    out_p = Path(out_dir)
    out_p.mkdir(parents=True, exist_ok=True)
    slug = out_p.name
    csv_path = out_p / f"{slug}_companies.csv"
    html_path = out_p / f"{slug}_report.html"
    json_path = out_p / f"{slug}_quadrant.json"

    with csv_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(list(DETAIL_COLUMNS))
        for r in detail_rows:
            w.writerow([r.get(h, "") for h in DETAIL_COLUMNS])

    payload = build_expand_quadrant_payload(
        detail_rows, query, country=country, audit=audit, chart_n=chart_n
    )
    json_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    write_quadrant_html_report(payload, html_path, open_browser=False)
    return {
        "csv": str(csv_path),
        "html": str(html_path),
        "json": str(json_path),
    }
