#!/usr/bin/env python3
"""
Verify + fix Found in (City, Country) for Global Flexible Packaging.

Agent-owned web verification (company site / Wikipedia / filings / DDGS).
Never invents — keep prior City,Country if already valid and not overridden.
Preserves Brand/Company/Role/Quadrant/X/Y/Overall.
"""
from __future__ import annotations

import json
import re
import sys
import time
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from openpyxl import load_workbook

from vendor_intel.enrichment.hq_city_country import (
    is_city_country,
    normalize_city_country,
    resolve_hq_city_country,
)
from vendor_intel.pipeline.expand_quadrant_score import (
    export_expand_quadrant_outputs,
    to_company_detail_rows,
)
from vendor_intel.pipeline.web_expand import write_final_xlsx

SLUG = "global_flexible_packaging_market_global"
QUERY = "Global Flexible Packaging Market"
OUT = ROOT / "output" / "chatgpt_expand" / SLUG
XLSX = OUT / f"{SLUG}_FINAL.xlsx"
AUDIT = ROOT / "output" / "chatgpt_expand" / "_audit" / f"{SLUG}_found_in_verify.json"

# Web-verified HQ only (Aug 2026 agent search). Format: City, Country
# Prefer corporate / registered HQ over a single plant when both exist.
VERIFIED: dict[str, str] = {
    # —— confirmed corrections ——
    "mondi": "Weybridge, United Kingdom",
    "klockner pentaplast": "London, United Kingdom",
    "klöckner pentaplast": "London, United Kingdom",
    "max speciality films": "Chandigarh, India",
    "toppan speciality films": "Chandigarh, India",
    "okura industrial": "Marugame, Japan",
    "thong guan": "Sungai Petani, Malaysia",
    "ahlstrom": "Espoo, Finland",
    "treofan": "Neunkirchen, Germany",
    "polyopt": "Neunkirchen, Germany",
    "gulf packaging industries": "Al Khobar, Saudi Arabia",
    "mylar specialty films": "Contern, Luxembourg",
    "hubei firsta": "Yunmeng, China",
    "jiangsu shuangxing": "Suqian, China",
    # —— reconfirmed majors (keep / normalize) ——
    "amcor": "Zurich, Switzerland",
    "huhtamaki": "Espoo, Finland",
    "proampac": "Cincinnati, Ohio, USA",
    "constantia flexibles": "Vienna, Austria",
    "coveris": "Vienna, Austria",
    "uflex": "Noida, Uttar Pradesh, India",
    "polyplex corporation": "Noida, Uttar Pradesh, India",
    "polyplex thailand": "Bangkok, Thailand",
    "berry global": "Evansville, Indiana, USA",
    "sealed air": "Charlotte, North Carolina, USA",
    "honeywell": "Charlotte, North Carolina, USA",
    "sonoco": "Hartsville, South Carolina, USA",
    "novolex": "Charlotte, North Carolina, USA",
    "printpack": "Atlanta, Georgia, USA",
    "winpak": "Winnipeg, Manitoba, Canada",
    "wipak": "Nastola, Finland",
    "taghleef": "Dubai, United Arab Emirates",
    "al ghurair packaging": "Dubai, United Arab Emirates",
    "arabian flexible packaging": "Dubai, United Arab Emirates",
    "cosmo first": "New Delhi, India",
    "cosmo films": "New Delhi, India",
    "epl limited": "Mumbai, Maharashtra, India",
    "essel": "Mumbai, Maharashtra, India",
    "scientex": "Shah Alam, Malaysia",
    "scg packaging": "Bangkok, Thailand",
    "sudpack verpackungen": "Ochsenhausen, Germany",
    "sudpack iberica": "Barcelona, Spain",
    "südpack": "Ochsenhausen, Germany",
    "aluflexpack": "Reinach, Switzerland",
    "epac": "Del Mar, California, USA",
    "innovia": "Wigton, United Kingdom",
    "clondalkin": "Amsterdam, Netherlands",
    "transcontinental": "Montreal, Quebec, Canada",
    "3m scotchpak": "St. Paul, Minnesota, USA",
    "dupont tyvek": "Wilmington, Delaware, USA",
    "kuraray": "Tokyo, Japan",
    "toray industries": "Tokyo, Japan",
    "mitsubishi polyester film": "Wiesbaden, Germany",
    "smurfit westrock": "Dublin, Ireland",
    "jindal poly films": "New Delhi, India",
    "jindal films": "LaGrange, Georgia, USA",
    "srf limited": "Gurugram, Haryana, India",
    "ester industries": "Gurugram, Haryana, India",
    "bilcare": "Pune, Maharashtra, India",
    "schur flexibles": "Wiener Neudorf, Austria",
    "bischof + klein": "Lengerich, Germany",
    "bischof klein": "Lengerich, Germany",
    "goglio": "Daverio, Italy",
    "walki": "Espoo, Finland",
    "pactiv evergreen": "Lake Forest, Illinois, USA",
    "reynolds consumer": "Lake Forest, Illinois, USA",
    "bemis": "Neenah, Wisconsin, USA",
    "ampac holdings": "Cincinnati, Ohio, USA",
    "inteplast": "Livingston, New Jersey, USA",
    "sigma plastics": "Lyndhurst, New Jersey, USA",
    "charter next generation": "Milton, Wisconsin, USA",
    "rkw": "Frankenthal, Germany",
    "polifilm": "Weißandt-Gölzau, Germany",
    "kalle": "Wiesbaden, Germany",
    "saica flex": "Zaragoza, Spain",
    "mpact flexible": "Johannesburg, South Africa",
    "futamura": "Nagoya, Japan",
    "toyobo": "Osaka, Japan",
    "rengo": "Osaka, Japan",
    "unitika": "Osaka, Japan",
    "kureha": "Tokyo, Japan",
    "toppan printing": "Tokyo, Japan",
    "dai nippon": "Tokyo, Japan",
    "toyo seikan": "Tokyo, Japan",
    "asahi kasei": "Tokyo, Japan",
    "mitsui chemicals": "Tokyo, Japan",
    "mitsubishi chemical corporation": "Tokyo, Japan",
    "mitsubishi gas chemical": "Tokyo, Japan",
    "skc": "Seoul, South Korea",
    "hyosung": "Seoul, South Korea",
    "kolon industries films": "Gwacheon, South Korea",
    "nan ya plastics": "Taipei, Taiwan",
    "far eastern new century": "Taipei, Taiwan",
    "shinkong synthetic": "Taipei, Taiwan",
    "formosa idemitsu": "Taipei, Taiwan",
    "indorama ventures packaging": "Bangkok, Thailand",
    "tcpl packaging": "Mumbai, Maharashtra, India",
    "vacmet": "Agra, India",
    "chiripal poly": "Ahmedabad, Gujarat, India",
    "manjushree": "Bengaluru, Karnataka, India",
    "oliver healthcare": "Grand Rapids, Michigan, USA",
    "interflex": "Wilkesboro, North Carolina, USA",
    "bryce": "Memphis, Tennessee, USA",
    "glenroy": "Menomonee Falls, Wisconsin, USA",
    "c-p flexible": "York, Pennsylvania, USA",
    "flair flexible": "Appleton, Wisconsin, USA",
    "ppc flexible": "Buffalo Grove, Illinois, USA",
    "pregis": "Chicago, Illinois, USA",
    "clear lam": "Elk Grove Village, Illinois, USA",
    "soarus": "Arlington Heights, Illinois, USA",
    "wipf": "Volketswil, Switzerland",
    "frobenius": "Wuppertal, Germany",
    "al watania plastics": "Riyadh, Saudi Arabia",
    "napco national": "Dammam, Saudi Arabia",
    "takween": "Al Khobar, Saudi Arabia",
    "qatar plastic": "Mesaieed, Qatar",
    "al khaleej": "Sohar, Oman",
    "pt trias sentosa": "Sidoarjo, Indonesia",
    "pt argha karya": "Jakarta, Indonesia",
    "bp plastics": "Melaka, Malaysia",
    "flexopack": "Koropi, Greece",
    "plastilene": "Bogotá, Colombia",
    "biofilm": "Cartagena, Colombia",
    "vitopel": "Buenos Aires, Argentina",
    "zaraplast": "São Paulo, Brazil",
    "videplast": "Videira, Brazil",
    "plastrela": "Estrela, Brazil",
    "fabbri": "Vignola, Italy",
    "gascogne flexible": "Dax, France",
    "paardekooper": "Oud-Beijerland, Netherlands",
    "oerlemans": "Genderen, Netherlands",
    "cedo": "Telford, United Kingdom",
    "parkside flexibles": "Normanton, United Kingdom",
    "sharpak": "Witney, United Kingdom",
    "rpc group": "Rushden, United Kingdom",
    "rpc bpi": "Greenock, United Kingdom",
    "selig": "Heist-op-den-Berg, Belgium",
    "huangshan novel": "Huangshan, China",
    "shanghai zijiang": "Shanghai, China",
    "gettel": "Foshan, China",
    "kangde xin": "Zhangjiagang, China",
    "zhejiang yamei": "Haining, China",
}


