#!/usr/bin/env python3
"""Verify Brand rows belong in Global Wearable Medical Devices; drop off-market; refill."""
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
from vendor_intel.quadrant.brand_meta import format_acquired_suffix
from vendor_intel.quadrant.rating_map import assign_quadrants_half_median

OUT = ROOT / "output" / "chatgpt_expand"
SLUG = "global_wearable_medical_devices_market_global"
QUERY = "Global Wearable Medical Devices Market"
FOLDER = OUT / SLUG
INDUSTRY = "Healthcare / Wearable Medical Devices"

# Body-worn / adhesive / textile / hearing / CGM-insulin-patch medical Brands only.
# Remove contactless, handheld exam/stethoscope/resting-ECG kits, pure software/telehealth,
# cold-chain IoT, cosmetics, sports-only, prosthetics, unverified names, BGM-only.
OFF_MARKET: dict[str, str] = {
    "dozee": "Contactless under-mattress BCG — not body-worn",
    "vitalthings": "Contactless wall-mounted monitor — not body-worn",
    "tytocare": "Handheld remote physical-exam kit — not wearable",
    "eko health": "Digital stethoscope — handheld, not wearable",
    "qt medical": "Portable resting 12-lead ECG kit — not wearable",
    "aerotel medical systems": "Handheld/portable event ECG transmitters — not body-worn wearable",
    "ayu devices": "Digital stethoscope / auscultation — handheld, not wearable",
    "nexxto": "Hospital cold-chain / asset IoT — not patient wearable",
    "medpass": "Telehealth / digital care platform — not wearable device Brand",
    "swasth": "Clinic / access network — not wearable device Brand",
    "pluri sistemas": "CRM / contact-center software — not wearable medical",
    "quro medical": "Digital care / telehealth — not wearable device Brand",
    "vitaliberty": "Digital health software — not wearable device Brand",
    "cure bionics": "Prosthetic limb Brand — outside wearable monitoring/therapy scope",
    "feeligreen": "Cosmetic/dermo iontophoresis — not clinical wearable medical Brand",
    "sonofit": "Athletic/performance ultrasound insights — not medical wearable Brand",
    "i-sens": "Primarily BGM meters/strips — not wearable CGM Brand",
    "roche diabetes care": "Primarily Accu-Chek BGM — not wearable CGM Brand",
    "everist health": "AngioDefender vascular test system — not wearable",
    "medlevensohn": "Medical products distributor profile — not wearable Brand",
    "smiths medical": "Infusion/airway consumables focus — not wearable medical Brand",
    "skanray technologies": "Broad patient-monitor OEM — no clear wearable Brand line",
    "bpl medical technologies": "Broad patient-monitor OEM — no clear wearable Brand line",
    "quantified": "No verified wearable medical device Brand identity",
    "medihelp": "No verified wearable medical device Brand identity",
    "meditech": "Ambiguous; no verified wearable medical Brand for this row",
    "aviro health": "No verified wearable medical device Brand identity",
    "healthq technologies": "No verified wearable medical device Brand identity",
    "humis": "No verified wearable medical device Brand identity",
    "mcube technology": "No verified wearable medical device Brand identity",
    "senvital": "No verified wearable medical device Brand identity",
    "sens4care": "No verified wearable medical device Brand identity",
}

