#!/usr/bin/env python3
"""Verify + fix GLP-1 Role = Brand | Marketer (evidence only, no hallucination).

Rules for Global GLP-1 Receptor Agonist Market:
  Brand    = discovers / owns / develops the GLP-1 (or dual/triple) asset,
             OR owns a biosimilar / authorized-generic brand (own label/MAH).
  Marketer = exclusive licensee / distributor / co-commercializer of SOMEONE
             ELSE'S GLP-1 brand (does not own the molecule).

Only forced flips below have a published source. Everything else stays as-is
unless it was wrongly forced Marketer without evidence → revert to Brand.
"""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from openpyxl import load_workbook

from vendor_intel.pipeline.expand_quadrant_score import (
    export_expand_quadrant_outputs,
    to_company_detail_rows,
)
from vendor_intel.pipeline.web_expand import write_final_xlsx

SLUG = "global_glp_1_receptor_agonist_market_global"
QUERY = "Global GLP-1 Receptor Agonist Market"
OUT = ROOT / "output" / "chatgpt_expand" / SLUG
XLSX = OUT / f"{SLUG}_FINAL.xlsx"
AUDIT = ROOT / "output" / "chatgpt_expand" / "_audit"

# stem -> (Role, key_brands_update, evidence_note)
# Marketer = verified in-license / exclusive commercialization of another's GLP-1
FORCE_MARKETER: dict[str, tuple[str, str]] = {
    "emcure": (
        "Poviztra (semaglutide 2.4 mg) — exclusive India commercialization for Novo Nordisk",
        "Novo Nordisk–Emcure India exclusive distribution/commercialization of Poviztra (Wegovy molecule), Nov 2025",
    ),
    "cipla": (
        "Yurpeak (tirzepatide) — distribute/promote India second brand for Eli Lilly",
        "Cipla–Eli Lilly India agreement to distribute and promote Yurpeak (tirzepatide); Lilly manufactures/supplies, Oct–Dec 2025",
    ),
    "lupin": (
        "Bofanglutide (GZR18) — exclusive India license from Gan & Lee",
        "Lupin–Gan & Lee exclusive license/supply/distribution for Bofanglutide in India, Dec 2025",
    ),
    "jw pharmaceutical": (
        "Bofanglutide — exclusive Korea license from Gan & Lee",
        "Gan & Lee–JW Pharmaceutical exclusive Korea develop/commercialize Bofanglutide, Apr 2026",
    ),
    "pfizer china": (
        "Ecnoglutide — exclusive Mainland China commercialization for Sciwind (Sciwind remains MAH)",
        "Sciwind–Pfizer China commercialization collaboration for Ecnoglutide, Feb 2026",
    ),
    "productos cientificos": (
        "Bofanglutide — exclusive Latin America license from Gan & Lee (Carnot)",
        "Gan & Lee–Productos Científicos (Carnot) exclusive LATAM license for Bofanglutide, Nov 2025",
    ),
    "productos científicos": (
        "Bofanglutide — exclusive Latin America license from Gan & Lee (Carnot)",
        "Gan & Lee–Productos Científicos (Carnot) exclusive LATAM license for Bofanglutide, Nov 2025",
    ),
    "qilu": (
        "RAY1225 (GLP-1/GIP) — exclusive China manufacture/commercialize for Raynovent (Raynovent remains MAH/IP owner)",
        "Raynovent–Qilu exclusive China manufacture/commercialization license for RAY1225, Jan 2026",
    ),
    "kailera": (
        "HRS9531 / KAI-9531 (+ HRS-7535, HRS-4729) — exclusive ex-Greater China license from Hengrui",
        "Hengrui–Kailera exclusive license to develop/manufacture/commercialize metabolic GLP-1 assets outside Greater China, May 2024",
    ),
}

# Originators / biosimilar brand owners wrongly labeled Marketer → Brand
FORCE_BRAND: dict[str, tuple[str, str]] = {
    "chugai": (
        "Orforglipron (OWL833) — discovered by Chugai; worldwide rights licensed to Eli Lilly",
        "Chugai discovered orforglipron; Lilly holds worldwide development/commercialization (2018 license)",
    ),
}

# Previously labeled Marketer with NO verified GLP-1 license found → Brand
# (do not keep hallucinated Marketer). Brands field cleared of fake "regional marketer" text.
UNVERIFIED_MARKETER_REVERT = {
    "adcock ingram": "No verified exclusive GLP-1 in-license found — revert Marketer→Brand",
    "pharmadynamics": "No verified exclusive GLP-1 in-license found — revert Marketer→Brand",
    "mundipharma": "No verified exclusive GLP-1 in-license found — revert Marketer→Brand",
    "menarini": "No verified exclusive GLP-1 in-license found — revert Marketer→Brand",
    "recordati": "No verified exclusive GLP-1 in-license found — revert Marketer→Brand",
    "ferrer": "No verified exclusive GLP-1 in-license found — revert Marketer→Brand",
    "tecnoquimicas": "No verified exclusive GLP-1 in-license found — revert Marketer→Brand",
    "moksha8": "No verified exclusive GLP-1 in-license found — revert Marketer→Brand",
}


def _norm(s: str) -> str:
    s = str(s or "").strip().lower()
    for a, b in {"ö": "o", "ü": "u", "ä": "a", "ß": "ss", "é": "e", "í": "i", "ó": "o", "ú": "u", "ç": "c", "ã": "a"}.items():
        s = s.replace(a, b)
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _match(name: str, table: dict) -> str | None:
    n = _norm(name)
    best = None
    best_len = -1
    for k in table:
        kn = _norm(k)
        if not kn:
            continue
        if n == kn or n.startswith(kn + " ") or kn in n:
            if len(kn) > best_len:
                best = k
                best_len = len(kn)
    return best


