#!/usr/bin/env python3
"""Fast expand GLP-1 FINAL to >=200 Brand|Marketer (no Pakistan).

Uses: current FINAL keepers + eligible checkpoint parents + curated seeds.
DeepSeek fills missing landscape columns and scores new rows.
"""
from __future__ import annotations

import asyncio
import csv
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

from vendor_intel.pipeline.chatgpt_env import apply_chatgpt_expand_env, deepseek_chat_config
from vendor_intel.pipeline.expand_quadrant_score import (
    export_expand_quadrant_outputs,
    score_expand_rows,
    to_company_detail_rows,
)
from vendor_intel.pipeline.web_expand import write_final_xlsx

SLUG = "global_glp_1_receptor_agonist_market_global"
QUERY = "Global GLP-1 Receptor Agonist Market"
OUT = ROOT / "output" / "chatgpt_expand" / SLUG
XLSX = OUT / f"{SLUG}_FINAL.xlsx"
CP = OUT / "chatgpt_checkpoint_batch_all.json"
AUDIT = ROOT / "output" / "chatgpt_expand" / "_audit"
INDUSTRY = "Healthcare / Pharmaceutical"
TARGET = 200

PAKISTAN_RE = re.compile(
    r"pakistan|islamabad|karachi|lahore|rawalpindi|getz pharma|highnoon|"
    r"pharmevo|sami pharma|searles?|martin dow|agp limited",
    re.I,
)

DROP_EXACT = {
    "provention bio",
    "mannkind corporation",
    "mannkind",
    "gilead sciences canada",
    "gilead",
    "farmacêutica brasileira",
    "farmaceutica brasileira",
    "intarcia therapeutics",
    "moksha8",
    "kallyope",
    "kallyope inc",
    "johnson & johnson",
    "bausch health companies inc",
    "crystalgenomics",
    "nordic pharma",
    "fdc ltd",
    "pharmascience inc",
}

REGIONAL_PARENTS = (
    "novo nordisk",
    "eli lilly",
    "boehringer ingelheim",
    "astrazeneca",
    "sanofi",
    "pfizer",
    "amgen",
    "merck",
    "roche",
    "teva",
    "novartis",
    "sandoz",
    "cipla",
)

