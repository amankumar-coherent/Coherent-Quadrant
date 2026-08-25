#!/usr/bin/env python3
"""Fix semiconductor crawl-fail domains, re-crawl, and rescore only those companies."""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from openpyxl import load_workbook

from vendor_intel.placeholders.load_keys import apply_env_overrides
from vendor_intel.pipeline.expand_quadrant_score import (
    export_expand_quadrant_outputs,
    score_expand_rows,
    to_company_detail_rows,
)
from vendor_intel.pipeline.web_expand import write_final_xlsx

OUT = ROOT / "output" / "chatgpt_expand"
SLUG = "global_semiconductor_market_global"
QUERY = "Global Semiconductor Market"
FOLDER = OUT / SLUG

# Verified official website replacements for crawl failures (real data only).
WEBSITE_FIXES: dict[str, str] = {
    "Cambridge GaN Devices": "https://camgandevices.com",
    "LAPIS Technology": "https://www.rohm.com",
    "Silead": "https://www.gigadevice.com",
    "GlobalWafers": "https://www.globalwafers.com",
    "Toshiba Electronic Devices & Storage": "https://toshiba.semicon-storage.com",
    "Hua Hong Semiconductor": "https://huahonggrace.com",
    "Key Foundry": "https://keyfoundry.tech",
    "CEITEC S.A.": "https://ceitec.org.br",
    "SSMC": "https://www.ssmc.com.sg",
    "Unisem": "https://www.unisemgroup.com",
    "IQE plc": "https://www.iqep.com",
    "Inuitive": "https://www.inuitive-inc.com",
    "Autotalks": "https://www.autotalks.com",
    "Solantro Semiconductor": "https://www.hdsc.com.cn",
    "GaN Systems": "https://www.infineon.com",
    "Kenya Semiconductor Technologies": "https://stlsemiconductor.com",
    "Polymatech Electronics": "https://polymatech.sg",
    "GlobalFoundries": "https://gf.com",
    "Sony Semiconductor Solutions": "https://www.sony-semicon.com",
    "Tokyo Electron": "https://www.tel.com",
    "Powertech Technology": "https://www.powertech.com.tw",
}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


def _fail_names() -> list[str]:
    audit = json.loads((FOLDER / "chatgpt_xy_scores_batch_all.json").read_text(encoding="utf-8"))
    return [str(r.get("company") or "").strip() for r in audit.get("rows") or [] if not r.get("crawled")]


def _patch_landscape_websites(names: set[str]) -> list[tuple[str, str, str]]:
    xlsx = FOLDER / f"{SLUG}_FINAL.xlsx"
    wb = load_workbook(xlsx)
    ws = wb["Landscape"] if "Landscape" in wb.sheetnames else wb[wb.sheetnames[0]]
    rows = list(ws.iter_rows(values_only=False))
    hdr = [str(c.value) if c.value is not None else "" for c in rows[0]]
    ci, wi = hdr.index("Company"), hdr.index("Website")
    changes: list[tuple[str, str, str]] = []
    for row in rows[1:]:
        name = str(row[ci].value or "").strip()
        if name not in names and _norm(name) not in {_norm(n) for n in names}:
            continue
        old = str(row[wi].value or "").strip()
        # Match by exact then normalized
        new = WEBSITE_FIXES.get(name)
        if not new:
            for k, v in WEBSITE_FIXES.items():
                if _norm(k) == _norm(name):
                    new = v
                    break
        if new and _norm(new) != _norm(old):
            row[wi].value = new
            changes.append((name, old, new))
        elif not old and new:
            row[wi].value = new
            changes.append((name, old, new))
    wb.save(xlsx)
    return changes


