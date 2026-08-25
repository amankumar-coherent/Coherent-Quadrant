#!/usr/bin/env python3
"""Dump Brand/Marketer rows for audit."""
from pathlib import Path
from openpyxl import load_workbook

p = Path("output/chatgpt_expand/global_wearable_medical_devices_market_global/global_wearable_medical_devices_market_global_FINAL.xlsx")
wb = load_workbook(p, data_only=True)
lws = wb["Landscape"]
lrows = list(lws.iter_rows(values_only=True))
lhdr = [str(h) for h in lrows[0]]

out = Path("output/chatgpt_expand/_audit/wearable_full_role_dump.tsv")
lines = ["role\tbrand\tcompany\tspecialty\tcategories\twebsite\townership"]
for r in lrows[1:]:
    if not r:
        continue
    d = {lhdr[i]: ("" if r[i] is None else str(r[i])) for i in range(len(lhdr)) if i < len(r)}
    brand = d.get("Brand") or d.get("Company") or ""
    role = d.get("Role") or ""
    lines.append(
        "\t".join(
            [
                role,
                brand,
                d.get("Company") or "",
                (d.get("Specialty Focus") or "").replace("\t", " ").replace("\n", " "),
                (d.get("Core Categories") or "").replace("\t", " "),
                d.get("Website") or "",
                (d.get("Ownership") or "").replace("\t", " "),
            ]
        )
    )

# Prefer Company Details for Brand + Company ownership suffix
if "Company Details" in wb.sheetnames:
    dws = wb["Company Details"]
    drows = list(dws.iter_rows(values_only=True))
    dhdr = [str(h) for h in drows[0]]
    lines2 = ["role\tbrand\tcompany_display\tx\ty\toverall\tquadrant"]
    for r in drows[1:]:
        if not r:
            continue
        d = {dhdr[i]: ("" if r[i] is None else str(r[i])) for i in range(len(dhdr)) if i < len(r)}
        lines2.append(
            "\t".join(
                [
                    d.get("Role") or "",
                    d.get("Brand") or "",
                    (d.get("Company") or "").replace("\t", " "),
                    str(d.get("X") or ""),
                    str(d.get("Y") or ""),
                    str(d.get("Overall") or ""),
                    d.get("Quadrant") or "",
                ]
            )
        )
    out2 = Path("output/chatgpt_expand/_audit/wearable_company_details_dump.tsv")
    out2.write_text("\n".join(lines2), encoding="utf-8")
    print(f"wrote {out2} ({len(lines2)-1})")

out.write_text("\n".join(lines), encoding="utf-8")
print(f"wrote {out} ({len(lines)-1})")
from collections import Counter
roles = Counter(l.split("\t")[0] for l in lines[1:])
print(dict(roles))