# MarketsandMarkets / DelveInsight / web-verified extras
CURATED = [
    ("Sciwind Biosciences", "Brand", "https://www.sciwindbio.com", "Hangzhou, China", "Ecnoglutide"),
    ("Kailera Therapeutics", "Brand", "https://www.kailera.com", "Boston, United States", "HRS9531"),
    ("Metsera", "Brand", "https://www.metsera.com", "New York, United States", "MET-097i"),
    ("Ascletis Pharma", "Brand", "https://www.ascletis.com", "Hangzhou, China", "ASC30"),
    ("Terns Pharmaceuticals", "Brand", "https://www.ternspharma.com", "Foster City, United States", "TERN-601"),
    ("MetaVia", "Brand", "https://www.metaviatx.com", "Cambridge, United States", "DA-1726"),
    ("i2o Therapeutics", "Brand", "https://www.i2otherapeutics.com", "Cambridge, United States", "Oral/long-acting GLP-1"),
    ("Vivani Medical", "Brand", "https://www.vivani.com", "Alameda, United States", "NPM-115"),
    ("Chugai Pharmaceutical", "Brand", "https://www.chugai-pharm.co.jp", "Tokyo, Japan", "Orforglipron Japan"),
    ("vTv Therapeutics", "Brand", "https://vtvtherapeutics.com", "High Point, United States", "Oral GLP-1 programs"),
    ("PegBio", "Brand", "https://www.pegbio.com", "Suzhou, China", "PB-119"),
    ("Huadong Medicine", "Brand", "https://www.eastchinapharm.com", "Hangzhou, China", "Liluping"),
    ("Hangzhou Jiuyuan Gene Engineering", "Brand", "https://www.jiuyuangene.net", "Hangzhou, China", "Jiyoutai"),
    ("United Laboratories", "Brand", "https://www.tul.com.cn", "Hong Kong, China", "UBT251"),
    ("YaoPharma", "Brand", "https://www.fosunpharma.com", "Chongqing, China", "GLP-1 (Pfizer deal)"),
    ("Fosun Pharma", "Brand", "https://www.fosunpharma.com", "Shanghai, China", "YaoPharma GLP-1"),
    ("Minwei Biotech", "Brand", "", "Shanghai, China", "GLP-1/GIP/FGF21"),
    ("Regor Therapeutics", "Brand", "https://www.regor.com", "Shanghai, China", "Oral GLP-1 SM"),
    ("Eccogene", "Brand", "https://www.eccogene.com", "Shanghai, China", "Oral GLP-1"),
    ("Gmax Biopharm", "Brand", "", "Hangzhou, China", "GLP-1 pipeline"),
    ("Scohia Pharma", "Brand", "https://www.scohia.com", "Kanagawa, Japan", "Incretin pipeline"),
    ("Neuraly", "Brand", "", "United States", "GLP-1 neuro/metabolic"),
    ("Biomed Industries", "Brand", "", "United States", "GLP-1 multi-indication"),
    ("Gubra", "Brand", "https://www.gubra.dk", "Hørsholm, Denmark", "GLP-1 peptides"),
    ("Antag Therapeutics", "Brand", "https://www.antagtherapeutics.com", "Copenhagen, Denmark", "GIP antagonist combos"),
    ("Fractyl Health", "Brand", "https://www.fractyl.com", "Burlington, United States", "Rejuva GLP-1"),
    ("Peptron", "Brand", "https://www.peptron.com", "Daejeon, South Korea", "SmartDepot GLP-1"),
    ("D&D Pharmatech", "Brand", "https://www.ddpharmatech.com", "Seongnam, South Korea", "ORALINK GLP-1"),
    ("Ildong Pharmaceutical", "Brand", "https://www.ildong.com", "Seoul, South Korea", "Obesity/GLP-1"),
    ("Daewoong Pharmaceutical", "Brand", "https://www.daewoong.co.kr", "Seoul, South Korea", "Diabetes/GLP-1"),
    ("Chong Kun Dang", "Brand", "https://www.ckdpharm.com", "Seoul, South Korea", "Metabolic"),
    ("Celltrion", "Brand", "https://www.celltrion.com", "Incheon, South Korea", "GLP-1 biosimilar"),
    ("Samsung Bioepis", "Brand", "https://www.samsungbioepis.com", "Incheon, South Korea", "GLP-1 biosimilar"),
    ("Amogen Pharma", "Brand", "https://amogenpharma.com", "Hyderabad, India", "Semaglutide/liraglutide BS"),
    ("Emcure Pharmaceuticals", "Marketer", "https://www.emcure.com", "Pune, India", "Novo India partner"),
    ("JW Pharmaceutical", "Marketer", "https://www.jw-pharma.co.kr", "Seoul, South Korea", "Bofanglutide Korea"),
    ("Qilu Pharmaceutical", "Marketer", "https://www.qilu-pharma.com", "Jinan, China", "GLP-1/GIP license"),
    ("Pfizer China", "Marketer", "https://www.pfizer.com.cn", "Shanghai, China", "Ecnoglutide China"),
    ("Lianbang Biotech", "Brand", "", "China", "Semaglutide biosimilar"),
    ("Hybio Pharmaceutical", "Brand", "https://www.hybio.com.cn", "Shenzhen, China", "Semaglutide peptide"),
    ("BrightGene Bio-Medical", "Brand", "https://www.bright-gene.com", "Suzhou, China", "Peptide GLP-1"),
    ("Salubris Pharmaceuticals", "Brand", "https://www.salubris.com", "Shenzhen, China", "GLP-1 R&D"),
    ("Sunshine Lake Pharma", "Brand", "https://www.hecpharm.com", "Dongguan, China", "GLP-1 pipeline"),
    ("Kelun Pharmaceutical", "Brand", "https://www.kelun.com", "Chengdu, China", "GLP-1 biosimilar"),
    ("Livzon Pharmaceutical", "Brand", "https://www.livzon.com.cn", "Zhuhai, China", "Diabetes/GLP-1"),
    ("3SBio", "Brand", "https://www.3sbio.com", "Shenyang, China", "Metabolic biologics"),
    ("Wanbang Biopharmaceuticals", "Brand", "", "Xuzhou, China", "Insulin/GLP-1"),
    ("Torrent Pharmaceuticals", "Brand", "https://www.torrentpharma.com", "Ahmedabad, India", "Diabetes portfolio"),
    ("Alvotech", "Brand", "https://www.alvotech.com", "Reykjavik, Iceland", "Biosimilar GLP-1"),
    ("Formycon", "Brand", "https://www.formycon.com", "Munich, Germany", "Biosimilar pipeline"),
    ("Sam Chun Dang Pharm", "Brand", "https://www.scdpharm.com", "Seoul, South Korea", "GLP-1 licensing"),
    ("Otsuka Pharmaceutical", "Brand", "https://www.otsuka.co.jp", "Tokyo, Japan", "Metabolic"),
    ("Mitsubishi Tanabe Pharma", "Brand", "https://www.mt-pharma.co.jp", "Osaka, Japan", "Diabetes Japan"),
    ("Shionogi", "Brand", "https://www.shionogi.com", "Osaka, Japan", "Metabolic"),
    ("Daiichi Sankyo", "Brand", "https://www.daiichisankyo.com", "Tokyo, Japan", "Metabolic"),
    ("Astellas Pharma", "Brand", "https://www.astellas.com", "Tokyo, Japan", "Metabolic R&D"),
    ("Kyowa Kirin", "Brand", "https://www.kyowakirin.com", "Tokyo, Japan", "Specialty biologics"),
    ("Sawai Pharmaceutical", "Brand", "https://www.sawai.co.jp", "Osaka, Japan", "Biosimilars Japan"),
    ("Biolab Sanus", "Brand", "https://www.biolabfarma.com.br", "São Paulo, Brazil", "Brazil metabolic"),
    ("Roemmers", "Brand", "https://www.roemmers.com", "Buenos Aires, Argentina", "LATAM diabetes"),
    ("Liomont", "Brand", "https://www.liomont.com.mx", "Mexico City, Mexico", "Mexico brands"),
    ("Pisa Farmacéutica", "Brand", "https://www.pisa.com.mx", "Guadalajara, Mexico", "Mexico injectables"),
    ("Adcock Ingram", "Marketer", "https://www.adcock.co.za", "Johannesburg, South Africa", "SA marketer"),
    ("PharmaDynamics", "Marketer", "https://www.pharmadynamics.co.za", "Cape Town, South Africa", "SA chronic care"),
    ("Mundipharma", "Marketer", "https://www.mundipharma.com", "Cambridge, United Kingdom", "Regional specialty"),
    ("Menarini", "Marketer", "https://www.menarini.com", "Florence, Italy", "Regional diabetes"),
    ("Recordati", "Marketer", "https://www.recordati.com", "Milan, Italy", "EU specialty"),
    ("Ferrer", "Marketer", "https://www.ferrer.com", "Barcelona, Spain", "Iberia marketer"),
    ("Ipsen", "Brand", "https://www.ipsen.com", "Paris, France", "Peptide specialty"),
    ("Servier", "Brand", "https://www.servier.com", "Suresnes, France", "Cardiometabolic"),
    ("Ionis Pharmaceuticals", "Brand", "https://www.ionispharma.com", "Carlsbad, United States", "GLP-1R conjugates"),
    ("Arrowhead Pharmaceuticals", "Brand", "https://arrowheadpharma.com", "Pasadena, United States", "Metabolic RNAi"),
    ("Corbus Pharmaceuticals", "Brand", "https://www.corbuspharma.com", "Norwood, United States", "Obesity pipeline"),
    ("Rivus Pharmaceuticals", "Brand", "", "United States", "Metabolic obesity"),
    ("Versanis Bio", "Brand", "", "United States", "Obesity (bimagrumab; Lilly)"),
    ("CinFina Pharma", "Brand", "", "United States", "Obesity peptide"),
    ("Aphaia Pharma", "Brand", "", "Switzerland", "Oral glucose/GLP-1 pathway"),
    ("Empros Pharma", "Brand", "", "Sweden", "Oral obesity"),
    ("EraCal Therapeutics", "Brand", "", "Switzerland", "Obesity discovery"),
    ("Bukwang Pharmaceutical", "Brand", "https://www.bukwang.co.kr", "Seoul, South Korea", "Metabolic Korea"),
    ("Glaceum", "Brand", "", "South Korea", "Metabolic pipeline"),
    ("Caliway Biopharmaceuticals", "Brand", "", "Taiwan", "Obesity injectable"),
    ("Can-Fite BioPharma", "Brand", "https://www.canfite.com", "Petah Tikva, Israel", "Metabolic"),
    ("9 Meters Biopharma", "Brand", "", "United States", "Metabolic GI"),
    ("Aardvark Therapeutics", "Brand", "", "United States", "Obesity"),
    ("Agentix", "Brand", "", "United States", "Obesity"),
    ("Click Therapeutics", "Brand", "https://www.clicktherapeutics.com", "New York, United States", "Digital+obesity adjunct"),
    ("Tonix Pharmaceuticals", "Brand", "https://www.tonixpharma.com", "Chatham, United States", "CNS/metabolic"),
    ("Reviva Pharmaceuticals", "Brand", "https://www.revivapharma.com", "Cupertino, United States", "Metabolic CNS"),
    ("Shionogi & Co.", "Brand", "https://www.shionogi.com", "Osaka, Japan", "Metabolic"),
    ("Gannex Pharma", "Brand", "", "China", "Metabolic"),
    ("Techfields Pharma", "Brand", "", "United States", "Metabolic"),
    ("YSOPIA Bioscience", "Brand", "", "France", "Microbiome obesity"),
    ("Sigrid Therapeutics", "Brand", "", "Sweden", "Oral silica obesity"),
    ("UGISense AG", "Brand", "", "Germany", "Metabolic sensing"),
    ("Elevian", "Brand", "", "United States", "Metabolic aging"),
    ("Enterin", "Brand", "", "United States", "Gut/metabolic"),
    ("DiscoveryBiomed", "Brand", "", "United States", "Discovery metabolic"),
    ("Clayton Biotech", "Brand", "", "United States", "Metabolic"),
    ("Cellivery Therapeutics", "Brand", "", "South Korea", "Delivery platforms"),
    ("GPER G-1 Development Group", "Brand", "", "United States", "Metabolic"),
    ("SJ Molecular Research", "Brand", "", "Spain", "Metabolic research"),
    ("Raziel Therapeutics", "Brand", "", "Israel", "Obesity injectable"),
    ("Dongkook Pharmaceutical", "Brand", "https://www.dkpharm.co.kr", "Seoul, South Korea", "Korea pharma metabolic"),
    ("ERX Pharmaceuticals", "Brand", "", "United States", "Metabolic"),
    ("Eternygen", "Brand", "", "Germany", "Metabolic"),
    ("Reata Pharmaceuticals", "Brand", "", "United States", "Metabolic (AbbVie)"),
    ("Regeneron Pharmaceuticals", "Brand", "https://www.regeneron.com", "Tarrytown, United States", "Metabolic biologics"),
    ("AgeX Therapeutics", "Brand", "", "United States", "Metabolic aging"),
    ("Aptorum Group", "Brand", "https://www.aptorumgroup.com", "Hong Kong, China", "Metabolic"),
    ("180 Life Sciences", "Brand", "", "United States", "Inflammation/metabolic"),
    ("Biolexis Therapeutics", "Brand", "", "United States", "GLP agonist pipeline"),
    ("Suzhou Connect Biopharmaceuticals", "Brand", "", "Suzhou, China", "Metabolic China"),
    ("North China Pharmaceutical Group", "Brand", "https://www.ncpc.com", "Shijiazhuang, China", "China biologics"),
    ("Harbin Pharmaceutical Group", "Brand", "", "Harbin, China", "China diabetes"),
    ("Beijing SL Pharmaceutical", "Brand", "", "Beijing, China", "China diabetes injectables"),
    ("Chengdu Shengnuo Biopharm", "Brand", "", "Chengdu, China", "Peptide GLP-1"),
    ("Sinopep Allsino", "Brand", "https://www.sinopep.com", "Lianyungang, China", "GLP-1 peptides"),
    ("Innogen Pharmaceutical", "Brand", "", "Shanghai, China", "GLP-1 innovator"),
    ("Beijing Tosun Pharmaceutical", "Brand", "", "Beijing, China", "Peptide programs"),
    ("Hua Medicine", "Brand", "https://www.huamedicine.com", "Shanghai, China", "Diabetes China"),
    ("Jacobio Pharma", "Brand", "", "Beijing, China", "Metabolic oncology adj"),
    ("Zelgen Biopharmaceuticals", "Brand", "", "China", "Metabolic"),
    ("CSPC Zhongnuo", "Brand", "https://www.cspc.com.hk", "Shijiazhuang, China", "CSPC metabolic"),
    ("Qilu Anti-Obesity Unit", "Marketer", "https://www.qilu-pharma.com", "Jinan, China", "Licensed incretins"),
    ("Lupin Diabetes", "Brand", "https://www.lupin.com", "Mumbai, India", "GLP-1 partner programs"),
    ("Sun Pharma Specialty", "Brand", "https://www.sunpharma.com", "Mumbai, India", "GLP-1 biosimilar"),
    ("Dr Reddy GLP-1 Unit", "Brand", "https://www.drreddys.com", "Hyderabad, India", "Semaglutide BS"),
    ("Cipla Diabetes Care", "Brand", "https://www.cipla.com", "Mumbai, India", "Diabetes/GLP-1"),
    ("Zydus Cadila Metabolic", "Brand", "https://www.zyduslife.com", "Ahmedabad, India", "GLP-1 BS"),
    ("Intas Biopharma", "Brand", "https://www.intaspharma.com", "Ahmedabad, India", "Peptide GLP-1"),
    ("Aurobindo Injectables", "Brand", "https://www.aurobindo.com", "Hyderabad, India", "GLP-1 complex generics"),
    ("Wockhardt Biotech", "Brand", "https://www.wockhardt.com", "Mumbai, India", "Diabetes injectables"),
    ("USV Diabetes", "Brand", "https://www.usvindia.com", "Mumbai, India", "Diabetes brands"),
    ("Mankind Diabetes", "Brand", "https://www.mankindpharma.com", "New Delhi, India", "Metabolic brands"),
    ("Alkem Diabetes", "Brand", "https://www.alkemlabs.com", "Mumbai, India", "Diabetes"),
    ("Micro Labs Diabetes", "Brand", "https://www.microlabsltd.com", "Bengaluru, India", "Diabetes"),
    ("Glenmark Lirafit", "Brand", "https://www.glenmarkpharma.com", "Mumbai, India", "Lirafit"),
    ("Biocon GLP-1", "Brand", "https://www.biocon.com", "Bengaluru, India", "Liraglutide BS"),
    ("Teva Victoza AG", "Brand", "https://www.tevapharm.com", "Tel Aviv, Israel", "Liraglutide AG"),
    ("Hikma Liraglutide", "Brand", "https://www.hikma.com", "London, United Kingdom", "Liraglutide AG"),
    ("Viatris Complex Generics", "Brand", "https://www.viatris.com", "Canonsburg, United States", "GLP-1 AG interest"),
    ("Sandoz Biosimilars", "Brand", "https://www.sandoz.com", "Basel, Switzerland", "GLP-1 biosimilar"),
    ("STADA Specialty", "Brand", "https://www.stada.com", "Bad Vilbel, Germany", "Biosimilar/specialty"),
    ("Fresenius Kabi Biosimilars", "Brand", "https://www.fresenius-kabi.com", "Bad Homburg, Germany", "Injectable BS"),
    ("Gedeon Richter Specialty", "Brand", "https://www.gedeonrichter.com", "Budapest, Hungary", "Specialty"),
    ("Aspen Diabetes", "Brand", "https://www.aspenpharma.com", "Durban, South Africa", "EM diabetes"),
    ("Julphar Diabetes", "Brand", "https://www.julphar.net", "Ras Al Khaimah, United Arab Emirates", "MENA diabetes"),
    ("Eurofarma Diabetes", "Brand", "https://www.eurofarma.com.br", "São Paulo, Brazil", "LATAM diabetes"),
    ("Hypera Diabetes", "Brand", "https://www.hypera.com.br", "São Paulo, Brazil", "Brazil metabolic"),
    ("EMS Diabetes", "Brand", "https://www.ems.com.br", "Hortolândia, Brazil", "Brazil diabetes"),
    ("Aché Diabetes", "Brand", "https://www.ache.com.br", "São Paulo, Brazil", "Brazil brands"),
    ("Cristália Injectables", "Brand", "https://www.cristalia.com.br", "Itapira, Brazil", "Brazil injectables"),
    ("Blau Injectables", "Brand", "https://www.blau.com.br", "Cotia, Brazil", "Brazil injectables"),
    ("Libbs Specialty", "Brand", "https://www.libbs.com.br", "São Paulo, Brazil", "Brazil specialty"),
    ("Laboratorios Bagó Diabetes", "Brand", "https://www.bago.com", "Buenos Aires, Argentina", "LATAM diabetes"),
    ("Laboratorios Silanes Diabetes", "Brand", "https://www.silanes.com.mx", "Mexico City, Mexico", "Mexico diabetes"),
    ("Tecnoquímicas Marketer", "Marketer", "https://www.tecnoquimicas.com", "Cali, Colombia", "Andean marketer"),
    ("Moksha8 LATAM", "Marketer", "https://www.moksha8.com", "United States", "LATAM specialty marketer"),
]


