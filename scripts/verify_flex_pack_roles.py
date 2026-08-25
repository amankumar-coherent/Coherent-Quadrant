"""Re-verify Brand vs Marketer for Global Flexible Packaging FINAL.

Rule (aligned with chatgpt_expand packaging verifier, clarified):
  Brand    = primary flexible packaging CONVERTER — prints/laminates/forms pouches,
             bags, lids, tubes sold to CPG/brand owners under its company name.
  Marketer = markets packaging FILM / barrier / specialty material brands, OR is
             mainly a base-film producer (BOPP/BOPET/CPP rolls sold to converters),
             OR a chemical specialty materials firm marketing film grades —
             not primarily a finished-pack converter.

Uses DeepSeek (.env) in batches, then rewrites Role + Distribution Type + Details.
"""
from __future__ import annotations

import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, _, v = line.partition("=")
    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

from openpyxl import load_workbook

from vendor_intel.pipeline.expand_quadrant_score import (
    export_expand_quadrant_outputs,
    to_company_detail_rows,
)
from vendor_intel.pipeline.web_expand import write_final_xlsx
from vendor_intel.placeholders import llm as llm_mod

SLUG = "global_flexible_packaging_market_global"
QUERY = "Global Flexible Packaging Market"
OUT = ROOT / "output" / "chatgpt_expand" / SLUG
XLSX = OUT / f"{SLUG}_FINAL.xlsx"
CACHE = OUT / "_role_verify_cache.jsonl"

# Deterministic Marketer stems (specialty film / chemical / base-film marketers)
MARKETER_STEMS = {
    # Specialty barrier / medical film brand marketers
    "honeywell",
    "aclar",
    "kuraray",
    "eval",
    "mitsui chemicals",
    "mitsubishi chemical",
    "mitsubishi gas chemical",
    "mitsubishi polyester film",
    "mylar specialty",
    "3m scotchpak",
    "scotchpak",
    "dupont tyvek",
    "tyvek",
    "soarus",
    "soarnol",
    "nippon gohsei",
    "mx-nylon",
    "plantic",
    # Base film producers (sell film rolls to converters) — Marketer
    "cosmo films",
    "cosmo first",
    "polyplex",
    "taghleef",
    "jindal films",
    "jindal poly films",
    "innovia",
    "treofan",
    "ester industries",
    "ester filmtech",
    "thai film industries",
    "srf limited",
    "srf ",
    "chiripal poly",
    "vacmet",
    "garware",
    "skc",
    "kolon industries films",
    "kolon industries",
    "hyosung chemical",
    "nan ya plastics",
    "shinkong",
    "far eastern new century",
    "formosa idemitsu",
    "toray advanced film",
    "toray industries",  # advanced materials / films parent marketer vs converter
    "toyobo",
    "unitika",
    "futamura",
    "okura industrial",
    "asahi kasei packaging",
    "celplast",
    "plastic suppliers",
    "danafilms",
    "polifilm",  # PE/PP film extruder selling film
    "folienwerk wolfen",
    "buergofol",
    "allvac folien",
    "wentus",
    "folien fischer",
    "rkw",  # specialty films marketer/producer
    "sigma stretch",
    "charter next generation",  # specialty films / material science
    "cng",
    "max speciality films",
    "toppan speciality films",
    "indorama ventures packaging films",
    "advanced film company",
    "pt trias sentosa",
    "pt argha karya",
    "jiangsu shuangxing",
    "gettel high-tech",
    "hubei firsta",
    "kangde xin",
    "huangshan novel",  # often converter+film — LLM may override; keep stem soft
    "vitopel",  # BOPP film producer LatAm
    "biofilm",  # BOPP film Colombia
    "al khaleej polypropylene",
    "gulf packaging industries",  # BOPP/CPP films
    "flex films",
    "uflex packaging films",
    "polyplex thailand",
    "jindal poly films nashik",
    "vacmet india",
    "mitsui",
    "kureha",  # Krehalon barrier films specialty
    "sumitomo bakelite",  # specialty films/materials
}

