"""Purge audited off-market rows from Flexible Packaging + Wearable FINAL Excels."""
from __future__ import annotations

import json
import re
from pathlib import Path

from openpyxl import load_workbook

from vendor_intel.pipeline.expand_quadrant_score import (
    export_expand_quadrant_outputs,
    to_company_detail_rows,
)
from vendor_intel.pipeline.web_expand import write_final_xlsx

ROOT = Path(r"D:\Coherent-Quadrant\output\chatgpt_expand")

# Exact / substring match keys (lowercase). Matched against Brand|Company.
FLEX_REMOVE = {
    "bemis associates",
    "essentra plc",
    "macfarlane group",
    "cascades inc",
    "intertape polymer",
}

# Prefer canonical brand when duplicates share a key
FLEX_DEDUP_KEYS = (
    "constantia flexibles",
    "taghleef",
    "essel propack",
    "schur flexibles",
    "mitsubishi chemical",
)

WEARABLE_REMOVE = {
    # IT / engineering services
    "infosys",
    "wipro",
    "tata consultancy",
    "tcs",
    "hcl technologies",
    "mindtree",
    "l&t technology",
    "l&t technology services",
    "tata elxsi",
    "sasken",
    "cambridge consultants",
    # Consumer gadgets (not medical)
    "boat",
    "portronics",
    "zebronics",
    "noise",
    "fire-boltt",
    "fire boltt",
    "mivi",
    "ambrane",
    "fossil group india",
    "titan company",
    "crossbeats",
    "coros wearables",
    "casio computer",
    # Wrong vertical / components / research
    "korea electric terminal",
    "cue health",
    "caredx",
    "sonoscape",
    "spartan bioscience",
    "csiro",
    "yamaha corporation",
    "rohm semiconductor",
    "infineon technologies",
    "bosch sensortec",
    "murata manufacturing",
    "japan display",
    "ams-osram",
    "plessey semiconductors",
    "ambiq",
}


def _norm(s: str) -> str:
    s = str(s or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s


def _identity(row: dict) -> str:
    return _norm(row.get("Brand") or row.get("Company") or row.get("name") or "")


def _should_remove(ident: str, needles: set[str]) -> str | None:
    for n in needles:
        if not n:
            continue
        if ident == n or n in ident or ident.startswith(n):
            return n
    return None


def _dedupe_flex(rows: list[dict]) -> tuple[list[dict], list[str]]:
    """Keep first occurrence per family key; drop later duplicates."""
    kept: list[dict] = []
    dropped: list[str] = []
    seen_family: set[str] = set()
    for row in rows:
        ident = _identity(row)
        family = ""
        for key in FLEX_DEDUP_KEYS:
            if key in ident:
                family = key
                break
        if family and family in seen_family:
            dropped.append(ident)
            continue
        if family:
            seen_family.add(family)
        kept.append(row)
    return kept, dropped


def _load(xlsx: Path) -> tuple[list[dict], dict[str, dict]]:
    wb = load_workbook(xlsx, data_only=True)
    landscape: list[dict] = []
    land_ws = wb["Landscape"] if "Landscape" in wb.sheetnames else wb[wb.sheetnames[0]]
    rows = list(land_ws.iter_rows(values_only=True))
    hdr = [str(h) for h in rows[0]]
    for r in rows[1:]:
        if not r:
            continue
        d = {hdr[i]: ("" if r[i] is None else r[i]) for i in range(len(hdr)) if i < len(r)}
        if str(d.get("Company") or "").strip():
            landscape.append(d)

    details_by: dict[str, dict] = {}
    if "Company Details" in wb.sheetnames:
        ws = wb["Company Details"]
        rows = list(ws.iter_rows(values_only=True))
        hdr = [str(h) for h in rows[0]]
        for r in rows[1:]:
            if not r:
                continue
            d = {hdr[i]: ("" if r[i] is None else r[i]) for i in range(len(hdr)) if i < len(r)}
            key = _norm(d.get("Brand") or d.get("Company") or "")
            if key:
                details_by[key] = d

    for row in landscape:
        key = _norm(row.get("Company") or "")
        det = details_by.get(key)
        if not det:
            for dk, dv in details_by.items():
                if dk in key or key in dk:
                    det = dv
                    break
        if det:
            for col in ("Quadrant", "X", "Y", "Overall", "Role"):
                if det.get(col) not in (None, ""):
                    row[col] = det[col]
                    if col == "X":
                        row["X Score"] = det[col]
                    elif col == "Y":
                        row["Y Score"] = det[col]
                    elif col == "Overall":
                        row["Overall Score"] = det[col]
            if det.get("Role"):
                row["Distribution Type"] = det["Role"]
            if det.get("Found in"):
                row["Headquarters"] = det["Found in"]
    return landscape, details_by


def _purge(landscape: list[dict], needles: set[str]) -> tuple[list[dict], list[tuple[str, str]]]:
    kept: list[dict] = []
    removed: list[tuple[str, str]] = []
    for row in landscape:
        ident = _identity(row)
        hit = _should_remove(ident, needles)
        if hit:
            removed.append((ident, hit))
            continue
        kept.append(row)
    return kept, removed


def _run_market(slug: str, query: str, needles: set[str], *, dedupe_flex: bool) -> None:
    folder = ROOT / slug
    xlsx = folder / f"{slug}_FINAL.xlsx"
    landscape, _ = _load(xlsx)
    before = len(landscape)
    landscape, removed = _purge(landscape, needles)
    deduped: list[str] = []
    if dedupe_flex:
        landscape, deduped = _dedupe_flex(landscape)
    after = len(landscape)

    audit_path = folder / "chatgpt_expand_batch_all_audit.json"
    audit: dict = {}
    if audit_path.exists():
        audit = json.loads(audit_path.read_text(encoding="utf-8")).get("xy_scoring") or {}

    detail_rows = to_company_detail_rows(landscape, query, audit)
    write_final_xlsx(
        xlsx,
        landscape,
        "Companies",
        {"query": query, "xy_scoring": audit, "purged": [r[0] for r in removed] + deduped},
        detail_rows=detail_rows,
    )
    extras = export_expand_quadrant_outputs(
        folder, detail_rows, query, country="global", audit=audit, chart_n=20
    )

    audit_out = ROOT / "_audit" / f"{slug}_purge.json"
    audit_out.parent.mkdir(exist_ok=True)
    audit_out.write_text(
        json.dumps(
            {
                "before": before,
                "after": after,
                "removed": [{"name": n, "matched": m} for n, m in removed],
                "deduped": deduped,
                "html": str(extras.get("html") or ""),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"{slug}: {before} → {after} (removed {len(removed)}, deduped {len(deduped)})")
    for n, m in removed:
        print(f"  - {n}  [{m}]")
    for n in deduped:
        print(f"  ~ dedupe {n}")
    print(f"  html -> {extras.get('html')}")


def main() -> None:
    _run_market(
        "global_flexible_packaging_market_global",
        "Global Flexible Packaging Market",
        FLEX_REMOVE,
        dedupe_flex=True,
    )
    _run_market(
        "global_wearable_medical_devices_market_global",
        "Global Wearable Medical Devices Market",
        WEARABLE_REMOVE,
        dedupe_flex=False,
    )


if __name__ == "__main__":
    main()
