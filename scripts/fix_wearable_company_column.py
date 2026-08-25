#!/usr/bin/env python3
"""Fix Brand/Company columns: Brand = product name; Company = ownership or legal."""
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

# Brand → Company display (ownership suffix OR legal company for product brands)
# Independent brands: Company == Brand (omit from map; default)
COMPANY_FOR_BRAND: dict[str, dict[str, str]] = {
    # Acquisitions / mergers
    "livongo": {"company": format_acquired_suffix("Teladoc Health", relation="acquired_by", year="2020")},
    "itamar medical": {"company": format_acquired_suffix("Zoll Medical / Asahi Kasei", relation="acquired_by", year="2021")},
    "propeller health": {"company": format_acquired_suffix("ResMed", relation="acquired_by", year="2022")},
    "nightbalance": {"company": format_acquired_suffix("Philips", relation="acquired_by", year="2018")},
    "enso": {"company": format_acquired_suffix("Hinge Health", relation="acquired_by", year="2021")},
    "leaf healthcare": {"company": format_acquired_suffix("Smith+Nephew", relation="acquired_by", year="2019")},
    "spry health": {"company": format_acquired_suffix("Itamar Medical", relation="acquired_by", year="2021")},
    "bardy diagnostics": {"company": format_acquired_suffix("Baxter", relation="acquired_by", year="2021")},
    "bigfoot biomedical": {"company": format_acquired_suffix("Abbott", relation="acquired_by", year="2023")},
    "nutrisense": {"company": format_acquired_suffix("Dexcom", relation="acquired_by", year="2026")},
    "biotelemetry": {"company": format_acquired_suffix("Philips", relation="acquired_by", year="2021")},
    "preventice solutions": {"company": format_acquired_suffix("Boston Scientific", relation="acquired_by", year="2021")},
    "ectosense": {"company": format_acquired_suffix("ResMed", relation="acquired_by", year="2021")},
    "everion": {"company": format_acquired_suffix("Biofourmis", relation="acquired_by", year="2019")},
    "zephyr technology": {"company": format_acquired_suffix("Medtronic", relation="acquired_by", year="2011")},
    "zoll medical": {"company": format_acquired_suffix("Asahi Kasei", relation="acquired_by", year="2012")},
    "smi (sensomotoric instruments)": {"company": format_acquired_suffix("Apple", relation="acquired_by", year="2017")},
    "cardiac insight": {"company": format_acquired_suffix("Dreamtech", relation="acquired_by", year="2022")},
    "cosinuss": {"company": format_acquired_suffix("corpuls", relation="acquired_by", year="2025")},
    "neurometrix": {"company": format_acquired_suffix("electroCore", relation="acquired_by", year="2025")},
    "masimo": {"company": format_acquired_suffix("Danaher", relation="acquired_by", year="2026")},
    "physiq": {"company": format_acquired_suffix("Prolaio", relation="acquired_by", year="")},
    "beijing choice (choicemmed)": {
        "company": format_acquired_suffix(
            "Tianjin Chase Sun Pharmaceutical", relation="acquired_by", year="2015"
        )
    },
    "medisana": {
        "company": format_acquired_suffix(
            "Ogawa Smart HealthCare (Xiamen Comfort Science)",
            relation="acquired_by",
            year="2016",
        )
    },
    "intelesens": {"company": format_acquired_suffix("Renew Health", relation="acquired_by", year="2017")},
    "hearx group": {"company": format_acquired_suffix("LXE Hearing", relation="merged_into", year="2025")},
    "eargo": {"company": format_acquired_suffix("LXE Hearing", relation="merged_into", year="2025")},
    "gn hearing": {"company": format_acquired_suffix("Amplifon", relation="acquired_by", year="2026")},
    # Subsidiaries
    "omron healthcare": {"company": format_acquired_suffix("Omron", relation="subsidiary_of")},
    "a&d": {"company": format_acquired_suffix("A&D Holon Holdings", relation="subsidiary_of")},
    "sensium healthcare": {
        "company": format_acquired_suffix("The Surgical Company Group", relation="subsidiary_of")
    },
    "ascensia diabetes care": {
        "company": format_acquired_suffix("PHC Holdings", relation="subsidiary_of")
    },
    "lively": {
        "company": format_acquired_suffix("Best Buy Health / Best Buy", relation="subsidiary_of")
    },
    "best buy health": {"company": format_acquired_suffix("Best Buy", relation="subsidiary_of")},
    "miracle-ear": {"company": format_acquired_suffix("Amplifon", relation="subsidiary_of")},
    "hearinglife": {"company": format_acquired_suffix("Demant", relation="subsidiary_of")},
    "audika": {"company": format_acquired_suffix("Demant", relation="subsidiary_of")},
    # Product brand → legal company (plain name, not suffix)
    "wellue": {"brand": "Wellue", "company": "Viatom Technology"},
    "temptraq": {"brand": "TempTraq", "company": "Blue Spark Technologies"},
    "circul": {"brand": "Circul", "company": "BodiMetrics"},
    "sleepimage": {"brand": "SleepImage", "company": "MyCardio"},
    "hexoskin": {"brand": "Hexoskin", "company": "Carré Technologies"},
}