def main() -> None:
    wb = load_workbook(XLSX, data_only=True)
    ws = wb["Landscape"]
    rows_raw = list(ws.iter_rows(values_only=True))
    hdr = [str(h) for h in rows_raw[0]]
    landscape: list[dict] = []
    changes: list[dict] = []

    for r in rows_raw[1:]:
        if not r:
            continue
        d = {hdr[i]: ("" if r[i] is None else r[i]) for i in range(len(hdr)) if i < len(r)}
        name = str(d.get("Company") or "").strip()
        if not name:
            continue
        old_role = str(d.get("Role") or d.get("Distribution Type") or "Brand").strip()
        if old_role not in ("Brand", "Marketer"):
            old_role = "Brand"

        new_role = old_role
        evidence = ""
        brands_update = None

        mk = _match(name, FORCE_MARKETER)
        bk = _match(name, FORCE_BRAND)
        uk = _match(name, UNVERIFIED_MARKETER_REVERT)

        if mk:
            brands_update, evidence = FORCE_MARKETER[mk]
            new_role = "Marketer"
        elif bk:
            brands_update, evidence = FORCE_BRAND[bk]
            new_role = "Brand"
        elif uk and old_role == "Marketer":
            evidence = UNVERIFIED_MARKETER_REVERT[uk]
            new_role = "Brand"
            # clear placeholder marketer brand text
            br = str(d.get("Key Brands Represented") or "")
            if re.search(r"marketer|regional|chronic care|specialty marketing|andean", br, re.I):
                brands_update = ""

        if new_role != old_role or (brands_update is not None and brands_update != str(d.get("Key Brands Represented") or "")):
            changes.append(
                {
                    "company": name,
                    "from": old_role,
                    "to": new_role,
                    "evidence": evidence,
                    "brands": brands_update,
                }
            )
        d["Role"] = new_role
        d["Distribution Type"] = new_role
        if brands_update is not None:
            d["Key Brands Represented"] = brands_update
        if new_role == "Marketer" and evidence:
            # keep a short specialty focus from evidence (first clause)
            d["Specialty Focus"] = f"Licensed GLP-1 commercialization — {evidence.split(',')[0]}"
        landscape.append(d)

    brand_n = sum(1 for r in landscape if r.get("Role") == "Brand")
    mark_n = sum(1 for r in landscape if r.get("Role") == "Marketer")
    print(f"total={len(landscape)} Brand={brand_n} Marketer={mark_n} changes={len(changes)}")

    audit = {}
    ap = OUT / "chatgpt_expand_batch_all_audit.json"
    if ap.exists():
        try:
            audit = json.loads(ap.read_text(encoding="utf-8")).get("xy_scoring") or {}
        except Exception:
            audit = {}
    audit.setdefault("industry_group", "Healthcare")
    audit.setdefault("industry_category", "Pharmaceutical")

    details = to_company_detail_rows(landscape, QUERY, audit)
    by = {_norm(r.get("Company") or ""): r for r in landscape}
    for drow in details:
        land = by.get(_norm(drow.get("Brand") or "")) or {}
        role = str(land.get("Role") or "Brand")
        drow["Role"] = role if role in ("Brand", "Marketer") else "Brand"
        if not str(drow.get("Company") or "").startswith("("):
            drow["Company"] = drow.get("Brand") or drow.get("Company")

    write_final_xlsx(
        XLSX,
        landscape,
        "Companies",
        {
            "query": QUERY,
            "role_verify": "2026-08-14",
            "brand": brand_n,
            "marketer": mark_n,
            "role_changes": len(changes),
            "xy_scoring": audit,
        },
        detail_rows=details,
    )
    extras = export_expand_quadrant_outputs(
        OUT, details, QUERY, country="global", audit=audit, chart_n=20
    )

    with (OUT / f"{SLUG}_companies.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["Brand", "Company", "Role", "Quadrant", "X", "Y", "Overall", "Found in"],
        )
        w.writeheader()
        for drow in details:
            w.writerow({k: drow.get(k, "") for k in w.fieldnames})

    AUDIT.mkdir(parents=True, exist_ok=True)
    report = {
        "total": len(landscape),
        "brand": brand_n,
        "marketer": mark_n,
        "changes": changes,
        "html": str(extras.get("html") or ""),
        "rule": {
            "Brand": "owns/develops GLP-1 asset or own biosimilar/AG brand",
            "Marketer": "exclusive licensee/distributor of another company's GLP-1",
        },
    }
    (AUDIT / f"{SLUG}_role_verify.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    lines = ["Company\tFrom\tTo\tEvidence"]
    for c in changes:
        lines.append(f"{c['company']}\t{c['from']}\t{c['to']}\t{c['evidence']}")
    (AUDIT / f"{SLUG}_role_changes.tsv").write_text("\n".join(lines), encoding="utf-8")

    print("--- changes ---")
    for c in changes:
        print(f"{c['from']} -> {c['to']}: {c['company']}")
        print(f"  {c['evidence']}")
    print("--- marketers now ---")
    for r in landscape:
        if r.get("Role") == "Marketer":
            print(f"  {r.get('Company')} | {r.get('Key Brands Represented')}")


if __name__ == "__main__":
    main()