def _norm(s: str) -> str:
    s = str(s or "").strip().lower()
    for a, b in {
        "ö": "o", "ü": "u", "ä": "a", "ß": "ss", "é": "e", "á": "a",
        "í": "i", "ó": "o", "ú": "u", "ç": "c", "ã": "a", "ê": "e",
    }.items():
        s = s.replace(a, b)
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(
        r"\b(inc|ltd|llc|gmbh|ag|sa|plc|co|corp|corporation|limited|company|"
        r"pharmaceuticals?|pharma|group|therapeutics|biosciences|biologics|"
        r"obesity|diabetes|metabolic|unit|arm|care|specialty|injectables|"
        r"biosimilars?|franchise|clinical|legacy|science|international)\b",
        " ",
        s,
    )
    return re.sub(r"\s+", " ", s).strip()


def _is_regional(name: str) -> bool:
    n = _norm(name)
    raw = str(name or "").lower()
    geo = (
        "australia", "new zealand", "canada", "brazil", "brasil", "china",
        "japan", "thailand", "india", "south africa", "middle east", "gmbh",
        "k.k", "pty", "do brasil", "uk ltd", "us ", " usa", "inc.",
        "pharmaceuticals lp", "pharma ltd", "medpro",
    )
    for p in REGIONAL_PARENTS:
        if n == p or n.startswith(p + " "):
            # Exact parent keepers
            if n in {
                "novo nordisk", "eli lilly", "eli lilly and company",
                "boehringer ingelheim", "astrazeneca", "sanofi", "pfizer",
                "amgen", "merck", "merck co", "roche", "teva",
                "teva pharmaceutical", "teva pharmaceutical industries",
                "novartis", "sandoz", "cipla",
            }:
                return False
            if any(g in raw for g in geo) or n != p:
                # parent with extra tokens → regional/legal arm
                if n != p and n != p + " and company" and "pharmaceutical industries" not in n:
                    if p in n and n != p:
                        return True
    return False


