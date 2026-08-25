"""Verify + fix Global Flexible Packaging FINAL: ownership, brands, roles, duplicates.

Web-verified Aug 2026. Updates Landscape Ownership / names / roles, rebuilds
Company Details + quadrant HTML.
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

SLUG = "global_flexible_packaging_market_global"
QUERY = "Global Flexible Packaging Market"
OUT = ROOT / "output" / "chatgpt_expand" / SLUG
XLSX = OUT / f"{SLUG}_FINAL.xlsx"


def _norm(s: str) -> str:
    s = str(s or "").strip().lower()
    s = s.replace("ö", "o").replace("ü", "u").replace("ä", "a").replace("ß", "ss")
    s = re.sub(r"[+/|&,_.:\-]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _stem(s: str) -> str:
    s = _norm(s)
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"\b(inc|llc|ltd|limited|plc|gmbh|ag|sa|co|corp|corporation|group|holdings?)\b", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# Exact / stem removals (off flexible-packaging market OR wrong role)
# KEEP = film converters / pouch makers / packaging film producers (Brand)
#        or specialty film brand marketers (Marketer: Aclar, EVAL, chem parents)
REMOVE_STEMS = {
    # Prior
    "ds smith",  # corrugated / paper (International Paper)
    "samyang",  # PET bottles / aseptic — rigid
    # Wrong industry
    "dongil industries",  # Pohang steel bars / ferroalloys — not packaging
    "orora",  # now glass + beverage cans only (sold OPS Dec 2024)
    "tetra pak",  # aseptic carton systems — not flexible film/pouch market
    # Wrong role (not Brand/Marketer manufacturer)
    "flex pack engineering",  # consulting / lab only — does not manufacture
    "flex-pack engineering",
    # Regional arms when parent already listed (gate: drop_regional_of_parent)
    "flex america",  # UFlex regional Marketer
    "flex middle east",  # UFlex regional Marketer
    "flex films usa",  # UFlex film plant / regional
    "flex films (usa)",
    "toray plastics america",  # Toray Industries already listed
    "toray plastics (america)",
}

# Canonical rename: stem -> new Company display name
RENAME = {
    "mondi group": "Mondi plc",
    "mondi plc": "Mondi plc",
    "tcpl packaging ltd": "TCPL Packaging Ltd.",
    "tcpl packaging limited": "TCPL Packaging Ltd.",
    "transcontinental inc": "Transcontinental Inc. (TC Transcontinental)",
    "transcontinental inc tc transcontinental": "Transcontinental Inc. (TC Transcontinental)",
    "reynolds consumer products llc": "Reynolds Consumer Products",
    "reynolds consumer products": "Reynolds Consumer Products",
    "plastrela": "Plastrela Embalagens Ltda.",
    "plastrela embalagens ltda": "Plastrela Embalagens Ltda.",
    "polifilm embalagens": "Polifilm",
    "polifilm": "Polifilm",
    "klockner pentaplast group": "Klöckner Pentaplast Group",
    "klöckner pentaplast group": "Klöckner Pentaplast Group",
    "uflex ltd": "UFlex Ltd.",
    "uflex ltd.": "UFlex Ltd.",
    "essel propack epl limited": "EPL Limited (Essel Propack)",
    "epl limited essel propack": "EPL Limited (Essel Propack)",
    "asia pulp paper sinar mas packaging": "Asia Pulp & Paper (Sinar Mas)",
    "sinar mas packaging": "Asia Pulp & Paper (Sinar Mas)",
    "bischof klein uk": "Bischof + Klein SE & Co. KG",
    "bischof klein se co kg": "Bischof + Klein SE & Co. KG",
    "rpc group now part of berry global": "RPC Group",
    "rpc group": "RPC Group",
}

# Prefer keeping these when deduping (stem of keep-name)
DEDUP_FAMILY = {
    "mondi": "mondi plc",
    "tcpl packaging": "tcpl packaging ltd",
    "transcontinental": "transcontinental inc tc transcontinental",
    "reynolds consumer": "reynolds consumer products",
    "plastrela": "plastrela embalagens ltda",
    "polifilm": "polifilm",
    "klockner pentaplast": "klöckner pentaplast group",
    "klöckner pentaplast": "klöckner pentaplast group",
    "bischof klein": "bischof klein se co kg",
    "asia pulp": "asia pulp paper sinar mas",
    "sinar mas packaging": "asia pulp paper sinar mas",
    "oji f tex": "oji holdings corporation",  # fold subsidiary into parent
    "oji holdings": "oji holdings corporation",
}

# Ownership overrides: stem -> (Ownership text, ownership_relation)
# Ownership text must start with acquired by / subsidiary of / merged into / owned by
# for Company Details to show the parent annotation.
OWNERSHIP: dict[str, tuple[str, str]] = {
    # Completed deals
    "bemis company": ("acquired by Amcor plc", "acquired_by"),
    "berry global group": ("acquired by Amcor plc", "acquired_by"),
    "berry global": ("acquired by Amcor plc", "acquired_by"),
    "aep industries": ("acquired by Berry Global; ultimate parent Amcor plc", "acquired_by"),
    "rpc group now part of berry global": (
        "acquired by Berry Global; ultimate parent Amcor plc",
        "acquired_by",
    ),
    "rpc group": ("acquired by Berry Global; ultimate parent Amcor plc", "acquired_by"),
    "rpc bpi british polythene industries": (
        "acquired by Berry Global; ultimate parent Amcor plc",
        "acquired_by",
    ),
    "rpc bpi": ("acquired by Berry Global; ultimate parent Amcor plc", "acquired_by"),
    "nordfolien": ("acquired by RPC Group; now part of Amcor via Berry", "acquired_by"),
    "ampac holdings": ("acquired by ProAmpac LLC", "acquired_by"),
    "aluflexpack": ("acquired by Constantia Flexibles", "acquired_by"),
    "innovia films": ("acquired by CCL Industries", "acquired_by"),
    "walki group": ("acquired by Oji Holdings Corporation", "acquired_by"),
    "walki": ("acquired by Oji Holdings Corporation", "acquired_by"),
    "al khaleej polypropylene": ("acquired by Taghleef Industries", "acquired_by"),
    "selig group": ("acquired by CC Industries", "acquired_by"),
    "alucoat": ("acquired by Grupo Alibérico", "acquired_by"),
    "pactiv evergreen": ("acquired by Novolex Holdings, LLC", "acquired_by"),
    # Subsidiaries / group (not classic third-party acquisitions)
    "flex films usa": ("subsidiary of UFlex Limited", "subsidiary_of"),
    "flex films": ("subsidiary of UFlex Limited", "subsidiary_of"),
    "flex america": ("subsidiary of UFlex Limited", "subsidiary_of"),
    "flex middle east": ("subsidiary of UFlex Limited", "subsidiary_of"),
    "toray plastics": ("subsidiary of Toray Industries, Inc.", "subsidiary_of"),
    "al watania plastics": ("subsidiary of Al Watania for Industries", "subsidiary_of"),
    "asia pulp paper sinar mas": ("subsidiary of Sinar Mas Group", "subsidiary_of"),
    "asia pulp": ("subsidiary of Sinar Mas Group", "subsidiary_of"),
    "wipak": ("subsidiary of Wihuri Group", "subsidiary_of"),
    "jindal films": ("subsidiary of B.C. Jindal Group", "subsidiary_of"),
    "oji f tex": ("subsidiary of Oji Holdings Corporation", "subsidiary_of"),
    # Canonical brand cleanup for RPC
    # (handled via RENAME below)
    # EPL: Indorama 51.8% merger NOT closed as of Aug 2026 — Blackstone still control
    "epl limited essel propack": (
        "acquired by Blackstone (Indorama Ventures ~24.9% minority; Indorama majority merger pending)",
        "acquired_by",
    ),
    "essel propack epl limited": (
        "acquired by Blackstone (Indorama Ventures ~24.9% minority; Indorama majority merger pending)",
        "acquired_by",
    ),
    "epl limited": (
        "acquired by Blackstone (Indorama Ventures ~24.9% minority; Indorama majority merger pending)",
        "acquired_by",
    ),
    # Reynolds: public (NASDAQ: REYN); Rank Group majority control — clear false self-acquisition
    "reynolds consumer products": (
        "Public (majority controlled by Rank Group Limited / Graeme Hart)",
        "",
    ),
}

# Role overrides (Brand | Marketer) — only for rows we KEEP
ROLE: dict[str, str] = {
    "honeywell": "Marketer",
    "kuraray": "Marketer",
    "mitsubishi chemical": "Marketer",
    "mitsui chemicals": "Marketer",
}

# After rename, drop exact duplicates by stem (keep higher Overall, then annotated ownership)
KEEP_PREFER_ANNOTATED = True


def _match_key(name: str, table: dict) -> str | None:
    # Strip parentheticals so "RPC Group (now part of Berry Global)" does not
    # match the Berry Global ownership key.
    n = _norm(re.sub(r"\([^)]*\)", " ", str(name or "")))
    n = re.sub(r"\s+", " ", n).strip()
    best = None
    best_len = -1
    for k in table:
        if k in n and len(k) > best_len:
            best = k
            best_len = len(k)
    return best


def _family_key(name: str) -> str:
    n = _norm(name)
    for fam, group in sorted(DEDUP_FAMILY.items(), key=lambda x: -len(x[0])):
        if fam in n:
            return group  # canonical family id
    return _stem(name)


def main() -> None:
    wb = load_workbook(XLSX, data_only=True)
    land_ws = wb["Landscape"]
    land_rows = list(land_ws.iter_rows(values_only=True))
    hdr = [str(h) for h in land_rows[0]]
    landscape: list[dict] = []
    for r in land_rows[1:]:
        if not r:
            continue
        d = {
            hdr[i]: ("" if r[i] is None else r[i])
            for i in range(len(hdr))
            if i < len(r)
        }
        if str(d.get("Company") or "").strip():
            landscape.append(d)

    report: dict = {
        "removed": [],
        "renamed": [],
        "ownership_fixed": [],
        "role_fixed": [],
        "deduped": [],
        "before": len(landscape),
    }

    # 1) Remove off-market
    kept: list[dict] = []
    for row in landscape:
        name = str(row.get("Company") or "")
        nk = _norm(name)
        drop = False
        for stem in REMOVE_STEMS:
            if stem in nk:
                report["removed"].append({"brand": name, "reason": f"off_market:{stem}"})
                drop = True
                break
        if not drop:
            kept.append(row)
    landscape = kept

    # 2) Rename + ownership + role
    for row in landscape:
        name = str(row.get("Company") or "").strip()
        rk = _match_key(name, RENAME)
        if rk:
            new_name = RENAME[rk]
            if new_name != name:
                report["renamed"].append({"from": name, "to": new_name})
                row["Company"] = new_name
                name = new_name

        ok = _match_key(name, OWNERSHIP)
        if ok:
            own, rel = OWNERSHIP[ok]
            old = str(row.get("Ownership") or "")
            if old != own:
                report["ownership_fixed"].append(
                    {"brand": name, "from": old, "to": own, "relation": rel}
                )
            row["Ownership"] = own
            row["ownership_relation"] = rel
            row["parent_owner"] = ""
            if rel:
                m = re.match(
                    r"(?i)^\s*(?:acquired by|subsidiary of|merged into|owned by)\s+(.+?)\s*$",
                    own,
                )
                if m:
                    row["parent_owner"] = m.group(1).strip()
            else:
                # Clear any prior parent so Company Details does not invent acquisition
                row.pop("parent_owner", None)
                row["ownership_relation"] = ""

        role_k = _match_key(name, ROLE)
        if role_k:
            new_role = ROLE[role_k]
            old_role = str(row.get("Role") or row.get("Distribution Type") or "")
            if old_role != new_role:
                report["role_fixed"].append(
                    {"brand": name, "from": old_role, "to": new_role}
                )
            row["Role"] = new_role
            row["Distribution Type"] = new_role
        else:
            # default Brand unless already Marketer from known list
            cur = str(row.get("Distribution Type") or row.get("Role") or "Brand")
            if cur not in ("Brand", "Marketer"):
                cur = "Brand"
            row["Role"] = cur
            row["Distribution Type"] = cur

    # 3) Deduplicate families
    by_fam: dict[str, list[dict]] = {}
    for row in landscape:
        fam = _family_key(str(row.get("Company") or ""))
        by_fam.setdefault(fam, []).append(row)

    final_rows: list[dict] = []
    for fam, rows in by_fam.items():
        if len(rows) == 1:
            final_rows.append(rows[0])
            continue
        prefer = fam  # fam is already the preferred canonical stem from DEDUP_FAMILY values
        scored = []
        for r in rows:
            nm = _norm(str(r.get("Company") or ""))
            score = 0
            if prefer and prefer in nm:
                score += 100
            # Prefer independent parent over pure subsidiary when folding
            own = str(r.get("Ownership") or "").lower()
            if "subsidiary of" in own and prefer in nm and "subsidiary" not in prefer:
                score -= 20
            if any(x in own for x in ("acquired", "subsidiary", "owned by", "merged")):
                score += 5
            try:
                score += int(float(r.get("Overall Score") or 0))
            except (TypeError, ValueError):
                pass
            score += min(len(str(r.get("Company") or "")), 40) // 10
            scored.append((score, r))
        scored.sort(key=lambda x: -x[0])
        chosen = scored[0][1]

        for r in rows:
            if r is not chosen:
                report["deduped"].append(
                    {
                        "kept": str(chosen.get("Company")),
                        "dropped": str(r.get("Company")),
                        "family": fam,
                    }
                )
        final_rows.append(chosen)

    landscape = final_rows

    # Ensure Marketer stems still Marketer after renames
    for row in landscape:
        blob = _norm(str(row.get("Company") or ""))
        for stem, role in ROLE.items():
            if stem in blob:
                row["Role"] = role
                row["Distribution Type"] = role

    brand_n = sum(
        1 for r in landscape if str(r.get("Role") or "") == "Brand"
    )
    marketer_n = sum(
        1 for r in landscape if str(r.get("Role") or "") == "Marketer"
    )

    audit_path = OUT / "chatgpt_expand_batch_all_audit.json"
    audit: dict = {}
    if audit_path.exists():
        audit = json.loads(audit_path.read_text(encoding="utf-8")).get("xy_scoring") or {}

    detail_rows = to_company_detail_rows(landscape, QUERY, audit)
    # Force Role from landscape
    by_co = {_norm(str(r.get("Company") or "")): str(r.get("Role") or "Brand") for r in landscape}
    for d in detail_rows:
        role = by_co.get(_norm(d.get("Brand") or "")) or by_co.get(
            _norm(d.get("Company") or "")
        )
        if role in ("Brand", "Marketer"):
            d["Role"] = role

    write_final_xlsx(
        XLSX,
        landscape,
        "Companies",
        {
            "query": QUERY,
            "xy_scoring": audit,
            "role_split": True,
            "ownership_verify": "2026-08-14",
        },
        detail_rows=detail_rows,
    )
    extras = export_expand_quadrant_outputs(
        OUT, detail_rows, QUERY, country="global", audit=audit, chart_n=20
    )

    report["after"] = len(landscape)
    report["brand"] = brand_n
    report["marketer"] = marketer_n
    report["html"] = str(extras.get("html") or "")

    audit_out = (
        ROOT
        / "output"
        / "chatgpt_expand"
        / "_audit"
        / f"{SLUG}_ownership_verify.json"
    )
    audit_out.parent.mkdir(exist_ok=True)
    audit_out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    # Also dump final Brand|Company|Role for quick check
    lines = ["Brand\tCompany\tRole\tFound in"]
    for d in detail_rows:
        lines.append(
            f"{d.get('Brand')}\t{d.get('Company')}\t{d.get('Role')}\t{d.get('Found in')}"
        )
    (
        ROOT
        / "output"
        / "chatgpt_expand"
        / "_audit"
        / f"{SLUG}_verified_rows.tsv"
    ).write_text("\n".join(lines), encoding="utf-8")

    print(
        f"before={report['before']} after={report['after']} "
        f"Brand={brand_n} Marketer={marketer_n}"
    )
    print(f"removed={len(report['removed'])} renamed={len(report['renamed'])} "
          f"ownership={len(report['ownership_fixed'])} role={len(report['role_fixed'])} "
          f"deduped={len(report['deduped'])}")
    print(f"audit -> {audit_out}")
    print(f"html -> {extras.get('html')}")
    for x in report["removed"]:
        print("REMOVED:", x)
    for x in report["deduped"]:
        print("DEDUP:", x["dropped"], "->", x["kept"])
    for x in report["ownership_fixed"]:
        print("OWN:", x["brand"], ":", x["from"][:60], "=>", x["to"][:60])


if __name__ == "__main__":
    main()