def _norm(s: str) -> str:
    s = str(s or "").strip().lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[+/|&,_.:\-()]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _match_verified(name: str) -> str | None:
    n = _norm(name)
    best = None
    best_len = -1
    for stem, loc in VERIFIED.items():
        if _norm(stem) in n and len(stem) > best_len:
            best = loc
            best_len = len(stem)
    return best


def _is_incomplete(loc: str) -> bool:
    loc = str(loc or "").strip()
    if not loc:
        return True
    if not is_city_country(loc):
        return True
    # Province/state-only China/India/Japan patterns without real city
    low = loc.lower()
    parts = [p.strip() for p in loc.split(",") if p.strip()]
    if len(parts) == 2 and parts[0].lower() in {
        "punjab",
        "hubei",
        "jiangsu",
        "guangdong",
        "zhejiang",
        "kagawa",
        "kedah",
        "selangor",
        "luxembourg",
    }:
        return True
    if len(parts) == 1:
        return True
    return False


def _ddgs_hq(brand: str, website: str = "") -> str:
    try:
        from ddgs import DDGS
    except Exception:
        return ""
    queries = [
        f"{brand} headquarters city",
        f"{brand} head office address",
        f"{brand} corporate headquarters location",
    ]
    if website:
        queries.append(f"site:{website} headquarters OR head office OR contact")
    chunks: list[str] = []
    try:
        with DDGS() as ddgs:
            for q in queries[:3]:
                try:
                    results = list(ddgs.text(q, max_results=5))
                except Exception:
                    results = []
                for r in results or []:
                    title = str(r.get("title") or "")
                    body = str(r.get("body") or r.get("snippet") or "")
                    chunks.append(f"{title}. {body}")
                time.sleep(0.2)
    except Exception:
        return ""
    blob = " ".join(chunks)
    # Prefer City, Country / City, State, Country patterns in snippets
    m = re.search(
        r"\b(?:headquartered in|headquarters in|based in|head office in)\s+"
        r"([A-Z][^.;|]{2,60})",
        blob,
        re.I,
    )
    if m:
        cand = m.group(1).strip(" ,.")
        cand = re.sub(r"\s+", " ", cand)
        norm = normalize_city_country(cand) or cand
        if is_city_country(norm) or ("," in norm and len(norm) > 6):
            return norm
    return ""