# If Brand was wrongly replaced by legal company, restore product Brand from website/ownership cues
RESTORE_FROM_LEGAL: dict[str, str] = {
    "blue spark technologies": "TempTraq",
    "bodimetrics": "Circul",
    "mycardio": "SleepImage",
    "carré technologies": "Hexoskin",
    "carre technologies": "Hexoskin",
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
    fixes: list[dict] = []
    seen_brand: set[str] = set()

    for r in rows_raw[1:]:
        if not r:
            continue
        d = {hdr[i]: ("" if r[i] is None else r[i]) for i in range(len(hdr)) if i < len(r)}
        brand = str(d.get("Brand") or d.get("Company") or "").strip()
        if not brand:
            continue
        # Prefer Brand from details when landscape Brand empty
        key = _norm(brand)
        det = details_by.get(key)
        if det:
            if det.get("Brand"):
                brand = str(det["Brand"]).strip()
                key = _norm(brand)
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

        # Restore product Brand if wrongly replaced by legal company
        if key in RESTORE_FROM_LEGAL:
            # Keep one Viatom Technology row as itself; only restore Wellue when website is getwellue
            website = str(d.get("Website") or "").lower()
            ownership = str(d.get("Ownership") or "").lower()
            if key == "viatom technology":
                if "getwellue" in website or "wellue" in ownership:
                    brand = "Wellue"
                    key = "wellue"
            else:
                brand = RESTORE_FROM_LEGAL[key]
                key = _norm(brand)

        # Special: Viatom Technology with getwellue site → Wellue product
        if key == "viatom technology" and "getwellue" in str(d.get("Website") or "").lower():
            brand = "Wellue"
            key = "wellue"

        info = COMPANY_FOR_BRAND.get(key)
        if info and info.get("brand"):
            brand = info["brand"]
            key = _norm(brand)

        # Dedupe by brand after restore
        if key in seen_brand:
            fixes.append({"brand": brand, "action": "dropped_duplicate"})
            continue
        seen_brand.add(key)

        if info:
            company_col = info["company"]
            old_c = str(d.get("Company") or "")
            d["Brand"] = brand
            d["Company"] = brand  # landscape identity
            d["_display_company"] = company_col
            if company_col.startswith("("):
                d["Ownership"] = company_col.strip("()")
            else:
                d["Ownership"] = f"product brand of {company_col}"
            fixes.append(
                {
                    "brand": brand,
                    "company": company_col,
                    "from": old_c,
                    "action": "set_ownership_or_legal",
                }
            )
        else:
            # Independent: Brand == Company plain (strip any leftover suffix)
            plain = brand
            plain = re.sub(
                r"\((?:acquired by|merged into|subsidiary of)\s+[^)]+\)\s*$",
                "",
                plain,
                flags=re.I,
            ).strip() or plain
            d["Brand"] = plain
            d["Company"] = plain
            d["_display_company"] = plain
            if str(d.get("Ownership") or "").lower().startswith(
                ("acquired", "subsidiary", "merged", "product brand")
            ):
                d["Ownership"] = "Independent"

        d["Role"] = d.get("Role") if d.get("Role") in {"Brand", "Marketer"} else "Brand"
        d["Distribution Type"] = d["Role"]
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
        det["Brand"] = src.get("Brand") or det.get("Brand")
        det["Company"] = src.get("_display_company") or src.get("Brand")

    write_final_xlsx(
        xlsx,
        kept,
        "Companies",
        {"query": QUERY, "xy_scoring": audit, "company_column_fixes": fixes},
        detail_rows=detail_rows,
    )
    extras = export_expand_quadrant_outputs(
        FOLDER, detail_rows, QUERY, country="global", audit=audit, chart_n=20
    )

    roles = dict(Counter(r.get("Role") for r in detail_rows))
    owned = [f for f in fixes if f.get("action") == "set_ownership_or_legal"]
    out = {
        "final_count": len(detail_rows),
        "roles": roles,
        "company_labels_applied": len(owned),
        "fixes": owned,
        "html": str(extras.get("html") or ""),
        "rule": (
            "Brand = plain brand/product name. "
            "Company = (acquired by|subsidiary of|merged into Parent) when owned; "
            "legal company when Brand is a product name; else Company = Brand."
        ),
    }
    path = OUT / "_audit" / "wearable_brand_company_column_fix.json"
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    md = OUT / "_audit" / "wearable_brand_company_column_fix.md"
    lines = [
        "# Brand → Company column fix",
        "",
        f"Final **{len(detail_rows)}** — {roles}",
        "",
        f"**Rule:** {out['rule']}",
        "",
        f"## Applied ({len(owned)})",
        "",
        "| Brand | Company |",
        "|---|---|",
    ]
    for f in owned:
        lines.append(f"| {f['brand']} | {f['company']} |")
    md.write_text("\n".join(lines), encoding="utf-8")
    print(f"Final {len(detail_rows)} {roles}; company labels {len(owned)}", flush=True)
    print(f"audit -> {md}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
