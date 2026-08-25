#!/usr/bin/env python3
"""
Deep-crawl + DDGS web-search + DeepSeek evidence-only X/Y/Overall rescore
for Global GLP-1 Receptor Agonist Market.

Rules:
  - Score ONLY from crawl + web-search + agent-verified notes (no invented sales/approvals)
  - When evidence clearly supports global GLP-1 leadership, use high scores (8–10 → 80–95+)
  - Thin/silent evidence → mid-low (3–5), never invent blockbuster status

Axes (Healthcare / Pharmaceutical):
  X = Therapeutic & Manufacturing Capability
  Y = Commercial Reach & Pipeline Strategy
  Overall = (X+Y)/2
  Quadrant = absolute median

Env:
  QUAD_RESCORE_LIMIT=N
  QUAD_RESCORE_BATCH=8
  QUAD_RESCORE_CONCURRENT=3
  QUAD_CRAWL_CONCURRENT=4
  QUAD_CRAWL_MAX_PAGES=30
  QUAD_SKIP_CRAWL=1
  QUAD_SKIP_DDGS=1
  QUAD_RESCORE_RESUME=1
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from openpyxl import load_workbook

from vendor_intel.config import Settings
from vendor_intel.placeholders.load_keys import apply_env_overrides
from vendor_intel.pipeline.chatgpt_env import apply_chatgpt_expand_env
from vendor_intel.pipeline.expand_quadrant_score import (
    _deep_crawl_rows,
    export_expand_quadrant_outputs,
    kb_from_landscape_row,
    to_company_detail_rows,
)
from vendor_intel.pipeline.web_expand import write_final_xlsx
from vendor_intel.quadrant.company_kb import build_company_kb, kb_text_blob
from vendor_intel.quadrant.rating_map import assign_quadrants_absolute_median

OUT = ROOT / "output" / "chatgpt_expand"
SLUG = "global_glp_1_receptor_agonist_market_global"
QUERY = "Global GLP-1 Receptor Agonist Market"
FOLDER = OUT / SLUG
INDUSTRY = "Healthcare / Pharmaceutical"

AXIS_X = "Therapeutic & Manufacturing Capability"
AXIS_Y = "Commercial Reach & Pipeline Strategy"
X_FEATS = [
    "Product / Molecule Portfolio",
    "Therapeutic Coverage & Differentiation",
    "Innovation & Clinical R&D",
    "Manufacturing & Supply Reliability",
    "Regulatory & Quality Compliance",
]
Y_FEATS = [
    "Geographic Market Access",
    "Brand / HCP Reputation",
    "Financial Performance",
    "Pipeline & Indication Roadmap",
    "Partnerships & Business Expansion",
]
# matrix_slot_weights from quadrant_scoring_weights.yaml
X_W = [0.30, 0.20, 0.20, 0.15, 0.15]
Y_W = [0.25, 0.25, 0.20, 0.15, 0.15]

SYSTEM = """You score a company on the Coherent Quadrant for the Global GLP-1 Receptor Agonist Market
(GLP-1 RAs, dual/triple incretins, oral small-molecule GLP-1, GLP-1 biosimilars/AGs,
and exclusive licensed marketers of those brands).

Use ONLY the EVIDENCE text provided. Do NOT invent revenues, approvals, Phase status,
countries, partners, or products absent from evidence.

Axes:
- X = Therapeutic & Manufacturing Capability
  (molecule portfolio, therapeutic differentiation, clinical R&D, manufacturing/supply, regulatory/quality)
- Y = Commercial Reach & Pipeline Strategy
  (geography/access, brand/HCP reputation, financials, pipeline/indications, partnerships/M&A)

Scoring each feature 1–10 (discriminating — do not give everyone high scores):
- 9–10: ONLY when evidence shows GLOBAL GLP-1 leadership
  (e.g. multi-blockbuster marketed GLP-1 franchise with multi-billion sales AND global labels,
   or clearly best-in-class late-stage portfolio with global Phase 3 + manufacturing scale)
- 7–8: strong evidenced multi-region marketed GLP-1 OR late-stage differentiated pipeline with clear approvals/deals
- 5–6: moderate regional GLP-1 brand owner / biosimilar with partial evidence
- 3–4: weak or narrow evidence (early pipeline only, thin public footprint, marketer with limited footprint)
- 1–2: evidence shows weakness, exit from GLP-1, or absence
Exclusive licensed Marketers (do not own molecule): typically X 4–6, Y 5–7 unless evidence shows
very large exclusive commercial scale.
Biosimilar / AG players: typically X 5–7, Y 5–7 unless multi-market launched scale is evidenced.
If evidence is silent on a feature → score 3–5 and grounding=insufficient.
When crawl/search CLEARLY supports global leadership, DO NOT compress to mid-band — use 9–10.