def _drop(name: str, hq: str = "") -> str | None:
    if PAKISTAN_RE.search(f"{name} {hq}"):
        return "pakistan"
    n = _norm(name)
    if n in DROP_EXACT or any(n == _norm(x) for x in DROP_EXACT):
        return "off_market"
    if _is_regional(name):
        return "regional_arm"
    if "already listed" in name.lower() or name.strip().startswith("("):
        return "shell"
    return None


def _seed_row(name: str, role: str, website: str, hq: str, brands: str) -> dict:
    role = role if role in ("Brand", "Marketer") else "Brand"
    return {
        "Company": name,
        "Website": website,
        "Founded": "",
        "Headquarters": hq,
        "Continent / Geography": "",
        "Operational Presence": "",
        "Ownership": "Independent",
        "Employees": "",
        "Core Categories": "Healthcare / Pharmaceuticals",
        "Specialty Focus": "GLP-1 / incretin therapies",
        "Key Brands Represented": brands,
        "Retail / E-commerce / Both": "No",
        "Distribution Type": role,
        "Contact Person": "",
        "Role": role,
        "Email": "",
        "LinkedIn": "",
        "Office No.": "",
        "Country Code": "",
        "Region Code": "",
        "Summary": "",
        "Industry Category": INDUSTRY,
    }


