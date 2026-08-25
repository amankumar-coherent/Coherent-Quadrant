"""Verify every Brand column name belongs in Global Flexible Packaging market.

KEEP: flexible packaging converters, base-film producers, specialty packaging film brands.
DROP: machinery-only, corrugated/carton-only, pulp-only, automotive film-only,
      unverified placeholder names, regional clones when parent already listed.
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

# Deterministic DROP — not flexible-packaging Brand/Marketer players
DROP_STEMS = {
    # Wrong vertical
    "syntegon",  # packaging machinery, not flex-pack products
    "ccl secure",  # banknote / security polymer films, not flex pack market
    "innovia security",
    "graphic packaging",  # paperboard cartons; not flex pack core
    "empresas cmpc",  # pulp/paper/tissue core
    "visy industries",  # corrugated / recycling core
    "nampak",  # rigid metal/glass/plastic Africa core
    "pact group",  # rigid plastics / recycling AU core
    "detmold",  # paper foodservice core
    "itc limited",  # FMCG conglomerate; packaging = paperboard mainly
    "oji holdings",  # paper parent (Walki already listed as flex brand)
    "asia pulp",  # pulp/paper
    "sinar mas packaging",
    "sappi",  # specialty paper mill — not flex pack converter/film OEM
    "ahlstrom packaging papers",  # duplicate of Ahlstrom; paper substrate only OK once
    "rollatainers",  # folding cartons focus
    "kyoraku",  # blow-molding / rigid plastics focus
    "sumitomo bakelite",  # semiconductor / specialty plastics — weak flex pack
    "garware polyester",  # automotive PPF / window films primary
    "garware hi-tech",  # same
    "polifilm protection",  # surface protection films, not packaging
    "rkw reroll / agricultural",  # ag films duplicate of RKW
    "time technoplast",  # FIBC industrial bulk — edge; drop for consumer flex pack purity
    "flexible packaging solutions (fps)",  # FIBC industrial
    "polyspin exports",  # FIBC
    # Unverified / placeholder-ish names from expansion
    "phoenix flexible packaging",
    "hfm packaging",
    "sun packaging technologies",
    "packaging india pvt",
    "pipl",
    "schmelzer flexible",
    "vf verpackungen",
    "pechiney plastic packaging legacy",
    # Regional clones (parent already in landscape)
    "wipak uk",
    "südpack ibérica",
    "sudpack iberica",
    "coveris flexibles austria",
    "huhtamaki flexible packaging global",
    "huhtamaki india",
    "mondi kraft paper",
    "clondalkin flexible packaging europe",
    "novolex bag & film brands",
    "pactiv food merchandising",
    "reynolds food wrap",
    "walki consumer packaging",
    "uflex packaging films india",
    "tcpl flexible packaging plants",
    "ahlstrom packaging papers",
}

# Keep even if stem overlaps DROP (exact exceptions)
KEEP_FORCE = {
    "amcor plc",
    "bemis company",  # acquired flex brand — market-related
    "walki group",
    "ahlstrom",  # fiber materials for flex pack — keep once
    "rkw group",
    "polifilm",  # film producer — keep (not Protection)
    "tcpl packaging ltd.",  # wait we're dropping carton focus
}


def _norm(s: str) -> str:
    s = str(s or "").strip().lower()
    s = s.replace("ö", "o").replace("ü", "u").replace("ä", "a").replace("ß", "ss")
    s = re.sub(r"[+/|&,_.:\-()]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def deterministic_drop(name: str) -> str | None:
    n = _norm(name)
    if n in KEEP_FORCE or any(k == n for k in KEEP_FORCE):
        return None
    for stem in sorted(DROP_STEMS, key=len, reverse=True):
        if stem in n:
            # don't drop Polifilm main when only Protection should drop
            if stem == "polifilm" and "protection" not in n:
                continue
            if stem == "ahlstrom" and "packaging papers" not in n:
                continue
            return f"drop_stem:{stem}"
    return None


SYSTEM = """You verify whether each company belongs in the Global Flexible Packaging Market landscape.
Return JSON only: {"items":[{"i":0,"keep":true|false,"reason":"short"}]}

KEEP if the company manufactures or markets flexible packaging products:
films, pouches, bags, laminates, barrier wraps, lids, tubes, BOPP/BOPET/CPP packaging films,
specialty packaging film brands (Aclar, EVAL, Scotchpak, Tyvek medical packaging).

DROP if primarily: packaging machinery only; corrugated boxes only; folding cartons only;
pulp/paper mills without flex film/pouch business; automotive paint-protection films only;
surface protection films only; FIBC-only industrial bulk bags; CPG brands that only BUY packaging;
retailers; consultancies; unverified placeholders; pure banknote/security films.