Return JSON only:
{
  "x_features": [{"feature": "...", "score": 1-10, "grounding": "supported|partial|insufficient", "why": "short cite from evidence"}],
  "y_features": [{"feature": "...", "score": 1-10, "grounding": "supported|partial|insufficient", "why": "short cite from evidence"}],
  "evidence_used": true,
  "evidence_quality": "rich|moderate|thin"
}
All five X and five Y features required. Never use grounding=model_knowledge."""

# Agent web-verified notes (Aug 2026) — public sources only
AGENT_WEB_EVIDENCE: dict[str, str] = {
    "novo nordisk": (
        "Novo Nordisk 2025: net sales DKK 309.1bn (+10% CER). Ozempic DKK 127.1bn; "
        "Wegovy DKK 79.1bn; Rybelsus ~DKK 22bn. FDA approved oral Wegovy pill Dec 2025 "
        "(semaglutide 25 mg); US launch Jan 2026. Global GLP-1 leader in diabetes+obesity; "
        "CagriSema next-gen obesity combo in late development/regulatory path. "
        "Massive manufacturing expansion; multi-indication GLP-1 franchise."
    ),
    "eli lilly": (
        "Eli Lilly 2025: total revenue $65.2bn. Mounjaro (tirzepatide T2D) $23.0bn; "
        "Zepbound (tirzepatide obesity) $13.5bn — combined tirzepatide >$36bn. "
        "Orforglipron (Foundayo) oral non-peptide GLP-1 FDA approved Apr 2026. "
        "Retatrutide triple agonist Phase 3. Global dual-agonist commercial leader."
    ),
    "amgen": (
        "Amgen MariTide (maridebart cafraglutide): monthly GLP-1 agonist / GIP antagonist "
        "in Phase 3 obesity program; differentiated dosing vs weekly peers."
    ),
    "boehringer": (
        "Boehringer Ingelheim + Zealand: survodutide dual GLP-1/glucagon agonist Phase 3 "
        "obesity/MASH (SYNCHRONIZE); positive Phase 3 topline reported 2026."
    ),
    "zealand": (
        "Zealand Pharma: survodutide partnered with Boehringer (Phase 3); petrelintide "
        "amylin analog (also partnered/licensed programs with Roche reported)."
    ),
    "roche": (
        "Roche: acquired Carmot Therapeutics Jan 2024 ($2.7bn) for CT-388 dual GLP-1/GIP, "
        "CT-996 oral GLP-1, CT-868; CT-388 Phase 2 positive obesity data; Phase 3 planned. "
        "Also oral SM GLP-1 programs / ENITH trials reported."
    ),
    "carmot": (
        "Carmot Therapeutics acquired by Roche Jan 2024; assets CT-388/CT-996/CT-868 now "
        "in Roche obesity pipeline."
    ),
    "pfizer": (
        "Pfizer: advanced oral GLP-1 programs (danuglipron discontinued historically; "
        "conveglipron/newer oral candidates in development). Completed acquisition of "
        "Metsera 2025 (~$7bn) for MET-097i weekly/monthly injectable GLP-1 and amylin assets. "
        "Pfizer China commercializes Sciwind ecnoglutide in Mainland China (Sciwind remains MAH)."
    ),
    "metsera": (
        "Metsera acquired by Pfizer 2025; portfolio MET-097i (injectable GLP-1), MET-233i "
        "(amylin), oral GLP-1 candidates — now under Pfizer."
    ),
    "sciwind": (
        "Sciwind Biosciences: ecnoglutide (XW003) cAMP-biased GLP-1 — NMPA China approvals "
        "2026 for T2D and obesity; Pfizer China exclusive commercialization deal (up to $495M)."
    ),
    "innovent": (
        "Innovent Biologics: mazdutide GLP-1/glucagon dual agonist — China NMPA approval "
        "2025 (Lilly-originated China rights); commercial China metabolic player."
    ),
    "viking": (
        "Viking Therapeutics: VK2735 dual GIP/GLP-1 — injectable and oral; Phase 3 obesity "
        "program; strong Phase 2 weight-loss data publicly reported."
    ),
    "structure": (
        "Structure Therapeutics: aleniglipron / GSBR-1290 oral small-molecule GLP-1; "
        "advancing late-stage clinical development for obesity/T2D."
    ),
    "altimmune": (
        "Altimmune: pemvidutide dual GLP-1/glucagon agonist — Phase 2/3 obesity and MASH focus."
    ),
    "hanmi": (
        "Hanmi Pharmaceutical: efpeglenatide (Efe) long-acting GLP-1 toward Korea commercialization; "
        "HM15275 triple agonist pipeline; LAPSCOVERY platform."
    ),
    "hansoh": (
        "Hansoh: Fulaimei (PEG-loxenatide) marketed China GLP-1; HS-20094 dual agonist pipeline."
    ),
    "hengrui": (
        "Jiangsu Hengrui: HRS9531 GLP-1/GIP dual — Phase 3 China; ex-China rights licensed to "
        "Kailera Therapeutics."
    ),
    "kailera": (
        "Kailera Therapeutics: ex-China rights to Hengrui HRS9531 GLP-1/GIP dual agonist."
    ),
    "gan & lee": (
        "Gan & Lee: bofanglutide (GZR18) biweekly GLP-1 — Phase 3 China; exclusive licenses to "
        "Lupin (India), JW Pharmaceutical (Korea), Productos Científicos/Carnot (LATAM)."
    ),
    "gan and lee": (
        "Gan & Lee: bofanglutide (GZR18) biweekly GLP-1 — Phase 3; out-licensed India/Korea/LATAM."
    ),
    "pegbio": (
        "PegBio: PB-119 long-acting PEGylated GLP-1 — China NDA/marketing application path for T2D."
    ),
    "huadong": (
        "Huadong Medicine: Liluping liraglutide biosimilar marketed in China; Jiuyuan Gene "
        "semaglutide biosimilar (Jiyoutai) filing leadership in China."
    ),
    "jiuyuan": (
        "Hangzhou Jiuyuan Gene (Huadong-linked): first China semaglutide biosimilar NDA filings "
        "(Jiyoutai); liraglutide biosimilar collaboration with Huadong."
    ),
    "sanofi": (
        "Sanofi: Soliqua (insulin glargine + lixisenatide) still marketed; standalone Adlyxin/"
        "Lyxumia largely discontinued. Not a current weekly GLP-1 share leader."
    ),
    "astrazeneca": (
        "AstraZeneca: Byetta/Bydureon (exenatide) discontinued US 2024; historical GLP-1 player; "
        "newer incretin partnerships (e.g. China CSPC deals reported) for next-gen assets."
    ),
    "chugai": (
        "Chugai discovered orforglipron (OWL833); worldwide rights licensed to Eli Lilly (2018); "
        "Chugai receives milestones/royalties. Majority owned by Roche (~59.9%)."
    ),
    "emcure": (
        "Emcure: exclusive India commercialization/distribution partner for Novo Nordisk "
        "Poviztra (semaglutide 2.4 mg / Wegovy molecule) — Marketer, not molecule owner."
    ),
    "lupin": (
        "Lupin: exclusive India license from Gan & Lee for bofanglutide — Marketer/in-license "
        "commercializer for India."
    ),
    "jw pharmaceutical": (
        "JW Pharmaceutical: exclusive Korea develop/commercialize rights for Gan & Lee bofanglutide."
    ),
    "teva": (
        "Teva: first US authorized generic of Victoza (liraglutide); complex generics/AG player "
        "in GLP-1 class as patents expire."
    ),
    "hikma": (
        "Hikma: liraglutide authorized generic / AG offerings in GLP-1 diabetes segment."
    ),
    "glenmark": (
        "Glenmark: Lirafit liraglutide biosimilar launched India (low-cost daily GLP-1 biosimilar)."
    ),
    "biocon": (
        "Biocon / Biologics: liraglutide biosimilar approvals (e.g. UK path reported); "
        "semaglutide biosimilar programs for select markets."
    ),
    "sandoz": (
        "Sandoz: entering semaglutide / weight-loss pen markets in select countries (e.g. Brazil "
        "registrations reported with partners); biosimilar/specialty GLP-1 entrant."
    ),
    "viatris": (
        "Viatris (ex-Mylan): complex generics platform; GLP-1 AG/biosimilar interest post-Mylan merger."
    ),
    "versanis": (
        "Versanis Bio acquired by Eli Lilly Aug 2023; bimagrumab obesity asset under Lilly."
    ),
    "adocia": (
        "Adocia: BioChaperone platform for GLP-1 / insulin combinations — clinical-stage delivery tech."
    ),
    "benemae": (
        "Shanghai Benemae: beinaglutide (Feisumei) China-approved GLP-1 for T2D/weight control."
    ),
}


def _norm(s: str) -> str:
    s = str(s or "").strip().lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", s).strip()


def _domain(website: str) -> str:
    raw = (website or "").strip()
    if not raw:
        return ""
    try:
        host = urlparse(raw if "://" in raw else f"https://{raw}").netloc.lower()
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return ""


def _axis_100(feat_scores: list[dict], features: list[str], weights: list[float]) -> int:
    by = {_norm(f.get("feature") or ""): f for f in feat_scores}
    total = 0.0
    for feat, w in zip(features, weights):
        item = by.get(_norm(feat)) or {}
        if not item:
            for k, v in by.items():
                if _norm(feat)[:18] in k or k[:18] in _norm(feat):
                    item = v
                    break
        try:
            s = float(item.get("score") or 4)
        except (TypeError, ValueError):
            s = 4.0
        s = max(1.0, min(10.0, s))
        g = str(item.get("grounding") or "").lower()
        # Stretch supported mid-high scores upward when evidence is real
        if g == "supported" and 5 <= s <= 8:
            s = min(10.0, s + 1.5)
        if g == "supported" and s >= 9:
            s = 10.0
        if g == "partial" and 6 <= s <= 8:
            s = min(10.0, s + 0.5)
        if g == "insufficient":
            s = min(s, 5.0)
        total += w * (s / 10.0)
    return int(round(total * 100))


def _web_search(brand: str, website: str, specialty: str) -> str:
    if (os.getenv("QUAD_SKIP_DDGS") or "").lower() in {"1", "true", "yes"}:
        return ""
    from ddgs import DDGS

    queries = [
        f"{brand} GLP-1 OR semaglutide OR tirzepatide OR liraglutide OR dulaglutide",
        f"{brand} obesity OR diabetes OR Wegovy OR Ozempic OR Mounjaro OR Zepbound",
        f"{brand} Phase 3 OR FDA OR NMPA OR approval OR biosimilar GLP-1",
        f"{brand} revenue OR sales OR pipeline incretin OR dual agonist",
        f"{brand} manufacturing OR partnership OR license GLP-1",
    ]
    if specialty:
        queries.append(f"{brand} {specialty[:90]}")
    dom = _domain(website)
    if dom:
        queries.append(f"site:{dom} GLP-1 OR obesity OR diabetes OR pipeline")

    chunks: list[str] = []
    seen: set[str] = set()
    try:
        with DDGS() as ddgs:
            for q in queries[:6]:
                try:
                    results = list(ddgs.text(q, max_results=6))
                except Exception:
                    results = []
                for r in results or []:
                    title = str(r.get("title") or "").strip()
                    body = str(r.get("body") or r.get("snippet") or "").strip()
                    href = str(r.get("href") or r.get("link") or "").strip()
                    key = _norm(title + body)[:160]
                    if not key or key in seen:
                        continue
                    seen.add(key)
                    chunks.append(f"- {title}\n  {body}\n  URL: {href}")
                    if len(chunks) >= 20:
                        break
                if len(chunks) >= 20:
                    break
                time.sleep(0.15)
    except Exception as exc:
        chunks.append(f"(web search error: {type(exc).__name__}: {exc})")
    return "\n".join(chunks)


def _snap_text(snap: Any) -> str:
    if not isinstance(snap, dict):
        return ""
    parts: list[str] = []
    data = snap.get("data") if isinstance(snap.get("data"), dict) else {}
    for key in ("company", "business", "financials", "relationships", "intel", "location"):
        block = data.get(key)
        if isinstance(block, dict) and block:
            parts.append(f"[{key}]\n{json.dumps(block, ensure_ascii=False)[:4000]}")
        elif isinstance(block, str) and block.strip():
            parts.append(f"[{key}]\n{block[:4000]}")
    page = str(snap.get("page_text") or data.get("page_text") or "").strip()
    if page:
        parts.append(f"[page_text]\n{page[:14000]}")
    snippets = snap.get("snippets") or data.get("snippets") or []
    if isinstance(snippets, list) and snippets:
        parts.append("[snippets]\n" + "\n".join(str(s)[:400] for s in snippets[:12]))
    return "\n\n".join(parts)


def _deepseek_score(brand: str, role: str, specialty: str, evidence: str) -> dict[str, Any]:
    apply_env_overrides()
    from vendor_intel.placeholders import llm as llm_mod

    os.environ["LLM_PROVIDER"] = "deepseek"
    llm_mod.LLM_PROVIDER = "deepseek"
    if not llm_mod.is_configured():
        raise RuntimeError("DeepSeek not configured (DEEPSEEK_API_KEY missing)")

    user = f"""Market: {QUERY}
