#!/usr/bin/env python3
"""Apply web-verified Brand / Company / Role for wearable medical devices market.

Company column uses ``(acquired by Parent)`` / ``(subsidiary of Parent)`` /
``(merged into Parent)`` when ownership is confirmed; otherwise Brand == Company.
Product brands (e.g. Eversense) keep Brand = product, Company = legal company.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

from openpyxl import load_workbook

from vendor_intel.pipeline.expand_quadrant_score import (
    export_expand_quadrant_outputs,
    to_company_detail_rows,
)
from vendor_intel.pipeline.web_expand import write_final_xlsx
from vendor_intel.quadrant.brand_meta import brand_display_fields, format_acquired_suffix

ROOT = Path(r"D:\Coherent-Quadrant\output\chatgpt_expand")
SLUG = "global_wearable_medical_devices_market_global"
QUERY = "Global Wearable Medical Devices Market"

# brand_key -> ownership. Only web-verified entries.
OWNERSHIP: dict[str, dict[str, str]] = {
    # --- Acquisitions ---
    "fitbit": {
        "owner": "Google",
        "relation": "acquired_by",
        "year": "2021",
        "source": "Google completed Fitbit Jan 2021",
    },
    "hillrom": {
        "owner": "Baxter",
        "relation": "acquired_by",
        "year": "2021",
        "source": "Baxter completed Hillrom Dec 2021",
    },
    "biotelemetry": {
        "owner": "Philips",
        "relation": "acquired_by",
        "year": "2021",
        "source": "Philips completed BioTelemetry Feb 2021",
    },
    "preventice solutions": {
        "owner": "Boston Scientific",
        "relation": "acquired_by",
        "year": "2021",
        "source": "Boston Scientific completed Preventice Mar 2021",
    },
    "smiths medical": {
        "owner": "ICU Medical",
        "relation": "acquired_by",
        "year": "2022",
        "source": "ICU Medical completed Smiths Medical Jan 2022",
    },
    "ectosense": {
        "owner": "ResMed",
        "relation": "acquired_by",
        "year": "2021",
        "source": "ResMed acquired Ectosense (NightOwl) 2021",
    },
    "everion": {
        "owner": "Biofourmis",
        "relation": "acquired_by",
        "year": "2019",
        "source": "Biofourmis acquired Biovotion/Everion 2019",
    },
    "zephyr technology": {
        "owner": "Medtronic",
        "relation": "acquired_by",
        "year": "2011",
        "source": "Medtronic acquired Zephyr Technology 2011",
    },
    "zoll medical": {
        "owner": "Asahi Kasei",
        "relation": "acquired_by",
        "year": "2012",
        "source": "Asahi Kasei acquired ZOLL Medical 2012",
    },
    "smi (sensomotoric instruments)": {
        "owner": "Apple",
        "relation": "acquired_by",
        "year": "2017",
        "source": "Apple acquired SMI 2017",
        "brand_rename": "SMI (SensoMotoric Instruments)",
    },
    "sensomotoric instruments": {
        "owner": "Apple",
        "relation": "acquired_by",
        "year": "2017",
        "source": "Apple acquired SMI 2017",
        "brand_rename": "SMI (SensoMotoric Instruments)",
    },
    "cardiac insight": {
        "owner": "Dreamtech",
        "relation": "acquired_by",
        "year": "2022",
        "source": "Dreamtech acquired Cardiac Insight Mar 2022",
    },
    "cosinuss": {
        "owner": "corpuls",
        "relation": "acquired_by",
        "year": "2025",
        "source": "corpuls acquired Cosinuss GmbH Jun 2025",
    },
    "neurometrix": {
        "owner": "electroCore",
        "relation": "acquired_by",
        "year": "2025",
        "source": "electroCore completed NeuroMetrix May 2025",
    },
    "masimo": {
        "owner": "Danaher",
        "relation": "acquired_by",
        "year": "2026",
        "source": "Danaher completed Masimo Jun 10, 2026",
    },
    "physiq": {
        "owner": "Prolaio",
        "relation": "acquired_by",
        "year": "",
        "source": "Crosstree: physIQ acquired by Prolaio (Prolaio later by Kardigan 2025)",
    },
    "nymi": {
        "owner": "Innominds",
        "relation": "acquired_by",
        "year": "2022",
        "source": "Innominds acquired Nymi Apr 2022",
    },
    "suunto": {
        "owner": "Liesheng",
        "relation": "acquired_by",
        "year": "2022",
        "source": "Liesheng completed Suunto from Amer Sports May 2022",
    },
    "sensitec": {
        "owner": "Sinomags",
        "relation": "acquired_by",
        "year": "2021",
        "source": "Sinomags completed Sensitec Sep 2021 (Körber sale)",
    },
    "beijing choice (choicemmed)": {
        "owner": "Tianjin Chase Sun Pharmaceutical",
        "relation": "acquired_by",
        "year": "2015",
        "source": "Chase Sun completed Beijing Choice / ChoiceMMed Nov 2015",
        "brand_rename": "Beijing Choice (ChoiceMMed)",
    },
    "choicemmed": {
        "owner": "Tianjin Chase Sun Pharmaceutical",
        "relation": "acquired_by",
        "year": "2015",
        "source": "Chase Sun completed Beijing Choice / ChoiceMMed Nov 2015",
        "brand_rename": "Beijing Choice (ChoiceMMed)",
    },
    "medisana": {
        "owner": "Ogawa Smart HealthCare (Xiamen Comfort Science)",
        "relation": "acquired_by",
        "year": "2016",
        "source": "Xiamen Comfort / Ogawa completed Medisana 2016",
    },
    "intelesens": {
        "owner": "Renew Health",
        "relation": "acquired_by",
        "year": "2017",
        "source": "Renew Health acquired Intelesens 2017",
    },
    "vivonic": {
        "owner": "Fresenius Medical Care",
        "relation": "acquired_by",
        "year": "2016",
        "source": "Fresenius Medical Care acquired Vivonic 2016",
    },
    "hearx group": {
        "owner": "LXE Hearing",
        "relation": "merged_into",
        "year": "2025",
        "source": "hearX + Eargo merger closed Mar 31, 2025 → LXE Hearing",
    },
    "eargo": {
        "owner": "LXE Hearing",
        "relation": "merged_into",
        "year": "2025",
        "source": "hearX + Eargo merger closed Mar 31, 2025 → LXE Hearing",
    },
    "livongo": {
        "owner": "Teladoc Health",
        "relation": "acquired_by",
        "year": "2020",
        "source": "Teladoc completed Livongo Oct 2020",
    },
    "itamar medical": {
        "owner": "Zoll Medical / Asahi Kasei",
        "relation": "acquired_by",
        "year": "2021",
        "source": "Zoll/Asahi Kasei acquired Itamar Medical 2021",
    },
    "propeller health": {
        "owner": "ResMed",
        "relation": "acquired_by",
        "year": "2022",
        "source": "ResMed acquired Propeller Health 2022",
    },
    "nightbalance": {
        "owner": "Philips",
        "relation": "acquired_by",
        "year": "2018",
        "source": "Philips acquired NightBalance 2018",
    },
    "enso": {
        "owner": "Hinge Health",
        "relation": "acquired_by",
        "year": "2021",
        "source": "Hinge Health acquired Enso 2021",
    },
    "leaf healthcare": {
        "owner": "Smith+Nephew",
        "relation": "acquired_by",
        "year": "2019",
        "source": "Smith+Nephew acquired Leaf Healthcare 2019",
    },
    "spry health": {
        "owner": "Itamar Medical",
        "relation": "acquired_by",
        "year": "2021",
        "source": "Itamar Medical acquired Spry Health 2021",
    },
    "bardy diagnostics": {
        "owner": "Baxter",
        "relation": "acquired_by",
        "year": "2021",
        "source": "Baxter acquired Bardy Diagnostics 2021",
    },
    "bigfoot biomedical": {
        "owner": "Abbott",
        "relation": "acquired_by",
        "year": "2023",
        "source": "Abbott acquired Bigfoot Biomedical 2023",
    },
    "nutrisense": {
        "owner": "Dexcom",
        "relation": "acquired_by",
        "year": "2026",
        "source": "Dexcom acquired Nutrisense 2026",
    },
    "gn hearing": {
        "owner": "Amplifon",
        "relation": "acquired_by",
        "year": "2026",
        "source": "GN Group sold Hearing business (ReSound/Beltone) to Amplifon 2026",
    },
    # --- Subsidiaries ---
    "samsung medison": {
        "owner": "Samsung Electronics",
        "relation": "subsidiary_of",
        "source": "Samsung Medison is Samsung Electronics healthcare imaging subsidiary",
    },
    "bosch healthcare solutions": {
        "owner": "Robert Bosch GmbH",
        "relation": "subsidiary_of",
        "source": "Bosch Healthcare Solutions GmbH is Bosch group company",
    },
    "ascensia diabetes care": {
        "owner": "PHC Holdings",
        "relation": "subsidiary_of",
        "source": "Ascensia is wholly owned subsidiary of PHC Holdings (ex Bayer Diabetes Care 2016)",
    },
    "lively": {
        "owner": "Best Buy Health / Best Buy",
        "relation": "subsidiary_of",
        "source": "Lively (ex GreatCall) is Best Buy Health medical-alert Brand",
    },
    "best buy health": {
        "owner": "Best Buy",
        "relation": "subsidiary_of",
        "source": "Best Buy Health is Best Buy's health division",
    },
    "miracle-ear": {
        "owner": "Amplifon",
        "relation": "subsidiary_of",
        "source": "Miracle-Ear is Amplifon retail Brand network",
    },
    "hearinglife": {
        "owner": "Demant",
        "relation": "subsidiary_of",
        "source": "HearingLife is Demant US clinic network",
    },
    "audika": {
        "owner": "Demant",
        "relation": "subsidiary_of",
        "source": "Audika is Demant hearing-care clinic Brand",
    },
    "omron healthcare": {
        "owner": "Omron",
        "relation": "subsidiary_of",
        "source": "Omron Healthcare is Omron Corporation healthcare division/subsidiary",
    },
    "omron healthcare (canada)": {
        "owner": "Omron",
        "relation": "subsidiary_of",
        "source": "Regional Omron Healthcare entity",
    },
    "omron healthcare middle east": {
        "owner": "Omron",
        "relation": "subsidiary_of",
        "source": "Regional Omron Healthcare entity",
    },
    "philips (canada)": {
        "owner": "Philips",
        "relation": "subsidiary_of",
        "source": "Regional Philips entity",
    },
    "philips (middle east)": {
        "owner": "Philips",
        "relation": "subsidiary_of",
        "source": "Regional Philips entity",
    },
    "philips brazil": {
        "owner": "Philips",
        "relation": "subsidiary_of",
        "source": "Regional Philips entity",
    },
    "apple (canada)": {
        "owner": "Apple",
        "relation": "subsidiary_of",
        "source": "Regional Apple entity",
    },
    "baxter (middle east)": {
        "owner": "Baxter",
        "relation": "subsidiary_of",
        "source": "Regional Baxter entity",
    },
    "roche (middle east)": {
        "owner": "Roche",
        "relation": "subsidiary_of",
        "source": "Regional Roche entity",
    },
    "nihon kohden latin america": {
        "owner": "Nihon Kohden",
        "relation": "subsidiary_of",
        "source": "Regional Nihon Kohden entity",
    },
    "a&d": {
        "owner": "A&D Holon Holdings",
        "relation": "subsidiary_of",
        "source": "A&D Company under A&D HOLON Holdings (Apr 2022 holding structure)",
    },
    "sensium healthcare": {
        "owner": "The Surgical Company Group",
        "relation": "subsidiary_of",
        "source": "TSC acquired Sensium from Toumaz; now TSC Connected Care",
    },
    "vitaliberty": {
        "owner": "vitagroup AG",
        "relation": "subsidiary_of",
        "source": "Vitaliberty is vitagroup AG company",
    },
    "sony": {
        "owner": "Sony Group",
        "relation": "subsidiary_of",
        "source": "Sony operating companies under Sony Group Corporation (no acquisition year)",
    },
    # Special / ceased
    "earlysense": {
        "owner": "Hillrom (hospital IP, 2021); remaining assets to TytoCare (2022)",
        "relation": "acquired_by",
        "year": "",
        "brand_rename": "EarlySense",
        "company_plain": "(ceased; hospital IP to Hillrom, 2021; remaining assets to TytoCare, 2022)",
        "source": "Hillrom bought hospital CFCM tech Feb 2021; receivership; remaining assets to TytoCare Nov 2022",
    },
}

# Product brand → legal company (Brand stays product name; Company = legal)
PRODUCT_COMPANY: dict[str, str] = {
    "eversense": "Senseonics",
    "vitalpatch": "VitalConnect",
    "temptraq": "Blue Spark Technologies",
    "wellue": "Viatom Technology",
    "circul": "BodiMetrics",
    "sleepimage": "MyCardio",
    "hexoskin": "Carré Technologies",
}

# Canonical brand renames (duplicates / spelling)
BRAND_CLEAN: dict[str, str] = {
    "vivalink": "VivaLNK",
    "vivalnk": "VivaLNK",
}

# Roles verified: component/sensor suppliers → OEM; device/platform brands → Brand
ROLE_OEM = {
    "valencell",
    "sensirion",
    "bluespark technologies",
    "leman micro devices",
    "tdk",
    "sensitec",
}

# Clear invented / unhelpful ownership (holding-company tautology)
CLEAR_TO_INDEPENDENT = {
    "huawei",  # was subsidiary of Huawei Investment & Holding — not useful
}


def _norm(s: str) -> str:
    s = str(s or "").strip().lower()
    s = re.sub(r"[®™]", "", s)
    s = re.sub(r"\s+", " ", s)
    # Drop legal suffixes so EarlySense Ltd. matches earlysense
    s = re.sub(
        r"\b(ltd\.?|limited|inc\.?|incorporated|llc|gmbh|ag|corp\.?|corporation|co\.|company|plc)\b\.?",
        "",
        s,
    )
    s = re.sub(r"\s+", " ", s).strip(" ,.")
    return s


def _identity_key(row: dict) -> str:
    for k in ("Brand", "Company", "company", "brand"):
        v = str(row.get(k) or "").strip()
        if not v:
            continue
        # Prefer plain brand over (acquired by …) company text
        if v.startswith("("):
            continue
        cleaned = re.sub(
            r"\((?:acquired by|merged into|subsidiary of)\s+[^)]+\)\s*$",
            "",
            v,
            flags=re.I,
        ).strip()
        if cleaned:
            return _norm(cleaned)
    return _norm(row.get("Brand") or row.get("Company") or "")


def _overall(row: dict) -> float:
    try:
        return float(row.get("Overall Score") or row.get("Overall") or 0)
    except (TypeError, ValueError):
        return 0.0


def _dedupe(landscape: list[dict]) -> tuple[list[dict], list[dict]]:
    buckets: dict[str, list[dict]] = defaultdict(list)
    for row in landscape:
        key = _identity_key(row)
        # Map Vivalink variants together
        if key in {"vivalink", "vivalnk"}:
            key = "vivalnk"
        buckets[key].append(row)
    kept: list[dict] = []
    dropped: list[dict] = []
    for key, rows in buckets.items():
        if len(rows) == 1:
            kept.append(rows[0])
            continue
        rows_sorted = sorted(rows, key=_overall, reverse=True)
        kept.append(rows_sorted[0])
        for r in rows_sorted[1:]:
            dropped.append(
                {
                    "brand": r.get("Brand") or r.get("Company"),
                    "overall": _overall(r),
                    "kept": rows_sorted[0].get("Brand") or rows_sorted[0].get("Company"),
                    "kept_overall": _overall(rows_sorted[0]),
                }
            )
    return kept, dropped


def main() -> int:
    folder = ROOT / SLUG
    xlsx = folder / f"{SLUG}_FINAL.xlsx"
    wb = load_workbook(xlsx, data_only=True)
    ws = wb["Landscape"]
    rows_raw = list(ws.iter_rows(values_only=True))
    hdr = [str(h) for h in rows_raw[0]]
    landscape: list[dict] = []
    for r in rows_raw[1:]:
        if not r:
            continue
        d = {hdr[i]: ("" if r[i] is None else r[i]) for i in range(len(hdr)) if i < len(r)}
        if str(d.get("Company") or d.get("Brand") or "").strip():
            landscape.append(d)

    # Overlay Company Details Brand/Company/Role/scores when present
    details_by: dict[str, dict] = {}
    if "Company Details" in wb.sheetnames:
        ws = wb["Company Details"]
        rows_raw = list(ws.iter_rows(values_only=True))
        dhdr = [str(h) for h in rows_raw[0]]
        for r in rows_raw[1:]:
            if not r:
                continue
            d = {dhdr[i]: ("" if r[i] is None else r[i]) for i in range(len(dhdr)) if i < len(r)}
            brand = str(d.get("Brand") or "").strip()
            if brand:
                details_by[_norm(brand)] = d

    for row in landscape:
        key = _identity_key(row)
        det = details_by.get(key)
        if not det:
            continue
        if det.get("Brand"):
            row["Brand"] = det["Brand"]
        if det.get("X") not in (None, ""):
            row["X Score"] = det["X"]
            row["Y Score"] = det["Y"]
            row["Overall Score"] = det["Overall"]
            row["Quadrant"] = det.get("Quadrant") or row.get("Quadrant") or ""
        if det.get("Role"):
            row["Role"] = det["Role"]
            row["Distribution Type"] = det["Role"]
        if det.get("Found in"):
            row["Found in"] = det["Found in"]
            row["Headquarters"] = det["Found in"]

    before_n = len(landscape)
    landscape, dropped = _dedupe(landscape)

    applied: list[dict] = []
    for row in landscape:
        ident = str(row.get("Brand") or row.get("Company") or "").strip()
        key = _identity_key(row)
        if key in {"vivalink", "vivalnk"}:
            key = "vivalnk"

        # Brand clean
        if key in BRAND_CLEAN:
            ident = BRAND_CLEAN[key]
            row["Brand"] = ident
            row["Company"] = ident
            key = _norm(ident)

        # Clear bad ownership
        if key in CLEAR_TO_INDEPENDENT:
            row["Brand"] = ident if not ident.startswith("(") else "Huawei"
            if key == "huawei":
                row["Brand"] = "Huawei"
            row["Company"] = row["Brand"]
            row["Ownership"] = "Independent"
            row.pop("parent_owner", None)
            applied.append(
                {
                    "brand": row["Brand"],
                    "company": row["Company"],
                    "owner": "",
                    "relation": "cleared_independent",
                    "year": "",
                    "source": "Cleared Huawei Investment & Holding tautology",
                    "matched_key": key,
                    "from": ident,
                }
            )
            continue

        # Product brand → legal company (not acquisition suffix)
        if key in PRODUCT_COMPANY:
            brand = BRAND_CLEAN.get(key) or (row.get("Brand") or ident)
            # Prefer canonical product name casing from existing Brand
            brand = str(brand).strip()
            if key == "eversense":
                brand = "Eversense"
            if key == "vitalpatch":
                brand = "VitalPatch"
            if key == "temptraq":
                brand = "TempTraq"
            if key == "wellue":
                brand = "Wellue"
            if key == "circul":
                brand = "Circul"
            if key == "sleepimage":
                brand = "SleepImage"
            if key == "hexoskin":
                brand = "Hexoskin"
            company = PRODUCT_COMPANY[key]
            row["Brand"] = brand
            row["Company"] = company
            row["Ownership"] = f"product brand of {company}"
            applied.append(
                {
                    "brand": brand,
                    "company": company,
                    "owner": company,
                    "relation": "product_of",
                    "year": "",
                    "source": f"{brand} is a product brand of {company}",
                    "matched_key": key,
                    "from": ident,
                }
            )
            continue

        info = OWNERSHIP.get(key)
        # Exact key only — never fuzzy-match "Apple" onto "Apple (Canada)" ownership.
        if not info:
            # Independent: Brand == Company plain
            plain = str(row.get("Brand") or ident).strip()
            plain = re.sub(
                r"\((?:acquired by|merged into|subsidiary of)\s+[^)]+\)\s*$",
                "",
                plain,
                flags=re.I,
            ).strip() or plain
            # If Company was only a suffix, restore brand
            company_now = str(row.get("Company") or "").strip()
            if company_now.startswith("(") or "acquired by" in company_now.lower():
                row["Company"] = plain
            row["Brand"] = plain
            if not str(row.get("Company") or "").strip():
                row["Company"] = plain
            # If Brand was regional and Company was suffix-only, keep Brand, set Company=Brand
            if str(row.get("Company") or "").startswith("("):
                row["Company"] = plain
            continue

        brand = str(info.get("brand_rename") or row.get("Brand") or ident).strip()
        brand = re.sub(
            r"\((?:acquired by|merged into|subsidiary of)\s+[^)]+\)\s*$",
            "",
            brand,
            flags=re.I,
        ).strip() or brand
        owner = info["owner"]
        relation = info.get("relation") or "acquired_by"
        year = info.get("year") or ""
        if info.get("company_plain"):
            company_col = info["company_plain"]
            ownership_label = company_col
        else:
            company_col = format_acquired_suffix(owner, relation=relation, year=year)
            verb = {
                "acquired_by": "acquired by",
                "merged_into": "merged into",
                "subsidiary_of": "subsidiary of",
            }.get(relation, "acquired by")
            ownership_label = f"{verb} {owner}" + (f", {year}" if year else "")

        row["Company"] = brand  # landscape identity stays brand; details get suffix
        row["Brand"] = brand
        row["Ownership"] = ownership_label
        row["parent_owner"] = owner
        row["ownership_relation"] = relation
        if year:
            row["ownership_year"] = year
        row["_display_company"] = company_col
        applied.append(
            {
                "brand": brand,
                "company": company_col,
                "owner": owner,
                "relation": relation,
                "year": year,
                "source": info.get("source") or "",
                "matched_key": key,
                "from": ident,
            }
        )

    # Roles: preserve Brand/Marketer for this market (do not force OEM)
    role_fixes: list[dict] = []
    for row in landscape:
        key = _identity_key(row)
        if key in {"vivalink", "vivalnk"}:
            key = "vivalnk"
        old = str(row.get("Role") or row.get("Distribution Type") or "").strip()
        if old in {"Brand", "Marketer"}:
            row["Role"] = old
            row["Distribution Type"] = old
            continue
        want = "OEM" if key in ROLE_OEM else "Brand"
        row["Role"] = want
        row["Distribution Type"] = want
        if old and old != want:
            role_fixes.append({"brand": row.get("Brand"), "from": old, "to": want})

    audit_path = folder / "chatgpt_expand_batch_all_audit.json"
    audit: dict = {}
    if audit_path.exists():
        audit = json.loads(audit_path.read_text(encoding="utf-8")).get("xy_scoring") or {}

    qjson = folder / f"{SLUG}_quadrant.json"
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
            if payload.get("industry_group"):
                audit["industry_group"] = payload["industry_group"]
            if payload.get("industry_category"):
                audit["industry_category"] = payload["industry_category"]
        except Exception:
            pass

    detail_rows = to_company_detail_rows(landscape, QUERY, audit)
    by_brand = {_norm(r.get("Brand") or r.get("Company") or ""): r for r in detail_rows}
    owned_brands = {_norm(a["brand"]) for a in applied if a.get("relation") not in {"product_of", "cleared_independent"}}
    product_brands = {_norm(a["brand"]) for a in applied if a.get("relation") == "product_of"}

    for item in applied:
        brand = item["brand"]
        key = _norm(brand)
        det = by_brand.get(key)
        if not det:
            for dk, dv in by_brand.items():
                if dk in key or key in dk:
                    det = dv
                    break
        if not det:
            continue
        if item.get("relation") == "product_of":
            det["Brand"] = brand
            det["Company"] = item["company"]
            continue
        if item.get("relation") == "cleared_independent":
            det["Brand"] = brand
            det["Company"] = brand
            continue
        # Prefer explicit company_plain / suffix already computed
        if item.get("company"):
            det["Brand"] = brand
            det["Company"] = item["company"]
            continue
        meta = {
            "company": brand,
            "brand": brand,
            "parent_owner": item["owner"],
            "ownership_relation": item["relation"],
            "ownership_year": item.get("year") or "",
            "parent": item.get("company")
            if str(item.get("company") or "").startswith("(")
            else f"acquired by {item['owner']}",
        }
        b, c, _ = brand_display_fields(
            meta,
            market=QUERY,
            industry_category="food",  # force consumer_brand path → (acquired by …)
            mode="consumer_brand",
        )
        det["Brand"] = b or brand
        det["Company"] = c or item["company"]

    for det in detail_rows:
        brand = str(det.get("Brand") or "").strip()
        company = str(det.get("Company") or "").strip()
        key = _norm(brand) or _norm(company)
        if key in {"vivalink", "vivalnk"}:
            det["Brand"] = "VivaLNK"
            if key not in owned_brands and key not in product_brands:
                det["Company"] = "VivaLNK"
            brand = "VivaLNK"
            key = "vivalnk"
        if key in product_brands:
            continue
        if key not in owned_brands and key not in CLEAR_TO_INDEPENDENT:
            # No verified ownership — Brand == Company plain
            plain = brand or company
            if plain.startswith("(") or "acquired by" in plain.lower() or "subsidiary of" in plain.lower() or "merged into" in plain.lower():
                plain = brand if brand and not brand.startswith("(") else company
            det["Brand"] = plain
            det["Company"] = plain
        if key in CLEAR_TO_INDEPENDENT:
            det["Brand"] = "Huawei"
            det["Company"] = "Huawei"
        # Preserve Role from landscape (Brand/Marketer)
        src_role = next(
            (
                str(r.get("Role") or "")
                for r in landscape
                if _norm(r.get("Brand") or r.get("Company") or "") == key
            ),
            "",
        )
        if src_role in {"Brand", "Marketer"}:
            det["Role"] = src_role
        else:
            det["Role"] = "OEM" if key in ROLE_OEM else "Brand"

    write_final_xlsx(
        xlsx,
        landscape,
        "Companies",
        {
            "query": QUERY,
            "xy_scoring": audit,
            "brand_company_ownership": applied,
            "deduped": dropped,
            "role_fixes": role_fixes,
        },
        detail_rows=detail_rows,
    )
    extras = export_expand_quadrant_outputs(
        folder, detail_rows, QUERY, country="global", audit=audit, chart_n=20
    )

    audit_out = {
        "market": QUERY,
        "before": before_n,
        "after": len(detail_rows),
        "ownership_applied": len([a for a in applied if a.get("relation") not in {"cleared_independent"}]),
        "cleared_independent": [a for a in applied if a.get("relation") == "cleared_independent"],
        "product_brands": [a for a in applied if a.get("relation") == "product_of"],
        "deduped": dropped,
        "role_oem": sorted(ROLE_OEM),
        "applied": sorted(applied, key=lambda x: str(x.get("brand") or "").lower()),
        "html": str(extras.get("html") or ""),
    }
    out_json = ROOT / "_audit" / "wearable_brand_company_ownership.json"
    out_json.parent.mkdir(exist_ok=True)
    out_json.write_text(json.dumps(audit_out, indent=2, ensure_ascii=False), encoding="utf-8")

    md = ROOT / "_audit" / "wearable_brand_company_ownership.md"
    lines = [
        "# Wearable Medical Devices — Brand / Company / Role verification",
        "",
        f"Total companies: **{len(detail_rows)}** (was {before_n}; deduped {len(dropped)})",
        f"Ownership / product labels applied: **{len(applied)}** (web-verified only)",
        "",
        "## Ownership / product Brand → Company",
        "",
        "| Brand | Company | Source |",
        "|---|---|---|",
    ]
    for a in sorted(applied, key=lambda x: str(x["brand"]).lower()):
        lines.append(f"| {a['brand']} | {a['company']} | {a['source']} |")
    lines.extend(
        [
            "",
            "## OEM roles",
            "",
            ", ".join(sorted(ROLE_OEM)) or "(none)",
            "",
            "## Deduped rows (kept higher Overall)",
            "",
        ]
    )
    for d in dropped:
        lines.append(
            f"- dropped `{d['brand']}` (Overall {d['overall']}) — kept `{d['kept']}` ({d['kept_overall']})"
        )
    lines.append("")
    md.write_text("\n".join(lines), encoding="utf-8")

    print(f"Companies {before_n} -> {len(detail_rows)} (deduped {len(dropped)})")
    print(f"Ownership/product labels: {len(applied)}")
    for a in sorted(applied, key=lambda x: str(x["brand"]).lower()):
        print(f"  {a['brand']} -> {a['company']}")
    print(f"OEM roles: {sorted(ROLE_OEM)}")
    print(f"html -> {extras.get('html')}")
    print(f"audit -> {md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
