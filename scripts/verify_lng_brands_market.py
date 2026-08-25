#!/usr/bin/env python3
"""Verify every Brand belongs in Global LNG market; drop non-LNG; top up to 200+.

KEEP: liquefaction/export, import terminals/FSRUs, LNG shippers, LNG traders/marketers,
      NOCs/IOCs/utilities with material LNG production, offtake, or terminal role.
DROP: LPG-only, pure upstream E&P with no LNG role, refining-only, steel-only,
      acquired shells when successor already listed, regional clones, vague duplicates.
No hallucinated drops — stems below are web-checked Aug 2026.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from openpyxl import load_workbook

from vendor_intel.pipeline.chatgpt_env import apply_chatgpt_expand_env, deepseek_chat_config
from vendor_intel.pipeline.expand_quadrant_score import (
    export_expand_quadrant_outputs,
    score_expand_rows,
    to_company_detail_rows,
)
from vendor_intel.pipeline.web_expand import write_final_xlsx

SLUG = "global_liquefied_natural_gas_market_global"
QUERY = "Global Liquefied Natural Gas Market"
OUT = ROOT / "output" / "chatgpt_expand" / SLUG
XLSX = OUT / f"{SLUG}_FINAL.xlsx"
AUDIT = ROOT / "output" / "chatgpt_expand" / "_audit"
INDUSTRY = "Energy / Liquefied Natural Gas"
TARGET_MIN = 200

# Same verified Marketer stems as scripts/verify_lng_roles.py
MARKETER_STEMS = {
    "vitol",
    "gunvor",
    "trafigura",
    "mercuria",
    "glencore",
    "castleton commodities",
    "hartree partners",
    "freepoint commodities",
    "bb energy",
    "pavilion energy",
    "qatarenergy trading",
    "lng japan",
    "sk gas trading",
    "ptt global lng",
    "mitsubishi corporation",
    "mitsui co",
    "marubeni",
    "itochu",
    "sumitomo corporation",
    "sojitz",
    "litasco",
}

# Web-verified NOT in global LNG Brand/Marketer landscape
DROP_STEMS: dict[str, str] = {
    "altagas": "LPG/propane export (RIPET/REEF) — not LNG",
    "apa corporation": "US E&P (ex-Apache) — no LNG liquefaction/trade brand",
    "anadarko petroleum": "acquired shell (Occidental 2019) — not active LNG brand",
    "wintershall dea": "E&P portfolio sold to Harbour Energy — residual shell",
    "qatargas operating": "merged/rebranded into QatarEnergy LNG — duplicate",
    "repsol sinopec brasil": "Brazil E&P JV — not LNG",
    "posco": "steelmaker; POSCO International already covers LNG-related arm",
    "kuwait national petroleum": "refining (KNPC) — KPC already listed for NOC LNG",
    "tellurian": "acquired by Woodside; Woodside Louisiana LNG already listed",
    "equinor uk": "regional subsidiary — Equinor ASA already listed",
    "trinidad and tobago lng": "vague label — Atlantic LNG already listed",
    "gujarat state petronet": "India gas transmission (GSPL) — not LNG terminal/trader",
    "korea national oil": "KNOC E&P — KOGAS is Korea’s LNG importer (already listed)",
    "petroperu": "Peru NOC — Peru LNG project company already listed",
    "petroper": "Peru NOC — Peru LNG project company already listed",
    "compania de petroleos de chile": "COPEC fuel retail — GNL Quintero already listed",
    "copec": "COPEC fuel retail — GNL Quintero already listed",
    "petronas lng": "duplicate marketing label — Petronas + MLNG already listed",
    "senex energy": "Surat Basin gas producer (feedstock) — not LNG operator/trader",
    "pakistan": "excluded per user",
}

# Prefer one when both present
DEDUP_DROP_IF_OTHER = {
    "texas lng brownsville": "texas lng",  # same Glenfarne Brownsville project family
}

# Verified LNG adds if count slips under TARGET_MIN
NEW_LNG: list[dict] = [
    {"Company": "Calcasieu Pass LNG", "Role": "Brand", "Website": "https://ventureglobal.com/calcasieu-pass/", "Headquarters": "Cameron Parish, Louisiana, United States", "Ownership": "subsidiary of Venture Global LNG", "Founded": "2019", "Specialty Focus": "US LNG liquefaction export", "Summary": "Venture Global’s operating Calcasieu Pass LNG export facility in Louisiana."},
    {"Company": "CP2 LNG", "Role": "Brand", "Website": "https://ventureglobal.com", "Headquarters": "Cameron Parish, Louisiana, United States", "Ownership": "subsidiary of Venture Global LNG", "Founded": "2022", "Specialty Focus": "US LNG liquefaction development", "Summary": "Venture Global’s CP2 LNG export project on the US Gulf Coast."},
    {"Company": "Arctic LNG 2", "Role": "Brand", "Website": "https://www.novatek.ru", "Headquarters": "Gydan Peninsula, Russia", "Ownership": "Novatek-led consortium", "Founded": "2019", "Specialty Focus": "Arctic LNG liquefaction", "Summary": "Novatek-led Arctic LNG 2 liquefaction project on the Gydan Peninsula."},
    {"Company": "Hunt Oil Company", "Role": "Brand", "Website": "https://www.huntoil.com", "Headquarters": "Dallas, Texas, United States", "Ownership": "Private", "Founded": "1934", "Specialty Focus": "Peru LNG operator/partner", "Summary": "Private US E&P; lead partner/operator interests in Peru LNG."},
    {"Company": "OMV", "Role": "Brand", "Website": "https://www.omv.com", "Headquarters": "Vienna, Austria", "Ownership": "Public", "Founded": "1956", "Specialty Focus": "European gas/LNG portfolio", "Summary": "Austrian integrated energy company with European gas and LNG supply portfolio."},
    {"Company": "Litasco", "Role": "Marketer", "Website": "https://www.litasco.com", "Headquarters": "Geneva, Switzerland", "Ownership": "subsidiary of Rosneft", "Founded": "2000", "Specialty Focus": "Oil & LNG trading", "Summary": "Rosneft’s international trading arm active in oil products and LNG marketing."},
    {"Company": "Qalhat LNG", "Role": "Brand", "Website": "https://www.omanlng.com", "Headquarters": "Qalhat, Oman", "Ownership": "Oman LNG related complex", "Founded": "2005", "Specialty Focus": "Oman LNG liquefaction trains", "Summary": "Qalhat LNG liquefaction complex associated with Oman’s LNG industry."},
    {"Company": "First Gen Corporation", "Role": "Brand", "Website": "https://www.firstgen.com.ph", "Headquarters": "Pasig, Philippines", "Ownership": "Public (Lopez Group)", "Founded": "1993", "Specialty Focus": "Philippines LNG import / power", "Summary": "Philippine energy company developing LNG import for gas-fired power."},
    {"Company": "Puma Energy", "Role": "Brand", "Website": "https://www.pumaenergy.com", "Headquarters": "Singapore", "Ownership": "Private (Trafigura-related historically)", "Founded": "1997", "Specialty Focus": "Weak — skip"},
]

NEW_LNG = [c for c in NEW_LNG if c.get("Company") and "skip" not in str(c.get("Specialty Focus") or "").lower()]


def _norm(s: str) -> str:
    s = str(s or "").strip().lower()
    s = (
        s.replace("ö", "o")
        .replace("ü", "u")
        .replace("ä", "a")
        .replace("ú", "u")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ñ", "n")
        .replace("ß", "ss")
    )
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def role_classify(name: str) -> tuple[str, str]:
    n = _norm(name)
    best = None
    best_len = -1
    for stem in MARKETER_STEMS:
        sn = _norm(stem)
        if sn in n and len(sn) > best_len:
            best = stem
            best_len = len(sn)
    if best:
        return "Marketer", best
    return "Brand", "default"


def _drop_reason(name: str) -> str | None:
    n = _norm(name)
    if "pakistan" in n:
        return DROP_STEMS["pakistan"]
    # POSCO exact: drop plain POSCO but not POSCO International
    if n == "posco" or (n.startswith("posco ") and "international" not in n):
        return DROP_STEMS["posco"]
    best = None
    best_len = -1
    for stem, reason in DROP_STEMS.items():
        if stem == "posco":
            continue
        if stem in n and len(stem) > best_len:
            best = reason
            best_len = len(stem)
    return best


def _blank(seed: dict) -> dict:
    role = seed.get("Role") or "Brand"
    # re-check marketer stems
    r2, _ = role_classify(seed["Company"])
    if r2 == "Marketer":
        role = "Marketer"
    row = {
        "Company": seed["Company"],
        "Website": seed.get("Website") or "",
        "Founded": seed.get("Founded") or "",
        "Headquarters": seed.get("Headquarters") or "",
        "Continent / Geography": "",
        "Operational Presence": "",
        "Ownership": seed.get("Ownership") or "",
        "Employees": "",
        "Core Categories": "Liquefied Natural Gas",
        "Specialty Focus": seed.get("Specialty Focus") or "LNG",
        "Key Brands Represented": seed["Company"],
        "Retail / E-commerce / Both": "N/A",
        "Distribution Type": role,
        "Contact Person": "",
        "Role": role,
        "Email": "",
        "LinkedIn": "",
        "Office No.": "",
        "Country Code": "",
        "Region Code": "",
        "Summary": seed.get("Summary") or "",
        "Industry Category": INDUSTRY,
    }
    own = str(row["Ownership"] or "").lower()
    if own.startswith("subsidiary of"):
        row["ownership_relation"] = "subsidiary_of"
        row["parent_owner"] = row["Ownership"][14:].strip()
    elif own.startswith("acquired by"):
        row["ownership_relation"] = "acquired_by"
        row["parent_owner"] = row["Ownership"][11:].strip()
    return row


async def _fill(rows: list[dict]) -> list[dict]:
    key, base, model = deepseek_chat_config()
    if not key or not rows:
        return rows
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=key, base_url=base)
    out = []
    for i in range(0, len(rows), 8):
        batch = rows[i : i + 8]
        names = [str(r.get("Company") or "") for r in batch]
        prompt = (
            "Fill Global LNG landscape fields. JSON array keys: company, website, founded, "
            "headquarters, continent_geography, operational_presence, ownership, "
            "specialty_focus, summary, country_code. Facts only; empty if unknown.\n"
            f"Companies: {json.dumps(names)}"
        )
        try:
            resp = await client.chat.completions.create(
                model=model,
                temperature=0.1,
                messages=[
                    {"role": "system", "content": "Return only valid JSON array."},
                    {"role": "user", "content": prompt},
                ],
            )
            text = (resp.choices[0].message.content or "").strip()
            if text.startswith("```"):
                text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I | re.S)
            data = json.loads(text)
            by = {_norm(x.get("company") or ""): x for x in data if isinstance(x, dict)}
        except Exception as e:
            print("fill fail", e, flush=True)
            by = {}
        for r in batch:
            x = by.get(_norm(r.get("Company") or ""), {})
            for dst, src in (
                ("Website", "website"),
                ("Founded", "founded"),
                ("Headquarters", "headquarters"),
                ("Continent / Geography", "continent_geography"),
                ("Operational Presence", "operational_presence"),
                ("Ownership", "ownership"),
                ("Specialty Focus", "specialty_focus"),
                ("Summary", "summary"),
                ("Country Code", "country_code"),
            ):
                val = str(x.get(src) or "").strip()
                if val and not str(r.get(dst) or "").strip():
                    r[dst] = val
            out.append(r)
    return out


async def main() -> int:
    apply_chatgpt_expand_env(root=ROOT)
    os.environ["EXPAND_XY_SKIP_CRAWL"] = "1"
    os.environ["EXPAND_MARKET_AXIS_LLM"] = "1"

    wb = load_workbook(XLSX, data_only=True)
    ws = wb["Landscape"]
    rows_raw = list(ws.iter_rows(values_only=True))
    hdr = [str(h) for h in rows_raw[0]]

    kept: list[dict] = []
    removed: list[dict] = []
    existing: set[str] = set()

    for r in rows_raw[1:]:
        d = {hdr[i]: ("" if r[i] is None else r[i]) for i in range(len(hdr)) if i < len(r)}
        name = str(d.get("Company") or "").strip()
        if not name:
            continue
        reason = _drop_reason(name)
        if reason:
            removed.append({"brand": name, "reason": reason})
            continue
        # role re-assert
        role, _ = role_classify(name)
        d["Role"] = role
        d["Distribution Type"] = role
        d["Industry Category"] = INDUSTRY
        d["Retail / E-commerce / Both"] = "N/A"
        kept.append(d)
        existing.add(_norm(name))

    # Dedup pairs
    final = []
    norms = {_norm(str(r.get("Company") or "")) for r in kept}
    for r in kept:
        n = _norm(str(r.get("Company") or ""))
        drop = False
        for a, b in DEDUP_DROP_IF_OTHER.items():
            if a in n and any(b == e or b in e for e in norms):
                # if the preferred exists as exact-ish, drop this
                if any(e == b or e.startswith(b) for e in norms if e != n):
                    removed.append(
                        {
                            "brand": r.get("Company"),
                            "reason": f"duplicate_of:{b}",
                        }
                    )
                    drop = True
                    break
        if not drop:
            final.append(r)
    kept = final
    existing = {_norm(str(r.get("Company") or "")) for r in kept}

    print(f"after drop kept={len(kept)} removed={len(removed)}", flush=True)

    # Top up
    to_add = []
    for c in NEW_LNG:
        key = _norm(c["Company"])
        if key in existing:
            continue
        if _drop_reason(c["Company"]):
            continue
        to_add.append(c)
        existing.add(key)
        if len(kept) + len(to_add) >= TARGET_MIN + 5:
            break

    new_rows: list[dict] = []
    if to_add:
        print(f"adding {len(to_add)} verified LNG companies", flush=True)
        new_rows = [_blank(s) for s in to_add]
        new_rows = await _fill(new_rows)
        scored, _ = await score_expand_rows(new_rows, QUERY, country="global")
        new_rows = scored or new_rows

    landscape = kept + new_rows
    # Final pakistan sweep
    clean = []
    for r in landscape:
        if "pakistan" in _norm(f"{r.get('Company')} {r.get('Headquarters')}"):
            removed.append({"brand": r.get("Company"), "reason": "pakistan"})
            continue
        role, _ = role_classify(str(r.get("Company") or ""))
        # preserve Marketer if already set from prior verify and still in stems
        cur = str(r.get("Role") or role)
        if cur not in ("Brand", "Marketer"):
            cur = role
        # if classify says Marketer, force it
        if role == "Marketer":
            cur = "Marketer"
        r["Role"] = cur
        r["Distribution Type"] = cur
        clean.append(r)
    landscape = clean

    brand_n = sum(1 for r in landscape if r["Role"] == "Brand")
    marketer_n = sum(1 for r in landscape if r["Role"] == "Marketer")

    audit = {}
    ap = OUT / "chatgpt_expand_batch_all_audit.json"
    if ap.exists():
        audit = json.loads(ap.read_text(encoding="utf-8")).get("xy_scoring") or {}
    details = to_company_detail_rows(landscape, QUERY, audit)
    by = {_norm(str(r.get("Company") or "")): str(r.get("Role") or "Brand") for r in landscape}
    for d in details:
        role = by.get(_norm(d.get("Brand") or ""))
        if role in ("Brand", "Marketer"):
            d["Role"] = role

    write_final_xlsx(
        XLSX,
        landscape,
        "Companies",
        {
            "query": QUERY,
            "brand_market_verify": "2026-08-14",
            "removed": len(removed),
            "added": len(new_rows),
            "brand": brand_n,
            "marketer": marketer_n,
            "xy_scoring": audit,
        },
        detail_rows=details,
    )
    extras = export_expand_quadrant_outputs(
        OUT, details, QUERY, country="global", audit=audit, chart_n=20
    )

    report = {
        "before": len(rows_raw) - 1,
        "after": len(landscape),
        "removed": removed,
        "added": [r.get("Company") for r in new_rows],
        "brand": brand_n,
        "marketer": marketer_n,
        "html": str(extras.get("html") or ""),
    }
    AUDIT.mkdir(parents=True, exist_ok=True)
    (AUDIT / f"{SLUG}_brand_market_verify.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(
        f"before={report['before']} after={report['after']} "
        f"Brand={brand_n} Marketer={marketer_n} removed={len(removed)} added={len(new_rows)}"
    )
    for x in removed:
        print(f"DROP: {x['brand']} — {x['reason']}")
    for a in report["added"]:
        print(f"ADD: {a}")
    return 0


if __name__ == "__main__":
    # allow importing classify from verify_lng_roles
    raise SystemExit(asyncio.run(main()))
