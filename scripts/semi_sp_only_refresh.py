#!/usr/bin/env python3
"""Keep only semiconductor Solution Providers; remove misfits; add verified SPs to >=200.

Fills Landscape columns from web-verified seed data + DeepSeek gap fill.
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

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from openpyxl import load_workbook

from vendor_intel.placeholders.load_keys import apply_env_overrides
from vendor_intel.pipeline.chatgpt_env import apply_chatgpt_expand_env, deepseek_chat_config
from vendor_intel.pipeline.expand_quadrant_score import (
    export_expand_quadrant_outputs,
    score_expand_rows,
    to_company_detail_rows,
)
from vendor_intel.pipeline.web_expand import write_final_xlsx

OUT = ROOT / "output" / "chatgpt_expand"
SLUG = "global_semiconductor_market_global"
QUERY = "Global Semiconductor Market"
FOLDER = OUT / SLUG
INDUSTRY = "ICT, Automation, Semiconductor / Semiconductors"
TARGET_MIN = 200

# Not semiconductor Solution Providers (OEM / conglomerate / passives / EMS / residual).
REMOVE = {
    "apple",
    "robert bosch gmbh",
    "cyient",
    "western digital",
    "murata manufacturing",
    "samsung electro-mechanics",
    "tdk corporation",
    "polymatech electronics",
    "ineda systems",
}

# Web-verified semiconductor Solution Providers to add (not already in FINAL).
# Ownership/parent notes applied later via apply_semi_brand_company where mapped.
NEW: list[dict] = [
    {
        "company": "Intel Corporation",
        "website": "https://www.intel.com",
        "founded": "1968",
        "hq": "Santa Clara, California, USA",
        "country": "US",
        "region": "NA",
        "continent": "NA(United States)",
        "presence": "United States; Europe; Asia; Middle East",
        "employees": "100000+",
        "ownership": "Public",
        "categories": "CPU; GPU; Foundry; AI accelerators; Chipsets",
        "specialty": "IDM designing and manufacturing CPUs, GPUs, foundry and AI accelerators.",
        "summary": "Intel is a leading semiconductor IDM providing CPUs, accelerators, chipsets and foundry services worldwide.",
    },
    {
        "company": "Sony Semiconductor Solutions",
        "website": "https://www.sony-semicon.com",
        "founded": "2015",
        "hq": "Atsugi, Kanagawa, Japan",
        "country": "JP",
        "region": "APAC",
        "continent": "APAC(Japan)",
        "presence": "Japan; Global",
        "employees": "8000+",
        "ownership": "Subsidiary of Sony Group",
        "categories": "Image sensors; CMOS; Sensing",
        "specialty": "World-leading CMOS image sensors and sensing devices for mobile and automotive.",
        "summary": "Sony Semiconductor Solutions designs and manufactures CMOS image sensors and related semiconductor devices.",
    },
    {
        "company": "Rohm Semiconductor",
        "website": "https://www.rohm.com",
        "founded": "1958",
        "hq": "Kyoto, Japan",
        "country": "JP",
        "region": "APAC",
        "continent": "APAC(Japan)",
        "presence": "Japan; Asia; Americas; Europe",
        "employees": "23000+",
        "ownership": "Public",
        "categories": "Power; Analog; SiC; Discrete",
        "specialty": "Power and analog semiconductors including SiC devices for automotive and industrial.",
        "summary": "ROHM designs and manufactures power, analog and SiC semiconductors for automotive and industrial markets.",
    },
    {
        "company": "Melexis",
        "website": "https://www.melexis.com",
        "founded": "1988",
        "hq": "Ieper, Belgium",
        "country": "BE",
        "region": "EMEA",
        "continent": "EMEA(Belgium)",
        "presence": "Belgium; Europe; Asia; Americas",
        "employees": "2000+",
        "ownership": "Public",
        "categories": "Automotive sensors; Drivers; Mixed-signal",
        "specialty": "Automotive sensor and driver ICs for safer, greener vehicles.",
        "summary": "Melexis engineers automotive sensor and driver semiconductor solutions for mobility applications.",
    },
    {
        "company": "Vishay Intertechnology",
        "website": "https://www.vishay.com",
        "founded": "1962",
        "hq": "Malvern, Pennsylvania, USA",
        "country": "US",
        "region": "NA",
        "continent": "NA(United States)",
        "presence": "United States; Europe; Asia",
        "employees": "20000+",
        "ownership": "Public",
        "categories": "Discrete; Optoelectronics; Power; Passives",
        "specialty": "Discrete semiconductors and passive electronic components for power and signal applications.",
        "summary": "Vishay manufactures discrete semiconductors and passive components used across industrial and automotive electronics.",
    },
    {
        "company": "Socionext",
        "website": "https://www.socionext.com",
        "founded": "2015",
        "hq": "Yokohama, Japan",
        "country": "JP",
        "region": "APAC",
        "continent": "APAC(Japan)",
        "presence": "Japan; United States; Europe; Asia",
        "employees": "2500+",
        "ownership": "Public",
        "categories": "Custom SoC; ASIC; Solution SoC",
        "specialty": "Fabless custom / Solution SoC design for automotive, data center and industrial.",
        "summary": "Socionext provides custom and Solution SoC semiconductor design for automotive, networking and industrial customers.",
    },
    {
        "company": "Hua Hong Semiconductor",
        "website": "https://www.huahonggrace.com",
        "founded": "1996",
        "hq": "Shanghai, China",
        "country": "CN",
        "region": "APAC",
        "continent": "APAC(China)",
        "presence": "China",
        "employees": "6000+",
        "ownership": "Public",
        "categories": "Foundry; Specialty process",
        "specialty": "Specialty foundry for power, embedded non-volatile memory and RF processes.",
        "summary": "Hua Hong Semiconductor operates specialty CMOS foundry capacity serving power, eNVM and RF customers.",
    },
    {
        "company": "Pragmatic Semiconductor",
        "website": "https://www.pragmaticsemi.com",
        "founded": "2010",
        "hq": "Cambridge, United Kingdom",
        "country": "GB",
        "region": "EMEA",
        "continent": "EMEA(United Kingdom)",
        "presence": "United Kingdom; Europe",
        "employees": "300+",
        "ownership": "Private",
        "categories": "Flexible semiconductors; Foundry",
        "specialty": "Flexible semiconductor technology and foundry for ultra-low-cost flexICs.",
        "summary": "Pragmatic Semiconductor pioneers flexible chip technology and manufacturing for IoT and ubiquitous electronics.",
    },
    {
        "company": "XMOS",
        "website": "https://www.xmos.com",
        "founded": "2005",
        "hq": "Bristol, United Kingdom",
        "country": "GB",
        "region": "EMEA",
        "continent": "EMEA(United Kingdom)",
        "presence": "United Kingdom; United States; Asia",
        "employees": "100+",
        "ownership": "Private",
        "categories": "Multicore SoC; Voice; Edge AI",
        "specialty": "xcore generative / real-time SoCs for voice, audio, DSP and physical AI.",
        "summary": "XMOS designs deterministic multicore SoCs for voice, audio and real-time edge applications.",
    },
    {
        "company": "Alpha and Omega Semiconductor",
        "website": "https://www.aosmd.com",
        "founded": "2000",
        "hq": "Sunnyvale, California, USA",
        "country": "US",
        "region": "NA",
        "continent": "NA(United States)",
        "presence": "United States; Asia",
        "employees": "2000+",
        "ownership": "Public",
        "categories": "Power MOSFET; IGBT; Power IC; GaN",
        "specialty": "Power semiconductors including MOSFETs, IGBTs, IPMs and power ICs.",
        "summary": "Alpha and Omega Semiconductor designs and supplies power MOSFETs, IGBTs and power management ICs.",
    },
    {
        "company": "WIN Semiconductors",
        "website": "https://www.winsemiconductorscorp.com",
        "founded": "1999",
        "hq": "Taoyuan, Taiwan",
        "country": "TW",
        "region": "APAC",
        "continent": "APAC(Taiwan)",
        "presence": "Taiwan; Global",
        "employees": "3000+",
        "ownership": "Public",
        "categories": "GaAs foundry; RF; Compound semiconductors",
        "specialty": "Pure-play GaAs / compound semiconductor foundry for RF and mmWave MMICs.",
        "summary": "WIN Semiconductors is a leading pure-play GaAs foundry serving RF and compound semiconductor customers.",
    },
    {
        "company": "Silergy",
        "website": "https://www.silergy.com",
        "founded": "2008",
        "hq": "Hangzhou, China",
        "country": "CN",
        "region": "APAC",
        "continent": "APAC(China)",
        "presence": "China; United States; Europe; Asia",
        "employees": "3000+",
        "ownership": "Public",
        "categories": "Power management; Analog; Signal chain",
        "specialty": "Analog and power-management ICs for consumer, industrial and automotive.",
        "summary": "Silergy designs analog and power-management semiconductor solutions for global electronics markets.",
    },
    {
        "company": "CEITEC S.A.",
        "website": "https://www.ceitec-sa.com",
        "founded": "2008",
        "hq": "Porto Alegre, Brazil",
        "country": "BR",
        "region": "LATAM",
        "continent": "LATAM(Brazil)",
        "presence": "Brazil",
        "employees": "200+",
        "ownership": "Public / Government-linked",
        "categories": "ASIC; RFID; Design services",
        "specialty": "Brazilian semiconductor design company for RFID, smart cards and ASICs.",
        "summary": "CEITEC designs and supplies semiconductor chips and ASICs with a focus on RFID and secure applications in Brazil.",
    },
    {
        "company": "Chipus Microelectronics",
        "website": "https://www.chipus.com.br",
        "founded": "2008",
        "hq": "Florianópolis, Brazil",
        "country": "BR",
        "region": "LATAM",
        "continent": "LATAM(Brazil)",
        "presence": "Brazil; Latin America",
        "employees": "50+",
        "ownership": "Private",
        "categories": "Analog IP; ASIC design",
        "specialty": "Analog and mixed-signal IP and ASIC design services.",
        "summary": "Chipus Microelectronics provides analog/mixed-signal IP and custom ASIC design services.",
    },
    {
        "company": "Tokyo Ohka Kogyo (TOK)",
        "website": "https://www.tok.co.jp",
        "founded": "1940",
        "hq": "Kawasaki, Japan",
        "country": "JP",
        "region": "APAC",
        "continent": "APAC(Japan)",
        "presence": "Japan; Global",
        "employees": "1800+",
        "ownership": "Public",
        "categories": "Photoresist; Process materials",
        "specialty": "Photoresists and process materials for semiconductor lithography.",
        "summary": "Tokyo Ohka Kogyo supplies photoresists and high-purity process materials used in semiconductor manufacturing.",
    },
    {
        "company": "Sanan Optoelectronics",
        "website": "https://www.sanan-e.com",
        "founded": "2000",
        "hq": "Xiamen, China",
        "country": "CN",
        "region": "APAC",
        "continent": "APAC(China)",
        "presence": "China; Global",
        "employees": "10000+",
        "ownership": "Public",
        "categories": "LED; Compound semiconductors; SiC/GaN epi",
        "specialty": "Compound semiconductor materials and devices including LED and wide-bandgap epi.",
        "summary": "Sanan Optoelectronics manufactures compound semiconductor materials and optoelectronic devices.",
    },
    {
        "company": "Nexchip",
        "website": "https://www.nexchip.com.cn",
        "founded": "2015",
        "hq": "Hefei, China",
        "country": "CN",
        "region": "APAC",
        "continent": "APAC(China)",
        "presence": "China",
        "employees": "3000+",
        "ownership": "Private / Public-affiliated",
        "categories": "Foundry; Display driver; Specialty CMOS",
        "specialty": "Foundry focused on display driver and specialty CMOS processes.",
        "summary": "Nexchip operates semiconductor foundry capacity specializing in display-related and specialty CMOS processes.",
    },
]


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


def _row_from_candidate(c: dict) -> dict:
    name = c["company"]
    hq = c.get("hq") or ""
    return {
        "Company": name,
        "Website": c.get("website") or "",
        "Founded": c.get("founded") or "",
        "Headquarters": hq,
        "Continent / Geography": c.get("continent") or "",
        "Operational Presence": c.get("presence") or "",
        "Ownership": c.get("ownership") or "",
        "Employees": c.get("employees") or "",
        "Core Categories": c.get("categories") or "",
        "Specialty Focus": c.get("specialty") or "",
        "Key Brands Represented": name,
        "Retail / E-commerce / Both": "No",
        "Distribution Type": "Solution Provider",
        "Contact Person": "",
        "Role": "Solution Provider",
        "Email": "",
        "LinkedIn": "",
        "Office No.": "",
        "Country Code": c.get("country") or "",
        "Region Code": c.get("region") or "",
        "Summary": c.get("summary")
        or f"{name} — semiconductor Solution Provider. {c.get('specialty') or ''}".strip(),
        "X Score": "",
        "Y Score": "",
        "Overall Score": "",
        "Quadrant": "",
        "Industry Category": INDUSTRY,
        "Brand": name,
        "Found in": hq,
    }


async def _deepseek_enrich(row: dict) -> dict:
    """Fill blank landscape fields via DeepSeek using known seed facts."""
    apply_chatgpt_expand_env(root=ROOT)
    api_key, base_url, model = deepseek_chat_config()
    if not api_key:
        return row
    if not base_url.endswith("/v1"):
        base_url = base_url.rstrip("/") + "/v1"

    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    seed = {
        "company": row.get("Company"),
        "website": row.get("Website"),
        "founded": row.get("Founded"),
        "hq": row.get("Headquarters"),
        "presence": row.get("Operational Presence"),
        "categories": row.get("Core Categories"),
        "specialty": row.get("Specialty Focus"),
        "ownership": row.get("Ownership"),
        "employees": row.get("Employees"),
        "summary": row.get("Summary"),
    }
    prompt = (
        "You enrich semiconductor Solution Provider landscape rows. "
        "Use ONLY the seed facts below plus widely known public facts about THIS company. "
        "Do not invent contacts, emails, phones, or LinkedIn. "
        "Return JSON keys: founded_year, headquarters, employees, ownership, "
        "core_categories, specialty_focus, operational_presence, summary, "
        "continent_geography, country_code, region_code. "
        "country_code = ISO2; region_code = NA|EMEA|APAC|LATAM|MEA. "
        "continent_geography like 'NA(United States)' or 'APAC(Taiwan)'. "
        "Role is always Solution Provider. Empty string if unknown.\n\n"
        f"SEED:\n{json.dumps(seed, ensure_ascii=False)}"
    )
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0,
        )
        text = (resp.choices[0].message.content or "").strip()
        data = json.loads(text) if text else {}
    except Exception as exc:
        print(f"  [deepseek] enrich fail {row.get('Company')}: {exc}")
        return row

    def _set(col: str, val: object) -> None:
        if val is None:
            return
        s = str(val).strip()
        if not s:
            return
        if not str(row.get(col) or "").strip():
            row[col] = s

    _set("Founded", data.get("founded_year"))
    _set("Headquarters", data.get("headquarters"))
    _set("Found in", data.get("headquarters"))
    _set("Employees", data.get("employees"))
    _set("Ownership", data.get("ownership"))
    _set("Core Categories", data.get("core_categories"))
    _set("Specialty Focus", data.get("specialty_focus"))
    _set("Operational Presence", data.get("operational_presence"))
    _set("Summary", data.get("summary"))
    _set("Continent / Geography", data.get("continent_geography"))
    _set("Country Code", data.get("country_code"))
    _set("Region Code", data.get("region_code"))
    row["Role"] = "Solution Provider"
    row["Distribution Type"] = "Solution Provider"
    row["Retail / E-commerce / Both"] = row.get("Retail / E-commerce / Both") or "No"
    return row


def _load_landscape(xlsx: Path) -> list[dict]:
    wb = load_workbook(xlsx, data_only=True)
    ws = wb["Landscape"]
    rows_raw = list(ws.iter_rows(values_only=True))
    hdr = [str(h) for h in rows_raw[0]]
    out: list[dict] = []
    for r in rows_raw[1:]:
        if not r:
            continue
        d = {hdr[i]: ("" if r[i] is None else r[i]) for i in range(len(hdr)) if i < len(r)}
        if str(d.get("Company") or "").strip():
            out.append(d)
    # Merge scores/role/HQ from Company Details
    if "Company Details" in wb.sheetnames:
        ws = wb["Company Details"]
        rows_raw = list(ws.iter_rows(values_only=True))
        hdr = [str(h) for h in rows_raw[0]]
        by = {}
        for r in rows_raw[1:]:
            if not r:
                continue
            d = {hdr[i]: ("" if r[i] is None else r[i]) for i in range(len(hdr)) if i < len(r)}
            key = _norm(d.get("Brand") or d.get("Company") or "")
            if key:
                by[key] = d
        for row in out:
            key = _norm(row.get("Company") or "")
            det = by.get(key)
            if not det:
                continue
            for col in ("Quadrant", "X", "Y", "Overall", "Role"):
                if det.get(col) not in (None, ""):
                    row[col] = det[col]
                    if col == "X":
                        row["X Score"] = det[col]
                    elif col == "Y":
                        row["Y Score"] = det[col]
                    elif col == "Overall":
                        row["Overall Score"] = det[col]
            if det.get("Found in"):
                row["Headquarters"] = det["Found in"]
                row["Found in"] = det["Found in"]
            if det.get("Role"):
                row["Distribution Type"] = det["Role"]
    return out


async def main() -> int:
    apply_env_overrides()
    apply_chatgpt_expand_env(root=ROOT)
    xlsx = FOLDER / f"{SLUG}_FINAL.xlsx"
    landscape = _load_landscape(xlsx)

    kept: list[dict] = []
    removed: list[str] = []
    existing = set()
    for row in landscape:
        name = str(row.get("Brand") or row.get("Company") or "").strip()
        key = _norm(name)
        # Strip ownership suffixes for identity
        plain = re.sub(r"\s*\((?:acquired by|subsidiary of|merged into)[^)]*\)\s*$", "", name, flags=re.I).strip()
        pkey = _norm(plain) or key
        if pkey in REMOVE or key in REMOVE:
            removed.append(name)
            continue
        row["Role"] = "Solution Provider"
        row["Distribution Type"] = "Solution Provider"
        kept.append(row)
        existing.add(pkey)
        existing.add(key)

    print(f"Removed {len(removed)} non-SP / off-market:")
    for n in removed:
        print(f"  - {n}")

    added_rows: list[dict] = []
    for c in NEW:
        key = _norm(c["company"])
        if key in existing:
            print(f"  skip existing: {c['company']}")
            continue
        row = _row_from_candidate(c)
        print(f"  enrich: {c['company']}")
        row = await _deepseek_enrich(row)
        added_rows.append(row)
        existing.add(key)

    # Ensure >= TARGET_MIN
    all_rows = kept + added_rows
    if len(all_rows) < TARGET_MIN:
        print(f"WARNING: only {len(all_rows)} < {TARGET_MIN}")
    else:
        print(f"Count OK: {len(all_rows)} (>= {TARGET_MIN})")

    # Score only newly added (crawl+LLM); preserve existing scores on kept
    os.environ["EXPAND_XY_SKIP_CRAWL"] = "0"
    os.environ["EXPAND_XY_FORCE_CRAWL"] = "1"
    os.environ.setdefault("EXPAND_XY_CONCURRENT", "3")
    os.environ.setdefault("QUADRANT_CRAWL_MAX_PAGES", "20")
    os.environ.setdefault("EXPAND_MARKET_AXIS_LLM", "1")

    audit: dict = {}
    audit_path = FOLDER / "chatgpt_expand_batch_all_audit.json"
    if audit_path.exists():
        try:
            audit = json.loads(audit_path.read_text(encoding="utf-8")).get("xy_scoring") or {}
        except Exception:
            audit = {}

    if added_rows:
        print(f"Scoring {len(added_rows)} new companies...")
        scored_new, new_audit = await score_expand_rows(added_rows, QUERY, country="global")
        # merge axis defs
        for k, v in (new_audit or {}).items():
            if v and not audit.get(k):
                audit[k] = v
        by_new = {_norm(r.get("Company") or ""): r for r in scored_new}
    else:
        by_new = {}

    final_rows: list[dict] = []
    for row in kept:
        final_rows.append(row)
    for row in added_rows:
        scored = by_new.get(_norm(row.get("Company") or ""))
        final_rows.append(scored or row)

    # Force SP role on everyone
    for row in final_rows:
        row["Role"] = "Solution Provider"
        row["Distribution Type"] = "Solution Provider"
        row["Industry Category"] = INDUSTRY
        if not str(row.get("Brand") or "").strip():
            row["Brand"] = str(row.get("Company") or "").strip()

    detail_rows = to_company_detail_rows(final_rows, QUERY, audit)
    for det in detail_rows:
        det["Role"] = "Solution Provider"

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

    write_final_xlsx(
        xlsx,
        final_rows,
        "Companies",
        {
            "query": QUERY,
            "xy_scoring": audit,
            "sp_only_refresh": {
                "removed": removed,
                "added": [r.get("Company") for r in added_rows],
                "total": len(final_rows),
            },
        },
        detail_rows=detail_rows,
    )
    extras = export_expand_quadrant_outputs(
        FOLDER, detail_rows, QUERY, country="global", audit=audit, chart_n=20
    )

    # CSV
    import csv

    csv_path = FOLDER / f"{SLUG}_companies.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["Brand", "Company", "Role", "Quadrant", "X", "Y", "Overall", "Found in"],
            extrasaction="ignore",
        )
        w.writeheader()
        for d in detail_rows:
            w.writerow(d)

    audit_out = OUT / "_audit" / "semi_sp_only_refresh.json"
    audit_out.write_text(
        json.dumps(
            {
                "before": len(landscape),
                "removed": removed,
                "added": [r.get("Company") for r in added_rows],
                "after": len(final_rows),
                "roles": {"Solution Provider": len(final_rows)},
                "html": str(extras.get("html") or ""),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"FINAL -> {xlsx} ({len(final_rows)} companies)")
    print(f"audit -> {audit_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
