#!/usr/bin/env python3
"""Audit-fix Brand list: remove non-brands; add verified wearable medical Brands."""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from openpyxl import load_workbook

from vendor_intel.placeholders.load_keys import apply_env_overrides
from vendor_intel.pipeline.expand_quadrant_score import (
    export_expand_quadrant_outputs,
    score_expand_rows,
    to_company_detail_rows,
)
from vendor_intel.pipeline.web_expand import write_final_xlsx
from vendor_intel.quadrant.rating_map import assign_quadrants_half_median

OUT = ROOT / "output" / "chatgpt_expand"
SLUG = "global_wearable_medical_devices_market_global"
QUERY = "Global Wearable Medical Devices Market"
FOLDER = OUT / SLUG
INDUSTRY = "Healthcare / Wearable Medical Devices"

# Web-verified: NOT a wearable-medical device Brand (wrong vertical / software-only /
# algorithm OEM / handheld non-wearable / product duplicate).
REMOVE_BRAND = {
    "everysens": "Rail freight TVMS — not medical wearable",
    "echonous": "Handheld POCUS ultrasound — not body-worn wearable",
    "cambridge cognition": "Cognitive assessment software on third-party devices — not device Brand",
    "lifeq": "Biometric algorithm OEM/enablement for other brands — not device Brand",
    "vitalograph": "Handheld spirometry — not wearable",
    "digital health technologies": "Unverified/placeholder name — no clear wearable Brand",
    "tanita": "Primarily body-composition scales — not wearable medical Brand",
    "earlysense": "Contact-free under-mattress sensor; company ceased — not worn wearable Brand",
    "siemens healthineers": "Hospital imaging/diagnostics conglomerate — no clear wearable medical Brand line",
    "tricog health": "VCardia is portable clinical ECG machine — not body-worn wearable Brand",
    "vitaliti": "Product brand of Cloud DX Vitaliti wearable — duplicate of Cloud DX Brand",
}

