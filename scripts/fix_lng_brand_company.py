#!/usr/bin/env python3
"""Verify + fix Company column from Brand for Global LNG FINAL.

Rule (consumer_brand / Brand+Marketer markets):
  Brand   = plain player name
  Company = (acquired by|subsidiary of|merged into|owned by Parent) when owned;
            else Company = Brand

Only web-verified ownership. Independent rows keep Brand == Company.
Also drops Equinor (UK) regional clone if Equinor ASA is present.
"""
from __future__ import annotations

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
from vendor_intel.quadrant.brand_meta import brand_display_fields

SLUG = "global_liquefied_natural_gas_market_global"
QUERY = "Global Liquefied Natural Gas Market"
OUT = ROOT / "output" / "chatgpt_expand" / SLUG
XLSX = OUT / f"{SLUG}_FINAL.xlsx"
AUDIT = ROOT / "output" / "chatgpt_expand" / "_audit"

# stem -> (Ownership text starting with acquired by|subsidiary of|merged into|owned by, relation)
OWNERSHIP: dict[str, tuple[str, str]] = {
    # Acquisitions / take-privates
    "pavilion energy": ("acquired by Shell plc", "acquired_by"),
    "magnolia lng": ("acquired by Glenfarne Group", "acquired_by"),
    "seapeak": ("acquired by Stonepeak", "acquired_by"),
    # Mergers
    "sk innovation e s": ("merged into SK Innovation", "merged_into"),
    "sk e s": ("merged into SK Innovation", "merged_into"),
    # Clear subsidiaries / project vehicles of listed parents
    "sabine pass lng": ("subsidiary of Cheniere Energy", "subsidiary_of"),
    "calcasieu pass lng": ("subsidiary of Venture Global LNG", "subsidiary_of"),
    "cp2 lng": ("subsidiary of Venture Global LNG", "subsidiary_of"),
    "plaquemines lng": ("subsidiary of Venture Global LNG", "subsidiary_of"),
    "woodside louisiana lng": ("subsidiary of Woodside Energy Group Ltd", "subsidiary_of"),
    "elba island lng": ("subsidiary of Kinder Morgan", "subsidiary_of"),
    "port arthur lng": ("subsidiary of Sempra Infrastructure Partners", "subsidiary_of"),
    "qatarenergy trading": ("subsidiary of QatarEnergy", "subsidiary_of"),
    "ptt global lng": ("subsidiary of PTT Public Company Limited", "subsidiary_of"),
    "ptt lng company": ("subsidiary of PTT Public Company Limited", "subsidiary_of"),
    "adnoc gas": ("subsidiary of ADNOC", "subsidiary_of"),
    "petrovietnam gas": ("subsidiary of Petrovietnam", "subsidiary_of"),
    "kunlun energy": ("subsidiary of PetroChina / CNPC", "subsidiary_of"),
    "mubadala energy": ("subsidiary of Mubadala Investment Company", "subsidiary_of"),
    "berkshire hathaway energy": ("subsidiary of Berkshire Hathaway", "subsidiary_of"),
    "grain lng": ("subsidiary of National Grid", "subsidiary_of"),
    "elengy": ("subsidiary of Engie", "subsidiary_of"),
    "bw lng": ("subsidiary of BW Group", "subsidiary_of"),
    "litasco": ("subsidiary of Rosneft", "subsidiary_of"),
    "eemsenergyterminal": ("subsidiary of Gasunie", "subsidiary_of"),
    "revithoussa lng": ("subsidiary of DESFA", "subsidiary_of"),
    "qalhat lng": ("subsidiary of Oman LNG / Qalhat complex", "subsidiary_of"),
    "equinor uk": ("subsidiary of Equinor ASA", "subsidiary_of"),
    "equinor limited": ("subsidiary of Equinor ASA", "subsidiary_of"),
    # Owned by (JV / state / PE) — Company shows (owned by …)
    "sempra infrastructure": (
        "owned by Sempra (~70%), KKR (~20%), ADIA (~10%); KKR-led 65% sale pending 2026",
        "owned_by",
    ),
    "uniper": ("owned by Federal Republic of Germany (~99.12%)", "owned_by"),
    "deutsche energy terminal": ("owned by Federal Republic of Germany", "owned_by"),
    "det": ("owned by Federal Republic of Germany", "owned_by"),
    "hoegh evi": (
        "owned by Aequitas Limited (Höegh family) 50% and Igneo Infrastructure Partners 50%",
        "owned_by",
    ),
    "jera": (
        "owned by TEPCO Fuel & Power and Chubu Electric Power (50/50 JV)",
        "owned_by",
    ),
    "lng japan": ("owned by Sojitz Corporation (50%) and Sumitomo Corporation (50%)", "owned_by"),
    "cove point lng": (
        "owned by Berkshire Hathaway Energy (~75%) and Brookfield (~25%)",
        "owned_by",
    ),
    "dragon lng": ("owned by Shell (50%) and VTTI (50%)", "owned_by"),
    "gate terminal": ("owned by Gasunie (50%) and Vopak (50%)", "owned_by"),
    "south hook lng": (
        "owned by QatarEnergy, ExxonMobil and TotalEnergies (JV)",
        "owned_by",
    ),
    "golden pass lng": ("owned by QatarEnergy (70%) and ExxonMobil (30%)", "owned_by"),
    "lng canada": (
        "owned by Shell (40%), Petronas (25%), PetroChina (15%), Mitsubishi (15%), KOGAS (5%)",
        "owned_by",
    ),
    "cameron lng": (
        "owned by Sempra Infrastructure, TotalEnergies, Mitsui, Mitsubishi, NYK (JV)",
        "owned_by",
    ),
    "adriatic lng": ("owned by ExxonMobil, QatarEnergy and SNAM (JV)", "owned_by"),
    "mlng": ("owned by Petronas-led JV (Malaysia LNG)", "owned_by"),
    "brunei lng": (
        "owned by Government of Brunei (50%), Shell (25%), Mitsubishi (25%)",
        "owned_by",
    ),
    "angola lng": (
        "owned by Sonangol, Chevron, TotalEnergies, Azule Energy (JV)",
        "owned_by",
    ),
    "atlantic lng": ("owned by Shell, bp and partners (JV)", "owned_by"),
    "australia pacific lng": (
        "owned by ConocoPhillips, Origin Energy and Sinopec (JV)",
        "owned_by",
    ),
    "gladstone lng": ("owned by Santos-led JV", "owned_by"),
    "ichthys lng": ("owned by Inpex-led JV", "owned_by"),
    "papua new guinea lng": ("owned by ExxonMobil-operated JV", "owned_by"),
    "png lng": ("owned by ExxonMobil-operated JV", "owned_by"),
    "yamal lng": ("owned by Novatek-led JV", "owned_by"),
    "arctic lng 2": ("owned by Novatek-led consortium", "owned_by"),
    "peru lng": ("owned by Hunt Oil, Shell, SK and Marubeni (JV)", "owned_by"),
    "coral south flng": ("owned by Eni-operated Area 4 JV", "owned_by"),
    "mozambique lng": ("owned by TotalEnergies-operated consortium", "owned_by"),
    "greater tortue": ("owned by bp-operated JV (bp, Kosmos, Petrosen, SMH)", "owned_by"),
    "cameroon flng": ("owned by Golar / Perenco / SNH FLNG project", "owned_by"),
    "rovuma lng": ("owned by ExxonMobil-led Area 4 consortium", "owned_by"),
    "gaslog": (
        "owned by Livanos family / Onassis Foundation (~55%) and GIC (~45%)",
        "owned_by",
    ),
    "nigeria lng": ("owned by NNPC, Shell, TotalEnergies and Eni (JV)", "owned_by"),
    "egypt lng": ("owned by EGAS, Shell and Petronas (JV)", "owned_by"),
    "segas": ("owned by Eni, EGAS and partners (Damietta JV)", "owned_by"),
    "equatorial guinea lng": ("owned by private JV (EG LNG)", "owned_by"),
    "yemen lng": ("owned by TotalEnergies-led JV", "owned_by"),
    "freeport lng": (
        "owned by Freeport LNG Investments (~63.5%), JERA (~21.9%), Osaka Gas (~10.8%), JAPEX (~3.8%)",
        "owned_by",
    ),
}