def main() -> None:
    wb = load_workbook(XLSX, data_only=True)
    ws = wb["Landscape"]
    rows_raw = list(ws.iter_rows(values_only=True))
    hdr = [str(h) for h in rows_raw[0]]
    landscape: list[dict] = []
    for r in rows_raw[1:]:
        d = {hdr[i]: ("" if r[i] is None else str(r[i])) for i in range(len(hdr)) if i < len(r)}
        if d.get("Company"):
            landscape.append(d)

    details_by: dict[str, dict] = {}
    if "Company Details" in wb.sheetnames:
        dws = wb["Company Details"]
        drows = list(dws.iter_rows(values_only=True))
        dhdr = [str(h) for h in drows[0]]
        for r in drows[1:]:
            d = {dhdr[i]: ("" if r[i] is None else str(r[i])) for i in range(len(dhdr)) if i < len(r)}
            key = _norm(d.get("Brand") or "")
            if key:
                details_by[key] = d

    report = {
        "fixed": [],
        "confirmed": [],
        "resolved_web": [],
        "still_incomplete": [],
        "unchanged_ok": [],
    }

    for row in landscape:
        brand = str(row.get("Company") or "").strip()
        det = details_by.get(_norm(brand)) or {}
        if det.get("Brand"):
            brand = str(det["Brand"]).strip()
            row["Brand"] = brand
            row["Company"] = brand
        if det.get("Company") and (
            str(det["Company"]).startswith("(") or _norm(det["Company"]) != _norm(brand)
        ):
            row["_display_company"] = det["Company"]
        for col in ("Role", "Quadrant", "X", "Y", "Overall", "Found in"):
            if det.get(col) not in (None, "") and col != "Found in":
                if col == "X":
                    row["X Score"] = det[col]
                elif col == "Y":
                    row["Y Score"] = det[col]
                elif col == "Overall":
                    row["Overall Score"] = det[col]
                else:
                    row[col] = det[col]
        if det.get("Role") in ("Brand", "Marketer"):
            row["Role"] = det["Role"]
            row["Distribution Type"] = det["Role"]

        old = (
            str(row.get("Headquarters") or "").strip()
            or str(det.get("Found in") or "").strip()
            or str(row.get("Found in") or "").strip()
        )
        verified = _match_verified(brand)
        new = ""
        source = ""

        if verified:
            new = verified
            source = "agent_web_verified"
            if normalize_city_country(old) != normalize_city_country(new) and old != new:
                report["fixed"].append({"brand": brand, "from": old, "to": new, "source": source})
            else:
                report["confirmed"].append({"brand": brand, "loc": new})
        elif old and is_city_country(old) and not _is_incomplete(old):
            new = normalize_city_country(old) or old
            source = "prior_ok"
            report["unchanged_ok"].append({"brand": brand, "loc": new})
        else:
            website = str(row.get("Website") or "")
            resolved = ""
            try:
                # Pass empty current so wiki/known can run even if prior was incomplete
                loc, src = resolve_hq_city_country(
                    brand, current="" if _is_incomplete(old) else old, allow_wiki=True
                )
                if loc:
                    resolved = loc
                    source = f"resolve:{src}"
            except Exception:
                resolved = ""
            if not resolved or _is_incomplete(resolved):
                ddgs = _ddgs_hq(brand, website)
                if ddgs and not _is_incomplete(ddgs):
                    resolved = ddgs
                    source = "ddgs"
            if resolved and not _is_incomplete(resolved):
                new = normalize_city_country(resolved) or resolved
                report["resolved_web"].append(
                    {"brand": brand, "from": old, "to": new, "source": source or "web"}
                )
            elif old:
                new = old  # keep best available rather than blank if something exists
                source = "kept_prior"
                if _is_incomplete(old):
                    report["still_incomplete"].append({"brand": brand, "loc": old})
            else:
                new = ""
                source = "unverified_blank"
                report["still_incomplete"].append({"brand": brand, "loc": ""})

        row["Headquarters"] = new
        row["Found in"] = new
        row["_found_in_source"] = source

    # Rebuild details
    audit: dict = {}
    ap = OUT / "chatgpt_expand_batch_all_audit.json"
    if ap.exists():
        try:
            audit = json.loads(ap.read_text(encoding="utf-8")).get("xy_scoring") or {}
        except Exception:
            audit = {}

    details = to_company_detail_rows(landscape, QUERY, audit)
    by = {_norm(r.get("Brand") or r.get("Company") or ""): r for r in landscape}
    for d in details:
        src = by.get(_norm(d.get("Brand") or ""))
        if not src:
            continue
        d["Role"] = src.get("Role") or d.get("Role") or "Brand"
        d["Quadrant"] = src.get("Quadrant") or d.get("Quadrant")
        d["X"] = src.get("X Score") or src.get("X") or d.get("X")
        d["Y"] = src.get("Y Score") or src.get("Y") or d.get("Y")
        d["Overall"] = src.get("Overall Score") or src.get("Overall") or d.get("Overall")
        d["Found in"] = src.get("Found in") or src.get("Headquarters") or d.get("Found in")
        if src.get("_display_company"):
            d["Company"] = src["_display_company"]

    write_final_xlsx(
        XLSX,
        landscape,
        "Companies",
        {
            "query": QUERY,
            "found_in_verify": "2026-08-14",
            "fixed": len(report["fixed"]),
            "resolved_web": len(report["resolved_web"]),
        },
        detail_rows=details,
    )
    extras = export_expand_quadrant_outputs(
        OUT, details, QUERY, country="global", audit=audit, chart_n=20
    )
    report["n"] = len(landscape)
    report["html"] = str(extras.get("html") or "")
    report["counts"] = {
        "fixed": len(report["fixed"]),
        "confirmed": len(report["confirmed"]),
        "resolved_web": len(report["resolved_web"]),
        "unchanged_ok": len(report["unchanged_ok"]),
        "still_incomplete": len(report["still_incomplete"]),
    }
    AUDIT.parent.mkdir(parents=True, exist_ok=True)
    AUDIT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(
        f"DONE n={len(landscape)} fixed={len(report['fixed'])} "
        f"confirmed={len(report['confirmed'])} web={len(report['resolved_web'])} "
        f"incomplete={len(report['still_incomplete'])}"
    )
    for x in report["fixed"]:
        print(f"  FIX {x['brand']}: {x['from']} => {x['to']}")
    for x in report["resolved_web"][:20]:
        print(f"  WEB {x['brand']}: {x['from']} => {x['to']}")
    if report["still_incomplete"]:
        print("Still incomplete:")
        for x in report["still_incomplete"]:
            print(f"  ? {x['brand']}: {x['loc'] or '(blank)'}")
    print("audit ->", AUDIT)


if __name__ == "__main__":
    main()