# New verified wearable medical Brands to replace removals
NEW_BRANDS = [
    {"company": "Acurable", "website": "https://acurable.com", "hq": "London, United Kingdom", "founded": "2016", "specialty": "AcuPebble CE-marked wearable for home sleep apnoea diagnosis", "categories": "Sleep wearable; Respiratory diagnostics", "continent": "Europe", "presence": "UK, Europe, USA", "country": "GB", "region": "EU"},
    {"company": "Onera Health", "website": "https://www.onerahealth.com", "hq": "Eindhoven, Netherlands", "founded": "2017", "specialty": "Onera STS wearable patch polysomnography for home sleep testing", "categories": "Sleep wearable; Polysomnography", "continent": "Europe", "presence": "Europe, USA", "country": "NL", "region": "EU"},
    {"company": "Itamar Medical", "website": "https://www.itamar-medical.com", "hq": "Caesarea, Israel", "founded": "1997", "specialty": "WatchPAT wearable home sleep apnea testing brand", "categories": "Sleep wearable; Home sleep testing", "continent": "Asia", "presence": "Israel, USA, global", "country": "IL", "region": "MEA", "owner": ("Zoll Medical / Asahi Kasei", "acquired_by", "2021")},
    {"company": "X-trodes", "website": "https://xtrodes.com", "hq": "Herzliya, Israel", "founded": "2019", "specialty": "Smart Skin wearable EEG/EMG electrode patches", "categories": "Neuro wearables; EEG/EMG", "continent": "Asia", "presence": "Israel, USA", "country": "IL", "region": "MEA"},
    {"company": "Epicore Biosystems", "website": "https://www.epicorebiosystems.com", "hq": "Cambridge, Massachusetts, USA", "founded": "2017", "specialty": "Gx Sweat Patch wearable microfluidic sweat biomarker sensors", "categories": "Sweat biosensor wearables; Hydration", "continent": "North America", "presence": "USA", "country": "US", "region": "NA"},
    {"company": "Rhaeos", "website": "https://www.rhaeos.com", "hq": "Evanston, Illinois, USA", "founded": "2018", "specialty": "FlowSense wearable skin sensor for shunt/flow monitoring", "categories": "Clinical wearables; Flow sensing", "continent": "North America", "presence": "USA", "country": "US", "region": "NA"},
    {"company": "PD Neurotechnology", "website": "https://www.pdneurotechnology.com", "hq": "London, United Kingdom", "founded": "2015", "specialty": "PDMonitor wearable for Parkinson's motor symptom monitoring", "categories": "Neuro wearables; Parkinson's", "continent": "Europe", "presence": "UK, Greece, Europe", "country": "GB", "region": "EU"},
    {"company": "Byteflies Sensor Dot", "website": "https://www.byteflies.com", "hq": "Antwerp, Belgium", "founded": "2015", "specialty": "Sensor Dot multimodal clinical wearable (keep if Byteflies exists skip)", "categories": "Clinical wearables; Multimodal", "continent": "Europe", "presence": "Belgium, Europe", "country": "BE", "region": "EU", "skip_if": "byteflies"},
    {"company": "Somnofy", "website": "https://www.somnofy.com", "hq": "Trondheim, Norway", "founded": "2015", "specialty": "Contactless/radar sleep monitor brand — borderline skip if not worn", "categories": "Sleep monitoring", "continent": "Europe", "presence": "Norway, Europe", "country": "NO", "region": "EU", "skip": True},
    {"company": "Circadia Health", "website": "https://www.circadia.health", "hq": "London, United Kingdom", "founded": "2016", "specialty": "Circadia C100 contactless respiratory monitor — skip if not worn", "categories": "Respiratory monitoring", "continent": "Europe", "presence": "UK, USA", "country": "GB", "region": "EU", "skip": True},
    {"company": "Biostrap", "website": "https://biostrap.com", "hq": "Los Angeles, California, USA", "founded": "2016", "specialty": "Clinical-grade wearable biometric wristband/platform", "categories": "Clinical wearables; Biometrics", "continent": "North America", "presence": "USA", "country": "US", "region": "NA"},
    {"company": "Whoop Medical", "website": "https://www.whoop.com", "hq": "Boston, Massachusetts, USA", "founded": "2012", "specialty": "skip consumer fitness", "categories": "Fitness", "continent": "North America", "presence": "USA", "country": "US", "region": "NA", "skip": True},
    {"company": "Oura Ring Medical", "website": "https://ouraring.com", "hq": "Oulu, Finland", "founded": "2013", "specialty": "skip consumer", "categories": "Fitness", "continent": "Europe", "presence": "Finland, USA", "country": "FI", "region": "EU", "skip": True},
    {"company": "G-Tech Medical", "website": "https://gtechmedical.com", "hq": "Mountain View, California, USA", "founded": "2010", "specialty": "Wearable gut electrophysiology patch for GI monitoring", "categories": "GI wearables; Electrophysiology", "continent": "North America", "presence": "USA", "country": "US", "region": "NA"},
    {"company": "Bloomlife", "website": "https://bloomlife.com", "hq": "San Francisco, California, USA", "founded": "2014", "specialty": "Wearable pregnancy contraction monitoring patch", "categories": "Maternal wearables; Ob/Gyn", "continent": "North America", "presence": "USA, Europe", "country": "US", "region": "NA"},
    {"company": "Nuvo Group", "website": "https://www.nuvocares.com", "hq": "Tel Aviv, Israel", "founded": "2014", "specialty": "INVU wearable remote pregnancy monitoring platform", "categories": "Maternal wearables; Remote monitoring", "continent": "Asia", "presence": "Israel, USA", "country": "IL", "region": "MEA"},
    {"company": "Sibel Health ANNE", "website": "https://sibelhealth.com", "hq": "Chicago, Illinois, USA", "founded": "2018", "specialty": "skip duplicate of Sibel Health", "categories": "Clinical wearables", "continent": "North America", "presence": "USA", "country": "US", "region": "NA", "skip_if": "sibel health"},
    {"company": "BioIntelliSense BioButton", "website": "https://biointellisense.com", "hq": "Golden, Colorado, USA", "founded": "2018", "specialty": "skip duplicate", "categories": "Clinical wearables", "continent": "North America", "presence": "USA", "country": "US", "region": "NA", "skip_if": "biointellisense"},
    {"company": "Enso", "website": "https://www.hingehealth.com", "hq": "San Francisco, California, USA", "founded": "2015", "specialty": "FDA-cleared wearable HFIT pain-relief device brand (Hinge Health)", "categories": "Pain wearable; Neuromodulation", "continent": "North America", "presence": "USA", "country": "US", "region": "NA", "owner": ("Hinge Health", "acquired_by", "2021")},
    {"company": "HeartCheck", "website": "https://cardiocommsolutions.com", "hq": "Toronto, Ontario, Canada", "founded": "2000", "specialty": "skip duplicate of CardioComm HeartCheck brand", "categories": "ECG", "continent": "North America", "presence": "Canada", "country": "CA", "region": "NA", "skip_if": "cardiocomm"},
]


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


