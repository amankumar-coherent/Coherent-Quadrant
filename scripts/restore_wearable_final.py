"""Restore wearable FINAL.xlsx from checkpoint + post-audit dumps."""
from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vendor_intel.pipeline.expand_quadrant_score import (
    export_expand_quadrant_outputs,
    to_company_detail_rows,
)
from vendor_intel.pipeline.web_expand import write_final_xlsx

OUT = ROOT / "output" / "chatgpt_expand"
SLUG = "global_wearable_medical_devices_market_global"
QUERY = "Global Wearable Medical Devices Market"
FOLDER = OUT / SLUG
AUDIT = OUT / "_audit"
INDUSTRY = "Healthcare / Wearable Medical Devices"


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


def main() -> int:
    ck = json.loads(
        (FOLDER / "chatgpt_checkpoint_batch_all.json").read_text(encoding="utf-8")
    )
    final_kept = ck.get("data", {}).get("final_kept") or []
    print(f"checkpoint final_kept: {len(final_kept)}")

    # Post-audit authoritative Brand list + Company display + Role
    details_path = AUDIT / "wearable_company_details_dump.tsv"
    details: list[dict] = []
    with details_path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            brand = (row.get("brand") or "").strip()
            if brand:
                details.append(row)
    print(f"company_details dump: {len(details)}")

    role_path = AUDIT / "wearable_full_role_dump.tsv"
    role_by: dict[str, dict] = {}
    with role_path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            brand = (row.get("brand") or "").strip()
            if brand:
                role_by[_norm(brand)] = row
    print(f"role dump: {len(role_by)}")

    # Removals from full role audit (if dump is older than removals)
    rem_path = AUDIT / "wearable_full_role_market_audit.json"
    removed = set()
    if rem_path.exists():
        rem = json.loads(rem_path.read_text(encoding="utf-8"))
        for r in rem.get("removed") or []:
            removed.add(_norm(r.get("brand") or ""))
        # also apply role fixes onto details if needed
        role_fixes = {
            _norm(r["brand"]): r["to"]
            for r in (rem.get("role_fixes") or [])
            if r.get("brand") and r.get("to")
        }
    else:
        role_fixes = {}

    # Company column fixes (latest ownership labels)
    col_fix = AUDIT / "wearable_brand_company_column_fix.json"
    company_override: dict[str, str] = {}
    keep_set: set[str] | None = None
    if col_fix.exists():
        cf = json.loads(col_fix.read_text(encoding="utf-8"))
        for fix in cf.get("fixes") or []:
            b = _norm(fix.get("brand") or "")
            c = (fix.get("company") or "").strip()
            if b and c:
                company_override[b] = c
        # Prefer brands present in details dump that were NOT removed
        print(f"column_fix final_count claim: {cf.get('final_count')} roles={cf.get('roles')}")

    # Index checkpoint by brand / company name (+ loose containment)
    ck_by: dict[str, dict] = {}
    ck_rows: list[tuple[str, dict]] = []
    for row in final_kept:
        name = _norm(row.get("Company") or row.get("Brand") or "")
        if not name:
            continue
        ck_rows.append((name, row))
        if name not in ck_by:
            ck_by[name] = row
        # also index plain tokens without legal suffixes
        plain = re.sub(
            r"\b(ltd|llc|inc|corp|corporation|co|gmbh|ag|nv|plc|sa|bv|limited)\b\.?",
            "",
            name,
        )
        plain = re.sub(r"[^a-z0-9]+", " ", plain).strip()
        if plain and plain not in ck_by:
            ck_by[plain] = row

    def _find_ck(brand: str) -> dict:
        key = _norm(brand)
        if key in ck_by:
            return ck_by[key]
        plain = re.sub(r"[^a-z0-9]+", " ", key).strip()
        if plain in ck_by:
            return ck_by[plain]
        # containment: brand inside company or company starts with brand
        best = None
        for name, row in ck_rows:
            if key and (key in name or name.startswith(key)):
                # prefer shorter company names (closer match)
                if best is None or len(name) < len(best[0]):
                    best = (name, row)
        return best[1] if best else {}

    landscape: list[dict] = []
    missing_ck = []
    for d in details:
        brand = (d.get("brand") or "").strip()
        key = _norm(brand)
        if key in removed:
            continue
        role = (d.get("role") or "Brand").strip()
        if key in role_fixes:
            role = role_fixes[key]
        # prefer role dump role if present
        rd = role_by.get(key) or {}
        if rd.get("role") in {"Brand", "Marketer"} and key not in role_fixes:
            role = rd["role"]

        company_disp = company_override.get(key) or (d.get("company_display") or brand).strip()
        src = _find_ck(brand)
        if not src and rd.get("company"):
            src = _find_ck(str(rd.get("company") or ""))
        if not src:
            missing_ck.append(brand)

        website = (
            str(rd.get("website") or src.get("Website") or src.get("website") or "").strip()
        )
        specialty = (
            str(
                rd.get("specialty")
                or src.get("Specialty Focus")
                or src.get("specialty")
                or ""
            ).strip()
        )
        categories = (
            str(
                rd.get("categories")
                or src.get("Core Categories")
                or src.get("categories")
                or ""
            ).strip()
        )
        ownership = (
            str(rd.get("ownership") or src.get("Ownership") or src.get("ownership") or "").strip()
        )
        hq = str(
            src.get("Headquarters")
            or src.get("Found in")
            or src.get("headquarters")
            or ""
        ).strip()
        founded = str(src.get("Founded") or src.get("founded") or "").strip()
        presence = str(src.get("Operational Presence") or src.get("presence") or "").strip()
        continent = str(src.get("Continent / Geography") or src.get("continent") or "").strip()
        employees = str(src.get("Employees") or src.get("employees") or "").strip()

        # Keep prior X/Y only as placeholders to clear later — use dump values for now
        try:
            x = int(float(d.get("x") or 50))
        except Exception:
            x = 50
        try:
            y = int(float(d.get("y") or 50))
        except Exception:
            y = 50
        overall = int(round((x + y) / 2))
        quad = (d.get("quadrant") or "").strip()

        landscape.append(
            {
                "Company": brand,
                "Brand": brand,
                "Website": website,
                "Founded": founded,
                "Headquarters": hq,
                "Found in": hq,
                "Continent / Geography": continent,
                "Operational Presence": presence,
                "Ownership": ownership,
                "Employees": employees,
                "Core Categories": categories,
                "Specialty Focus": specialty,
                "Distribution Type": role,
                "Role": role,
                "Industry Category": INDUSTRY,
                "X Score": x,
                "Y Score": y,
                "Overall Score": overall,
                "Quadrant": quad,
                "_display_company": company_disp,
                "Summary": str(src.get("Summary") or specialty or "")[:500],
            }
        )

    roles = Counter(r["Role"] for r in landscape)
    print(f"restored landscape: {len(landscape)} roles={dict(roles)}")
    print(f"missing from checkpoint (using dump fields only): {len(missing_ck)}")
    if missing_ck[:15]:
        print("  e.g.", missing_ck[:15])

    detail_rows = to_company_detail_rows(landscape, QUERY, {"restored": True})
    for det in detail_rows:
        key = _norm(det.get("Brand") or "")
        src = next((r for r in landscape if _norm(r.get("Brand") or "") == key), None)
        if not src:
            continue
        det["Role"] = src.get("Role") or "Brand"
        if src.get("_display_company"):
            det["Company"] = src["_display_company"]

    xlsx = FOLDER / f"{SLUG}_FINAL.xlsx"
    # backup truncated file
    if xlsx.exists() and xlsx.stat().st_size < 50_000:
        bak = xlsx.with_suffix(".xlsx.truncated_bak")
        bak.write_bytes(xlsx.read_bytes())
        print(f"saved truncated bak -> {bak}")

    write_final_xlsx(
        xlsx,
        landscape,
        "Companies",
        {"query": QUERY, "restored_from": "checkpoint+audit_dumps"},
        detail_rows=detail_rows,
    )
    export_expand_quadrant_outputs(
        FOLDER, detail_rows, QUERY, country="global", audit={"restored": True}, chart_n=20
    )
    print(f"wrote {xlsx}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