def _load_fail_rows(names: set[str]) -> list[dict]:
    xlsx = FOLDER / f"{SLUG}_FINAL.xlsx"
    wb = load_workbook(xlsx, data_only=True)
    ws = wb["Landscape"] if "Landscape" in wb.sheetnames else wb[wb.sheetnames[0]]
    rows_raw = list(ws.iter_rows(values_only=True))
    hdr = [str(h) for h in rows_raw[0]]
    landscape: list[dict] = []
    for r in rows_raw[1:]:
        if not r:
            continue
        d = {hdr[i]: ("" if r[i] is None else r[i]) for i in range(len(hdr)) if i < len(r)}
        name = str(d.get("Company") or d.get("Brand") or "").strip()
        if name and (_norm(name) in {_norm(n) for n in names} or name in names):
            # Clear scores so score_expand_rows re-scores
            for col in ("X Score", "Y Score", "Overall Score", "X", "Y", "Overall", "Quadrant"):
                d[col] = ""
            landscape.append(d)

    # Merge Found in / Role / ownership from Company Details
    if "Company Details" in wb.sheetnames:
        ws = wb["Company Details"]
        rows_raw = list(ws.iter_rows(values_only=True))
        hdr = [str(h) for h in rows_raw[0]]
        details = {}
        for r in rows_raw[1:]:
            if not r:
                continue
            d = {hdr[i]: ("" if r[i] is None else r[i]) for i in range(len(hdr)) if i < len(r)}
            key = _norm(d.get("Brand") or d.get("Company") or "")
            if key:
                details[key] = d
        for row in landscape:
            key = _norm(row.get("Company") or "")
            det = details.get(key)
            if not det:
                continue
            brand = str(det.get("Brand") or "").strip()
            if brand:
                row["Company"] = brand
                row["Brand"] = brand
            if det.get("Role"):
                row["Distribution Type"] = det["Role"]
                row["Role"] = det["Role"]
            if det.get("Found in"):
                row["Headquarters"] = det["Found in"]
                row["Found in"] = det["Found in"]
            company_col = str(det.get("Company") or "").strip()
            if company_col and company_col != brand:
                row["_display_company"] = company_col
    return landscape


