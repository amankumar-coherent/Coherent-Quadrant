"""Resolve + apply City, Country Found-in for semiconductor market.

Uses Wikipedia infobox + verified MANUAL map. Never invents blanks.
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from openpyxl import load_workbook

from vendor_intel.pipeline.expand_quadrant_score import (
    export_expand_quadrant_outputs,
    to_company_detail_rows,
)
from vendor_intel.pipeline.web_expand import write_final_xlsx

OUT = ROOT / "output" / "chatgpt_expand"
AUDIT = OUT / "_audit"
SLUG = "global_semiconductor_market_global"
QUERY = "Global Semiconductor Market"
UA = {"User-Agent": "CoherentQuadrantHQBot/1.0 (research; contact=local)"}

# Verified public HQ (Wikipedia / company About / filings). Format: City, Country
MANUAL: dict[str, str] = {
    "rohde & schwarz": "Munich, Germany",
    "micron technology": "Boise, Idaho, USA",
    "siltronic ag": "Munich, Germany",
    "globalfoundries": "Malta, New York, USA",
    "jenoptik ag": "Jena, Germany",
    "lam research": "Fremont, California, USA",
    "pva tepla ag": "Wettenberg, Germany",
    "teledyne dalsa": "Waterloo, Ontario, Canada",
    "tower semiconductor": "Migdal HaEmek, Israel",
    "wolfspeed": "Durham, North Carolina, USA",
    "cerebras systems": "Sunnyvale, California, USA",
    "stats chippac": "Singapore, Singapore",
    "suss microtec se": "Garching, Germany",
    "ase technology holding": "Kaohsiung, Taiwan",
    "bluglass limited": "Silverwater, New South Wales, Australia",
    "carsem": "Ipoh, Malaysia",
    "nexperia": "Nijmegen, Netherlands",
    "d-wave systems": "Burnaby, British Columbia, Canada",
    "silterra malaysia": "Kulim, Malaysia",
    "inari amertron": "Penang, Malaysia",
    "tsmc": "Hsinchu, Taiwan",
    "x-fab silicon foundries": "Erfurt, Germany",
    "asm international": "Almere, Netherlands",
    "asml holding": "Veldhoven, Netherlands",
    "alchip technologies": "Taipei, Taiwan",
    "ensilica": "Abingdon, Oxfordshire, United Kingdom",
    "marvell technology": "Santa Clara, California, USA",
    "megachips corporation": "Osaka, Japan",
    "plessey semiconductors": "Plymouth, United Kingdom",
    "semikron danfoss": "Nuremberg, Germany",
    "valens semiconductor": "Hod Hasharon, Israel",
    "aixtron se": "Herzogenrath, Germany",
    "global unichip corporation (guc)": "Hsinchu, Taiwan",
    "arm holdings": "Cambridge, United Kingdom",
    "ev group (evg)": "St. Florian am Inn, Austria",
    "elmos semiconductor": "Dortmund, Germany",
    "ht micron": "Porto Alegre, Brazil",
    "kla corporation": "Milpitas, California, USA",
    "renesas electronics": "Tokyo, Japan",
    "stmicroelectronics": "Geneva, Switzerland",
    "tata electronics": "Mumbai, Maharashtra, India",
    "ams ag": "Premstätten, Austria",
    "cdil (continental device india)": "New Delhi, India",
    "jcet group": "Jiangyin, Jiangsu, China",
    "kioxia": "Tokyo, Japan",
    "nanya technology": "New Taipei City, Taiwan",
    "nordic semiconductor": "Trondheim, Norway",
    "ineda systems": "Hyderabad, Telangana, India",
    "redlen technologies": "Saanichton, British Columbia, Canada",
    "robert bosch gmbh": "Gerlingen, Germany",
    "sambanova systems": "Palo Alto, California, USA",
    "sondrel": "Reading, United Kingdom",
    "texas instruments": "Dallas, Texas, USA",
    "nxp semiconductors": "Eindhoven, Netherlands",
    "alphawave ip": "London, United Kingdom",
    "amkor technology": "Tempe, Arizona, USA",
    "apple": "Cupertino, California, USA",
    "aura semiconductor": "Bengaluru, Karnataka, India",
    "lattice semiconductor": "Hillsboro, Oregon, USA",
    "mitsubishi electric": "Tokyo, Japan",
    "murata manufacturing": "Nagaokakyo, Kyoto, Japan",
    "peraso technologies": "San Jose, California, USA",
    "powerchip semiconductor manufacturing corporation (psmc)": "Hsinchu, Taiwan",
    "qorvo": "Greensboro, North Carolina, USA",
    "samsung electronics": "Suwon, South Korea",
    "siliconware precision industries (spil)": "Taichung, Taiwan",
    "skywater technology": "Bloomington, Minnesota, USA",
    "samsung electro-mechanics": "Suwon, South Korea",
    "advantest": "Tokyo, Japan",
    "analog devices": "Wilmington, Massachusetts, USA",
    "changxin memory technologies": "Hefei, Anhui, China",
    "polymatech electronics": "Chennai, Tamil Nadu, India",
    "sahasra semiconductors": "Bhiwadi, Rajasthan, India",
    "semileds": "Zhunan, Miaoli, Taiwan",
    "applied materials": "Santa Clara, California, USA",
    "toshiba electronic devices & storage corporation": "Tokyo, Japan",
    "globalwafers": "Hsinchu, Taiwan",
    "western digital": "San Jose, California, USA",
    "mobileye": "Jerusalem, Israel",
    "power integrations, inc.": "San Jose, California, USA",
    "ampere computing llc": "Santa Clara, California, USA",
    "disco corporation": "Tokyo, Japan",
    "infineon technologies": "Neubiberg, Germany",
    "lasertec corporation": "Yokohama, Japan",
    "teradyne": "North Reading, Massachusetts, USA",
    "smic": "Shanghai, China",
    "amd": "Santa Clara, California, USA",
    "bosch sensortec": "Reutlingen, Germany",
    "cambridge gan devices": "Cambridge, United Kingdom",
    "graphcore": "Bristol, United Kingdom",
    "helix semiconductors": "Irvine, California, USA",
    "inuitive": "Ra'anana, Israel",
    "key foundry co., ltd.": "Cheongju, South Korea",
    "lapis technology co., ltd.": "Yokohama, Japan",
    "lx semicon co., ltd.": "Daejeon, South Korea",
    "mediatek": "Hsinchu, Taiwan",
    "melexis": "Ieper, Belgium",
    "microchip technology": "Chandler, Arizona, USA",
    "nvidia": "Santa Clara, California, USA",
    "powertech technology": "Hsinchu, Taiwan",
    "qualcomm": "San Diego, California, USA",
    "rohm semiconductor": "Kyoto, Japan",
    "sk hynix": "Icheon, South Korea",
    "sitime corporation": "Santa Clara, California, USA",
    "silead india": "Bengaluru, Karnataka, India",
    "silicon labs": "Austin, Texas, USA",
    "tokyo electron": "Tokyo, Japan",
    "wiliot": "Caesarea, Israel",
    "xmos": "Bristol, United Kingdom",
    "cr microelectronics": "Wuxi, Jiangsu, China",
    "cadence design systems, inc.": "San Jose, California, USA",
    "kenya semiconductor technologies": "Nyeri, Kenya",
    "lg innotek": "Seoul, South Korea",
    "magnachip semiconductor corporation": "Luxembourg City, Luxembourg",
    "realtek": "Hsinchu, Taiwan",
    "siemens eda (formerly mentor graphics)": "Wilsonville, Oregon, USA",
    "solantro semiconductor": "Ottawa, Ontario, Canada",
    "winbond electronics": "Taichung, Taiwan",
    "autotalks": "Kfar Netter, Israel",
    "broadcom": "San Jose, California, USA",
    "ceitec s.a.": "Porto Alegre, Brazil",
    "chipus microelectronics": "Florianópolis, Brazil",
    "cyient": "Hyderabad, Telangana, India",
    "db hitek": "Bucheon, South Korea",
    "gan systems": "Ottawa, Ontario, Canada",
    "hua hong semiconductor": "Shanghai, China",
    "iqe plc": "Cardiff, United Kingdom",
    "intel corporation": "Santa Clara, California, USA",
    "mosaic microsystems": "Rochester, New York, USA",
    "on semiconductor": "Phoenix, Arizona, USA",
    "pragmatic semiconductor": "Cambridge, United Kingdom",
    "rir power electronics": "Mumbai, Maharashtra, India",
    "sid microeletrônica": "São Paulo, Brazil",
    "ssmc (systems on silicon manufacturing company)": "Singapore, Singapore",
    "saankhya labs": "Bengaluru, Karnataka, India",
    "socionext inc.": "Yokohama, Japan",
    "sony semiconductor solutions": "Atsugi, Kanagawa, Japan",
    "surecore": "Sheffield, United Kingdom",
    "synopsys, inc.": "Sunnyvale, California, USA",
    "umc": "Hsinchu, Taiwan",
    "unisem": "Kuala Lumpur, Malaysia",
    "unitec semiconductores": "Ribeirão das Neves, Minas Gerais, Brazil",
    "vishay intertechnology": "Malvern, Pennsylvania, USA",
    "silex systems limited": "Sydney, New South Wales, Australia",
}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


def _get_json(url: str) -> dict | list:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=25) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def wiki_search(name: str) -> str | None:
    q = urllib.parse.quote(name)
    url = (
        "https://en.wikipedia.org/w/api.php?action=opensearch&limit=1&namespace=0"
        f"&search={q}&format=json"
    )
    try:
        data = _get_json(url)
        if isinstance(data, list) and len(data) > 1 and data[1]:
            return str(data[1][0])
    except Exception:
        return None
    return None


def wiki_page_html(title: str) -> str:
    q = urllib.parse.quote(title.replace(" ", "_"))
    url = f"https://en.wikipedia.org/api/rest_v1/page/html/{q}"
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception:
        return ""


def extract_hq_from_infobox(html: str) -> str | None:
    if not html:
        return None
    m = re.search(r">Headquarters</th>\s*<td[^>]*>(.*?)</td>", html, re.I | re.S)
    if not m:
        m = re.search(
            r"(?:Headquarters|Head office|HQ)[^<]{0,80}</th>\s*<td[^>]*>(.*?)</td>",
            html,
            re.I | re.S,
        )
    if not m:
        return None
    text = re.sub(r"<[^>]+>", " ", m.group(1))
    text = re.sub(r"\[[^\]]*\]", "", text)
    text = re.sub(r"\d{4,}", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" ,;")
    if len(text) < 3 or len(text) > 120:
        return None
    return text


def normalize_location(raw: str) -> str | None:
    if not raw:
        return None
    s = raw.strip()
    s = s.replace("U.S.", "USA").replace("U.S.A.", "USA").replace("United States of America", "USA")
    s = s.replace("United States", "USA")
    s = re.sub(r"\s+", " ", s).replace(" ,", ",")
    parts = [p.strip() for p in re.split(r",|\n", s) if p.strip()]
    if not parts:
        return None
    if len(parts) > 3:
        parts = parts[-3:]
    out = ", ".join(parts)
    if "," not in out:
        return None  # require City, Country form
    if len(out) < 4:
        return None
    return out


def lookup_manual(brand: str) -> str | None:
    b = _norm(brand)
    if b in MANUAL:
        return MANUAL[b]
    best: tuple[int, str] | None = None
    for k, v in MANUAL.items():
        if b == k or b.startswith(k + " ") or b.startswith(k + "(") or k in b and len(k) >= 10:
            cand = (len(k), v)
            if best is None or cand[0] > best[0]:
                best = cand
    return best[1] if best else None


def resolve_one(brand: str) -> tuple[str | None, str]:
    man = lookup_manual(brand)
    if man:
        return man, "manual_verified"
    clean = re.sub(r"\([^)]*\)", "", brand).strip(" ,/")
    clean = re.sub(r"\s+", " ", clean)
    if len(clean) < 3:
        return None, "skip"
    title = wiki_search(clean)
    if not title and len(clean.split()) >= 2:
        title = wiki_search(" ".join(clean.split()[:3]))
    if not title:
        return None, "wiki_miss"
    html = wiki_page_html(title)
    hq = extract_hq_from_infobox(html)
    norm = normalize_location(hq or "")
    if norm:
        return norm, f"wikipedia:{title}"
    return None, f"wiki_no_hq:{title}"


def resolve_all() -> list[dict]:
    items = json.loads(
        (AUDIT / f"{SLUG}_found_in_audit.json").read_text(encoding="utf-8")
    )
    results = []
    filled = missed = 0
    for it in items:
        brand = it["brand"]
        loc, src = resolve_one(brand)
        if loc:
            filled += 1
        else:
            missed += 1
        results.append(
            {
                "brand": brand,
                "old": it.get("found_in") or "",
                "found_in": loc or "",
                "source": src,
            }
        )
        print(f"  {'OK' if loc else 'MISS'} {brand}: {loc or src}")
        time.sleep(0.12)
    out_path = AUDIT / f"{SLUG}_found_in_resolved.json"
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nResolved: filled={filled} missed={missed} -> {out_path}")
    return results


def apply(results: list[dict]) -> None:
    by = {_norm(r["brand"]): r for r in results}
    folder = OUT / SLUG
    xlsx = folder / f"{SLUG}_FINAL.xlsx"
    wb = load_workbook(xlsx, data_only=True)
    land_ws = wb["Landscape"] if "Landscape" in wb.sheetnames else wb[wb.sheetnames[0]]
    land_rows = list(land_ws.iter_rows(values_only=True))
    land_hdr = [str(h) for h in land_rows[0]]
    landscape: list[dict] = []
    for r in land_rows[1:]:
        if not r:
            continue
        d = {
            land_hdr[i]: ("" if r[i] is None else r[i])
            for i in range(len(land_hdr))
            if i < len(r)
        }
        if str(d.get("Company") or "").strip():
            landscape.append(d)

    details_by: dict[str, dict] = {}
    if "Company Details" in wb.sheetnames:
        ws = wb["Company Details"]
        rows = list(ws.iter_rows(values_only=True))
        hdr = [str(h) for h in rows[0]]
        for r in rows[1:]:
            if not r:
                continue
            d = {
                hdr[i]: ("" if r[i] is None else str(r[i]))
                for i in range(len(hdr))
                if i < len(r)
            }
            key = _norm(d.get("Brand") or d.get("Company") or "")
            if key:
                details_by[key] = d

    filled = blank = 0
    report = []
    for row in landscape:
        brand = str(row.get("Company") or "").strip()
        det = details_by.get(_norm(brand))
        brand_l = str((det or {}).get("Brand") or brand)
        res = by.get(_norm(brand_l)) or by.get(_norm(brand))
        loc = str((res or {}).get("found_in") or "").strip()
        src = str((res or {}).get("source") or "")
        if loc and "," not in loc:
            loc = ""
            src = "rejected_country_only"
        if loc:
            row["Headquarters"] = loc
            filled += 1
        else:
            row["Headquarters"] = ""
            blank += 1
        if det:
            for col in ("Quadrant", "X", "Y", "Overall", "Role"):
                if det.get(col) not in (None, ""):
                    row[col] = det[col]
                    if col == "X":
                        row["X Score"] = det[col]
                    elif col == "Y":
                        row["Y Score"] = det[col]
                    elif col == "Overall":
                        row["Overall Score"] = det[col]
            if det.get("Role"):
                row["Distribution Type"] = det["Role"]
        report.append({"brand": brand_l, "found_in": loc, "source": src})

    audit_path = folder / "chatgpt_expand_batch_all_audit.json"
    audit: dict = {}
    if audit_path.exists():
        audit = json.loads(audit_path.read_text(encoding="utf-8")).get("xy_scoring") or {}

    detail_rows = to_company_detail_rows(landscape, QUERY, audit)
    write_final_xlsx(
        xlsx,
        landscape,
        "Companies",
        {"query": QUERY, "xy_scoring": audit, "found_in_fill": True},
        detail_rows=detail_rows,
    )
    extras = export_expand_quadrant_outputs(
        folder, detail_rows, QUERY, country="global", audit=audit, chart_n=20
    )
    (AUDIT / f"{SLUG}_found_in_applied.json").write_text(
        json.dumps({"filled": filled, "blank": blank, "rows": report}, indent=2),
        encoding="utf-8",
    )
    print(f"Applied: filled={filled} blank={blank}")
    print(f"html -> {extras.get('html')}")
    for r in report:
        if not r["found_in"]:
            print(f"  BLANK {r['brand']!r} ({r['source']})")


def main() -> None:
    results = resolve_all()
    apply(results)


if __name__ == "__main__":
    main()