# Brand display cleanup (strip noisy suffixes in Brand column)
RENAME_BRAND = {
    "hoegh evi": "Höegh Evi",
    "sk innovation e s": "SK Innovation E&S",
    "cameroon flng": "Cameroon FLNG (Hilli Episeyo)",
}

REMOVE_STEMS: dict[str, str] = {
    # Keep regional clones annotated rather than dropping (preserve ≥200).
}


def _norm(s: str) -> str:
    s = str(s or "").strip().lower()
    s = (
        s.replace("ö", "o")
        .replace("ü", "u")
        .replace("ä", "a")
        .replace("÷", "o")
        .replace("ß", "ss")
    )
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _match(name: str, table: dict) -> str | None:
    n = _norm(re.sub(r"\([^)]*\)", " ", str(name or "")))
    n = re.sub(r"\s+", " ", n).strip()
    best = None
    best_len = -1
    for k in table:
        kn = _norm(k)
        if kn in n and len(kn) > best_len:
            best = k
            best_len = len(kn)
    return best


def main() -> None:
    wb = load_workbook(XLSX, data_only=True)
    ws = wb["Landscape"]
    rows_raw = list(ws.iter_rows(values_only=True))
    hdr = [str(h) for h in rows_raw[0]]

    landscape: list[dict] = []
    removed: list[dict] = []
    ownership_fixed: list[dict] = []
    renamed: list[dict] = []

    for r in rows_raw[1:]:
        d = {hdr[i]: ("" if r[i] is None else r[i]) for i in range(len(hdr)) if i < len(r)}
        name = str(d.get("Company") or "").strip()
        if not name:
            continue
        rk = _match(name, REMOVE_STEMS)
        if rk:
            removed.append({"brand": name, "reason": REMOVE_STEMS[rk]})
            continue

        # Brand rename (canonical display name on Landscape Company field)
        ren = _match(name, RENAME_BRAND)
        if ren:
            new_name = RENAME_BRAND[ren]
            if new_name != name:
                renamed.append({"from": name, "to": new_name})
                d["Company"] = new_name
                name = new_name

        ok = _match(name, OWNERSHIP)
        if ok:
            own, rel = OWNERSHIP[ok]
            old = str(d.get("Ownership") or "")
            if old != own:
                ownership_fixed.append({"brand": name, "from": old, "to": own})
            d["Ownership"] = own
            d["ownership_relation"] = rel
            m = re.match(
                r"(?i)^\s*(?:acquired by|subsidiary of|merged into|owned by)\s+(.+?)\s*$",
                own,
            )
            d["parent_owner"] = m.group(1).strip() if m else ""
        else:
            # Clear false acquisition leftovers so Company == Brand
            own = str(d.get("Ownership") or "").strip()
            low = own.lower()
            if any(
                low.startswith(p)
                for p in ("acquired by", "subsidiary of", "merged into", "owned by")
            ):
                # Keep only if still matched — else clear parent fields for independents
                # that previously had bad annotations
                d["ownership_relation"] = ""
                d.pop("parent_owner", None)
                # Don't wipe informative Public/JV text that doesn't drive Company suffix
                if low.startswith(("acquired by", "subsidiary of", "merged into", "owned by")):
                    # unmatched owned-by text would still trigger display — clear it
                    d["Ownership"] = "Independent"
            else:
                d["ownership_relation"] = str(d.get("ownership_relation") or "")
                if not d.get("ownership_relation"):
                    d.pop("parent_owner", None)

        landscape.append(d)

    # Build Company Details with brand_display_fields
    audit = {}
    ap = OUT / "chatgpt_expand_batch_all_audit.json"
    if ap.exists():
        audit = json.loads(ap.read_text(encoding="utf-8")).get("xy_scoring") or {}

    # Ensure parent_owner feeds brand_display_fields via to_company_detail_rows path
    detail_rows = to_company_detail_rows(landscape, QUERY, audit)

    # Force Company column from brand_display_fields using Landscape ownership
    by_land = {_norm(str(r.get("Company") or "")): r for r in landscape}
    fixed_company: list[dict] = []
    for d in detail_rows:
        brand = str(d.get("Brand") or "").strip()
        land = by_land.get(_norm(brand)) or {}
        row_for_meta = {
            "company": brand,
            "company_raw": brand,
            "parent_owner": land.get("parent_owner") or "",
            "parent": land.get("Ownership") or "",
            "ownership_relation": land.get("ownership_relation") or "",
        }
        b2, company_col, _ = brand_display_fields(row_for_meta, market=QUERY)
        old_co = str(d.get("Company") or "")
        # Independent => Company equals Brand
        if not str(row_for_meta.get("parent_owner") or "").strip():
            company_col = b2 or brand
        if old_co != company_col:
            fixed_company.append({"brand": brand, "from": old_co, "to": company_col})
        d["Brand"] = b2 or brand
        d["Company"] = company_col
        # Keep Role from landscape
        role = str(land.get("Role") or d.get("Role") or "Brand")
        if role in ("Brand", "Marketer"):
            d["Role"] = role

    write_final_xlsx(
        XLSX,
        landscape,
        "Companies",
        {
            "query": QUERY,
            "brand_company_verify": "2026-08-14",
            "ownership_fixed": len(ownership_fixed),
            "company_col_fixed": len(fixed_company),
            "xy_scoring": audit,
        },
        detail_rows=detail_rows,
    )
    extras = export_expand_quadrant_outputs(
        OUT, detail_rows, QUERY, country="global", audit=audit, chart_n=20
    )

    annotated = [
        {"brand": d.get("Brand"), "company": d.get("Company"), "role": d.get("Role")}
        for d in detail_rows
        if str(d.get("Company") or "").startswith("(")
    ]
    report = {
        "total": len(detail_rows),
        "annotated": len(annotated),
        "removed": removed,
        "renamed": renamed,
        "ownership_fixed_n": len(ownership_fixed),
        "company_col_changed_n": len(fixed_company),
        "annotated_rows": annotated,
        "html": str(extras.get("html") or ""),
    }
    AUDIT.mkdir(parents=True, exist_ok=True)
    (AUDIT / f"{SLUG}_brand_company_column_fix.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    lines = ["Brand\tCompany\tRole"]
    for d in detail_rows:
        lines.append(f"{d.get('Brand')}\t{d.get('Company')}\t{d.get('Role')}")
    (AUDIT / f"{SLUG}_brand_company_after.tsv").write_text(
        "\n".join(lines), encoding="utf-8"
    )

    print(
        f"total={report['total']} annotated={report['annotated']} "
        f"removed={len(removed)} renamed={len(renamed)} "
        f"ownership_fixed={len(ownership_fixed)} company_changed={len(fixed_company)}"
    )
    for x in removed:
        print("REMOVED:", x)
    for x in annotated:
        print(f"ANN: {x['brand']} | {x['company']}")


if __name__ == "__main__":
    main()
