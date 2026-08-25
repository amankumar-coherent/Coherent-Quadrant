#!/usr/bin/env python3
"""Verify + fix Company column from Brand for Global GLP-1 FINAL.

Rule (consumer_brand market):
  Brand   = plain player name
  Company = (acquired by|subsidiary of|merged into|owned by Parent[, year]) when owned;
            else Company = Brand

Only web-verified ownership. Independent rows keep Brand == Company.
Also canonicalizes fake unit Brand labels (e.g. Glenmark Lirafit -> Glenmark Pharmaceuticals).
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
from vendor_intel.quadrant.brand_meta import brand_display_fields, format_acquired_suffix

SLUG = "global_glp_1_receptor_agonist_market_global"
QUERY = "Global GLP-1 Receptor Agonist Market"
OUT = ROOT / "output" / "chatgpt_expand" / SLUG
XLSX = OUT / f"{SLUG}_FINAL.xlsx"
AUDIT = ROOT / "output" / "chatgpt_expand" / "_audit"

# Canonical Brand rename (unit/product suffixes -> real company)
RENAME_BRAND: dict[str, str] = {
    "mylan pharmaceuticals ulc viatris": "Mylan Pharmaceuticals ULC",
    "mylan pharmaceuticals ulc (viatris)": "Mylan Pharmaceuticals ULC",
    "sandoz novartis generics": "Sandoz",
    "sandoz (novartis generics)": "Sandoz",
    "glenmark lirafit": "Glenmark Pharmaceuticals",
    "biocon glp 1": "Biocon",
    "biocon glp-1": "Biocon",
    "hikma liraglutide": "Hikma Pharmaceuticals",
    "aspen diabetes": "Aspen Pharmacare",
    "alkem diabetes": "Alkem Laboratories",
    "cipla diabetes care": "Cipla",
    "usv diabetes": "USV Private Limited",
    "ems diabetes": "Laboratório Farmacêutico EMS",
    "ache diabetes": "Aché Laboratórios Farmacêuticos",
    "aché diabetes": "Aché Laboratórios Farmacêuticos",
    "zydus cadila metabolic": "Zydus Lifesciences",
    "intas biopharma": "Intas Pharmaceuticals",
    "wockhardt biotech": "Wockhardt",
    "viatris complex generics": "Viatris",
    "stada specialty": "STADA Arzneimittel",
    "fresenius kabi biosimilars": "Fresenius Kabi",
    "cspc zhongnuo": "CSPC Pharmaceutical Group",
    "jiangsu hansoh pharmaceutical": "Hansoh Pharmaceutical Group",
    "qilu anti obesity unit": "Qilu Pharmaceutical",
    "qilu anti-obesity unit": "Qilu Pharmaceutical",
    "tecnoquimicas marketer": "Tecnoquímicas",
    "moksha8 latam": "Moksha8",
    "hypera s a": "Hypera Pharma",
    "hypera s.a.": "Hypera Pharma",
    "laboratorio chile teva": "Laboratorio Chile",
    "laboratorio chile (teva)": "Laboratorio Chile",
    "blau injectables": "Blau Farmacêutica",
    "cristalia injectables": "Cristália Produtos Químicos Farmacêuticos",
    "cristália injectables": "Cristália Produtos Químicos Farmacêuticos",
    "libbs specialty": "Libbs Farmacêutica",
    "sumitomo pharma co ltd": "Sumitomo Pharma",
    "sumitomo pharma co., ltd.": "Sumitomo Pharma",
    "altimmune inc": "Altimmune",
    "altimmune, inc.": "Altimmune",
    "carmot therapeutics inc": "Carmot Therapeutics",
    "carmot therapeutics, inc.": "Carmot Therapeutics",
}

# stem -> (ownership text, relation, year)
# ownership text must start with acquired by|subsidiary of|merged into|owned by
OWNERSHIP: dict[str, tuple[str, str, str]] = {
    # Acquisitions (completed)
    "carmot": ("acquired by Roche", "acquired_by", "2024"),
    "metsera": ("acquired by Pfizer", "acquired_by", "2025"),
    "versanis": ("acquired by Eli Lilly and Company", "acquired_by", "2023"),
    "reata": ("acquired by AbbVie", "acquired_by", "2023"),
    "ratiopharm": ("acquired by Teva Pharmaceutical Industries", "acquired_by", "2010"),
    # Mergers
    "mylan": ("merged into Viatris", "merged_into", "2020"),
    # Subsidiaries / group
    "hexal": ("subsidiary of Sandoz", "subsidiary_of", ""),
    "laboratorio chile": ("subsidiary of Teva Pharmaceutical Industries", "subsidiary_of", ""),
    "neuraly": ("subsidiary of D&D Pharmatech", "subsidiary_of", ""),
    "yaopharma": ("subsidiary of Fosun Pharma", "subsidiary_of", ""),
    "biocon biologics": ("subsidiary of Biocon", "subsidiary_of", ""),
    "hangzhou jiuyuan": ("subsidiary of Huadong Medicine", "subsidiary_of", ""),
    "jiuyuan gene": ("subsidiary of Huadong Medicine", "subsidiary_of", ""),
    "pfizer china": ("subsidiary of Pfizer", "subsidiary_of", ""),
    "sanofi medley": ("subsidiary of Sanofi", "subsidiary_of", ""),
    # Majority ownership (listed but controlled)
    "chugai": ("owned by Roche Holding Ltd (~59.9%)", "owned_by", ""),
}


def _norm(s: str) -> str:
    s = str(s or "").strip().lower()
    for a, b in {
        "ö": "o", "ü": "u", "ä": "a", "ß": "ss", "é": "e", "á": "a",
        "í": "i", "ó": "o", "ú": "u", "ç": "c", "ã": "a", "ê": "e",
    }.items():
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
    renamed: list[dict] = []
    ownership_fixed: list[dict] = []
    removed_dupes: list[str] = []
    seen: set[str] = set()

    for r in rows_raw[1:]:
        if not r:
            continue
        d = {hdr[i]: ("" if r[i] is None else r[i]) for i in range(len(hdr)) if i < len(r)}
        name = str(d.get("Company") or "").strip()
        if not name:
            continue

        # Brand rename
        rk = _match(name, RENAME_BRAND)
        if rk:
            new_name = RENAME_BRAND[rk]
            if new_name != name:
                renamed.append({"from": name, "to": new_name})
                d["Company"] = new_name
                name = new_name

        k = _norm(name)
        if k in seen:
            removed_dupes.append(name)
            continue
        seen.add(k)

        # Ownership
        ok = _match(name, OWNERSHIP)
        if ok:
            own, rel, year = OWNERSHIP[ok]
            old = str(d.get("Ownership") or "")
            if old != own:
                ownership_fixed.append({"brand": name, "from": old, "to": own})
            d["Ownership"] = own
            d["ownership_relation"] = rel
            d["ownership_year"] = year
            m = re.match(
                r"(?i)^\s*(?:acquired by|subsidiary of|merged into|owned by)\s+(.+?)\s*$",
                own,
            )
            parent = m.group(1).strip() if m else ""
            # strip ~pct noise for parent_owner used in format_acquired_suffix
            parent_clean = re.sub(r"\s*\([^)]*\)\s*$", "", parent).strip()
            d["parent_owner"] = parent_clean or parent
        else:
            # Independent — clear false acquisition leftovers
            own = str(d.get("Ownership") or "").strip()
            low = own.lower()
            if any(
                low.startswith(p)
                for p in ("acquired by", "subsidiary of", "merged into", "owned by")
            ):
                # Only keep if matched above; else clear
                d["Ownership"] = "Independent"
            elif not own or own.lower() in {"not publicly disclosed", "n/a", "na"}:
                d["Ownership"] = "Independent"
            d["ownership_relation"] = ""
            d["ownership_year"] = ""
            d.pop("parent_owner", None)

        landscape.append(d)

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
    by_land = {_norm(str(r.get("Company") or "")): r for r in landscape}
    company_changed: list[dict] = []
    annotated: list[dict] = []

    for drow in details:
        brand = str(drow.get("Brand") or "").strip()
        # Apply rename on detail Brand too
        rk = _match(brand, RENAME_BRAND)
        if rk:
            brand = RENAME_BRAND[rk]
        land = by_land.get(_norm(brand)) or {}
        parent_owner = str(land.get("parent_owner") or "").strip()
        relation = str(land.get("ownership_relation") or "").strip() or "acquired_by"
        year = str(land.get("ownership_year") or "").strip()

        row_for_meta = {
            "company": brand,
            "company_raw": brand,
            "parent_owner": parent_owner,
            "parent": land.get("Ownership") or "",
            "ownership_relation": relation,
            "ownership_year": year,
        }
        b2, company_col, _ = brand_display_fields(row_for_meta, market=QUERY)
        if not parent_owner:
            company_col = b2 or brand
        else:
            # Ensure consistent suffix formatting
            company_col = format_acquired_suffix(
                parent_owner, relation=relation, year=year
            )

        old_co = str(drow.get("Company") or "")
        if old_co != company_col or str(drow.get("Brand") or "") != (b2 or brand):
            company_changed.append(
                {
                    "brand": b2 or brand,
                    "from": old_co,
                    "to": company_col,
                }
            )
        drow["Brand"] = b2 or brand
        drow["Company"] = company_col
        role = str(land.get("Role") or drow.get("Role") or "Brand")
        if role not in ("Brand", "Marketer"):
            role = "Brand"
        drow["Role"] = role
        if company_col.startswith("("):
            annotated.append(
                {"brand": drow["Brand"], "company": company_col, "role": role}
            )

    # Deduplicate details after rename
    seen_d: set[str] = set()
    clean_details: list[dict] = []
    clean_land: list[dict] = []
    land_by = {_norm(r.get("Company") or ""): r for r in landscape}
    for drow in details:
        k = _norm(drow.get("Brand") or "")
        if not k or k in seen_d:
            continue
        seen_d.add(k)
        clean_details.append(drow)
        if k in land_by:
            clean_land.append(land_by[k])
        else:
            # synthesize minimal land row
            clean_land.append(
                {
                    "Company": drow["Brand"],
                    "Role": drow["Role"],
                    "Distribution Type": drow["Role"],
                    "Ownership": "Independent",
                    "Industry Category": "Healthcare / Pharmaceutical",
                    "X Score": drow.get("X"),
                    "Y Score": drow.get("Y"),
                    "Overall Score": drow.get("Overall"),
                    "Quadrant": drow.get("Quadrant"),
                    "Headquarters": drow.get("Found in"),
                }
            )

    write_final_xlsx(
        XLSX,
        clean_land,
        "Companies",
        {
            "query": QUERY,
            "brand_company_verify": "2026-08-14",
            "renamed": len(renamed),
            "ownership_fixed": len(ownership_fixed),
            "company_col_fixed": len(company_changed),
            "dupes_removed": len(removed_dupes),
            "xy_scoring": audit,
        },
        detail_rows=clean_details,
    )
    extras = export_expand_quadrant_outputs(
        OUT, clean_details, QUERY, country="global", audit=audit, chart_n=20
    )

    with (OUT / f"{SLUG}_companies.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["Brand", "Company", "Role", "Quadrant", "X", "Y", "Overall", "Found in"],
        )
        w.writeheader()
        for d in clean_details:
            w.writerow({k: d.get(k, "") for k in w.fieldnames})

    AUDIT.mkdir(parents=True, exist_ok=True)
    report = {
        "total": len(clean_details),
        "annotated": len([d for d in clean_details if str(d.get("Company") or "").startswith("(")]),
        "renamed": renamed,
        "ownership_fixed": ownership_fixed,
        "company_changed_n": len(company_changed),
        "dupes_removed": removed_dupes,
        "annotated_rows": [
            {"brand": d.get("Brand"), "company": d.get("Company"), "role": d.get("Role")}
            for d in clean_details
            if str(d.get("Company") or "").startswith("(")
        ],
        "html": str(extras.get("html") or ""),
        "rule": "Brand=plain name; Company=Brand if independent else (acquired by|subsidiary of|merged into|owned by Parent)",
    }
    (AUDIT / f"{SLUG}_brand_company_column_fix.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    lines = ["Brand\tCompany\tRole"]
    for d in clean_details:
        lines.append(f"{d.get('Brand')}\t{d.get('Company')}\t{d.get('Role')}")
    (AUDIT / f"{SLUG}_brand_company_after.tsv").write_text(
        "\n".join(lines), encoding="utf-8"
    )

    print(
        f"total={report['total']} annotated={report['annotated']} "
        f"renamed={len(renamed)} ownership_fixed={len(ownership_fixed)} "
        f"dupes_removed={len(removed_dupes)}"
    )
    for x in report["annotated_rows"]:
        print(f"ANN: {x['brand']} | {x['company']} | {x['role']}")
    for x in renamed[:20]:
        print(f"REN: {x['from']} -> {x['to']}")


if __name__ == "__main__":
    main()
