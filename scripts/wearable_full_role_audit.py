#!/usr/bin/env python3
"""Full Brand/Marketer audit fixes for wearable medical devices."""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from openpyxl import load_workbook

from vendor_intel.pipeline.expand_quadrant_score import (
    export_expand_quadrant_outputs,
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

# Off-market / wrong identity Brands
REMOVE_BRAND = {
    "t+ medical": "Defunct UK mobile-phone RPM (acquired by OBS); not a wearable medical Brand",
    "vital beats": "Software for implantable cardiac-device remote monitoring — not wearable medical",
    "biospectal": "Smartphone-camera BP software — not body-worn wearable hardware",
    "boston scientific": "LUX-Dx is insertable ICM; wearable MCT covered by Preventice row — not a wearable Brand here",
    "hillrom": "Hospital beds / acute-care furniture focus — not wearable medical Brand",
    "bosch healthcare solutions": "Vivalytic lab analyzer focus — not wearable medical Brand",
    "biosign technologies": "Legacy wrist-cuff Pulsewave BP (c.2012) — not continuous wearable medical Brand",
}

# Marketer → Brand (own product/platform Brand, not pure channel)
TO_BRAND = {
    "huma": {
        "specialty": "FDA/EU-regulated SaMD digital health Brand for disease-agnostic RPM / virtual care (device-agnostic)",
        "categories": "Digital health SaMD; Remote patient monitoring",
        "summary": "Huma — Brand. Regulated SaMD platform for RPM and disease management; integrates third-party wearables.",
    },
    "lively": {
        "specialty": "Lively Mobile2 / medical-alert wearable Brand for seniors (fall detection, GPS, Urgent Response)",
        "categories": "Medical alert wearables; Senior safety",
        "summary": "Lively — Brand. Best Buy Health medical-alert wearable Brand (GreatCall lineage).",
        "owner": ("Best Buy Health / Best Buy", "subsidiary_of", ""),
    },
}

# Keep as Marketer but refresh notes
MARKETER_NOTES = {
    "ascensia diabetes care": "Exclusive commercial partner/distributor for Senseonics Eversense CGM (Contour BGM is separate, non-wearable)",
    "cadence": "Technology-enabled chronic-care RPM programs that commercialize clinical wearable data pathways",
    "ultrahuman": "Markets third-party Abbott CGM metabolic programs (M1/M2); Ring AIR is consumer wellness, not medical Brand",
    "nutrisense": "CGM subscription + coaching programs using Abbott/Dexcom sensors (acquired by Dexcom)",
    "levels health": "Metabolic health programs marketing third-party CGM sensors",
    "signos": "FDA-cleared CGM weight-management programs using Dexcom sensors",
    "veri": "Metabolic health subscriptions marketing Abbott Libre CGMs",
    "january ai": "CGM + digital-twin metabolic programs using third-party sensors",
    "zoe": "Personalized nutrition programs that include CGM testing kits",
    "supersapiens": "Sports glucose performance programs marketing Abbott Libre Sense",
    "hello inside": "Women's metabolic health programs marketing third-party CGMs",
    "amplifon": "Global hearing-care retailer/marketer of wearable hearing aids (Miracle-Ear network)",
    "miracle-ear": "US hearing-aid retail Brand network under Amplifon (clinic marketer)",
    "hearinglife": "US Demant clinic network marketing Oticon wearable hearing aids",
    "audika": "Demant hearing-care clinic Brand marketing wearable hearing aids",
    "specsavers hearcare": "Optical/hearing retailer marketing Specsavers hearing aids",
    "fielmann group": "European optical/hearing retailer marketing wearable hearing devices",
    "kind hörgeräte": "German hearing-care chain marketing wearable hearing aids",
    "gemco medical": "Specialty CGM resupply marketer (Abbott/Dexcom) into DME channels",
    "ddp medical supply": "Authorized wholesaler/marketer of Abbott and Dexcom CGMs to DMEs",
    "ancillare": "Clinical-trial supply marketer of Dexcom CGMs",
    "best buy health": "Retail/health channel marketing Lively and home health wearable programs",
}

# Specialty corrections for kept Brands
FIX_SPECIALTY = {
    "avertus": "Wireless medical-grade EEG headset for epilepsy / neuromonitoring (not fall detection)",
    "vitalerter": "Bio Patch wearable vitals sensor for care homes (also offers contactless bed sensor)",
    "alivecor": "Kardia personal ECG Brand (pocket/wrist-contact medical ECG) for AFib detection",
}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


def main() -> int:
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
    role_fixes: list[dict] = []
    specialty_fixes: list[str] = []

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
        if role == "Brand" and key in REMOVE_BRAND:
            removed.append({"brand": brand, "reason": REMOVE_BRAND[key]})
            continue

        if key in TO_BRAND:
            info = TO_BRAND[key]
            old = role
            d["Role"] = "Brand"
            d["Distribution Type"] = "Brand"
            d["Specialty Focus"] = info["specialty"]
            d["Core Categories"] = info["categories"]
            d["Summary"] = info["summary"]
            owner = info.get("owner")
            if owner:
                o, rel, year = owner
                d["_display_company"] = format_acquired_suffix(o, relation=rel, year=year or "")
                d["Ownership"] = f"{rel.replace('_', ' ')} {o}" + (f", {year}" if year else "")
            role_fixes.append({"brand": brand, "from": old, "to": "Brand", "why": info["summary"]})

        if key in MARKETER_NOTES and (role == "Marketer" or key not in TO_BRAND):
            if key not in TO_BRAND:
                d["Role"] = "Marketer"
                d["Distribution Type"] = "Marketer"
                d["Specialty Focus"] = MARKETER_NOTES[key]
                d["Summary"] = f"{brand} — Marketer. {MARKETER_NOTES[key]}"

        if key in FIX_SPECIALTY:
            d["Specialty Focus"] = FIX_SPECIALTY[key]
            specialty_fixes.append(brand)

        # Livongo already Brand — ensure stays Brand
        if key == "livongo":
            d["Role"] = "Brand"
            d["Distribution Type"] = "Brand"

        d["Brand"] = brand
        d["Company"] = brand
        d["Role"] = d.get("Role") if d.get("Role") in {"Brand", "Marketer"} else "Brand"
        d["Distribution Type"] = d["Role"]
        d["Industry Category"] = INDUSTRY
        kept.append(d)

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
        {"query": QUERY, "xy_scoring": audit, "full_audit": True},
        detail_rows=detail_rows,
    )
    extras = export_expand_quadrant_outputs(
        FOLDER, detail_rows, QUERY, country="global", audit=audit, chart_n=20
    )

    roles = dict(Counter(r.get("Role") for r in detail_rows))
    out = {
        "criterion": {
            "Brand": "Owns/builds body-worn or adhesive medical wearable / hearing / CGM-insulin-patch / medical-alert / regulated SaMD+device platform Brand",
            "Marketer": "Commercializes third-party wearable medical devices (CGM programs, hearing retail, DME/channel) without being the primary device OEM Brand",
            "exclude": "Contactless-only, handheld exam kits, pure implant software, lab analyzers, hospital furniture, defunct/wrong-identity rows",
        },
        "removed": removed,
        "role_fixes": role_fixes,
        "specialty_fixes": specialty_fixes,
        "final_count": len(detail_rows),
        "roles": roles,
        "html": str(extras.get("html") or ""),
        "marketers_verified_ok": sorted(MARKETER_NOTES.keys()),
    }
    path = OUT / "_audit" / "wearable_full_role_market_audit.json"
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    md = OUT / "_audit" / "wearable_full_role_market_audit.md"
    lines = [
        "# Full Brand / Marketer audit — Wearable Medical Devices",
        "",
        f"Final **{len(detail_rows)}** — {roles}",
        "",
        "## Role rules",
        "",
        f"- **Brand:** {out['criterion']['Brand']}",
        f"- **Marketer:** {out['criterion']['Marketer']}",
        f"- **Exclude:** {out['criterion']['exclude']}",
        "",
        "## Role fixes (Marketer → Brand)",
        "",
    ]
    for r in role_fixes:
        lines.append(f"- **{r['brand']}**: {r['from']} → {r['to']} — {r['why']}")
    lines.extend(["", "## Removed", "", "| Brand | Reason |", "|---|---|"])
    for r in removed:
        lines.append(f"| {r['brand']} | {r['reason']} |")
    lines.extend(
        [
            "",
            "## Specialty corrections",
            "",
            ", ".join(specialty_fixes) or "(none)",
            "",
            "## Marketers re-verified OK",
            "",
            ", ".join(sorted(b.title() if False else k for k in MARKETER_NOTES)) ,
            "",
        ]
    )
    # prettier marketer list from current kept
    mk = [r.get("Brand") for r in detail_rows if r.get("Role") == "Marketer"]
    lines[-3] = ", ".join(str(x) for x in mk)
    md.write_text("\n".join(lines), encoding="utf-8")

    print(f"Removed {len(removed)}; role_fixes {len(role_fixes)}; final {len(detail_rows)} {roles}", flush=True)
    print(f"audit -> {md}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