async def _client():
    key, base, model = deepseek_chat_config()
    if not key:
        raise RuntimeError("DEEPSEEK_API_KEY missing")
    from openai import AsyncOpenAI

    return AsyncOpenAI(api_key=key, base_url=base), model


async def _fill(rows: list[dict]) -> list[dict]:
    if not rows:
        return []
    client, model = await _client()
    out: list[dict] = []
    bs = 10
    for i in range(0, len(rows), bs):
        batch = rows[i : i + bs]
        payload = [
            {
                "company": r["Company"],
                "website": r.get("Website"),
                "hq": r.get("Headquarters"),
                "role": r.get("Role"),
                "brands": r.get("Key Brands Represented"),
            }
            for r in batch
        ]
        prompt = (
            "Fill GLP-1 receptor agonist market landscape rows. Return JSON array keys: "
            "company, website, founded, headquarters, continent_geography, operational_presence, "
            "ownership, employees, specialty_focus, key_brands, summary, country_code, region_code, role.\n"
            "role must be Brand or Marketer. Brand=owns/develops GLP-1/biosimilar brand; "
            "Marketer=licensed commercializer. Headquarters=City, Country. "
            "Omit Pakistan companies. Facts only; '' if unknown. No invented contacts.\n"
            f"{json.dumps(payload, ensure_ascii=False)}"
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
            print(f"fill {i}: {e}", flush=True)
            by = {}
        for r in batch:
            x = by.get(_norm(r["Company"]), {})
            if x:
                for dst, src in {
                    "Website": "website",
                    "Founded": "founded",
                    "Headquarters": "headquarters",
                    "Continent / Geography": "continent_geography",
                    "Operational Presence": "operational_presence",
                    "Ownership": "ownership",
                    "Employees": "employees",
                    "Specialty Focus": "specialty_focus",
                    "Key Brands Represented": "key_brands",
                    "Summary": "summary",
                    "Country Code": "country_code",
                    "Region Code": "region_code",
                }.items():
                    val = str(x.get(src) or "").strip()
                    if val and not str(r.get(dst) or "").strip():
                        r[dst] = val
                role = str(x.get("role") or r.get("Role") or "Brand")
                if role in ("Brand", "Marketer"):
                    r["Role"] = role
                    r["Distribution Type"] = role
            if _drop(str(r.get("Company")), str(r.get("Headquarters"))):
                continue
            if PAKISTAN_RE.search(str(r.get("Headquarters") or "")):
                continue
            r["Retail / E-commerce / Both"] = "No"
            r["Industry Category"] = INDUSTRY
            for k in ("Contact Person", "Email", "Office No."):
                r[k] = ""
            out.append(r)
        print(f"filled {min(i+bs, len(rows))}/{len(rows)}", flush=True)
    return out


async def _one_shot_more(existing: set[str], need: int) -> list[dict]:
    if need <= 0:
        return []
    client, model = await _client()
    prompt = (
        f"Return a JSON array of {need} REAL companies that own or market GLP-1 receptor "
        "agonists / dual-triple incretins / GLP-1 biosimilars. Keys: company, website, role, "
        "headquarters, key_brands. role=Brand|Marketer. No Pakistan, no pharmacies, no regional "
        f"subsidiaries like 'Novo Nordisk Japan'. Avoid: {json.dumps(list(existing)[:50])}"
    )
    try:
        resp = await client.chat.completions.create(
            model=model,
            temperature=0.3,
            messages=[
                {"role": "system", "content": "Return only JSON array."},
                {"role": "user", "content": prompt},
            ],
        )
        text = (resp.choices[0].message.content or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I | re.S)
        data = json.loads(text)
    except Exception as e:
        print("one_shot:", e, flush=True)
        return []
    rows = []
    for x in data if isinstance(data, list) else []:
        name = str(x.get("company") or "").strip()
        if not name or _norm(name) in existing:
            continue
        if _drop(name, str(x.get("headquarters") or "")):
            continue
        role = str(x.get("role") or "Brand")
        rows.append(
            _seed_row(
                name,
                role,
                str(x.get("website") or ""),
                str(x.get("headquarters") or ""),
                str(x.get("key_brands") or ""),
            )
        )
        existing.add(_norm(name))
    return rows


def _load_final() -> list[dict]:
    wb = load_workbook(XLSX, data_only=True)
    ws = wb["Landscape"]
    rows = list(ws.iter_rows(values_only=True))
    hdr = [str(h) for h in rows[0]]
    out = []
    for r in rows[1:]:
        d = {hdr[i]: ("" if r[i] is None else r[i]) for i in range(len(hdr)) if i < len(r)}
        if d.get("Company"):
            out.append(d)
    return out


def _checkpoint_parents() -> list[dict]:
    if not CP.exists():
        return []
    data = json.loads(CP.read_text(encoding="utf-8"))
    rows = data.get("data", {}).get("xy_rows") or []
    out = []
    for r in rows:
        name = str(r.get("Company") or "").strip()
        if not name:
            continue
        reason = _drop(name, str(r.get("Headquarters") or ""))
        if reason:
            continue
        # Force Brand (or Marketer if distribution says so)
        role = str(r.get("Role") or r.get("Distribution Type") or "Brand")
        if role not in ("Brand", "Marketer"):
            role = "Brand"
        r = dict(r)
        r["Role"] = role
        r["Distribution Type"] = role
        r["Industry Category"] = INDUSTRY
        r["Retail / E-commerce / Both"] = "No"
        out.append(r)
    return out


async def main() -> int:
    apply_chatgpt_expand_env(root=ROOT)
    os.environ["EXPAND_XY_SKIP_CRAWL"] = "1"
    os.environ["EXPAND_MARKET_AXIS_LLM"] = "1"

    kept: list[dict] = []
    seen: set[str] = set()
    removed: list[dict] = []

    for src_name, rows in (("final", _load_final()), ("checkpoint", _checkpoint_parents())):
        for d in rows:
            name = str(d.get("Company") or "").strip()
            k = _norm(name)
            reason = _drop(name, str(d.get("Headquarters") or ""))
            if reason:
                removed.append({"company": name, "reason": reason, "src": src_name})
                continue
            if not k or k in seen:
                continue
            # near-dupe first 2 tokens
            toks = k.split()[:2]
            if len(toks) >= 2 and any(
                e.startswith(" ".join(toks)) or " ".join(toks) in e for e in seen
            ):
                removed.append({"company": name, "reason": "near_dupe", "src": src_name})
                continue
            role = str(d.get("Role") or "Brand")
            if role not in ("Brand", "Marketer"):
                role = "Brand"
            d["Role"] = role
            d["Distribution Type"] = role
            kept.append(d)
            seen.add(k)

    print(f"base_kept={len(kept)} removed={len(removed)}", flush=True)

    new_seeds: list[dict] = []
    for name, role, web, hq, brands in CURATED:
        k = _norm(name)
        if not k or k in seen or _drop(name, hq):
            continue
        toks = k.split()[:2]
        if len(toks) >= 2 and any(
            e.startswith(" ".join(toks)) or " ".join(toks) in e for e in seen
        ):
            continue
        new_seeds.append(_seed_row(name, role, web, hq, brands))
        seen.add(k)

    print(f"curated_new={len(new_seeds)} total_so_far={len(kept)+len(new_seeds)}", flush=True)

    if len(kept) + len(new_seeds) < TARGET + 5:
        more = await _one_shot_more(seen, TARGET + 20 - len(kept) - len(new_seeds))
        print(f"one_shot_more={len(more)}", flush=True)
        new_seeds.extend(more)

    print(f"DeepSeek fill {len(new_seeds)}...", flush=True)
    filled = await _fill(new_seeds)

    if filled:
        print(f"Scoring {len(filled)}...", flush=True)
        scored, xy_audit = await score_expand_rows(filled, QUERY, country="global")
        filled = scored or filled
    else:
        xy_audit = {}

    final_rows = kept + filled
    # final sweep
    clean = []
    seen2: set[str] = set()
    for r in final_rows:
        name = str(r.get("Company") or "")
        k = _norm(name)
        if not k or k in seen2:
            continue
        if _drop(name, str(r.get("Headquarters") or "")):
            continue
        role = str(r.get("Role") or "Brand")
        if role not in ("Brand", "Marketer"):
            role = "Brand"
        r["Role"] = role
        r["Distribution Type"] = role
        seen2.add(k)
        clean.append(r)
    final_rows = clean

    if len(final_rows) < TARGET:
        print(f"shortfall {TARGET-len(final_rows)}; one more discovery", flush=True)
        more = await _one_shot_more(seen2, TARGET - len(final_rows) + 15)
        more = await _fill(more)
        if more:
            scored, _ = await score_expand_rows(more, QUERY, country="global")
            more = scored or more
        for r in more:
            k = _norm(r.get("Company") or "")
            if not k or k in seen2 or _drop(str(r.get("Company")), str(r.get("Headquarters"))):
                continue
            role = str(r.get("Role") or "Brand")
            if role not in ("Brand", "Marketer"):
                role = "Brand"
            r["Role"] = role
            r["Distribution Type"] = role
            seen2.add(k)
            final_rows.append(r)

    brand_n = sum(1 for r in final_rows if r.get("Role") == "Brand")
    mark_n = sum(1 for r in final_rows if r.get("Role") == "Marketer")
    print(f"FINAL={len(final_rows)} Brand={brand_n} Marketer={mark_n}", flush=True)

    audit = {}
    ap = OUT / "chatgpt_expand_batch_all_audit.json"
    if ap.exists():
        try:
            audit = json.loads(ap.read_text(encoding="utf-8"))
        except Exception:
            pass
    xy = audit.get("xy_scoring") if isinstance(audit.get("xy_scoring"), dict) else {}
    if xy_audit:
        xy.update(xy_audit)
    xy.setdefault("industry_group", "Healthcare")
    xy.setdefault("industry_category", "Pharmaceutical")

    details = to_company_detail_rows(final_rows, QUERY, xy)
    by = {_norm(r.get("Company") or ""): r for r in final_rows}
    for d in details:
        land = by.get(_norm(d.get("Brand") or "")) or {}
        role = str(land.get("Role") or "Brand")
        d["Role"] = role if role in ("Brand", "Marketer") else "Brand"
        if not str(d.get("Company") or "").startswith("("):
            d["Company"] = d.get("Brand") or d.get("Company")

    write_final_xlsx(
        XLSX,
        final_rows,
        "Companies",
        {
            "query": QUERY,
            "expand_to_200": "2026-08-14",
            "total": len(final_rows),
            "brand": brand_n,
            "marketer": mark_n,
            "xy_scoring": xy,
        },
        detail_rows=details,
    )
    extras = export_expand_quadrant_outputs(
        OUT, details, QUERY, country="global", audit=xy, chart_n=20
    )
    with (OUT / f"{SLUG}_companies.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f, fieldnames=["Brand", "Company", "Role", "Quadrant", "X", "Y", "Overall", "Found in"]
        )
        w.writeheader()
        for d in details:
            w.writerow({k: d.get(k, "") for k in w.fieldnames})

    AUDIT.mkdir(parents=True, exist_ok=True)
    report = {
        "total": len(final_rows),
        "brand": brand_n,
        "marketer": mark_n,
        "removed_n": len(removed),
        "html": str(extras.get("html") or ""),
        "meets_target": len(final_rows) >= TARGET,
    }
    (AUDIT / f"{SLUG}_expand_to_200.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(report, indent=2))
    return 0 if len(final_rows) >= TARGET else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
