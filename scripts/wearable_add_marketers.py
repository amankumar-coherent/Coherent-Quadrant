#!/usr/bin/env python3
"""Split wearable Brand vs Marketer; add verified Marketer companies."""
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

# Existing rows that commercialize / market wearable medical products
# primarily without being the device OEM brand owner.
RECLASSIFY_MARKETER = {
    "ascensia diabetes care": "Exclusive commercial/marketing partner for Senseonics Eversense CGM (Contour BGM is separate)",
    # livongo / huma / lively kept as Brand — do not reclass to Marketer
    "cadence": "Markets technology-enabled RPM programs using clinical wearables",
}

# New Marketer companies (web-verified: commercialize wearables they do not primarily manufacture)
NEW_MARKETERS = [
    {
        "company": "Nutrisense",
        "website": "https://www.nutrisense.io",
        "hq": "Chicago, Illinois, USA",
        "founded": "2019",
        "specialty": "Markets Abbott/Dexcom CGM subscriptions with dietitian coaching (acquired by Dexcom)",
        "categories": "CGM program marketer; Metabolic health",
        "continent": "North America",
        "presence": "USA",
        "country": "US",
        "region": "NA",
        "owner": ("Dexcom", "acquired_by", "2026"),
    },
    {
        "company": "Levels Health",
        "website": "https://www.levelshealth.com",
        "hq": "New York, New York, USA",
        "founded": "2019",
        "specialty": "Markets CGM-based metabolic health programs using third-party sensors",
        "categories": "CGM program marketer; Metabolic health",
        "continent": "North America",
        "presence": "USA",
        "country": "US",
        "region": "NA",
    },
    {
        "company": "Signos",
        "website": "https://www.signos.com",
        "hq": "San Francisco, California, USA",
        "founded": "2018",
        "specialty": "Markets FDA-cleared CGM weight-management programs (Dexcom sensors)",
        "categories": "CGM program marketer; Weight management",
        "continent": "North America",
        "presence": "USA",
        "country": "US",
        "region": "NA",
    },
    {
        "company": "Veri",
        "website": "https://www.veri.co",
        "hq": "Helsinki, Finland",
        "founded": "2019",
        "specialty": "Markets Abbott Libre CGM metabolic health subscriptions",
        "categories": "CGM program marketer; Metabolic health",
        "continent": "Europe",
        "presence": "Europe, USA",
        "country": "FI",
        "region": "EU",
    },
    {
        "company": "January AI",
        "website": "https://www.january.ai",
        "hq": "Menlo Park, California, USA",
        "founded": "2017",
        "specialty": "Markets CGM + digital twin metabolic programs",
        "categories": "CGM program marketer; AI metabolic",
        "continent": "North America",
        "presence": "USA",
        "country": "US",
        "region": "NA",
    },
    {
        "company": "ZOE",
        "website": "https://zoe.com",
        "hq": "London, United Kingdom",
        "founded": "2017",
        "specialty": "Markets personalized nutrition programs including CGM testing kits",
        "categories": "Metabolic program marketer; Nutrition",
        "continent": "Europe",
        "presence": "UK, USA",
        "country": "GB",
        "region": "EU",
    },
    {
        "company": "Supersapiens",
        "website": "https://www.supersapiens.com",
        "hq": "Atlanta, Georgia, USA",
        "founded": "2019",
        "specialty": "Markets Abbott Libre Sense glucose sports performance programs",
        "categories": "CGM program marketer; Sports performance",
        "continent": "North America",
        "presence": "USA, Europe",
        "country": "US",
        "region": "NA",
    },
    {
        "company": "HELLO INSIDE",
        "website": "https://www.helloinside.com",
        "hq": "Vienna, Austria",
        "founded": "2021",
        "specialty": "Markets CGM-based women's metabolic health programs",
        "categories": "CGM program marketer; Women's health",
        "continent": "Europe",
        "presence": "Europe",
        "country": "AT",
        "region": "EU",
    },
    {
        "company": "Amplifon",
        "website": "https://www.amplifon.com",
        "hq": "Milan, Italy",
        "founded": "1950",
        "specialty": "Global hearing-care marketer/retailer of wearable hearing devices (Miracle-Ear, Amplifon)",
        "categories": "Hearing care marketer; Wearable hearing aids",
        "continent": "Europe",
        "presence": "Global (10,000+ points of sale)",
        "country": "IT",
        "region": "EU",
    },
    {
        "company": "Miracle-Ear",
        "website": "https://www.miracle-ear.com",
        "hq": "Minneapolis, Minnesota, USA",
        "founded": "1948",
        "specialty": "US hearing-aid marketer brand network (Amplifon)",
        "categories": "Hearing care marketer; Hearing aids",
        "continent": "North America",
        "presence": "USA (1,500+ centers)",
        "country": "US",
        "region": "NA",
        "owner": ("Amplifon", "subsidiary_of", ""),
    },
    {
        "company": "HearingLife",
        "website": "https://www.hearinglife.com",
        "hq": "Somerset, New Jersey, USA",
        "founded": "2017",
        "specialty": "US hearing-care clinic network marketing Oticon/Demant wearable aids",
        "categories": "Hearing care marketer; Hearing aids",
        "continent": "North America",
        "presence": "USA",
        "country": "US",
        "region": "NA",
        "owner": ("Demant", "subsidiary_of", ""),
    },
    {
        "company": "Audika",
        "website": "https://www.audika.com",
        "hq": "Copenhagen, Denmark",
        "founded": "2002",
        "specialty": "Global Demant hearing-care clinic brand marketing wearable hearing aids",
        "categories": "Hearing care marketer; Hearing aids",
        "continent": "Europe",
        "presence": "24+ countries",
        "country": "DK",
        "region": "EU",
        "owner": ("Demant", "subsidiary_of", ""),
    },
    {
        "company": "Specsavers Hearcare",
        "website": "https://www.specsavers.com",
        "hq": "Guernsey, United Kingdom",
        "founded": "1984",
        "specialty": "Markets Specsavers hearing aids and wearable hearing care services",
        "categories": "Hearing care marketer; Optical/hearing retail",
        "continent": "Europe",
        "presence": "UK, Europe, ANZ",
        "country": "GB",
        "region": "EU",
    },
    {
        "company": "Fielmann Group",
        "website": "https://www.fielmann.com",
        "hq": "Hamburg, Germany",
        "founded": "1972",
        "specialty": "European optical/hearing retailer marketing wearable hearing devices",
        "categories": "Hearing care marketer; Optical retail",
        "continent": "Europe",
        "presence": "Europe",
        "country": "DE",
        "region": "EU",
    },
    {
        "company": "Kind Hörgeräte",
        "website": "https://www.kind.com",
        "hq": "Großburgwedel, Germany",
        "founded": "1952",
        "specialty": "German hearing-care chain marketing wearable hearing aids",
        "categories": "Hearing care marketer; Hearing aids",
        "continent": "Europe",
        "presence": "Germany, Europe",
        "country": "DE",
        "region": "EU",
    },
    {
        "company": "GEMCO Medical",
        "website": "https://www.gemcomedical.com",
        "hq": "Hudson, Ohio, USA",
        "founded": "1987",
        "specialty": "Specialty marketer of CGM resupply programs (Abbott/Dexcom) to DME channels",
        "categories": "CGM channel marketer; Diabetes supplies",
        "continent": "North America",
        "presence": "USA",
        "country": "US",
        "region": "NA",
    },
    {
        "company": "DDP Medical Supply",
        "website": "https://ddpmedical.com",
        "hq": "USA",
        "founded": "",
        "specialty": "Authorized specialty marketer/wholesaler of Abbott and Dexcom CGMs to DMEs",
        "categories": "CGM channel marketer; Diabetes supplies",
        "continent": "North America",
        "presence": "USA",
        "country": "US",
        "region": "NA",
    },
    {
        "company": "Ancillare",
        "website": "https://www.ancillare.com",
        "hq": "Horsham, Pennsylvania, USA",
        "founded": "2005",
        "specialty": "Markets/supplies Dexcom CGMs into global clinical trials",
        "categories": "Clinical trial CGM marketer; Trial supply",
        "continent": "North America",
        "presence": "USA, global trials",
        "country": "US",
        "region": "NA",
    },
    {
        "company": "Ultrahuman",
        "website": "https://www.ultrahuman.com",
        "hq": "Bengaluru, Karnataka, India",
        "founded": "2019",
        "specialty": "Markets M1 CGM metabolic programs (sensor partners)",
        "categories": "CGM program marketer; Metabolic health",
        "continent": "Asia",
        "presence": "India, UAE, global",
        "country": "IN",
        "region": "APAC",
    },
    # Lively is Brand (medical-alert wearable), not Marketer — see wearable_full_role_audit.py
    {
        "company": "Best Buy Health",
        "website": "https://www.bestbuy.com/health",
        "hq": "Richfield, Minnesota, USA",
        "founded": "2018",
        "specialty": "Markets home health wearable and RPM device programs (Lively, care platforms)",
        "categories": "Health wearable marketer; Retail health",
        "continent": "North America",
        "presence": "USA",
        "country": "US",
        "region": "NA",
        "owner": ("Best Buy", "subsidiary_of", ""),
    },
]