def _row_brand(c: dict) -> dict:
    name = c["company"]
    hq = c.get("hq") or ""
    row = {
        "Company": name,
        "Website": c.get("website") or "",
        "Founded": c.get("founded") or "",
        "Headquarters": hq,
        "Continent / Geography": c.get("continent") or "",
        "Operational Presence": c.get("presence") or "",
        "Ownership": "Independent",
        "Employees": "",
        "Core Categories": c.get("categories") or "",
        "Specialty Focus": c.get("specialty") or "",
        "Key Brands Represented": name,
        "Retail / E-commerce / Both": "No",
        "Distribution Type": "Brand",
        "Contact Person": "",
        "Role": "Brand",
        "Email": "",
        "LinkedIn": "",
        "Office No.": "",
        "Country Code": c.get("country") or "",
        "Region Code": c.get("region") or "",
        "Summary": f"{name} — wearable medical Brand. {c.get('specialty') or ''}".strip(),
        "X Score": "",
        "Y Score": "",
        "Overall Score": "",
        "Quadrant": "",
        "Industry Category": INDUSTRY,
        "Brand": name,
        "Found in": hq,
    }
    owner = c.get("owner")
    if owner:
        from vendor_intel.quadrant.brand_meta import format_acquired_suffix

        o, rel, year = owner
        row["_display_company"] = format_acquired_suffix(o, relation=rel, year=year)
        row["Ownership"] = f"{rel.replace('_', ' ')} {o}" + (f", {year}" if year else "")
    return row