async def main() -> int:
    apply_env_overrides()
    os.environ["EXPAND_XY_SKIP_CRAWL"] = "0"
    os.environ["EXPAND_XY_FORCE_CRAWL"] = "1"
    os.environ.setdefault("EXPAND_XY_CONCURRENT", "4")
    os.environ.setdefault("QUADRANT_CRAWL_MAX_PAGES", "30")
    os.environ.setdefault("EXPAND_MARKET_AXIS_LLM", "1")

    # Prefer still-failed from last retry if present, else original fail list
    retry_path = OUT / "_audit" / "semi_crawl_fail_retry.json"
    if retry_path.exists():
        prev = json.loads(retry_path.read_text(encoding="utf-8"))
        still = [
            str(r.get("company") or "").strip()
            for r in (prev.get("rescored") or [])
            if r and not r.get("crawled")
        ]
        fails = [n for n in still if n] or [n for n in _fail_names() if n]
    else:
        fails = [n for n in _fail_names() if n]
    print(f"Crawl-fail companies: {len(fails)}", flush=True)
    changes = _patch_landscape_websites(set(fails))
    print(f"Website fixes applied: {len(changes)}", flush=True)
    for name, old, new in changes:
        print(f"  {name}: {old} -> {new}", flush=True)

    need = _load_fail_rows(set(fails))
    print(f"Re-scoring {len(need)} rows with crawl…", flush=True)
    scored, audit = await score_expand_rows(
        need, QUERY, country="global", concurrent=int(os.getenv("EXPAND_XY_CONCURRENT") or "4")
    )

    # Merge into full FINAL
    xlsx = FOLDER / f"{SLUG}_FINAL.xlsx"
    wb = load_workbook(xlsx, data_only=True)
    # Load all landscape + details for merge
    ws = wb["Landscape"] if "Landscape" in wb.sheetnames else wb[wb.sheetnames[0]]
    rows_raw = list(ws.iter_rows(values_only=True))
    hdr = [str(h) for h in rows_raw[0]]
    all_rows: list[dict] = []
    for r in rows_raw[1:]:
        if not r:
            continue
        d = {hdr[i]: ("" if r[i] is None else r[i]) for i in range(len(hdr)) if i < len(r)}
        if str(d.get("Company") or "").strip():
            all_rows.append(d)

    details_by: dict[str, dict] = {}
    if "Company Details" in wb.sheetnames:
        ws = wb["Company Details"]
        rows_raw = list(ws.iter_rows(values_only=True))
        hdr = [str(h) for h in rows_raw[0]]
        for r in rows_raw[1:]:
            if not r:
                continue
            d = {hdr[i]: ("" if r[i] is None else r[i]) for i in range(len(hdr)) if i < len(r)}
            key = _norm(d.get("Brand") or d.get("Company") or "")
            if key:
                details_by[key] = d

    scored_by = {_norm(r.get("Company") or r.get("Brand") or ""): r for r in scored}
    for row in all_rows:
        key = _norm(row.get("Company") or "")
        det = details_by.get(key)
        if det:
            brand = str(det.get("Brand") or "").strip()
            if brand:
                row["Company"] = brand
                row["Brand"] = brand
                key = _norm(brand)
            if det.get("Role"):
                row["Distribution Type"] = det["Role"]
            if det.get("Found in"):
                row["Headquarters"] = det["Found in"]
            company_col = str(det.get("Company") or "").strip()
            if company_col and company_col != brand:
                row["_display_company"] = company_col
            # Keep prior scores unless rescored
            if det.get("X") not in (None, "") and key not in scored_by:
                row["X Score"] = det["X"]
                row["Y Score"] = det["Y"]
                row["Overall Score"] = det["Overall"]
                row["Quadrant"] = det.get("Quadrant") or ""
        if key in scored_by:
            s = scored_by[key]
            for col in ("X Score", "Y Score", "Overall Score", "Quadrant", "X", "Y", "Overall"):
                if s.get(col) not in (None, ""):
                    row[col] = s[col]
            if s.get("_evidence_snapshot"):
                row["_evidence_snapshot"] = s["_evidence_snapshot"]

    # Prefer axes/defs from previous full audit
    full_audit_path = FOLDER / "chatgpt_xy_scores_batch_all.json"
    full_audit = json.loads(full_audit_path.read_text(encoding="utf-8")) if full_audit_path.exists() else {}
    for k in (
        "axis_x",
        "axis_y",
        "x_features",
        "y_features",
        "parameter_definitions",
        "industry_group",
        "industry_category",
        "x_feature_weights",
        "y_feature_weights",
        "question_weights",
        "overall_formula",
        "axis_definition_method",
    ):
        if full_audit.get(k) is not None:
            audit[k] = full_audit[k]

    detail_rows = to_company_detail_rows(all_rows, QUERY, audit)
    for det in detail_rows:
        key = _norm(det.get("Brand") or "")
        src = next((r for r in all_rows if _norm(r.get("Company") or r.get("Brand") or "") == key), None)
        if src and src.get("_display_company"):
            det["Company"] = src["_display_company"]

    write_final_xlsx(
        xlsx,
        all_rows,
        "Companies",
        {"query": QUERY, "xy_scoring": {k: v for k, v in audit.items() if k != "rows"}},
        detail_rows=detail_rows,
    )
    extras = export_expand_quadrant_outputs(
        FOLDER, detail_rows, QUERY, country="global", audit=audit, chart_n=20
    )

    # Patch full xy audit rows for rescored companies
    old_rows = list(full_audit.get("rows") or [])
    by_old = {_norm(r.get("company") or ""): r for r in old_rows}
    for r in audit.get("rows") or []:
        by_old[_norm(r.get("company") or "")] = r
    full_audit["rows"] = list(by_old.values())
    full_audit["crawl_retry"] = audit.get("crawl")
    full_audit["scored"] = len(full_audit["rows"])
    full_audit_path.write_text(json.dumps(full_audit, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    summary = {
        "retried": len(need),
        "website_fixes": [{"company": a, "from": b, "to": c} for a, b, c in changes],
        "crawl": audit.get("crawl"),
        "rescored": [
            {
                "company": r.get("company"),
                "x": r.get("x"),
                "y": r.get("y"),
                "overall": r.get("overall"),
                "crawled": r.get("crawled"),
                "kb_chars": r.get("kb_chars"),
            }
            for r in (audit.get("rows") or [])
        ],
        "html": extras.get("html"),
    }
    out = OUT / "_audit" / "semi_crawl_fail_retry.json"
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"crawl retry: {audit.get('crawl')}", flush=True)
    crawled_n = sum(1 for r in summary["rescored"] if r.get("crawled"))
    print(f"rescored crawled={crawled_n}/{len(summary['rescored'])}", flush=True)
    for r in sorted(summary["rescored"], key=lambda x: -int(x.get("overall") or 0))[:12]:
        print(
            f"  {r['company']}: O={r['overall']} X={r['x']} Y={r['y']} "
            f"crawled={r['crawled']} kb={r['kb_chars']}",
            flush=True,
        )
    print(f"audit -> {out}", flush=True)
    print(f"html -> {extras.get('html')}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