def _norm(s: str) -> str:
    s = str(s or "").strip().lower()
    s = re.sub(r"[®™]", "", s)
    s = re.sub(r"\s+", " ", s)
    return s


def _row_marketer(c: dict) -> dict:
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
        "Retail / E-commerce / Both": "Both",
        "Distribution Type": "Marketer",
        "Contact Person": "",
        "Role": "Marketer",
        "Email": "",
        "LinkedIn": "",
        "Office No.": "",
        "Country Code": c.get("country") or "",
        "Region Code": c.get("region") or "",
        "Summary": f"{name} — wearable medical Marketer. {c.get('specialty') or ''}".strip(),
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
        row["_display_company"] = format_acquired_suffix(o, relation=rel, year=year)
        row["Ownership"] = f"{rel.replace('_', ' ')} {o}" + (f", {year}" if year else "")
        row["parent_owner"] = o
        row["ownership_relation"] = rel
        if year:
            row["ownership_year"] = year
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

    landscape: list[dict] = []
    existing: set[str] = set()
    reclassed: list[dict] = []
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

        d["Brand"] = brand
        d["Company"] = brand
        if key in RECLASSIFY_MARKETER:
            d["Role"] = "Marketer"
            d["Distribution Type"] = "Marketer"
            note = RECLASSIFY_MARKETER[key]
            d["Specialty Focus"] = note
            if d.get("Summary"):
                d["Summary"] = f"{brand} — Marketer. {note}"
            reclassed.append({"brand": brand, "reason": note})
        else:
            d["Role"] = str(d.get("Role") or "Brand")
            if d["Role"] not in {"Brand", "Marketer"}:
                d["Role"] = "Brand"
            d["Distribution Type"] = d["Role"]
        d["Industry Category"] = INDUSTRY
        landscape.append(d)
        existing.add(_norm(brand))

    added: list[str] = []
    need_score: list[dict] = []
    for c in NEW_MARKETERS:
        name = c["company"]
        if _norm(name) in existing:
            continue
        row = _row_marketer(c)
        landscape.append(row)
        need_score.append(row)
        added.append(name)
        existing.add(_norm(name))

    print(f"Reclassified Marketer: {len(reclassed)}; added Marketer: {len(added)}; total {len(landscape)}", flush=True)

    if need_score:
        print(f"Scoring {len(need_score)} new Marketers via DeepSeek...", flush=True)
        scored, _ = await score_expand_rows(need_score, QUERY, country="global")
        by = {_norm(r.get("Company") or r.get("Brand") or ""): r for r in scored}
        for r in landscape:
            s = by.get(_norm(r.get("Brand") or ""))
            if not s:
                continue
            for col in ("X Score", "Y Score", "Overall Score", "Quadrant", "Summary"):
                if s.get(col) not in (None, ""):
                    r[col] = s[col]
            r["Role"] = "Marketer"
            r["Distribution Type"] = "Marketer"

    xs, ys = [], []
    for r in landscape:
        try:
            xs.append(float(r.get("X Score") or 50))
        except (TypeError, ValueError):
            xs.append(50.0)
        try:
            ys.append(float(r.get("Y Score") or 50))
        except (TypeError, ValueError):
            ys.append(50.0)
    quads, _, _ = assign_quadrants_half_median(xs, ys)
    for r, q in zip(landscape, quads):
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

    detail_rows = to_company_detail_rows(landscape, QUERY, audit)
    for det in detail_rows:
        key = _norm(det.get("Brand") or "")
        src = next((r for r in landscape if _norm(r.get("Brand") or "") == key), None)
        if not src:
            continue
        det["Role"] = src.get("Role") or "Brand"
        if src.get("_display_company"):
            det["Company"] = src["_display_company"]
        elif not str(det.get("Company") or "").startswith("("):
            det["Company"] = det.get("Brand") or det.get("Company")

    write_final_xlsx(
        xlsx,
        landscape,
        "Companies",
        {"query": QUERY, "xy_scoring": audit, "marketers_added": added, "reclassed": reclassed},
        detail_rows=detail_rows,
    )
    extras = export_expand_quadrant_outputs(
        FOLDER, detail_rows, QUERY, country="global", audit=audit, chart_n=20
    )

    roles = dict(Counter(r.get("Role") for r in detail_rows))
    out = {
        "final_count": len(detail_rows),
        "roles": roles,
        "reclassified_to_marketer": reclassed,
        "added_marketers": added,
        "html": str(extras.get("html") or ""),
    }
    path = OUT / "_audit" / "wearable_marketer_split.json"
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Final {out['final_count']} roles={roles}", flush=True)
    print(f"audit -> {path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