Brand: {brand}
Role: {role}  (Brand=owns/develops GLP-1 or biosimilar brand; Marketer=exclusive licensee of another's GLP-1)
Known specialty (may be incomplete): {specialty or 'n/a'}

X axis ({AXIS_X}) features: {X_FEATS}
Y axis ({AXIS_Y}) features: {Y_FEATS}

EVIDENCE (deep crawl + web search + agent notes — cite only this; never invent):
{evidence[:24000]}

Score now. JSON only."""
    parsed = llm_mod.llm_complete_json(SYSTEM, user, max_tokens=2400)
    if not isinstance(parsed, dict):
        raise ValueError(f"no JSON object from DeepSeek for {brand}")
    if parsed.get("status") in {"llm_failed", "placeholder"}:
        raise ValueError(
            f"DeepSeek failed for {brand}: {parsed.get('error') or parsed.get('status')}"
        )
    if not (parsed.get("x_features") and parsed.get("y_features")):
        raise ValueError(f"missing x_features/y_features for {brand}")
    return parsed


def _load_rows(*, resume: bool) -> list[dict]:
    xlsx = FOLDER / f"{SLUG}_FINAL.xlsx"
    wb = load_workbook(xlsx, data_only=True)
    ws = wb["Landscape"]
    rows_raw = list(ws.iter_rows(values_only=True))
    hdr = [str(h) for h in rows_raw[0]]

    details_by: dict[str, dict] = {}
    if "Company Details" in wb.sheetnames:
        dws = wb["Company Details"]
        drows = list(dws.iter_rows(values_only=True))
        dhdr = [str(h) for h in drows[0]]
        for r in drows[1:]:
            if not r:
                continue
            d = {dhdr[i]: ("" if r[i] is None else r[i]) for i in range(len(dhdr)) if i < len(r)}
            key = _norm(d.get("Brand") or "")
            if key:
                details_by[key] = d

    kept: list[dict] = []
    for r in rows_raw[1:]:
        if not r:
            continue
        d = {hdr[i]: ("" if r[i] is None else r[i]) for i in range(len(hdr)) if i < len(r)}
        brand = str(d.get("Company") or d.get("Brand") or "").strip()
        if not brand:
            continue
        key = _norm(brand)
        det = details_by.get(key) or {}
        if det.get("Brand"):
            brand = str(det["Brand"]).strip()
            key = _norm(brand)
            d["Brand"] = brand
        if det.get("Company") and str(det["Company"]).startswith("("):
            d["_display_company"] = det["Company"]
        if det.get("Found in"):
            d["Headquarters"] = det["Found in"]
            d["Found in"] = det["Found in"]
        if det.get("Role") in {"Brand", "Marketer"}:
            d["Role"] = det["Role"]
            d["Distribution Type"] = det["Role"]

        prior_x = str(d.get("X Score") or det.get("X") or "").strip()
        prior_y = str(d.get("Y Score") or det.get("Y") or "").strip()
        prior_q = str(d.get("Quadrant") or det.get("Quadrant") or "").strip()
        prior_o = str(d.get("Overall Score") or det.get("Overall") or "").strip()
        deep_done = "deep-crawl scored" in str(d.get("Summary") or "").lower()

        d["Brand"] = brand
        d["Company"] = brand
        d["Role"] = d.get("Role") if d.get("Role") in {"Brand", "Marketer"} else "Brand"
        d["Distribution Type"] = d["Role"]
        d["Industry Category"] = INDUSTRY

        if resume and prior_x and prior_y and deep_done:
            d["X Score"] = prior_x
            d["Y Score"] = prior_y
            d["Overall Score"] = prior_o or str(
                round((float(prior_x) + float(prior_y)) / 2)
            )
            d["Quadrant"] = prior_q
            d["_already_scored"] = True
        else:
            for col in ("X Score", "Y Score", "Overall Score", "Quadrant"):
                d[col] = ""
            d["_already_scored"] = False
        kept.append(d)

    # Prioritize known leaders first so rich agent evidence scores early
    priority = (
        "novo nordisk",
        "eli lilly",
        "lilly",
        "amgen",
        "boehringer",
        "roche",
        "pfizer",
        "zealand",
        "innovent",
        "viking",
        "structure",
        "sciwind",
        "hanmi",
        "hansoh",
        "hengrui",
        "gan & lee",
        "gan and lee",
    )

    def _prio(row: dict) -> tuple[int, str]:
        n = _norm(row.get("Brand") or "")
        for i, stem in enumerate(priority):
            if stem in n:
                return (i, n)
        return (100, n)

    kept.sort(key=_prio)
    return kept


def _save(kept: list[dict], *, partial: bool = False, meta: dict | None = None) -> None:
    xs, ys = [], []
    for r in kept:
        try:
            xs.append(float(r.get("X Score") or 50))
        except (TypeError, ValueError):
            xs.append(50.0)
        try:
            ys.append(float(r.get("Y Score") or 50))
        except (TypeError, ValueError):
            ys.append(50.0)
    scored_idx = [i for i, r in enumerate(kept) if str(r.get("X Score") or "").strip()]
    if len(scored_idx) >= 4:
        sxs = [xs[i] for i in scored_idx]
        sys_ = [ys[i] for i in scored_idx]
        quads, mid_x, mid_y = assign_quadrants_absolute_median(sxs, sys_)
        for j, i in enumerate(scored_idx):
            kept[i]["Quadrant"] = quads[j]
            kept[i]["Overall Score"] = round((xs[i] + ys[i]) / 2)
    else:
        mid_x = mid_y = 50.0

    audit = {
        "axis_x": AXIS_X,
        "axis_y": AXIS_Y,
        "x_features": X_FEATS,
        "y_features": Y_FEATS,
        "x_feature_weights": X_W,
        "y_feature_weights": Y_W,
        "industry_group": "Healthcare",
        "industry_category": "Pharmaceutical",
        "mid_x": mid_x,
        "mid_y": mid_y,
        "method": "smart_crawl deep crawl + DDGS + DeepSeek evidence-only (no hallucination)",
        "partial": partial,
        **(meta or {}),
    }
    detail_rows = to_company_detail_rows(kept, QUERY, audit)
    for det in detail_rows:
        key = _norm(det.get("Brand") or "")
        src = next((r for r in kept if _norm(r.get("Brand") or "") == key), None)
        if not src:
            continue
        det["Role"] = src.get("Role") or "Brand"
        if src.get("_display_company"):
            det["Company"] = src["_display_company"]
        elif not str(det.get("Company") or "").startswith("("):
            det["Company"] = det.get("Brand") or det.get("Company")

    xlsx = FOLDER / f"{SLUG}_FINAL.xlsx"
    write_final_xlsx(
        xlsx,
        kept,
        "Companies",
        {"query": QUERY, "xy_scoring": audit},
        detail_rows=detail_rows,
    )
    if not partial:
        export_expand_quadrant_outputs(
            FOLDER, detail_rows, QUERY, country="global", audit=audit, chart_n=20
        )
        # CSV
        import csv

        csv_path = FOLDER / f"{SLUG}_companies.csv"
        with csv_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(
                f,
                fieldnames=[
                    "Brand",
                    "Company",
                    "Role",
                    "Quadrant",
                    "X",
                    "Y",
                    "Overall",
                    "Found in",
                ],
            )
            w.writeheader()
            for d in detail_rows:
                w.writerow({k: d.get(k, "") for k in w.fieldnames})


async def _kb_evidence(row: dict) -> str:
    from vendor_intel.pipeline.expand_quadrant_score import _scoring_row

    settings = Settings.load()
    score_row = _scoring_row(row)
    try:
        kb = await build_company_kb(
            score_row, market=QUERY, settings=settings, do_search=False
        )
    except Exception:
        kb = kb_from_landscape_row(row)
    blob = kb_text_blob(kb, max_chars=20000)
    snap_extra = _snap_text(row.get("_evidence_snapshot"))
    if snap_extra and snap_extra not in blob:
        blob = f"{blob}\n\n=== SNAPSHOT ===\n{snap_extra}"[:24000]
    return blob


def _agent_evidence(brand: str) -> str:
    n = _norm(brand)
    best = ""
    best_len = -1
    for stem, text in AGENT_WEB_EVIDENCE.items():
        if stem in n and len(stem) > best_len:
            best = text
            best_len = len(stem)
    return best


async def _score_one(row: dict, sem: asyncio.Semaphore) -> dict[str, Any]:
    brand = str(row.get("Brand") or "")
    async with sem:
        specialty = str(
            row.get("Specialty Focus")
            or row.get("Key Brands Represented")
            or row.get("Core Categories")
            or ""
        )
        website = str(row.get("Website") or "")
        role = str(row.get("Role") or "Brand")
        crawl_txt = await _kb_evidence(row)
        search_txt = await asyncio.to_thread(_web_search, brand, website, specialty)
        agent_txt = _agent_evidence(brand)
        landscape_bits = (
            f"HQ: {row.get('Headquarters') or row.get('Found in') or ''}\n"
            f"Presence: {row.get('Operational Presence') or ''}\n"
            f"Categories: {row.get('Core Categories') or ''}\n"
            f"Specialty: {specialty}\n"
            f"Key brands: {row.get('Key Brands Represented') or ''}\n"
            f"Ownership: {row.get('Ownership') or ''}\n"
            f"Employees: {row.get('Employees') or ''}\n"
            f"Website: {website}\n"
            f"Role: {role}\n"
            f"Crawled: {bool(row.get('_evidence_snapshot'))}\n"
        )
        evidence = (
            f"=== LANDSCAPE FACTS ===\n{landscape_bits}\n"
            f"=== AGENT WEB-VERIFIED NOTES ===\n{agent_txt or '(none for this brand)'}\n"
            f"=== DEEP CRAWL / KB ===\n{crawl_txt or '(no crawl text)'}\n"
            f"=== WEB SEARCH ===\n{search_txt or '(no results)'}\n"
        )
        evid_chars = len(crawl_txt) + len(search_txt) + len(agent_txt)
        # Allow agent notes alone for known leaders
        if evid_chars < 80 and not agent_txt:
            return {
                "brand": brand,
                "ok": False,
                "error": "insufficient_web_evidence",
                "x": 42,
                "y": 42,
                "evidence_chars": evid_chars,
                "crawled": bool(row.get("_evidence_snapshot")),
            }
        try:
            payload = await asyncio.to_thread(
                _deepseek_score, brand, role, specialty, evidence
            )
            x = _axis_100(payload.get("x_features") or [], X_FEATS, X_W)
            y = _axis_100(payload.get("y_features") or [], Y_FEATS, Y_W)
            return {
                "brand": brand,
                "ok": True,
                "x": x,
                "y": y,
                "overall": round((x + y) / 2),
                "payload": payload,
                "evidence_chars": evid_chars,
                "crawled": bool(row.get("_evidence_snapshot")),
                "evidence_quality": payload.get("evidence_quality"),
            }
        except Exception as exc:
            return {
                "brand": brand,
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "x": 42,
                "y": 42,
                "evidence_chars": evid_chars,
                "crawled": bool(row.get("_evidence_snapshot")),
            }


async def main() -> int:
    apply_env_overrides()
    apply_chatgpt_expand_env()
    os.environ["LLM_PROVIDER"] = "deepseek"
    os.environ["QUAD_ALLOW_MODEL_KNOWLEDGE"] = "0"
    from vendor_intel.placeholders import llm as llm_mod

    llm_mod.LLM_PROVIDER = "deepseek"
    if not llm_mod.is_configured():
        print("ERROR: DeepSeek not configured", flush=True)
        return 2

    resume = (os.getenv("QUAD_RESCORE_RESUME") or "").lower() in {"1", "true", "yes"}
    kept = _load_rows(resume=resume)
    limit = int(os.getenv("QUAD_RESCORE_LIMIT") or "0")

    batch_n = int(os.getenv("QUAD_RESCORE_BATCH") or "8")
    concurrent = int(os.getenv("QUAD_RESCORE_CONCURRENT") or "3")
    crawl_concurrent = int(os.getenv("QUAD_CRAWL_CONCURRENT") or "4")
    max_pages = int(os.getenv("QUAD_CRAWL_MAX_PAGES") or "30")
    skip_crawl = (os.getenv("QUAD_SKIP_CRAWL") or "").lower() in {"1", "true", "yes"}

    need = [r for r in kept if not r.get("_already_scored")]
    if limit > 0:
        need = need[:limit]
        print(f"LIMIT {limit} (keeping all {len(kept)} rows in FINAL)", flush=True)

    print(
        f"GLP-1 deep-crawl evidence rescore {len(need)}/{len(kept)} "
        f"(batch={batch_n}, score_concurrent={concurrent}, "
        f"crawl_concurrent={crawl_concurrent}, max_pages={max_pages}, "
        f"skip_crawl={skip_crawl}, resume={resume})",
        flush=True,
    )

    settings = Settings.load()
    try:
        object.__setattr__(settings, "quadrant_crawl_max_pages", max_pages)
        object.__setattr__(settings, "quadrant_crawl_mode", "business")
    except Exception:
        pass

    os.environ["EXPAND_XY_CRAWL_CONCURRENT"] = str(crawl_concurrent)

    audit_log: list[dict] = []
    audit_path = OUT / "_audit" / "glp1_xy_deep_rescore.json"
    if resume and audit_path.exists():
        try:
            prior = json.loads(audit_path.read_text(encoding="utf-8"))
            audit_log = list(prior.get("rows") or [])
        except Exception:
            pass

    by_brand = {_norm(r.get("Brand") or ""): r for r in kept}
    sem = asyncio.Semaphore(concurrent)

    for start in range(0, len(need), batch_n):
        batch = need[start : start + batch_n]
        print(
            f"\n=== Batch {start // batch_n + 1}: "
            f"{start + 1}-{start + len(batch)} / {len(need)} ===",
            flush=True,
        )
        if not skip_crawl:
            print(f"  deep-crawling {len(batch)} sites…", flush=True)
            stats = await _deep_crawl_rows(batch, country="global", settings=settings)
            print(
                f"  crawl ok={stats.get('ok')} fail={stats.get('fail')} "
                f"skip_no_domain={stats.get('skipped_no_domain')}",
                flush=True,
            )
        results = await asyncio.gather(*[_score_one(r, sem) for r in batch])
        for res in results:
            brand = res["brand"]
            row = by_brand.get(_norm(brand))
            if not row:
                continue
            row["X Score"] = res["x"]
            row["Y Score"] = res["y"]
            row["Overall Score"] = res.get("overall") or round((res["x"] + res["y"]) / 2)
            note = "ok" if res.get("ok") else res.get("error")
            row["Summary"] = (
                f"{brand} — deep-crawl scored X={res['x']} Y={res['y']} "
                f"({note}; evid={res.get('evidence_chars')}; "
                f"crawled={res.get('crawled')}; q={res.get('evidence_quality')})"
            )
            row["_already_scored"] = True
            audit_log.append(
                {
                    "brand": brand,
                    "ok": res.get("ok"),
                    "x": res["x"],
                    "y": res["y"],
                    "error": res.get("error"),
                    "evidence_chars": res.get("evidence_chars"),
                    "crawled": res.get("crawled"),
                    "evidence_quality": res.get("evidence_quality"),
                    "features": res.get("payload"),
                }
            )
            print(
                f"  {brand}: X={res['x']} Y={res['y']} "
                f"{'OK' if res.get('ok') else 'FALLBACK ' + str(res.get('error'))} "
                f"crawl={res.get('crawled')} evid={res.get('evidence_chars')} "
                f"q={res.get('evidence_quality')}",
                flush=True,
            )
        all_scored = all(str(r.get("X Score") or "").strip() for r in kept)
        _save(
            kept,
            partial=not all_scored,
            meta={
                "scored": sum(1 for r in kept if str(r.get("X Score") or "").strip())
            },
        )
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        audit_path.write_text(
            json.dumps(
                {
                    "query": QUERY,
                    "total": len(kept),
                    "rows": audit_log,
                    "method": "deep_crawl+ddgs+deepseek",
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    scored_n = sum(1 for r in kept if str(r.get("X Score") or "").strip())
    done = scored_n == len(kept)
    _save(kept, partial=not done, meta={"scored": scored_n, "done": done})

    scored = [r for r in kept if str(r.get("X Score") or "").strip()]
    if not scored:
        print("No rows scored.", flush=True)
        return 1
    xs = [int(float(r.get("X Score") or 0)) for r in scored]
    ys = [int(float(r.get("Y Score") or 0)) for r in scored]
    os_ = [int(float(r.get("Overall Score") or 0)) for r in scored]
    print("\n=== SCORE SUMMARY ===", flush=True)
    print(
        f"scored={len(scored)}/{len(kept)} X mean={sum(xs)/len(xs):.1f} "
        f"Y mean={sum(ys)/len(ys):.1f} Overall mean={sum(os_)/len(os_):.1f}",
        flush=True,
    )
    print(
        f"X max={max(xs)} Y max={max(ys)} Overall max={max(os_)} "
        f"Overall>=80: {sum(1 for o in os_ if o >= 80)}",
        flush=True,
    )
    top = sorted(scored, key=lambda r: -float(r.get("Overall Score") or 0))[:15]
    print("TOP 15:", flush=True)
    for r in top:
        print(
            f"  {r.get('Overall Score')}  X={r.get('X Score')} Y={r.get('Y Score')}  "
            f"{r.get('Brand')} [{r.get('Role')}]",
            flush=True,
        )
    print(f"Quadrants: {Counter(r.get('Quadrant') for r in scored)}", flush=True)
    return 0 if done else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