# Verified wearable-medical company Brands not already on the sheet.
NEW_BRANDS = [
    {
        "company": "Leaf Healthcare",
        "website": "https://leafhealthcare.com",
        "hq": "Pleasanton, California, USA",
        "founded": "2010",
        "specialty": "LEAF Patient Monitoring System — wearable chest sensor for pressure-injury prevention",
        "categories": "Clinical wearables; Pressure injury",
        "continent": "North America",
        "presence": "USA",
        "country": "US",
        "region": "NA",
        "owner": ("Smith+Nephew", "acquired_by", "2019"),
    },
    {
        "company": "Spry Health",
        "website": "https://www.spryhealth.com",
        "hq": "Palo Alto, California, USA",
        "founded": "2014",
        "specialty": "Loop FDA-cleared clinical wristband for COPD / chronic RPM (SpO2, RR, HR)",
        "categories": "RPM wearables; Respiratory",
        "continent": "North America",
        "presence": "USA",
        "country": "US",
        "region": "NA",
        "owner": ("Itamar Medical", "acquired_by", "2021"),
    },
    {
        "company": "Rooti Labs",
        "website": "https://www.rooticare.com",
        "hq": "Taipei, Taiwan",
        "founded": "2014",
        "specialty": "RootiRx wearable adhesive ECG patch for ambulatory arrhythmia monitoring",
        "categories": "Wearable ECG; Cardiac monitoring",
        "continent": "Asia",
        "presence": "Taiwan, Asia, US",
        "country": "TW",
        "region": "APAC",
    },
    {
        "company": "CardiacSense",
        "website": "https://www.cardiacsense.com",
        "hq": "Caesarea, Israel",
        "founded": "2009",
        "specialty": "Medical-grade wearable watch for continuous AF / vital-sign monitoring",
        "categories": "Wearable cardiac; Continuous monitoring",
        "continent": "Asia",
        "presence": "Israel, Europe",
        "country": "IL",
        "region": "MEA",
    },
    {
        "company": "Cala Health",
        "website": "https://calahealth.com",
        "hq": "San Mateo, California, USA",
        "founded": "2014",
        "specialty": "Cala kIQ wearable neuromodulation for essential tremor",
        "categories": "Wearable neuromodulation; Neurology",
        "continent": "North America",
        "presence": "USA",
        "country": "US",
        "region": "NA",
    },
    {
        "company": "Theranica",
        "website": "https://theranica.com",
        "hq": "Netanya, Israel",
        "founded": "2016",
        "specialty": "Nerivio wearable remote electrical neuromodulation for migraine",
        "categories": "Wearable neuromodulation; Migraine",
        "continent": "Asia",
        "presence": "Israel, USA",
        "country": "IL",
        "region": "MEA",
    },
    {
        "company": "Cefaly Technology",
        "website": "https://www.cefaly.com",
        "hq": "Seraing, Belgium",
        "founded": "2004",
        "specialty": "CEFALY wearable external trigeminal nerve stimulation for migraine",
        "categories": "Wearable neuromodulation; Migraine",
        "continent": "Europe",
        "presence": "Belgium, USA, Global",
        "country": "BE",
        "region": "EU",
    },
    {
        "company": "BioSerenity",
        "website": "https://www.bioserenity.com",
        "hq": "Paris, France",
        "founded": "2014",
        "specialty": "Neuronaute / Cardioskin wearable EEG and ECG medical monitoring solutions",
        "categories": "Wearable EEG/ECG; Neurology; Cardiology",
        "continent": "Europe",
        "presence": "France, USA, Global",
        "country": "FR",
        "region": "EU",
    },
    {
        "company": "Cortrium",
        "website": "https://www.cortrium.com",
        "hq": "Copenhagen, Denmark",
        "founded": "2014",
        "specialty": "C3+ wearable clinical ECG patch for ambulatory monitoring",
        "categories": "Wearable ECG; Cardiac monitoring",
        "continent": "Europe",
        "presence": "Denmark, Europe",
        "country": "DK",
        "region": "EU",
    },
    {
        "company": "Mawi Health",
        "website": "https://www.mawi.band",
        "hq": "Wilmington, Delaware, USA",
        "founded": "2017",
        "specialty": "Mawi Heart Band wearable ECG for arrhythmia detection",
        "categories": "Wearable ECG; Cardiac",
        "continent": "North America",
        "presence": "USA, Europe",
        "country": "US",
        "region": "NA",
    },
    {
        "company": "Nox Medical",
        "website": "https://noxmedical.com",
        "hq": "Reykjavik, Iceland",
        "founded": "2006",
        "specialty": "Nox A1 / T3 wearable sleep diagnostic sensors and belts",
        "categories": "Sleep diagnostics; Wearable PSG",
        "continent": "Europe",
        "presence": "Iceland, Global",
        "country": "IS",
        "region": "EU",
    },
    {
        "company": "Advanced Brain Monitoring",
        "website": "https://www.advancedbrainmonitoring.com",
        "hq": "Carlsbad, California, USA",
        "founded": "1997",
        "specialty": "Stat X24 / B-Alert wearable EEG systems for clinical and research use",
        "categories": "Wearable EEG; Neurodiagnostics",
        "continent": "North America",
        "presence": "USA",
        "country": "US",
        "region": "NA",
    },
    {
        "company": "Propeller Health",
        "website": "https://propellerhealth.com",
        "hq": "Madison, Wisconsin, USA",
        "founded": "2010",
        "specialty": "Propeller sensor attaches to inhalers for adherence / respiratory monitoring",
        "categories": "Respiratory sensors; Connected therapeutics",
        "continent": "North America",
        "presence": "USA, Global",
        "country": "US",
        "region": "NA",
        "owner": ("ResMed", "acquired_by", "2022"),
    },
    {
        "company": "Amiko",
        "website": "https://www.amiko.io",
        "hq": "Milan, Italy",
        "founded": "2015",
        "specialty": "Respiro wearable smart inhaler sensors for respiratory adherence",
        "categories": "Respiratory sensors; Connected therapeutics",
        "continent": "Europe",
        "presence": "Italy, Europe",
        "country": "IT",
        "region": "EU",
    },
    {
        "company": "Adherium",
        "website": "https://www.adherium.com",
        "hq": "Melbourne, Victoria, Australia",
        "founded": "2001",
        "specialty": "Hailie wearable smart inhaler sensors for asthma / COPD adherence",
        "categories": "Respiratory sensors; Connected therapeutics",
        "continent": "Oceania",
        "presence": "Australia, Global",
        "country": "AU",
        "region": "APAC",
    },
    {
        "company": "NightBalance",
        "website": "https://www.nightbalance.com",
        "hq": "Amsterdam, Netherlands",
        "founded": "2009",
        "specialty": "Sleep position trainer wearable for positional obstructive sleep apnea",
        "categories": "Sleep therapy wearables",
        "continent": "Europe",
        "presence": "Netherlands, Global",
        "country": "NL",
        "region": "EU",
        "owner": ("Philips", "acquired_by", "2018"),
    },
    {
        "company": "Compumedics",
        "website": "https://www.compumedics.com.au",
        "hq": "Melbourne, Victoria, Australia",
        "founded": "1987",
        "specialty": "Somté / Grael wearable ambulatory sleep and neurodiagnostic systems",
        "categories": "Sleep diagnostics; Ambulatory EEG",
        "continent": "Oceania",
        "presence": "Australia, Global",
        "country": "AU",
        "region": "APAC",
    },
    {
        "company": "Bitbrain",
        "website": "https://www.bitbrain.com",
        "hq": "Zaragoza, Spain",
        "founded": "2010",
        "specialty": "Wearable dry-EEG headsets and biosensor systems for clinical research",
        "categories": "Wearable EEG; Neurotech",
        "continent": "Europe",
        "presence": "Spain, Europe",
        "country": "ES",
        "region": "EU",
    },
    {
        "company": "Sana Health",
        "website": "https://www.sana.io",
        "hq": "San Francisco, California, USA",
        "founded": "2017",
        "specialty": "Sana wearable audiovisual neuromodulation mask for pain / sleep",
        "categories": "Wearable neuromodulation",
        "continent": "North America",
        "presence": "USA",
        "country": "US",
        "region": "NA",
    },
    {
        "company": "NeuraMetrix",
        "website": "https://www.neurametrix.com",
        "hq": "San Francisco, California, USA",
        "founded": "2015",
        "specialty": "skip — typing biometrics software not wearable hardware",
        "categories": "Digital biomarker",
        "continent": "North America",
        "presence": "USA",
        "country": "US",
        "region": "NA",
        "skip": True,
    },
    {
        "company": "Happy Health",
        "website": "https://www.happy.org",
        "hq": "Austin, Texas, USA",
        "founded": "2017",
        "specialty": "Happy Ring medical-grade wearable ring for continuous health monitoring",
        "categories": "Clinical wearable ring",
        "continent": "North America",
        "presence": "USA",
        "country": "US",
        "region": "NA",
    },
    {
        "company": "Circul",
        "website": "https://www.bodimetrics.com",
        "hq": "Manhattan Beach, California, USA",
        "founded": "2015",
        "specialty": "Circul ring wearable overnight SpO2 / sleep apnea screening",
        "categories": "Wearable SpO2; Sleep",
        "continent": "North America",
        "presence": "USA",
        "country": "US",
        "region": "NA",
    },
    {
        "company": "Belun Technology",
        "website": "https://belun.tech",
        "hq": "Hong Kong, China",
        "founded": "2016",
        "specialty": "Belun Ring FDA-cleared wearable for sleep apnea / SpO2 monitoring",
        "categories": "Wearable SpO2; Sleep",
        "continent": "Asia",
        "presence": "Hong Kong, USA, Asia",
        "country": "HK",
        "region": "APAC",
    },
    {
        "company": "SleepImage",
        "website": "https://sleepimage.com",
        "hq": "Denver, Colorado, USA",
        "founded": "2009",
        "specialty": "SleepImage Ring wearable cardiopulmonary coupling sleep assessment",
        "categories": "Wearable sleep diagnostics",
        "continent": "North America",
        "presence": "USA",
        "country": "US",
        "region": "NA",
    },
    {
        "company": "Sunrise",
        "website": "https://www.hellosunrise.com",
        "hq": "Namur, Belgium",
        "founded": "2015",
        "specialty": "Sunrise chin sensor wearable for home sleep apnea testing",
        "categories": "Wearable sleep diagnostics",
        "continent": "Europe",
        "presence": "Belgium, Europe, USA",
        "country": "BE",
        "region": "EU",
    },
    {
        "company": "Acurable",
        "website": "https://acurable.com",
        "hq": "London, United Kingdom",
        "founded": "2016",
        "specialty": "skip if already present",
        "categories": "Sleep",
        "continent": "Europe",
        "presence": "UK",
        "country": "GB",
        "region": "EU",
        "skip_if": "acurable",
    },
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
        o, rel, year = owner
        row["_display_company"] = format_acquired_suffix(o, relation=rel, year=year or "")
        row["Ownership"] = f"{rel.replace('_', ' ')} {o}" + (f", {year}" if year else "")
    return row


async def main() -> int:
    apply_env_overrides()
    os.environ["EXPAND_XY_SKIP_CRAWL"] = "1"
    os.environ["EXPAND_MARKET_AXIS_LLM"] = "1"

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

        role = str(d.get("Role") or "Brand")
        if role == "Brand" and key in OFF_MARKET:
            removed.append({"brand": brand, "reason": OFF_MARKET[key]})
            continue

        d["Brand"] = brand
        d["Company"] = brand
        d["Role"] = role if role in {"Brand", "Marketer"} else "Brand"
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
        if skip_if and any(str(skip_if).lower() in e for e in existing):
            continue
        name = c["company"]
        if _norm(name) in existing:
            continue
        row = _row_brand(c)
        kept.append(row)
        need_score.append(row)
        added.append(name)
        existing.add(_norm(name))

    print(f"Removed {len(removed)} off-market; added {len(added)}; total {len(kept)}", flush=True)

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
            r["Overall Score"] = round(
                (float(r.get("X Score") or 50) + float(r.get("Y Score") or 50)) / 2
            )
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
        {
            "query": QUERY,
            "xy_scoring": audit,
            "off_market_removed": removed,
            "added": added,
        },
        detail_rows=detail_rows,
    )
    extras = export_expand_quadrant_outputs(
        FOLDER, detail_rows, QUERY, country="global", audit=audit, chart_n=20
    )

    roles = dict(Counter(r.get("Role") for r in detail_rows))
    out = {
        "removed": removed,
        "added": added,
        "final_count": len(detail_rows),
        "roles": roles,
        "html": str(extras.get("html") or ""),
        "criterion": (
            "Body-worn / adhesive / textile / hearing / CGM-insulin-patch medical Brands "
            "for Global Wearable Medical Devices. Exclude contactless, handheld exam kits, "
            "pure software/telehealth, cold-chain IoT, cosmetics, sports-only, prosthetics, "
            "and unverified names."
        ),
    }
    path = OUT / "_audit" / "wearable_brand_market_relevance.json"
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    md = OUT / "_audit" / "wearable_brand_market_relevance.md"
    lines = [
        "# Brand market-relevance verification — Wearable Medical Devices",
        "",
        f"Final **{len(detail_rows)}** — {roles}",
        "",
        "## Criterion",
        "",
        out["criterion"],
        "",
        "## Removed (not related)",
        "",
        "| Brand | Reason |",
        "|---|---|",
    ]
    for r in removed:
        lines.append(f"| {r['brand']} | {r['reason']} |")
    lines.extend(["", f"## Added ({len(added)})", "", ", ".join(added) or "(none)", ""])
    md.write_text("\n".join(lines), encoding="utf-8")
    print(f"Final {out['final_count']} roles={roles}", flush=True)
    print(f"audit -> {md}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