async def main() -> int:
    apply_env_overrides()
    os.environ["EXPAND_XY_SKIP_CRAWL"] = "1"
    os.environ["EXPAND_MARKET_AXIS_LLM"] = "1"
    os.environ.setdefault("EXPAND_XY_CONCURRENT", "6")

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
            key = _norm(d.get("Brand") or d.get("Company") or "")
            if key:
                details_by[key] = d

    kept: list[dict] = []
    removed: list[dict] = []
    existing: set[str] = set()
    for r in rows_raw[1:]:
        if not r:
            continue
        d = {hdr[i]: ("" if r[i] is None else r[i]) for i in range(len(hdr)) if i < len(r)}
        brand = str(d.get("Company") or d.get("Brand") or "").strip()
        if not brand:
            continue
        key = _norm(brand)
        det = details_by.get(key)
        if det:
            if det.get("Brand"):
                brand = str(det["Brand"]).strip()
                key = _norm(brand)
                d["Brand"] = brand
            if det.get("Company") and str(det["Company"]).startswith("("):
                d["_display_company"] = det["Company"]
            if det.get("X") not in (None, ""):
                d["X Score"] = det["X"]
                d["Y Score"] = det["Y"]
                d["Overall Score"] = det["Overall"]
                d["Quadrant"] = det.get("Quadrant") or ""
            if det.get("Found in"):
                d["Headquarters"] = det["Found in"]
                d["Found in"] = det["Found in"]
            if det.get("Role") in {"Brand", "Marketer"}:
                d["Role"] = det["Role"]
                d["Distribution Type"] = det["Role"]

        reason = REMOVE_BRAND.get(key)
        if reason and (d.get("Role") or "Brand") == "Brand":
            removed.append({"brand": brand, "reason": reason})
            continue
        # Also remove if key matches even when role Marketer? only Brand list audit
        if reason:
            removed.append({"brand": brand, "reason": reason})
            continue

        d["Brand"] = brand
        d["Company"] = brand
        d["Role"] = d.get("Role") or "Brand"
        if d["Role"] not in {"Brand", "Marketer"}:
            d["Role"] = "Brand"
        d["Distribution Type"] = d["Role"]
        d["Industry Category"] = INDUSTRY
        kept.append(d)
        existing.add(_norm(brand))

    added: list[str] = []
    need_score: list[dict] = []
    for c in NEW_BRANDS:
        if c.get("skip"):
            continue
        skip_if = c.get("skip_if")
        if skip_if and any(skip_if in e for e in existing):
            continue
        name = c["company"]
        if _norm(name) in existing:
            continue
        row = _row_brand(c)
        kept.append(row)
        need_score.append(row)
        added.append(name)
        existing.add(_norm(name))

    print(f"Removed {len(removed)} false Brands; added {len(added)}; total {len(kept)}", flush=True)

    if need_score:
        scored, _ = await score_expand_rows(need_score, QUERY, country="global")
        by = {_norm(r.get("Company") or r.get("Brand") or ""): r for r in scored}
        for r in kept:
            s = by.get(_norm(r.get("Brand") or ""))
            if not s:
                continue
            for col in ("X Score", "Y Score", "Overall Score", "Quadrant", "Summary"):
                if s.get(col) not in (None, ""):
                    r[col] = s[col]
            r["Role"] = "Brand"
            r["Distribution Type"] = "Brand"

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
    quads, _, _ = assign_quadrants_half_median(xs, ys)
    for r, q in zip(kept, quads):
        r["Quadrant"] = q
        try:
            r["Overall Score"] = round((float(r.get("X Score") or 50) + float(r.get("Y Score") or 50)) / 2)
        except (TypeError, ValueError):
            pass

    audit: dict = {}
    audit_path = FOLDER / "chatgpt_expand_batch_all_audit.json"
    if audit_path.exists():
        audit = json.loads(audit_path.read_text(encoding="utf-8")).get("xy_scoring") or {}
    qjson = FOLDER / f"{SLUG}_quadrant.json"
    if qjson.exists():
        try:
            payload = json.loads(qjson.read_text(encoding="utf-8"))
            crit = payload.get("criteria") or {}
            if crit.get("parameter_definitions"):
                audit["parameter_definitions"] = crit["parameter_definitions"]
            labels = crit.get("axis_labels") or {}
            if labels.get("x"):
                audit["axis_x"] = labels["x"]
            if labels.get("y"):
                audit["axis_y"] = labels["y"]
            if crit.get("x_axis"):
                audit["x_features"] = crit["x_axis"]
            if crit.get("y_axis"):
                audit["y_features"] = crit["y_axis"]
        except Exception:
            pass

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

    write_final_xlsx(
        xlsx,
        kept,
        "Companies",
        {"query": QUERY, "xy_scoring": audit, "brand_audit_removed": removed, "brand_audit_added": added},
        detail_rows=detail_rows,
    )
    extras = export_expand_quadrant_outputs(
        FOLDER, detail_rows, QUERY, country="global", audit=audit, chart_n=20
    )

    roles = dict(Counter(r.get("Role") for r in detail_rows))
    out = {
        "verdict": "Not all prior Brands were legitimate wearable-medical Brands",
        "removed_false_brands": removed,
        "added_true_brands": added,
        "final_count": len(detail_rows),
        "roles": roles,
        "html": str(extras.get("html") or ""),
    }
    path = OUT / "_audit" / "wearable_brand_verification.json"
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    md = OUT / "_audit" / "wearable_brand_verification.md"
    lines = [
        "# Wearable Brand verification",
        "",
        f"Final: **{len(detail_rows)}** companies — roles {roles}",
        "",
        "## Removed (were labeled Brand but are NOT wearable-medical Brands)",
        "",
        "| Brand | Reason |",
        "|---|---|",
    ]
    for r in removed:
        lines.append(f"| {r['brand']} | {r['reason']} |")
    lines.extend(["", "## Added verified Brands", "", ", ".join(added) or "(none)", ""])
    md.write_text("\n".join(lines), encoding="utf-8")
    print(f"Final {out['final_count']} roles={roles}", flush=True)
    print(f"audit -> {md}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