# Explicit Brand converters (always Brand even if stem overlaps)
BRAND_STEMS = {
    "amcor",
    "constantia",
    "proampac",
    "printpack",
    "coveris",
    "schur flexibles",
    "südpack",
    "sudpack",
    "wipak",
    "goglio",
    "glenroy",
    "epac",
    "bryce",
    "interflex",
    "ppc flexible",
    "flair flexible",
    "emerald packaging",
    "american packaging",
    "c-p flexible",
    "parkside",
    "paharpur 3p",
    "bilcare",
    "epl limited",
    "essel",
    "clondalkin",
    "bischof",
    "huhtamaki",
    "mondi",
    "sealed air",
    "sonoco",
    "winpak",
    "transcontinental",
    "tcpl",
    "novolex",
    "pactiv",
    "berry global",
    "bemis",
    "ampac holdings",
    "aluflexpack",
    "flexopack",  # Greek converter
    "wipf ag",
    "fabbri",
    "saica flex",
    "gascogne flexible",
    "oliver healthcare",
    "st. johns packaging",
    "shield pack",
    "swiss pac",
    "cadillac products",
    "clear lam",
    "mpact flexible",
    "arabian flexible packaging",
    "zaraplast",
    "plastilene",
    "takween",
    "scientex",
    "uflex ltd",
    "uflex ltd.",
}


def _norm(s: str) -> str:
    s = str(s or "").strip().lower()
    s = s.replace("ö", "o").replace("ü", "u").replace("ä", "a")
    return re.sub(r"\s+", " ", s)


def heuristic_role(name: str, cats: str = "", specialty: str = "") -> str | None:
    blob = _norm(f"{name} {cats} {specialty}")
    for stem in sorted(BRAND_STEMS, key=len, reverse=True):
        if stem in blob:
            return "Brand"
    for stem in sorted(MARKETER_STEMS, key=len, reverse=True):
        if stem in blob:
            return "Marketer"
    # category heuristics
    if any(
        x in blob
        for x in (
            "bopp film",
            "bopet film",
            "cpp film",
            "polyester film",
            "base film",
            "specialty film producer",
            "film manufacturer",
            "evoh",
            "barrier resin",
            "barrier film brand",
        )
    ) and not any(
        x in blob
        for x in ("pouch", "converter", "laminat", "printing", "gravure", "flexo print")
    ):
        return "Marketer"
    if any(
        x in blob
        for x in (
            "pouch",
            "converter",
            "laminat",
            "stand-up",
            "standup",
            "retort pouch",
            "flexible packaging converter",
        )
    ):
        return "Brand"
    return None


SYSTEM = """Classify each company as Brand or Marketer for the Global Flexible Packaging Market.
Return JSON: {"items":[{"i":0,"role":"Brand"|"Marketer","reason":"short"}]}

Definitions:
- Brand = primarily a FLEXIBLE PACKAGING CONVERTER: prints, laminates, and/or forms finished
  pouches/bags/lids/tubes sold to CPG or brand owners under its company name
  (Amcor, Constantia, ProAmpac, Printpack, Coveris, ePac, Bryce, Glenroy, Schur, Südpack, Wipak).
- Marketer = primarily markets packaging FILM / barrier / specialty material brands, OR mainly
  produces base films (BOPP/BOPET/CPP/metallized rolls) sold to converters, OR is a chemical/
  specialty materials firm marketing film grades (Honeywell Aclar, Kuraray EVAL, Cosmo Films,
  Polyplex, Taghleef, Innovia, Treofan, SRF films, Toray films, 3M Scotchpak, DuPont Tyvek).

Pick exactly one role per company. Prefer Marketer when the company is mainly a film-roll
supplier; prefer Brand when mainly a finished-pack converter.
"""


def load_landscape() -> list[dict]:
    wb = load_workbook(XLSX, data_only=True)
    ws = wb["Landscape"]
    rows = list(ws.iter_rows(values_only=True))
    hdr = [str(h) for h in rows[0]]
    out = []
    for r in rows[1:]:
        d = {hdr[i]: ("" if r[i] is None else str(r[i])) for i in range(len(hdr)) if i < len(r)}
        if d.get("Company"):
            out.append(d)
    return out


def load_cache() -> dict[str, str]:
    cache: dict[str, str] = {}
    if CACHE.exists():
        for line in CACHE.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            if o.get("company") and o.get("role") in ("Brand", "Marketer"):
                cache[_norm(o["company"])] = o["role"]
    return cache


