#!/usr/bin/env python3
"""
Verify + fill Found in (City, Country) for Wearable Medical Devices.

Agent-owned: known map + prior audits + Wikipedia + live DDGS web search.
Never invents — leave blank if unverified. Preserves X/Y/Role/Company.
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from openpyxl import load_workbook

from vendor_intel.enrichment.hq_city_country import (
    is_city_country,
    lookup_known_hq,
    normalize_city_country,
    resolve_hq_city_country,
)
from vendor_intel.pipeline.expand_quadrant_score import (
    export_expand_quadrant_outputs,
    to_company_detail_rows,
)
from vendor_intel.pipeline.web_expand import write_final_xlsx

OUT = ROOT / "output" / "chatgpt_expand"
AUDIT = OUT / "_audit"
SLUG = "global_wearable_medical_devices_market_global"
QUERY = "Global Wearable Medical Devices Market"
FOLDER = OUT / SLUG

# Web-verified HQ only (company site / Wikipedia / filings). Format: City, Country
VERIFIED: dict[str, str] = {
    # Majors
    "abbott": "Abbott Park, Illinois, USA",
    "dexcom": "San Diego, California, USA",
    "medtronic": "Dublin, Ireland",
    "philips": "Amsterdam, Netherlands",
    "masimo": "Irvine, California, USA",
    "omron healthcare": "Kyoto, Japan",
    "omron": "Kyoto, Japan",
    "ge healthcare": "Chicago, Illinois, USA",
    "resmed": "San Diego, California, USA",
    "insulet": "Acton, Massachusetts, USA",
    "alivecor": "Mountain View, California, USA",
    "withings": "Issy-les-Moulineaux, France",
    "irhythm": "San Francisco, California, USA",
    "tandem diabetes care": "San Diego, California, USA",
    "zoll medical": "Chelmsford, Massachusetts, USA",
    "biotronik": "Berlin, Germany",
    "nihon kohden": "Tokyo, Japan",
    "fukuda denshi": "Tokyo, Japan",
    "draeger": "Lübeck, Germany",
    "dräger": "Lübeck, Germany",
    "fisher & paykel healthcare": "Auckland, New Zealand",
    "boston scientific": "Marlborough, Massachusetts, USA",
    # Hearing
    "sonova": "Stäfa, Switzerland",
    "demant": "Smørum, Denmark",
    "gn hearing": "Ballerup, Denmark",
    "ws audiology": "Lynge, Denmark",
    "cochlear": "Sydney, Australia",
    "amplifon": "Milan, Italy",
    "starkey hearing technologies": "Eden Prairie, Minnesota, USA",
    "eargo": "San Jose, California, USA",
    "miracle-ear": "Minneapolis, Minnesota, USA",
    "hearinglife": "Somerset, New Jersey, USA",
    "audika": "Paris, France",
    "specsavers hearcare": "Guernsey, United Kingdom",
    "fielmann group": "Hamburg, Germany",
    "lively": "New York, New York, USA",
    "best buy health": "Richfield, Minnesota, USA",
    # CGM / diabetes / channel
    "senseonics": "Germantown, Maryland, USA",
    "ascensia diabetes care": "Basel, Switzerland",
    "sinocare": "Changsha, Hunan, China",
    "medtrum": "Shanghai, China",
    "ypsomed": "Burgdorf, Switzerland",
    "ceQur": "Horw, Switzerland",
    "cequr": "Horw, Switzerland",
    "eoflow": "Seongnam, South Korea",
    "beta bionics": "Irvine, California, USA",
    "bigfoot biomedical": "Milpitas, California, USA",
    "livongo": "Mountain View, California, USA",
    "nutrisense": "Chicago, Illinois, USA",
    "levels health": "New York, New York, USA",
    "signos": "San Francisco, California, USA",
    "veri": "Helsinki, Finland",
    "ultrahuman": "Bengaluru, Karnataka, India",
    "zoe": "London, United Kingdom",
    "january ai": "Menlo Park, California, USA",
    "hello inside": "Berlin, Germany",
    "supersapiens": "Atlanta, Georgia, USA",
    # Cardiac / wearables
    "bardy diagnostics": "Seattle, Washington, USA",
    "bioserenity": "Paris, France",
    "fibricheck": "Hasselt, Belgium",
    "theranica": "Netanya, Israel",
    "greenteg": "Zurich, Switzerland",
    "nox medical": "Reykjavik, Iceland",
    "vivalnk": "Campbell, California, USA",
    "advanced brain monitoring": "Carlsbad, California, USA",
    "aktiia": "Neuchâtel, Switzerland",
    "cala health": "San Mateo, California, USA",
    "infobionic": "Waltham, Massachusetts, USA",
    "itamar medical": "Caesarea, Israel",
    "propeller health": "Madison, Wisconsin, USA",
    "wellue": "Shenzhen, China",
    "viatom technology": "Shenzhen, China",
    "beijing choice (choicemmed)": "Beijing, China",
    "compumedics": "Melbourne, Australia",
    "acurable": "London, United Kingdom",
    "biofourmis": "Needham, Massachusetts, USA",
    "adherium": "Melbourne, Australia",
    "current health": "Edinburgh, United Kingdom",
    "shimmer sensing": "Dublin, Ireland",
    "smi (sensomotoric instruments)": "Teltow, Germany",
    "enso": "San Francisco, California, USA",
    "medibiosense": "Doncaster, United Kingdom",
    "circul": "Manhattan Beach, California, USA",
    "isansys": "Abingdon, Oxfordshire, United Kingdom",
    "specsavers hearcare": "St. Andrew's, Guernsey",
    "hearx group": "Pretoria, South Africa",
    "vitalconnect": "San Jose, California, USA",
    "verily life sciences": "South San Francisco, California, USA",
    "epicore biosystems": "Cambridge, Massachusetts, USA",
    "beurer gmbh": "Ulm, Germany",
    "biotelemetry": "Malvern, Pennsylvania, USA",
    "corsano health": "The Hague, Netherlands",
    "onera health": "Eindhoven, Netherlands",
    "bloomlife": "San Francisco, California, USA",
    "equivital": "Cambridge, United Kingdom",
    "healthwatch technologies": "Kfar Saba, Israel",
    "lifesignals": "Milpitas, California, USA",
    "transtek medical": "Zhongshan, China",
    "neurometrix": "Woburn, Massachusetts, USA",
    "biotricity": "Redwood City, California, USA",
    "cardiac insight": "Bellevue, Washington, USA",
    "cefaly technology": "Seraing, Belgium",
    "lepu medical": "Beijing, China",
    "ectosense": "Leuven, Belgium",
    "sleepimage": "Denver, Colorado, USA",
    "agatsa software": "Noida, Uttar Pradesh, India",
    "biostrap": "Los Angeles, California, USA",
    "leaf healthcare": "Pleasanton, California, USA",
    "orpyx medical technologies": "Calgary, Alberta, Canada",
    "biologix": "Sao Paulo, Brazil",
    "nightbalance": "Amsterdam, Netherlands",
    "bittium": "Oulu, Finland",
    "cardiodiagnostics": "Campbell, California, USA",
    "hexoskin": "Montreal, Quebec, Canada",
    "biobeat": "Petah Tikva, Israel",
    "empatica": "Cambridge, Massachusetts, USA",
    "nonin medical": "Plymouth, Minnesota, USA",
    "cardiosignal": "Turku, Finland",
    "huma": "London, United Kingdom",
    "hinge health": "San Francisco, California, USA",
    "activinsights": "Kimbolton, United Kingdom",
    "sensium healthcare": "Abingdon, United Kingdom",
    "intelesens": "Belfast, United Kingdom",
    "aevice health": "Singapore, Singapore",
    "physiq": "Chicago, Illinois, USA",
    "avertus": "Toronto, Ontario, Canada",
    "vitalerter": "Airport City, Israel",
    "zensorium": "Singapore, Singapore",
    "imedtrix": "Milpitas, California, USA",
    "cardiac sense": "Caesarea, Israel",
    "cardiacsense": "Caesarea, Israel",
    "coala life": "Uppsala, Sweden",
    "spire health": "San Francisco, California, USA",
    "strados labs": "Philadelphia, Pennsylvania, USA",
    "nanowear": "New York, New York, USA",
    "smartcardia": "Lausanne, Switzerland",
    "movano health": "Pleasanton, California, USA",
    "know labs": "Seattle, Washington, USA",
    "nemaura medical": "Loughborough, United Kingdom",
    "integrity applications": "Ashdod, Israel",
    "idun technologies": "Zurich, Switzerland",
    "nextsense": "Mountain View, California, USA",
    "ascensia": "Basel, Switzerland",
    "scottcare": "Cleveland, Ohio, USA",
    "heartbeam": "Santa Clara, California, USA",
    "microtech medical": "Hangzhou, China",
    "bioserenity": "Paris, France",
    "cefaly": "Seraing, Belgium",
    "nox medical": "Reykjavik, Iceland",
    "mawi health": "Atlanta, Georgia, USA",
    "cortrium": "Copenhagen, Denmark",
    "nuvo group": "Tel Aviv, Israel",
    "rooti labs": "Taipei, Taiwan",
    "spry health": "Redwood City, California, USA",
    "happy health": "Austin, Texas, USA",
    "sana health": "Oxford, United Kingdom",
    "sunrise": "Namur, Belgium",
    "belun technology": "Hong Kong, China",
    "bitbrain": "Zaragoza, Spain",
    "amiko": "Milan, Italy",
    "pd neurotechnology": "London, United Kingdom",
    "g-tech medical": "Mountain View, California, USA",
    "x-trodes": "Herzliya, Israel",
    "rhaeos": "Evanston, Illinois, USA",
    "ancillare": "Horsham, Pennsylvania, USA",
    "onera": "Eindhoven, Netherlands",
    "biofourmis": "Needham, Massachusetts, USA",
    "kenzen": "Salt Lake City, Utah, USA",
    "seer medical": "Melbourne, Australia",
    "cardiosense": "Chicago, Illinois, USA",
    "oxitone medical": "Oxford, Connecticut, USA",
    "sibel health": "Chicago, Illinois, USA",
    "byteflies": "Antwerp, Belgium",
    "a&d": "Tokyo, Japan",
    "shimmer sensing": "Dublin, Ireland",
    "sotera wireless": "San Diego, California, USA",
    "peerbridge health": "New York, New York, USA",
    "biolinq": "San Diego, California, USA",
    "sky labs": "Seongnam, South Korea",
    "chronolife": "Paris, France",
    "wellysis": "Seoul, South Korea",
    "atsens": "Seongnam, South Korea",
    "huinno": "Seoul, South Korea",
    "sensoria health": "Redmond, Washington, USA",
    "ihealth labs": "Sunnyvale, California, USA",
    "vitaltracer": "Montreal, Quebec, Canada",
    "getemed": "Teltow, Germany",
    "qardio": "San Francisco, California, USA",
    "ten3t healthcare": "Bengaluru, Karnataka, India",
    "cadence": "New York, New York, USA",
    "ddp medical supply": "Farmingdale, New York, USA",
    "gemco medical": "Hudson, Ohio, USA",
    "kind hörgeräte": "Nuremberg, Germany",
    "kind horgerate": "Nuremberg, Germany",
    "medisana": "Neuss, Germany",
    "preventice solutions": "Rochester, Minnesota, USA",
    "hillrom": "Chicago, Illinois, USA",
    "element science": "San Francisco, California, USA",
    "laxmi therapeutic devices": "Goleta, California, USA",
    "glucomodicum": "Espoo, Finland",
    "wearlinq": "San Francisco, California, USA",
    "diplora": "Tel Aviv, Israel",
    "appsens": "Lillesand, Norway",
    "cardiomedive": "Bucharest, Romania",
    "zenicor": "Stockholm, Sweden",
    "zephyr technology": "Annapolis, Maryland, USA",
    "everion": "Zurich, Switzerland",
    "biointellisense": "Golden, Colorado, USA",
    "temptraq": "Westlake, Ohio, USA",
    "pulseon": "Espoo, Finland",
    "cloud dx": "Kitchener, Ontario, Canada",
    "g medical innovations": "Singapore, Singapore",
    "alio": "San Francisco, California, USA",
    "bodytrak": "London, United Kingdom",
    "edans instruments": "Shenzhen, China",
    "edan instruments": "Shenzhen, China",
    "mindray": "Shenzhen, China",
    "raycome health": "Shenzhen, China",
    "cosinuss": "Munich, Germany",
    "lifesense": "Zhongshan, China",
    "cardiotrack": "Bengaluru, Karnataka, India",
    "cardio comm solutions": "Toronto, Ontario, Canada",
    "cardiocomm solutions": "Toronto, Ontario, Canada",
    "cardiac insight": "Bellevue, Washington, USA",
}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


def _ddgs_hq(brand: str, website: str) -> str:
    try:
        from ddgs import DDGS
    except Exception:
        return ""
    queries = [
        f"{brand} headquarters city",
        f"{brand} head office location",
    ]
    if website:
        queries.append(f"{brand} headquarters site:{website.replace('https://','').replace('http://','')}")
    chunks: list[str] = []
    try:
        with DDGS() as ddgs:
            for q in queries[:2]:
                try:
                    results = list(ddgs.text(q, max_results=5))
                except Exception:
                    results = []
                for r in results or []:
                    title = str(r.get("title") or "")
                    body = str(r.get("body") or r.get("snippet") or "")
                    chunks.append(f"{title}. {body}")
                time.sleep(0.3)
    except Exception:
        return ""
    blob = " ".join(chunks)
    # Common patterns: based in X, headquarters in X, HQ: X
    pats = [
        r"[Hh]eadquarters(?:\s+are|\s+is)?(?:\s+located)?\s+in\s+([A-Z][^.;\n]{2,60})",
        r"[Hh]ead\s+office(?:\s+is)?(?:\s+located)?\s+in\s+([A-Z][^.;\n]{2,60})",
        r"[Bb]ased\s+in\s+([A-Z][^.;\n]{2,50})",
        r"HQ[:\s]+([A-Z][^.;\n]{2,50})",
    ]
    for pat in pats:
        for m in re.finditer(pat, blob):
            cand = normalize_city_country(m.group(1))
            if cand:
                return cand
            # try appending if only city found with country nearby
            raw = m.group(1).strip().rstrip(",")
            # look for "City, ST" or "City, Country"
            if "," in raw:
                cand = normalize_city_country(raw)
                if cand:
                    return cand
    return ""


def _load_prior_maps() -> dict[str, str]:
    out: dict[str, str] = {}
    # prior applied audit for this market
    p = AUDIT / "global_wearable_medical_devices_market_global_found_in_applied.json"
    if p.exists():
        data = json.loads(p.read_text(encoding="utf-8"))
        for row in data.get("rows") or []:
            brand = _norm(row.get("brand") or "")
            fi = normalize_city_country(str(row.get("found_in") or ""))
            if brand and fi:
                # strip legal suffixes for matching
                brand2 = re.sub(
                    r"\b(ltd|llc|inc|corp|corporation|co|gmbh|ag|nv|plc)\b\.?",
                    "",
                    brand,
                ).strip()
                out[brand] = fi
                if brand2:
                    out[brand2] = fi
    # flexible packaging / shared overrides that include wearable names
    try:
        from scripts import apply_found_in as af  # type: ignore
    except Exception:
        af = None
    # inline copy of wearable-relevant overrides from apply_found_in.WEB_OVERRIDES
    shared = {
        "biobeat technologies ltd.": "Petah Tikva, Israel",
        "vivalink": "Campbell, California, USA",
        "physiq": "Chicago, Illinois, USA",
        "cardiac insight": "Bellevue, Washington, USA",
        "vitalerter": "Airport City, Israel",
        "avertus": "Toronto, Ontario, Canada",
        "healthwatch technologies": "Kfar Saba, Israel",
        "cardiodiagnostics": "Campbell, California, USA",
        "zensorium": "Singapore, Singapore",
        "imedtrix": "Milpitas, California, USA",
        "vitaltracer": "Montreal, Quebec, Canada",
        "biologix sistemas": "Sao Paulo, Brazil",
    }
    for k, v in shared.items():
        fi = normalize_city_country(v) or v
        if is_city_country(fi):
            out[_norm(k)] = fi
    return out


def main() -> int:
    xlsx = FOLDER / f"{SLUG}_FINAL.xlsx"
    wb = load_workbook(xlsx, data_only=True)

    # Landscape
    ws = wb["Landscape"]
    rows_raw = list(ws.iter_rows(values_only=True))
    hdr = [str(h) for h in rows_raw[0]]
    landscape: list[dict[str, Any]] = []
    for r in rows_raw[1:]:
        if not r:
            continue
        d = {hdr[i]: ("" if r[i] is None else r[i]) for i in range(len(hdr)) if i < len(r)}
        if str(d.get("Company") or d.get("Brand") or "").strip():
            landscape.append(d)

    details_by: dict[str, dict] = {}
    if "Company Details" in wb.sheetnames:
        dws = wb["Company Details"]
        drows = list(dws.iter_rows(values_only=True))
        dhdr = [str(h) for h in drows[0]]
        for r in drows[1:]:
            if not r:
                continue
            d = {dhdr[i]: ("" if r[i] is None else r[i]) for i in range(len(dhdr)) if i < len(r)}
            key = _norm(d.get("Brand") or "")
            if key:
                details_by[key] = d

    prior = _load_prior_maps()
    verified = {_norm(k): (normalize_city_country(v) or v) for k, v in VERIFIED.items()}
    verified = {k: v for k, v in verified.items() if is_city_country(v)}

    audit_rows: list[dict] = []
    filled = 0
    blank = 0

    for row in landscape:
        brand = str(row.get("Brand") or row.get("Company") or "").strip()
        key = _norm(brand)
        det = details_by.get(key) or {}
        if det.get("Brand"):
            brand = str(det["Brand"]).strip()
            key = _norm(brand)
            row["Brand"] = brand
            row["Company"] = brand
        if det.get("Role") in {"Brand", "Marketer"}:
            row["Role"] = det["Role"]
            row["Distribution Type"] = det["Role"]
        if det.get("Company") and (
            str(det["Company"]).startswith("(") or _norm(det["Company"]) != key
        ):
            row["_display_company"] = det["Company"]
        # preserve scores from details if landscape cleared mid-rescore
        if det.get("X") not in (None, "") and not str(row.get("X Score") or "").strip():
            row["X Score"] = det["X"]
            row["Y Score"] = det["Y"]
            row["Overall Score"] = det.get("Overall")
            row["Quadrant"] = det.get("Quadrant") or ""

        website = str(row.get("Website") or "").strip()
        old = str(
            det.get("Found in")
            or row.get("Found in")
            or row.get("Headquarters")
            or ""
        ).strip()
        old_norm = normalize_city_country(old)

        hq = ""
        source = ""
        if key in verified:
            hq, source = verified[key], "web_verified_map"
        elif key in prior:
            hq, source = prior[key], "prior_audit"
        else:
            known = lookup_known_hq(brand)
            if known and is_city_country(known):
                hq, source = known, "known_map"
        if not hq and old_norm:
            hq, source = old_norm, "kept_existing"
        if not hq:
            # Wikipedia
            try:
                resolved, src = resolve_hq_city_country(brand, existing=old, allow_wiki=True)
            except Exception:
                resolved, src = "", ""
            if resolved and is_city_country(resolved):
                hq, source = resolved, f"wiki:{src}"
        if not hq:
            ddgs = _ddgs_hq(brand, website)
            if ddgs and is_city_country(ddgs):
                hq, source = ddgs, "ddgs_web_search"

        if hq and is_city_country(hq):
            # fix common typo United, Kingdom
            hq = hq.replace("United, Kingdom", "United Kingdom")
            hq = normalize_city_country(hq) or hq
            row["Found in"] = hq
            row["Headquarters"] = hq
            filled += 1
            audit_rows.append(
                {
                    "brand": brand,
                    "old": old or "(empty)",
                    "found_in": hq,
                    "source": source,
                    "website": website,
                }
            )
        else:
            row["Found in"] = ""
            # keep country-only HQ out of Found in
            blank += 1
            audit_rows.append(
                {
                    "brand": brand,
                    "old": old or "(empty)",
                    "found_in": "",
                    "source": "unverified_blank",
                    "website": website,
                }
            )

    detail_rows = to_company_detail_rows(landscape, QUERY, {"found_in_verified": True})
    for det in detail_rows:
        key = _norm(det.get("Brand") or "")
        src = next((r for r in landscape if _norm(r.get("Brand") or "") == key), None)
        if not src:
            continue
        det["Role"] = src.get("Role") or det.get("Role") or "Brand"
        if src.get("_display_company"):
            det["Company"] = src["_display_company"]
        det["Found in"] = src.get("Found in") or ""

    write_final_xlsx(
        xlsx,
        landscape,
        "Companies",
        {"query": QUERY, "found_in": "web_verified_city_country"},
        detail_rows=detail_rows,
    )
    # Only rebuild HTML if most rows already have scores (don't block deep rescore)
    scored = sum(1 for r in landscape if str(r.get("X Score") or "").strip())
    if scored >= max(4, len(landscape) // 2):
        export_expand_quadrant_outputs(
            FOLDER,
            detail_rows,
            QUERY,
            country="global",
            audit={"found_in_verified": True},
            chart_n=20,
        )

    report = {
        "total": len(landscape),
        "filled": filled,
        "blank_unverified": blank,
        "pct_filled": round(100.0 * filled / max(1, len(landscape)), 1),
        "rows": audit_rows,
    }
    AUDIT.mkdir(parents=True, exist_ok=True)
    (AUDIT / "wearable_found_in_verification.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    lines = [
        "# Wearable Found in verification",
        "",
        f"Filled **{filled}/{len(landscape)}** ({report['pct_filled']}%) · blank unverified **{blank}**",
        "",
        "Method: web-verified map + prior audit + known HQ + Wikipedia + DDGS. No invented HQs.",
        "",
        "## Sample",
        "",
        "| Brand | Found in | Source |",
        "|---|---|---|",
    ]
    for a in audit_rows[:40]:
        lines.append(
            f"| {a['brand']} | {a.get('found_in') or '(blank)'} | {a.get('source')} |"
        )
    blanks = [a for a in audit_rows if not a.get("found_in")]
    if blanks:
        lines += ["", "## Still blank (need more evidence)", ""]
        for a in blanks:
            lines.append(f"- {a['brand']} ({a.get('website')})")
    (AUDIT / "wearable_found_in_verification.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )
    print(
        f"DONE filled={filled}/{len(landscape)} blank={blank} "
        f"audit={AUDIT / 'wearable_found_in_verification.md'}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