When unsure but they clearly sell flexible packaging films or converted flex packs, KEEP.
"""


def llm_batch(batch: list[tuple[int, dict]]) -> dict[int, bool]:
    payload = {
        "items": [
            {
                "i": i,
                "brand": d.get("Company"),
                "role": d.get("Role"),
                "categories": (d.get("Core Categories") or "")[:160],
                "summary": (d.get("Summary") or "")[:140],
            }
            for i, d in batch
        ]
    }
    raw = llm_mod.llm_complete_json(
        SYSTEM, json.dumps(payload, ensure_ascii=False), max_tokens=1800
    )
    out: dict[int, bool] = {}
    if not isinstance(raw, dict):
        return out
    for item in raw.get("items") or []:
        if not isinstance(item, dict):
            continue
        try:
            i = int(item.get("i"))
        except (TypeError, ValueError):
            continue
        if "keep" in item:
            out[i] = bool(item.get("keep"))
    return out


def main() -> None:
    wb = load_workbook(XLSX, data_only=True)
    ws = wb["Landscape"]
    rows = list(ws.iter_rows(values_only=True))
    hdr = [str(h) for h in rows[0]]
    landscape = []
    for r in rows[1:]:
        d = {hdr[i]: ("" if r[i] is None else str(r[i])) for i in range(len(hdr)) if i < len(r)}
        if d.get("Company"):
            landscape.append(d)

    dropped: list[dict] = []
    kept: list[dict] = []
    need_llm: list[tuple[int, dict]] = []

    for i, d in enumerate(landscape):
        reason = deterministic_drop(str(d.get("Company") or ""))
        if reason:
            dropped.append({"brand": d.get("Company"), "role": d.get("Role"), "reason": reason})
            continue
        need_llm.append((i, d))
        kept.append(d)  # provisional; LLM may remove

    # LLM only on provisional kept — re-filter
    provisional = list(kept)
    kept = []
    llm_drop_idx: set[int] = set()

    print(f"before={len(landscape)} deterministic_drop={len(dropped)} llm_check={len(provisional)}")

    B = 15
    decisions: dict[int, bool] = {}
    # map provisional position -> original index via need_llm
    with ThreadPoolExecutor(max_workers=3) as ex:
        futs = []
        for start in range(0, len(need_llm), B):
            futs.append(ex.submit(llm_batch, need_llm[start : start + B]))
        for fut in as_completed(futs):
            decisions.update(fut.result())

    for i, d in need_llm:
        keep = decisions.get(i, True)  # default KEEP if LLM missed
        if keep:
            kept.append(d)
        else:
            dropped.append(
                {
                    "brand": d.get("Company"),
                    "role": d.get("Role"),
                    "reason": "llm_drop",
                }
            )
            llm_drop_idx.add(i)

    # Ensure Brand/Marketer only
    final = []
    for d in kept:
        role = str(d.get("Role") or d.get("Distribution Type") or "Brand")
        if role not in ("Brand", "Marketer"):
            role = "Brand"
        d["Role"] = role
        d["Distribution Type"] = role
        final.append(d)

    brand_n = sum(1 for d in final if d.get("Role") == "Brand")
    marketer_n = sum(1 for d in final if d.get("Role") == "Marketer")

    audit = {}
    ap = OUT / "chatgpt_expand_batch_all_audit.json"
    if ap.exists():
        audit = json.loads(ap.read_text(encoding="utf-8")).get("xy_scoring") or {}

    details = to_company_detail_rows(final, QUERY, audit)
    by = {_norm(r.get("Company") or ""): r.get("Role") for r in final}
    for det in details:
        role = by.get(_norm(det.get("Brand") or "")) or by.get(_norm(det.get("Company") or ""))
        if role in ("Brand", "Marketer"):
            det["Role"] = role

    write_final_xlsx(
        XLSX,
        final,
        "Companies",
        {
            "query": QUERY,
            "brand_market_verify": True,
            "brand": brand_n,
            "marketer": marketer_n,
            "after": len(final),
        },
        detail_rows=details,
    )
    extras = export_expand_quadrant_outputs(
        OUT, details, QUERY, country="global", audit=audit, chart_n=20
    )

    report = {
        "before": len(landscape),
        "after": len(final),
        "removed": len(dropped),
        "brand": brand_n,
        "marketer": marketer_n,
        "dropped": dropped,
        "kept_brands": [d.get("Company") for d in final],
        "html": str(extras.get("html") or ""),
    }
    outp = (
        ROOT
        / "output"
        / "chatgpt_expand"
        / "_audit"
        / f"{SLUG}_brand_market_verify.json"
    )
    outp.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(
        f"DONE before={report['before']} after={report['after']} "
        f"removed={report['removed']} Brand={brand_n} Marketer={marketer_n}"
    )
    print("Dropped:")
    for x in dropped:
        print(f"  - {x['brand']} [{x['role']}] ({x['reason']})")
    print("audit ->", outp)


if __name__ == "__main__":
    main()