def append_cache(company: str, role: str, reason: str = "") -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    with CACHE.open("a", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {"company": company, "role": role, "reason": reason},
                ensure_ascii=False,
            )
            + "\n"
        )


def llm_batch(batch: list[tuple[int, dict]]) -> dict[int, str]:
    payload = {
        "items": [
            {
                "i": i,
                "company": d.get("Company"),
                "categories": (d.get("Core Categories") or "")[:180],
                "specialty": (d.get("Specialty Focus") or "")[:120],
                "summary": (d.get("Summary") or "")[:160],
            }
            for i, d in batch
        ]
    }
    raw = llm_mod.llm_complete_json(SYSTEM, json.dumps(payload, ensure_ascii=False), max_tokens=2000)
    out: dict[int, str] = {}
    if not isinstance(raw, dict):
        return out
    for item in raw.get("items") or []:
        if not isinstance(item, dict):
            continue
        try:
            i = int(item.get("i"))
        except (TypeError, ValueError):
            continue
        role = str(item.get("role") or "").strip()
        if role in ("Brand", "Marketer"):
            out[i] = role
    return out


def main() -> None:
    landscape = load_landscape()
    cache = load_cache()
    roles: dict[int, str] = {}
    need_llm: list[tuple[int, dict]] = []

    for i, d in enumerate(landscape):
        name = str(d.get("Company") or "")
        nk = _norm(name)
        # heuristic first
        h = heuristic_role(
            name,
            str(d.get("Core Categories") or ""),
            str(d.get("Specialty Focus") or ""),
        )
        if h:
            roles[i] = h
            continue
        if nk in cache:
            roles[i] = cache[nk]
            continue
        need_llm.append((i, d))

    print(f"total={len(landscape)} heuristic/cache={len(roles)} llm={len(need_llm)}")

    # batch LLM
    B = 12
    with ThreadPoolExecutor(max_workers=3) as ex:
        futs = []
        for start in range(0, len(need_llm), B):
            chunk = need_llm[start : start + B]
            futs.append(ex.submit(llm_batch, chunk))
        for fut in as_completed(futs):
            got = fut.result()
            roles.update(got)

    # fill remaining defaults + cache writes
    changed = []
    brand_n = marketer_n = 0
    for i, d in enumerate(landscape):
        old = str(d.get("Role") or d.get("Distribution Type") or "")
        role = roles.get(i) or heuristic_role(str(d.get("Company") or ""), str(d.get("Core Categories") or ""), "") or "Brand"
        if role not in ("Brand", "Marketer"):
            role = "Brand"
        d["Role"] = role
        d["Distribution Type"] = role
        append_cache(str(d.get("Company")), role)
        if role != old:
            changed.append({"company": d.get("Company"), "from": old, "to": role})
        if role == "Brand":
            brand_n += 1
        else:
            marketer_n += 1

    audit = {}
    ap = OUT / "chatgpt_expand_batch_all_audit.json"
    if ap.exists():
        audit = json.loads(ap.read_text(encoding="utf-8")).get("xy_scoring") or {}

    details = to_company_detail_rows(landscape, QUERY, audit)
    by = {_norm(r.get("Company") or ""): r.get("Role") for r in landscape}
    for det in details:
        role = by.get(_norm(det.get("Brand") or "")) or by.get(_norm(det.get("Company") or ""))
        if role in ("Brand", "Marketer"):
            det["Role"] = role

    write_final_xlsx(
        XLSX,
        landscape,
        "Companies",
        {
            "query": QUERY,
            "role_split": True,
            "brand": brand_n,
            "marketer": marketer_n,
            "role_verify": "2026-08-14",
        },
        detail_rows=details,
    )
    extras = export_expand_quadrant_outputs(
        OUT, details, QUERY, country="global", audit=audit, chart_n=20
    )

    report = {
        "brand": brand_n,
        "marketer": marketer_n,
        "changed": changed,
        "marketers": [d.get("Company") for d in landscape if d.get("Role") == "Marketer"],
        "html": str(extras.get("html") or ""),
    }
    outp = ROOT / "output" / "chatgpt_expand" / "_audit" / f"{SLUG}_role_verify.json"
    outp.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Brand={brand_n} Marketer={marketer_n} changed={len(changed)}")
    print("Marketers:")
    for m in report["marketers"]:
        print(" -", m)
    print("audit ->", outp)


if __name__ == "__main__":
    main()
