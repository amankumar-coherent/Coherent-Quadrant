"""Build curated Flexible Packaging Brand/Marketer seeds from checkpoint + web verify.

KEEP only companies that manufacture / convert / brand flexible packaging (films,
pouches, laminates, barrier wraps) — NOT CPG buyers, retailers, or commodity resin.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(r"D:\Coherent-Quadrant")
CKPT = (
    ROOT
    / "output"
    / "chatgpt_expand"
    / "global_flexible_packaging_market_global"
    / "chatgpt_checkpoint_batch_all.json"
)
OUT = ROOT / "queries" / "seeds" / "global_flexible_packaging_market_global.txt"
AUDIT = ROOT / "queries" / "seeds" / "global_flexible_packaging_market_global_AUDIT.json"

# Web-confirmed flexible packaging players (Mordor, BusinessWire/ResearchAndMarkets,
# SkyQuest, company sites UFlex/Cosmo, NatLawReview flex-pack competitive overview).
# name_stem -> (canonical_name, domain)
WEB_OK: dict[str, tuple[str, str]] = {
    "amcor": ("Amcor plc", "amcor.com"),
    "berry global": ("Berry Global Group, Inc.", "berryglobal.com"),
    "mondi": ("Mondi plc", "mondigroup.com"),
    "sealed air": ("Sealed Air Corporation", "sealedair.com"),
    "sonoco": ("Sonoco Products Company", "sonoco.com"),
    "huhtamaki": ("Huhtamaki Oyj", "huhtamaki.com"),
    "huhtamäki": ("Huhtamaki Oyj", "huhtamaki.com"),
    "constantia": ("Constantia Flexibles Group GmbH", "cflex.com"),
    "transcontinental": ("Transcontinental Inc. (TC Transcontinental)", "tc.tc"),
    "coveris": ("Coveris Holdings S.A.", "coveris.com"),
    "proampac": ("ProAmpac LLC", "proampac.com"),
    "winpak": ("Winpak Ltd.", "winpak.com"),
    "printpack": ("Printpack, Inc.", "printpack.com"),
    "ampac holdings": ("Ampac Holdings LLC", "ampac.com"),
    "bemis": ("Bemis Associates / Amcor Flexibles legacy", "amcor.com"),
    "flex films": ("Flex Films (USA) Inc.", "flexfilm.com"),
    "uflex": ("Uflex Ltd.", "uflexltd.com"),
    "jindal poly": ("Jindal Poly Films Ltd.", "jindalpoly.com"),
    "jindal films": ("Jindal Films", "jindalfilms.com"),
    "cosmo films": ("Cosmo Films Ltd.", "cosmofilms.com"),
    "cosmo first": ("Cosmo Films Ltd.", "cosmofilms.com"),
    "toray plastics": ("Toray Plastics (America), Inc.", "toraytpa.com"),
    "toyobo": ("Toyobo Co., Ltd.", "toyobo-global.com"),
    "klockner pentaplast": ("Klöckner Pentaplast Group", "kpfilms.com"),
    "klöckner pentaplast": ("Klöckner Pentaplast Group", "kpfilms.com"),
    "rkw": ("RKW Group", "rkw-group.com"),
    "schur flexibles": ("Schur Flexibles Group", "schur.com"),
    "wipak": ("Wipak Group", "wipak.com"),
    "glenroy": ("Glenroy, Inc.", "glenroy.com"),
    "graphic packaging": ("Graphic Packaging International, LLC", "graphicpkg.com"),
    "westrock": ("WestRock / Smurfit Westrock", "smurfitwestrock.com"),
    "smurfit": ("Smurfit Westrock / Smurfit Kappa", "smurfitwestrock.com"),
    "ds smith": ("DS Smith Plc", "dssmith.com"),
    "polyplex": ("Polyplex Corporation Ltd.", "polyplex.com"),
    "taghleef": ("Taghleef Industries Group", "ti-films.com"),
    "treofan": ("Treofan Group", "treofan.com"),
    "innovia": ("Innovia Films", "innoviafilms.com"),
    "toppan": ("Toppan Printing Co., Ltd.", "toppan.com"),
    "reynolds consumer": ("Reynolds Consumer Products LLC", "reynoldsconsumer.com"),
    "sigma plastics": ("Sigma Plastics Group", "sigmaplastics.com"),
    "novolex": ("Novolex Holdings, LLC", "novolex.com"),
    "american packaging": ("American Packaging Corporation", "ampacpackaging.com"),
    "bischof": ("Bischof + Klein SE & Co. KG", "bk-international.com"),
    "ahlstrom": ("Ahlstrom", "ahlstrom.com"),
    "aptar": ("AptarGroup, Inc.", "aptar.com"),
    "clondalkin": ("Clondalkin Group", "clondalkin.com"),
    "südpack": ("Südpack Verpackungen GmbH & Co. KG", "suedpack.com"),
    "sudpack": ("Südpack Verpackungen GmbH & Co. KG", "suedpack.com"),
    "walki": ("Walki Group", "walki.com"),
    "fabbri": ("Fabbri Group", "fabbri.com"),
    "essel propack": ("Essel Propack / EPL Limited", "eplglobal.com"),
    "epl limited": ("Essel Propack / EPL Limited", "eplglobal.com"),
    "garware polyester": ("Garware Polyester Ltd.", "garwarepoly.com"),
    "ester industries": ("Ester Industries Ltd.", "esterindustries.com"),
    "vacmet": ("Vacmet India Ltd.", "vacmet.com"),
    "intertape": ("Intertape Polymer Group Inc.", "itape.com"),
    "kuraray": ("Kuraray Co., Ltd. (EVAL barrier films)", "kuraray.com"),
    "honeywell": ("Honeywell International Inc. (Aclar / barrier films)", "honeywell.com"),
    "mitsubishi chemical": ("Mitsubishi Chemical Corporation (packaging films)", "mcgc.com"),
    "tetra pak": ("Tetra Pak International S.A.", "tetrapak.com"),
    "cascades": ("Cascades Inc.", "cascades.com"),
    "georgia-pacific": ("Georgia-Pacific LLC", "gp.com"),
    "oji holdings": ("Oji Holdings Corporation", "ojiholdings.co.jp"),
    "stora enso": ("Stora Enso Oyj", "storaenso.com"),
    "billerud": ("Billerud AB", "billerud.com"),
    "sappi": ("Sappi Limited", "sappi.com"),
    "aluflexpack": ("Aluflexpack AG", "aluflexpack.com"),
    "rpc group": ("RPC Group (now Berry / Amcor)", "berryglobal.com"),
    "pactiv": ("Pactiv Evergreen", "pactivevergreen.com"),
    "c-p flexible": ("C-P Flexible Packaging", "cpflexpack.com"),
    "interflex": ("InterFlex Group", "interflexgroup.com"),
    "swisspac": ("Swisspac", "swisspac.com"),
    "flexopack": ("Flexopack S.A.", "flexopack.com"),
    "nordfolien": ("Nordfolien GmbH", "nordfolien.de"),
    "videplast": ("Videplast", "videplast.com.br"),
    "macfarlane": ("Macfarlane Group", "macfarlanegroup.com"),
    "scholle": ("Scholle IPN", "scholleipn.com"),
    "goglio": ("Goglio S.p.A.", "goglio.it"),
    "dai nippon": ("Dai Nippon Printing", "dnp.co.jp"),
    "dnp": ("Dai Nippon Printing", "dnp.co.jp"),
    "unitika": ("Unitika Ltd.", "unitika.co.jp"),
    "asahi kasei": ("Asahi Kasei Corporation", "asahi-kasei.com"),
    "futamura": ("Futamura Chemical", "futamura.co.jp"),
    "teijin": ("Teijin Limited", "teijin.com"),
    "skc": ("SKC Co., Ltd.", "skc.kr.com"),
    "plastrela": ("Plastrela", "plastrela.com"),
    "du pont": ("DuPont (Tyvek / packaging films)", "dupont.com"),
    "dupont": ("DuPont (Tyvek / packaging films)", "dupont.com"),
    "ccl industries": ("CCL Industries / Innovia", "cclind.com"),
    "ar packaging": ("AR Packaging (Graphic Packaging)", "graphicpkg.com"),
    "flexpak": ("FlexPak Services LLC", "flexpakservices.com"),
    "alpla": ("ALPLA", "alpla.com"),
    "sinar mas": ("Asia Pulp & Paper / Sinar Mas packaging", "asiapulppaper.com"),
    "asia pulp": ("Asia Pulp & Paper / Sinar Mas packaging", "asiapulppaper.com"),
    "thai film": ("Thai Film Industries Public Company Limited", "thaifilm.co.th"),
    "scg packaging": ("SCG Packaging (SCGP)", "scgpackaging.com"),
    "scgp": ("SCG Packaging (SCGP)", "scgpackaging.com"),
    "tcpl packaging": ("TCPL Packaging Ltd.", "tcpl.in"),
}

# Extra majors from web lists if missing from checkpoint
EXTRA_SEEDS: list[tuple[str, str]] = [
    ("Amcor plc", "amcor.com"),
    ("Berry Global Group, Inc.", "berryglobal.com"),
    ("Mondi plc", "mondigroup.com"),
    ("Sealed Air Corporation", "sealedair.com"),
    ("Sonoco Products Company", "sonoco.com"),
    ("Huhtamaki Oyj", "huhtamaki.com"),
    ("Constantia Flexibles Group GmbH", "cflex.com"),
    ("Transcontinental Inc. (TC Transcontinental)", "tc.tc"),
    ("Coveris Holdings S.A.", "coveris.com"),
    ("ProAmpac LLC", "proampac.com"),
    ("Winpak Ltd.", "winpak.com"),
    ("Uflex Ltd.", "uflexltd.com"),
    ("Cosmo Films Ltd.", "cosmofilms.com"),
    ("Jindal Poly Films Ltd.", "jindalpoly.com"),
    ("Printpack, Inc.", "printpack.com"),
    ("Glenroy, Inc.", "glenroy.com"),
    ("Bischof + Klein SE & Co. KG", "bk-international.com"),
    ("Novolex Holdings, LLC", "novolex.com"),
    ("Clondalkin Group", "clondalkin.com"),
    ("AptarGroup, Inc.", "aptar.com"),
    ("American Packaging Corporation", "ampacpackaging.com"),
    ("Schur Flexibles Group", "schur.com"),
    ("Wipak Group", "wipak.com"),
    ("Südpack Verpackungen GmbH & Co. KG", "suedpack.com"),
    ("Polyplex Corporation Ltd.", "polyplex.com"),
    ("Taghleef Industries Group", "ti-films.com"),
    ("Toray Plastics (America), Inc.", "toraytpa.com"),
    ("Klöckner Pentaplast Group", "kpfilms.com"),
    ("RKW Group", "rkw-group.com"),
    ("Sigma Plastics Group", "sigmaplastics.com"),
    ("Graphic Packaging International, LLC", "graphicpkg.com"),
    ("Smurfit Westrock", "smurfitwestrock.com"),
    ("Ahlstrom", "ahlstrom.com"),
    ("Tetra Pak International S.A.", "tetrapak.com"),
    ("Essel Propack / EPL Limited", "eplglobal.com"),
    ("Aluflexpack AG", "aluflexpack.com"),
    ("Flexopack S.A.", "flexopack.com"),
    ("Innovia Films", "innoviafilms.com"),
    ("Reynolds Consumer Products LLC", "reynoldsconsumer.com"),
]


DROP_RE = re.compile(
    r"(?i)\b("
    r"walmart|target|amazon|costco|aldi|lidl|tesco|carrefour|loblaw|couche.?tard|"
    r"cencosud|kroger|asda|sainsbury|"
    r"pepsico|nestl[eé]|unilever|kraft|heinz|kellogg|conagra|hershey|mars|"
    r"mondelez|clorox|kimberly.?clark|procter|colgate|ferrero|danone|"
    r"bimbo|natura|arcor|\blala\b|nutresa|andina|alicorp|almarai|ghurair|"
    r"tiger brands|pioneer foods|rcl foods|\bavi\b|bidco|astral foods|"
    r"coca.?cola|heineken|anheuser|ab inbev|diageo|parmalat|saputo|agropur|"
    r"general mills|johnson.?johnson|cerve[cz]|sab\b|south african brewer|"
    r"dangote|riviera farms|"
    r"exxon|dow inc|lyondell|sabic|borealis|nova chem|mitsui chem|"
    r"sumitomo chem|braskem|ineos|formosa|basf|hyundai chemical|"
    r"samsung fine chemical|lotte fine|"
    r"henkel|h\.?b\.?\s*fuller|kraton|"
    r"sidel group|frobenius"
    r")\b"
)

KEEP_NAME_RE = re.compile(
    r"(?i)("
    r"packag|flexib|film|pouch|laminat|wrap|converter|verpack|"
    r"bopp|bopet|barrier|polyester|plastics america|"
    r"embalagens flex|flex[ií]veis"
    r")"
)


def norm(s: str) -> str:
    s = (s or "").lower()
    s = s.replace("ä", "a").replace("ö", "o").replace("ü", "u").replace("ß", "ss")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s&+]", " ", s)).strip()


def match_web_ok(name: str) -> tuple[str, str] | None:
    n = norm(name)
    for stem, (canon, domain) in sorted(WEB_OK.items(), key=lambda x: -len(x[0])):
        if norm(stem) in n:
            return canon, domain
    return None


# Name heuristics that look like packaging but are usually wrong for this market
WEAK_FALSE_POS = re.compile(
    r"(?i)\b("
    r"fujifilm|fuji film|mold.?tek|new zealand packaging|"
    r"b&b box|box & packaging|advance packaging \(india\)|"
    r"flexible packaging nz|hcp packaging"
    r")\b"
)


def main() -> None:
    state = json.loads(CKPT.read_text(encoding="utf-8"))
    rows = state.get("data", {}).get("to_fill") or state.get("data", {}).get("merged") or []
    names = [str(r.get("Company") or r.get("name") or "").strip() for r in rows]
    names = [n for n in names if n]

    kept: list[tuple[str, str, str]] = []  # name, domain, reason
    dropped: list[tuple[str, str]] = []
    seen: set[str] = set()

    for name in names:
        key = norm(name)
        if not key or key in seen:
            continue
        if WEAK_FALSE_POS.search(name):
            dropped.append((name, "weak_or_non_flex_pack_name_hit"))
            seen.add(key)
            continue
        if DROP_RE.search(name) or DROP_RE.search(key):
            dropped.append((name, "cpg_retail_resin_adhesive_or_equipment"))
            seen.add(key)
            continue
        hit = match_web_ok(name)
        if hit:
            canon, domain = hit
            ckey = norm(canon)
            if ckey not in seen:
                kept.append((canon, domain, "web_confirmed_flex_pack_player"))
                seen.add(ckey)
            seen.add(key)
            continue
        # Keep only strong packaging-name signals (not generic "film" alone like Fujifilm)
        if re.search(
            r"(?i)(flexible\s+packag|flexibles|packaging\s+film|embalagens\s+flex|"
            r"verpack|pouches|laminat|bopp|bopet|converter|nordfolien|polifilm|"
            r"parkside\s+flex|flexibras|videplast|plastrela)",
            name,
        ):
            kept.append((name, "", "name_indicates_flex_pack_converter_or_films"))
            seen.add(key)
            continue
        dropped.append((name, "not_verified_as_flex_pack_brand_marketer"))
        seen.add(key)

    for canon, domain in EXTRA_SEEDS:
        ckey = norm(canon)
        if ckey in seen:
            continue
        kept.append((canon, domain, "extra_from_market_reports"))
        seen.add(ckey)

    # de-dupe by norm name preferring entries with domain
    by: dict[str, tuple[str, str, str]] = {}
    for name, domain, reason in kept:
        k = norm(name)
        # collapse near-duplicate Brazilian Embalagens Flexiveis variants
        if "embalagens flex" in k:
            k = "embalagens flexiveis"
            name = "Embalagens Flexíveis (Brasil converters)"
        prev = by.get(k)
        if not prev or (domain and not prev[1]):
            by[k] = (name, domain, reason)
    kept_final = sorted(by.values(), key=lambda x: x[0].lower())

    OUT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Global Flexible Packaging Market — Brand / Marketer seeds",
        "# Verified: packaging converters / film manufacturers that OWN or MARKET",
        "# flexible packaging products (not CPG buyers, retailers, or resin feedstock).",
        "# Sources: Mordor converted flex-pack list, BusinessWire flex-pack report 2025,",
        "# SkyQuest, NatLawReview competitive overview, UFlex/Cosmo company sites.",
        "# Format: Company | domain | note",
        "",
    ]
    for name, domain, reason in kept_final:
        if domain:
            lines.append(f"{name} | {domain} | Brand / Marketer; {reason}")
        else:
            lines.append(f"{name} | Brand / Marketer; {reason}")
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")

    audit = {
        "market": "Global Flexible Packaging Market",
        "expected_role": "Brand / Marketer",
        "source_checkpoint_rows": len(names),
        "kept_seeds": len(kept_final),
        "dropped": len(dropped),
        "seed_file": str(OUT),
        "kept": [{"name": n, "domain": d, "reason": r} for n, d, r in kept_final],
        "dropped_sample": [{"name": n, "reason": r} for n, r in dropped[:150]],
        "dropped_total": len(dropped),
    }
    AUDIT.write_text(json.dumps(audit, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"checkpoint companies: {len(names)}")
    print(f"kept seeds:           {len(kept_final)}")
    print(f"dropped:              {len(dropped)}")
    print(f"wrote: {OUT}")
    print(f"audit: {AUDIT}")
    print("\nALL KEPT:")
    for n, d, r in kept_final:
        print(f"  + {n}  [{d or '-'}]  ({r})")
    print("\nDROPPED sample (first 50):")
    for n, r in dropped[:50]:
        print(f"  - {n}  ({r})")


if __name__ == "__main__":
    main()
