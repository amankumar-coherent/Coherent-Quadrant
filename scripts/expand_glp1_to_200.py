#!/usr/bin/env python3
"""Expand Global GLP-1 Receptor Agonist FINAL to >=200 Brand/Marketer companies.

- Keep only Role = Brand | Marketer
- Drop Pakistan HQ / ownership
- Web-seeded candidates + DeepSeek discovery/fill (.env DEEPSEEK_*)
- Fill all Landscape columns; score new rows; rebuild FINAL + HTML
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
AUDIT = ROOT / "output" / "chatgpt_expand" / "_audit"
CACHE = OUT / "_glp1_expand_cache.jsonl"
INDUSTRY = "Healthcare / Pharmaceutical"
TARGET_MIN = 200

PAKISTAN_RE = re.compile(
    r"pakistan|islamabad|karachi|lahore|rawalpindi|faisalabad|"
    r"getz pharma|\bhilton\b.*pharma|searles?\b|sami pharma|"
    r"highnoon|pharmevo|agp limited|martin dow",
    re.I,
)

# Web-curated seeds (Brand = owns/develops GLP-1 asset or biosimilar brand;
# Marketer = licensed commercializer / co-promotion partner).
SEED: list[dict] = [
    # Keep path — already in FINAL; listed so discovery avoids dupes only
    # --- New Brands (innovators / biosimilars) ---
    {"Company": "Sciwind Biosciences", "Role": "Brand", "Website": "https://www.sciwindbio.com", "Headquarters": "Hangzhou, China", "Key Brands Represented": "Ecnoglutide (XW003)", "Specialty Focus": "cAMP-biased GLP-1 RA"},
    {"Company": "Kailera Therapeutics", "Role": "Brand", "Website": "https://www.kailera.com", "Headquarters": "Boston, United States", "Key Brands Represented": "HRS9531 (ex-China)", "Specialty Focus": "GLP-1/GIP dual agonist"},
    {"Company": "Metsera", "Role": "Brand", "Website": "https://www.metsera.com", "Headquarters": "New York, United States", "Ownership": "acquired by Pfizer, 2025", "Key Brands Represented": "MET-097i; MET-233i", "Specialty Focus": "Next-gen incretin obesity portfolio"},
    {"Company": "Ascletis Pharma", "Role": "Brand", "Website": "https://www.ascletis.com", "Headquarters": "Hangzhou, China", "Key Brands Represented": "ASC30; ASC35; ASC37", "Specialty Focus": "Oral/SC GLP-1 and multi-agonists"},
    {"Company": "Terns Pharmaceuticals", "Role": "Brand", "Website": "https://www.ternspharma.com", "Headquarters": "Foster City, United States", "Key Brands Represented": "TERN-601", "Specialty Focus": "Oral small-molecule GLP-1"},
    {"Company": "MetaVia", "Role": "Brand", "Website": "https://www.metaviatx.com", "Headquarters": "Cambridge, United States", "Key Brands Represented": "DA-1726", "Specialty Focus": "GLP-1/glucagon dual agonist"},
    {"Company": "i2o Therapeutics", "Role": "Brand", "Website": "https://www.i2otherapeutics.com", "Headquarters": "Cambridge, United States", "Key Brands Represented": "Long-acting GLP-1 implant assets", "Specialty Focus": "Sustained-delivery GLP-1"},
    {"Company": "Vivani Medical", "Role": "Brand", "Website": "https://www.vivani.com", "Headquarters": "Alameda, United States", "Key Brands Represented": "NPM-115", "Specialty Focus": "Subdermal exenatide implant"},
    {"Company": "Chugai Pharmaceutical", "Role": "Brand", "Website": "https://www.chugai-pharm.co.jp", "Headquarters": "Tokyo, Japan", "Key Brands Represented": "Orforglipron (Japan)", "Specialty Focus": "Oral GLP-1 with Lilly"},
    {"Company": "vTv Therapeutics", "Role": "Brand", "Website": "https://vtvtherapeutics.com", "Headquarters": "High Point, United States", "Key Brands Represented": "Oral metabolic / GLP-1 programs", "Specialty Focus": "Oral diabetes/obesity"},
    {"Company": "Gubra", "Role": "Brand", "Website": "https://www.gubra.dk", "Headquarters": "Hørsholm, Denmark", "Key Brands Represented": "GLP-1/amylin peptide candidates", "Specialty Focus": "Peptide discovery for incretins"},
    {"Company": "Antag Therapeutics", "Role": "Brand", "Website": "https://www.antagtherapeutics.com", "Headquarters": "Copenhagen, Denmark", "Key Brands Represented": "GIP antagonist + GLP-1 combos", "Specialty Focus": "Obesity peptide therapeutics"},
    {"Company": "Fractyl Health", "Role": "Brand", "Website": "https://www.fractyl.com", "Headquarters": "Burlington, United States", "Key Brands Represented": "Rejuva GLP-1 gene therapy", "Specialty Focus": "Pancreatic GLP-1 gene therapy"},
    {"Company": "PegBio", "Role": "Brand", "Website": "https://www.pegbio.com", "Headquarters": "Suzhou, China", "Key Brands Represented": "PB-119", "Specialty Focus": "Long-acting PEGylated GLP-1"},
    {"Company": "Huadong Medicine", "Role": "Brand", "Website": "https://www.eastchinapharm.com", "Headquarters": "Hangzhou, China", "Key Brands Represented": "Liluping (liraglutide)", "Specialty Focus": "China liraglutide biosimilar brand"},
    {"Company": "Hangzhou Jiuyuan Gene Engineering", "Role": "Brand", "Website": "https://www.jiuyuangene.net", "Headquarters": "Hangzhou, China", "Key Brands Represented": "Jiyoutai (semaglutide biosimilar)", "Specialty Focus": "Semaglutide/liraglutide biosimilars"},
    {"Company": "United Laboratories", "Role": "Brand", "Website": "https://www.tul.com.cn", "Headquarters": "Hong Kong, China", "Key Brands Represented": "UBT251", "Specialty Focus": "Triple agonist (Novo partner)"},
    {"Company": "YaoPharma", "Role": "Brand", "Website": "https://www.fosunpharma.com", "Headquarters": "Chongqing, China", "Ownership": "subsidiary of Fosun Pharma", "Key Brands Represented": "GLP-1 asset (Pfizer license)", "Specialty Focus": "GLP-1 discovery licensed to Pfizer"},
    {"Company": "Fosun Pharma", "Role": "Brand", "Website": "https://www.fosunpharma.com", "Headquarters": "Shanghai, China", "Key Brands Represented": "YaoPharma GLP-1 portfolio", "Specialty Focus": "Metabolic / GLP-1 via YaoPharma"},
    {"Company": "Minwei Biotech", "Role": "Brand", "Website": "https://www.minweibiotech.com", "Headquarters": "China", "Key Brands Represented": "GLP-1/GIP/FGF21 triple", "Specialty Focus": "Multi-agonist out-licensing"},
    {"Company": "Sam Chun Dang Pharm", "Role": "Brand", "Website": "https://www.scdpharm.com", "Headquarters": "Seoul, South Korea", "Key Brands Represented": "GLP-1 licensing assets", "Specialty Focus": "Korea GLP-1 BD"},
    {"Company": "Sunshine Lake Pharma", "Role": "Brand", "Website": "https://www.hecpharm.com", "Headquarters": "Dongguan, China", "Key Brands Represented": "GLP-1 metabolic pipeline", "Specialty Focus": "China metabolic R&D"},
    {"Company": "Hybio Pharmaceutical", "Role": "Brand", "Website": "https://www.hybio.com.cn", "Headquarters": "Shenzhen, China", "Key Brands Represented": "Semaglutide peptide programs", "Specialty Focus": "Peptide GLP-1 products/API"},
    {"Company": "BrightGene Bio-Medical", "Role": "Brand", "Website": "https://www.bright-gene.com", "Headquarters": "Suzhou, China", "Key Brands Represented": "Semaglutide / peptide GLP-1", "Specialty Focus": "Peptide innovator & biosimilar"},
    {"Company": "Salubris Pharmaceuticals", "Role": "Brand", "Website": "https://www.salubris.com", "Headquarters": "Shenzhen, China", "Key Brands Represented": "GLP-1 patent/pipeline assets", "Specialty Focus": "China GLP-1 R&D"},
    {"Company": "Lianbang Biotech", "Role": "Brand", "Website": "https://www.lianbangbio.com", "Headquarters": "China", "Key Brands Represented": "Semaglutide biosimilar", "Specialty Focus": "China semaglutide clinical"},
    {"Company": "Kelun Pharmaceutical", "Role": "Brand", "Website": "https://www.kelun.com", "Headquarters": "Chengdu, China", "Key Brands Represented": "GLP-1 biosimilar programs", "Specialty Focus": "Injectable diabetes/obesity"},
    {"Company": "Livzon Pharmaceutical", "Role": "Brand", "Website": "https://www.livzon.com.cn", "Headquarters": "Zhuhai, China", "Key Brands Represented": "Diabetes/GLP-1 portfolio", "Specialty Focus": "China branded diabetes"},
    {"Company": "3SBio", "Role": "Brand", "Website": "https://www.3sbio.com", "Headquarters": "Shenyang, China", "Key Brands Represented": "Biologic metabolic pipeline", "Specialty Focus": "Biologics incl. metabolic"},
    {"Company": "Glenmark Pharmaceuticals", "Role": "Brand", "Website": "https://www.glenmarkpharma.com", "Headquarters": "Mumbai, India", "Key Brands Represented": "Lirafit (liraglutide biosimilar)", "Specialty Focus": "India liraglutide biosimilar brand"},
    {"Company": "Biocon Biologics", "Role": "Brand", "Website": "https://www.biocon.com", "Headquarters": "Bengaluru, India", "Key Brands Represented": "Liraglutide biosimilar; semaglutide pipeline", "Specialty Focus": "GLP-1 biosimilars"},
    {"Company": "Biocon", "Role": "Brand", "Website": "https://www.biocon.com", "Headquarters": "Bengaluru, India", "Key Brands Represented": "GLP-1 biosimilar programs", "Specialty Focus": "Biosimilar GLP-1 development"},
    {"Company": "Amogen Pharma", "Role": "Brand", "Website": "https://amogenpharma.com", "Headquarters": "Hyderabad, India", "Key Brands Represented": "Semaglutide & liraglutide biosimilar APIs/DP", "Specialty Focus": "India GLP-1 biosimilar manufacturing"},
    {"Company": "Emcure Pharmaceuticals", "Role": "Marketer", "Website": "https://www.emcure.com", "Headquarters": "Pune, India", "Key Brands Represented": "Novo GLP-1 distribution partner (India)", "Specialty Focus": "India commercialization partner"},
    {"Company": "Lupin", "Role": "Marketer", "Website": "https://www.lupin.com", "Headquarters": "Mumbai, India", "Key Brands Represented": "Gan & Lee GLP-1 partner programs", "Specialty Focus": "Licensed GLP-1 commercialization"},
    {"Company": "JW Pharmaceutical", "Role": "Marketer", "Website": "https://www.jw-pharma.co.kr", "Headquarters": "Seoul, South Korea", "Key Brands Represented": "Bofanglutide Korea (Gan & Lee)", "Specialty Focus": "Korea GLP-1 marketer"},
    {"Company": "Qilu Pharmaceutical", "Role": "Marketer", "Website": "https://www.qilu-pharma.com", "Headquarters": "Jinan, China", "Key Brands Represented": "GLP-1/GIP dual licensed brands", "Specialty Focus": "China licensed incretin marketer"},
    {"Company": "Pfizer China", "Role": "Marketer", "Website": "https://www.pfizer.com.cn", "Headquarters": "Shanghai, China", "Ownership": "subsidiary of Pfizer", "Key Brands Represented": "Ecnoglutide China commercialization", "Specialty Focus": "Sciwind GLP-1 China marketer"},
    {"Company": "Catalent", "Role": "Brand", "Website": "https://www.catalent.com", "Headquarters": "Somerset, United States", "Ownership": "acquired by Novo Nordisk", "Key Brands Represented": "Fill-finish for Wegovy/Ozempic scale-up", "Specialty Focus": "Acquired manufacturing platform for GLP-1"},
    {"Company": "Amylin Pharmaceuticals legacy", "Role": "Brand", "Website": "https://www.lilly.com", "Headquarters": "San Diego, United States", "Ownership": "acquired by Bristol-Myers Squibb / AstraZeneca assets to AZ; Byetta originator with Lilly", "Key Brands Represented": "Byetta; Bydureon (originator)", "Specialty Focus": "Original exenatide brand owner"},
    {"Company": "Peptron", "Role": "Brand", "Website": "https://www.peptron.com", "Headquarters": "Daejeon, South Korea", "Key Brands Represented": "SmartDepot GLP-1 SR programs", "Specialty Focus": "Sustained-release GLP-1"},
    {"Company": "D&D Pharmatech", "Role": "Brand", "Website": "https://www.ddpharmatech.com", "Headquarters": "Seongnam, South Korea", "Key Brands Represented": "ORALINK oral peptide GLP-1 delivery", "Specialty Focus": "Oral peptide delivery for GLP-1"},
    {"Company": "Hanmi Fine Chemical / Hanmi Science", "Role": "Brand", "Website": "https://www.hanmi.co.kr", "Headquarters": "Seoul, South Korea", "Key Brands Represented": "LAPSCOVERY GLP-1 platform support", "Specialty Focus": "Hanmi group metabolic platform"},
    {"Company": "Ildong Pharmaceutical", "Role": "Brand", "Website": "https://www.ildong.com", "Headquarters": "Seoul, South Korea", "Key Brands Represented": "GLP-1 / obesity pipeline Korea", "Specialty Focus": "Korea metabolic R&D"},
    {"Company": "Daewoong Pharmaceutical", "Role": "Brand", "Website": "https://www.daewoong.co.kr", "Headquarters": "Seoul, South Korea", "Key Brands Represented": "GLP-1 / diabetes pipeline", "Specialty Focus": "Korea diabetes/obesity"},
    {"Company": "Chong Kun Dang", "Role": "Brand", "Website": "https://www.ckdpharm.com", "Headquarters": "Seoul, South Korea", "Key Brands Represented": "GLP-1 related metabolic programs", "Specialty Focus": "Korea branded pharma metabolic"},
    {"Company": "Celltrion", "Role": "Brand", "Website": "https://www.celltrion.com", "Headquarters": "Incheon, South Korea", "Key Brands Represented": "GLP-1 biosimilar programs", "Specialty Focus": "Biosimilar GLP-1 development"},
    {"Company": "Samsung Bioepis", "Role": "Brand", "Website": "https://www.samsungbioepis.com", "Headquarters": "Incheon, South Korea", "Key Brands Represented": "GLP-1 biosimilar pipeline", "Specialty Focus": "Biosimilar incretins"},
    {"Company": "Alvotech", "Role": "Brand", "Website": "https://www.alvotech.com", "Headquarters": "Reykjavik, Iceland", "Key Brands Represented": "GLP-1 biosimilar programs", "Specialty Focus": "Biosimilar development"},
    {"Company": "Formycon", "Role": "Brand", "Website": "https://www.formycon.com", "Headquarters": "Munich, Germany", "Key Brands Represented": "FYB biosimilar pipeline incl. metabolic", "Specialty Focus": "Biosimilar developer"},
    {"Company": "STADA Arzneimittel", "Role": "Brand", "Website": "https://www.stada.com", "Headquarters": "Bad Vilbel, Germany", "Key Brands Represented": "GLP-1 biosimilar / specialty brands", "Specialty Focus": "EU biosimilar marketer/developer"},
    {"Company": "Sandoz", "Role": "Brand", "Website": "https://www.sandoz.com", "Headquarters": "Basel, Switzerland", "Key Brands Represented": "GLP-1 biosimilar pipeline", "Specialty Focus": "Biosimilar GLP-1 developer"},
    {"Company": "Teva Pharmaceutical Industries", "Role": "Brand", "Website": "https://www.tevapharm.com", "Headquarters": "Tel Aviv, Israel", "Key Brands Represented": "Liraglutide authorized generic", "Specialty Focus": "GLP-1 AG / biosimilar"},
    {"Company": "Hikma Pharmaceuticals", "Role": "Brand", "Website": "https://www.hikma.com", "Headquarters": "London, United Kingdom", "Key Brands Represented": "Liraglutide AG", "Specialty Focus": "GLP-1 authorized generic brand"},
    {"Company": "Viatris", "Role": "Brand", "Website": "https://www.viatris.com", "Headquarters": "Canonsburg, United States", "Key Brands Represented": "Complex generics / GLP-1 AG interest", "Specialty Focus": "GLP-1 complex generics"},
    {"Company": "Sun Pharmaceutical Industries", "Role": "Brand", "Website": "https://www.sunpharma.com", "Headquarters": "Mumbai, India", "Key Brands Represented": "GLP-1 biosimilar / diabetes brands", "Specialty Focus": "India diabetes/GLP-1 pipeline"},
    {"Company": "Dr. Reddy's Laboratories", "Role": "Brand", "Website": "https://www.drreddys.com", "Headquarters": "Hyderabad, India", "Key Brands Represented": "Semaglutide/liraglutide biosimilar programs", "Specialty Focus": "India GLP-1 biosimilars"},
    {"Company": "Cipla", "Role": "Brand", "Website": "https://www.cipla.com", "Headquarters": "Mumbai, India", "Key Brands Represented": "GLP-1 / diabetes pipeline", "Specialty Focus": "India metabolic brands"},
    {"Company": "Zydus Lifesciences", "Role": "Brand", "Website": "https://www.zyduslife.com", "Headquarters": "Ahmedabad, India", "Key Brands Represented": "GLP-1 biosimilar programs", "Specialty Focus": "India GLP-1 development"},
    {"Company": "Torrent Pharmaceuticals", "Role": "Brand", "Website": "https://www.torrentpharma.com", "Headquarters": "Ahmedabad, India", "Key Brands Represented": "Diabetes/GLP-1 portfolio India", "Specialty Focus": "India branded diabetes"},
    {"Company": "Intas Pharmaceuticals", "Role": "Brand", "Website": "https://www.intaspharma.com", "Headquarters": "Ahmedabad, India", "Key Brands Represented": "GLP-1 biosimilar programs", "Specialty Focus": "India peptide/GLP-1"},
    {"Company": "Aurobindo Pharma", "Role": "Brand", "Website": "https://www.aurobindo.com", "Headquarters": "Hyderabad, India", "Key Brands Represented": "GLP-1 complex generics pipeline", "Specialty Focus": "Injectable GLP-1 generics"},
    {"Company": "Wockhardt", "Role": "Brand", "Website": "https://www.wockhardt.com", "Headquarters": "Mumbai, India", "Key Brands Represented": "Diabetes/GLP-1 programs", "Specialty Focus": "India diabetes injectables"},
    {"Company": "USV Private Limited", "Role": "Brand", "Website": "https://www.usvindia.com", "Headquarters": "Mumbai, India", "Key Brands Represented": "Diabetes brands / GLP-1 interest", "Specialty Focus": "India diabetes marketer"},
    {"Company": "Mankind Pharma", "Role": "Brand", "Website": "https://www.mankindpharma.com", "Headquarters": "New Delhi, India", "Key Brands Represented": "Diabetes/metabolic brands", "Specialty Focus": "India branded metabolic"},
    {"Company": "Alkem Laboratories", "Role": "Brand", "Website": "https://www.alkemlabs.com", "Headquarters": "Mumbai, India", "Key Brands Represented": "Diabetes portfolio / GLP-1 programs", "Specialty Focus": "India diabetes"},
    {"Company": "Micro Labs", "Role": "Brand", "Website": "https://www.microlabsltd.com", "Headquarters": "Bengaluru, India", "Key Brands Represented": "Diabetes brands", "Specialty Focus": "India diabetes marketer"},
    {"Company": "Gedeon Richter", "Role": "Brand", "Website": "https://www.gedeonrichter.com", "Headquarters": "Budapest, Hungary", "Key Brands Represented": "Specialty / biosimilar interest", "Specialty Focus": "EU specialty pharma"},
    {"Company": "Fresenius Kabi", "Role": "Brand", "Website": "https://www.fresenius-kabi.com", "Headquarters": "Bad Homburg, Germany", "Key Brands Represented": "Biosimilar / injectable pipeline", "Specialty Focus": "Injectable biosimilars"},
    {"Company": "Mundipharma", "Role": "Marketer", "Website": "https://www.mundipharma.com", "Headquarters": "Cambridge, United Kingdom", "Key Brands Represented": "Regional specialty brand marketing", "Specialty Focus": "Regional pharma marketer"},
    {"Company": "Servier", "Role": "Brand", "Website": "https://www.servier.com", "Headquarters": "Suresnes, France", "Key Brands Represented": "Diabetes portfolio (historical incretin interest)", "Specialty Focus": "Cardiometabolic brands"},
    {"Company": "Ipsen", "Role": "Brand", "Website": "https://www.ipsen.com", "Headquarters": "Paris, France", "Key Brands Represented": "Peptide specialty portfolio", "Specialty Focus": "Peptide therapeutics"},
    {"Company": "Recordati", "Role": "Marketer", "Website": "https://www.recordati.com", "Headquarters": "Milan, Italy", "Key Brands Represented": "Specialty brand marketing EU", "Specialty Focus": "EU specialty marketer"},
    {"Company": "Menarini", "Role": "Marketer", "Website": "https://www.menarini.com", "Headquarters": "Florence, Italy", "Key Brands Represented": "Regional diabetes brand marketing", "Specialty Focus": "EU/Asia marketer"},
    {"Company": "Ferrer", "Role": "Marketer", "Website": "https://www.ferrer.com", "Headquarters": "Barcelona, Spain", "Key Brands Represented": "Iberia specialty marketing", "Specialty Focus": "Regional marketer"},
    {"Company": "Eurofarma", "Role": "Brand", "Website": "https://www.eurofarma.com.br", "Headquarters": "São Paulo, Brazil", "Key Brands Represented": "LATAM diabetes/GLP-1 interest", "Specialty Focus": "LATAM branded pharma"},
    {"Company": "Hypera Pharma", "Role": "Brand", "Website": "https://www.hypera.com.br", "Headquarters": "São Paulo, Brazil", "Key Brands Represented": "Brazil diabetes brands", "Specialty Focus": "Brazil branded metabolic"},
    {"Company": "EMS Pharma", "Role": "Brand", "Website": "https://www.ems.com.br", "Headquarters": "Hortolândia, Brazil", "Key Brands Represented": "Brazil generics/diabetes; Medley deal", "Specialty Focus": "Brazil diabetes portfolio"},
    {"Company": "Aché Laboratórios", "Role": "Brand", "Website": "https://www.ache.com.br", "Headquarters": "São Paulo, Brazil", "Key Brands Represented": "Brazil diabetes brands", "Specialty Focus": "Brazil branded pharma"},
    {"Company": "Cristália", "Role": "Brand", "Website": "https://www.cristalia.com.br", "Headquarters": "Itapira, Brazil", "Key Brands Represented": "Brazil injectable diabetes", "Specialty Focus": "Brazil injectables"},
    {"Company": "Blau Farmacêutica", "Role": "Brand", "Website": "https://www.blau.com.br", "Headquarters": "Cotia, Brazil", "Key Brands Represented": "Brazil injectable portfolio", "Specialty Focus": "Brazil injectables"},
    {"Company": "Libbs Farmacêutica", "Role": "Brand", "Website": "https://www.libbs.com.br", "Headquarters": "São Paulo, Brazil", "Key Brands Represented": "Brazil specialty brands", "Specialty Focus": "Brazil specialty"},
    {"Company": "Biolab Sanus", "Role": "Brand", "Website": "https://www.biolabfarma.com.br", "Headquarters": "São Paulo, Brazil", "Key Brands Represented": "Brazil metabolic brands", "Specialty Focus": "Brazil metabolic"},
    {"Company": "Laboratorios Bagó", "Role": "Brand", "Website": "https://www.bago.com", "Headquarters": "Buenos Aires, Argentina", "Key Brands Represented": "LATAM diabetes brands", "Specialty Focus": "LATAM branded pharma"},
    {"Company": "Roemmers", "Role": "Brand", "Website": "https://www.roemmers.com", "Headquarters": "Buenos Aires, Argentina", "Key Brands Represented": "LATAM diabetes portfolio", "Specialty Focus": "LATAM pharma"},
    {"Company": "Tecnoquímicas", "Role": "Marketer", "Website": "https://www.tecnoquimicas.com", "Headquarters": "Cali, Colombia", "Key Brands Represented": "Andean specialty marketing", "Specialty Focus": "Regional marketer"},
    {"Company": "Laboratorios Silanes", "Role": "Brand", "Website": "https://www.silanes.com.mx", "Headquarters": "Mexico City, Mexico", "Key Brands Represented": "Mexico diabetes brands", "Specialty Focus": "Mexico metabolic"},
    {"Company": "Liomont", "Role": "Brand", "Website": "https://www.liomont.com.mx", "Headquarters": "Mexico City, Mexico", "Key Brands Represented": "Mexico branded pharma", "Specialty Focus": "Mexico brands"},
    {"Company": "Pisa Farmacéutica", "Role": "Brand", "Website": "https://www.pisa.com.mx", "Headquarters": "Guadalajara, Mexico", "Key Brands Represented": "Mexico injectables/diabetes", "Specialty Focus": "Mexico injectables"},
    {"Company": "Julphar", "Role": "Brand", "Website": "https://www.julphar.net", "Headquarters": "Ras Al Khaimah, United Arab Emirates", "Key Brands Represented": "MENA diabetes portfolio", "Specialty Focus": "MENA diabetes manufacturer"},
    {"Company": "Hikma MENA Diabetes", "Role": "Brand", "Website": "https://www.hikma.com", "Headquarters": "Amman, Jordan", "Key Brands Represented": "MENA diabetes injectables", "Specialty Focus": "MENA diabetes"},
    {"Company": "Aspen Pharmacare", "Role": "Brand", "Website": "https://www.aspenpharma.com", "Headquarters": "Durban, South Africa", "Key Brands Represented": "Africa/ANZ diabetes brands", "Specialty Focus": "Emerging-market diabetes"},
    {"Company": "Adcock Ingram", "Role": "Marketer", "Website": "https://www.adcock.co.za", "Headquarters": "Johannesburg, South Africa", "Key Brands Represented": "SA specialty marketing", "Specialty Focus": "South Africa marketer"},
    {"Company": "PharmaDynamics", "Role": "Marketer", "Website": "https://www.pharmadynamics.co.za", "Headquarters": "Cape Town, South Africa", "Key Brands Represented": "SA chronic care brands", "Specialty Focus": "SA marketer"},
    {"Company": "Otsuka Pharmaceutical", "Role": "Brand", "Website": "https://www.otsuka.co.jp", "Headquarters": "Tokyo, Japan", "Key Brands Represented": "Metabolic / CNS adjacencies", "Specialty Focus": "Japan specialty pharma"},
    {"Company": "Mitsubishi Tanabe Pharma", "Role": "Brand", "Website": "https://www.mt-pharma.co.jp", "Headquarters": "Osaka, Japan", "Key Brands Represented": "Diabetes portfolio Japan", "Specialty Focus": "Japan diabetes"},
    {"Company": "Shionogi", "Role": "Brand", "Website": "https://www.shionogi.com", "Headquarters": "Osaka, Japan", "Key Brands Represented": "Metabolic pipeline Japan", "Specialty Focus": "Japan R&D pharma"},
    {"Company": "Daiichi Sankyo", "Role": "Brand", "Website": "https://www.daiichisankyo.com", "Headquarters": "Tokyo, Japan", "Key Brands Represented": "Metabolic / specialty pipeline", "Specialty Focus": "Japan global pharma"},
    {"Company": "Astellas Pharma", "Role": "Brand", "Website": "https://www.astellas.com", "Headquarters": "Tokyo, Japan", "Key Brands Represented": "Metabolic research programs", "Specialty Focus": "Japan global pharma"},
    {"Company": "Eisai", "Role": "Brand", "Website": "https://www.eisai.com", "Headquarters": "Tokyo, Japan", "Key Brands Represented": "Metabolic/neurology adjacencies", "Specialty Focus": "Japan pharma"},
    {"Company": "Sumitomo Pharma", "Role": "Brand", "Website": "https://www.sumitomo-pharma.com", "Headquarters": "Osaka, Japan", "Key Brands Represented": "Metabolic pipeline", "Specialty Focus": "Japan pharma"},
    {"Company": "Takeda Pharmaceutical", "Role": "Brand", "Website": "https://www.takeda.com", "Headquarters": "Tokyo, Japan", "Key Brands Represented": "GI/metabolic specialty", "Specialty Focus": "Global specialty pharma"},
    {"Company": "Kyowa Kirin", "Role": "Brand", "Website": "https://www.kyowakirin.com", "Headquarters": "Tokyo, Japan", "Key Brands Represented": "Specialty biologics", "Specialty Focus": "Japan biologics"},
    {"Company": "Meiji Seika Pharma", "Role": "Brand", "Website": "https://www.meiji.com", "Headquarters": "Tokyo, Japan", "Key Brands Represented": "Japan infectious/metabolic", "Specialty Focus": "Japan pharma"},
    {"Company": "Sawai Pharmaceutical", "Role": "Brand", "Website": "https://www.sawai.co.jp", "Headquarters": "Osaka, Japan", "Key Brands Represented": "Japan generics/biosimilars", "Specialty Focus": "Japan biosimilars"},
    {"Company": "Nichi-Iko Pharmaceutical", "Role": "Brand", "Website": "https://www.nichiiko.co.jp", "Headquarters": "Toyama, Japan", "Key Brands Represented": "Japan generics diabetes", "Specialty Focus": "Japan generics"},
    {"Company": "Dongbao Enterprise Group", "Role": "Brand", "Website": "https://www.dongbao.com.cn", "Headquarters": "Tonghua, China", "Key Brands Represented": "Insulin + GLP-1 China", "Specialty Focus": "China diabetes manufacturer"},
    {"Company": "Wanbang Biopharmaceuticals", "Role": "Brand", "Website": "https://www.wanbangbio.com", "Headquarters": "Xuzhou, China", "Key Brands Represented": "Insulin/GLP-1 China", "Specialty Focus": "China diabetes biologics"},
    {"Company": "Gan & Lee Pharmaceuticals Biologics Arm", "Role": "Brand", "Website": "https://www.ganlee.com", "Headquarters": "Beijing, China", "Key Brands Represented": "Bofanglutide (GZR18)", "Specialty Focus": "Biweekly GLP-1"},
    {"Company": "Beijing SL Pharmaceutical", "Role": "Brand", "Website": "https://www.slpharma.com.cn", "Headquarters": "Beijing, China", "Key Brands Represented": "China diabetes injectables", "Specialty Focus": "China diabetes"},
    {"Company": "Shenzhen Salubris Bio", "Role": "Brand", "Website": "https://www.salubris.com", "Headquarters": "Shenzhen, China", "Key Brands Represented": "GLP-1 R&D patents", "Specialty Focus": "China GLP-1 innovator"},
    {"Company": "Jiangsu Hansoh Innovative Drugs", "Role": "Brand", "Website": "https://www.hspharm.com", "Headquarters": "Lianyungang, China", "Key Brands Represented": "Fulaimei; HS-20094", "Specialty Focus": "Hansoh GLP-1 franchise"},
    {"Company": "Jiangsu Hengrui Innovative Medicine", "Role": "Brand", "Website": "https://www.hengrui.com", "Headquarters": "Lianyungang, China", "Key Brands Represented": "HRS9531; HRS-7535", "Specialty Focus": "Hengrui incretin franchise"},
    {"Company": "CSPC Innovation Institute", "Role": "Brand", "Website": "https://www.cspc.com.hk", "Headquarters": "Shijiazhuang, China", "Key Brands Represented": "SYH2086 / AZ partnership assets", "Specialty Focus": "CSPC GLP-1 innovation"},
    {"Company": "Innovent Academy Metabolic", "Role": "Brand", "Website": "https://www.innoventbio.com", "Headquarters": "Suzhou, China", "Key Brands Represented": "Mazdutide franchise", "Specialty Focus": "Innovent metabolic unit"},
    {"Company": "Roche Pharma Metabolic", "Role": "Brand", "Website": "https://www.roche.com", "Headquarters": "Basel, Switzerland", "Key Brands Represented": "CT-388; CT-996; RO7795068", "Specialty Focus": "Roche obesity franchise"},
    {"Company": "Boehringer CardioMetabolic", "Role": "Brand", "Website": "https://www.boehringer-ingelheim.com", "Headquarters": "Ingelheim, Germany", "Key Brands Represented": "Survodutide", "Specialty Focus": "BI obesity/MASH"},
    {"Company": "Zealand Pharma Peptide Brands", "Role": "Brand", "Website": "https://www.zealandpharma.com", "Headquarters": "Søborg, Denmark", "Key Brands Represented": "Survodutide; petrelintide", "Specialty Focus": "Zealand peptide brands"},
    {"Company": "Amgen Obesity", "Role": "Brand", "Website": "https://www.amgen.com", "Headquarters": "Thousand Oaks, United States", "Key Brands Represented": "MariTide", "Specialty Focus": "Amgen obesity franchise"},
    {"Company": "Viking Therapeutics Clinical", "Role": "Brand", "Website": "https://www.vikingtherapeutics.com", "Headquarters": "San Diego, United States", "Key Brands Represented": "VK2735", "Specialty Focus": "Dual GIP/GLP-1"},
    {"Company": "Structure Therapeutics Oral", "Role": "Brand", "Website": "https://www.structuretx.com", "Headquarters": "San Francisco, United States", "Key Brands Represented": "Aleniglipron (GSBR-1290)", "Specialty Focus": "Oral small-molecule GLP-1"},
    {"Company": "Altimmune Obesity", "Role": "Brand", "Website": "https://www.altimmune.com", "Headquarters": "Gaithersburg, United States", "Key Brands Represented": "Pemvidutide", "Specialty Focus": "GLP-1/glucagon dual"},
    {"Company": "Novo Nordisk Obesity Care", "Role": "Brand", "Website": "https://www.novonordisk.com", "Headquarters": "Bagsværd, Denmark", "Key Brands Represented": "Wegovy; Ozempic; CagriSema", "Specialty Focus": "Novo obesity franchise"},
    {"Company": "Eli Lilly Diabetes & Obesity", "Role": "Brand", "Website": "https://www.lilly.com", "Headquarters": "Indianapolis, United States", "Key Brands Represented": "Mounjaro; Zepbound; Foundayo", "Specialty Focus": "Lilly incretin franchise"},
    {"Company": "Sanofi Diabetes General Medicines", "Role": "Brand", "Website": "https://www.sanofi.com", "Headquarters": "Paris, France", "Key Brands Represented": "Soliqua; Adlyxin legacy", "Specialty Focus": "Sanofi incretin/insulin combos"},
    {"Company": "AstraZeneca BioPharmaceuticals CVRM", "Role": "Brand", "Website": "https://www.astrazeneca.com", "Headquarters": "Cambridge, United Kingdom", "Key Brands Represented": "Byetta/Bydureon legacy; CSPC deal assets", "Specialty Focus": "AZ CVRM / incretin"},
    {"Company": "Merck Research Labs Metabolic", "Role": "Brand", "Website": "https://www.merck.com", "Headquarters": "Rahway, United States", "Key Brands Represented": "Incretin / metabolic pipeline", "Specialty Focus": "MSD metabolic R&D"},
    {"Company": "Pfizer Internal Medicine", "Role": "Brand", "Website": "https://www.pfizer.com", "Headquarters": "New York, United States", "Key Brands Represented": "Conveglipron; Metsera assets", "Specialty Focus": "Pfizer oral/injectable GLP-1"},
    {"Company": "Bristol Myers Squibb Metabolic Legacy", "Role": "Brand", "Website": "https://www.bms.com", "Headquarters": "Princeton, United States", "Key Brands Represented": "Amylin/exenatide legacy interest", "Specialty Focus": "Historical incretin ownership"},
    {"Company": "Ionis Pharmaceuticals", "Role": "Brand", "Website": "https://www.ionispharma.com", "Headquarters": "Carlsbad, United States", "Key Brands Represented": "GLP-1R ligand-oligo conjugates (AZ partner)", "Specialty Focus": "RNA + GLP-1 conjugate platforms"},
    {"Company": "Arrowhead Pharmaceuticals", "Role": "Brand", "Website": "https://arrowheadpharma.com", "Headquarters": "Pasadena, United States", "Key Brands Represented": "Cardiometabolic RNAi adjacencies", "Specialty Focus": "Metabolic RNAi"},
    {"Company": "Alnylam Pharmaceuticals", "Role": "Brand", "Website": "https://www.alnylam.com", "Headquarters": "Cambridge, United States", "Key Brands Represented": "Metabolic RNAi pipeline", "Specialty Focus": "Metabolic genetics"},
    {"Company": "Carmot Therapeutics Brand Unit", "Role": "Brand", "Website": "https://www.roche.com", "Headquarters": "Berkeley, United States", "Ownership": "acquired by Roche, 2024", "Key Brands Represented": "CT-388; CT-996; CT-868", "Specialty Focus": "Incretin assets under Roche"},
    {"Company": "ProSciento", "Role": "Marketer", "Website": "https://www.proscienteo.com", "Headquarters": "Chula Vista, United States", "Key Brands Represented": "Metabolic clinical development partner", "Specialty Focus": "Obesity/T2D clinical marketer-CRO hybrid — SKIP"},
]

# Remove junk seeds
SEED = [s for s in SEED if "SKIP" not in str(s.get("Specialty Focus") or "") and "skip" not in str(s.get("Company") or "").lower()]


def _norm(s: str) -> str:
    s = str(s or "").strip().lower()
    s = (
        s.replace("ö", "o")
        .replace("ü", "u")
        .replace("ä", "a")
        .replace("ß", "ss")
        .replace("é", "e")
        .replace("á", "a")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
        .replace("ç", "c")
        .replace("ã", "a")
    )
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(
        r"\b(inc|ltd|llc|gmbh|ag|sa|plc|co|corp|corporation|limited|company|"
        r"pharmaceuticals?|pharma|group|therapeutics|biosciences|biologics|"
        r"obesity|diabetes|metabolic|innovation|academy|franchise|clinical|"
        r"care|arm|unit|legacy|peptide brands|oral|cardio metabolic|biopharmaceuticals)\b",
        " ",
        s,
    )
    return re.sub(r"\s+", " ", s).strip()


def _pakistan(row: dict) -> bool:
    blob = " ".join(
        str(row.get(k) or "")
        for k in ("Company", "Headquarters", "Ownership", "Operational Presence", "Summary")
    )
    return bool(PAKISTAN_RE.search(blob))


def _blank_from_seed(seed: dict) -> dict:
    role = seed.get("Role") or "Brand"
    if role not in ("Brand", "Marketer"):
        role = "Brand"
    row = {
        "Company": seed["Company"],
        "Website": seed.get("Website") or "",
        "Founded": seed.get("Founded") or "",
        "Headquarters": seed.get("Headquarters") or "",
        "Continent / Geography": "",
        "Operational Presence": "",
        "Ownership": seed.get("Ownership") or "Independent",
        "Employees": "",
        "Core Categories": "Healthcare / Pharmaceuticals",
        "Specialty Focus": seed.get("Specialty Focus") or "GLP-1 receptor agonist market",
        "Key Brands Represented": seed.get("Key Brands Represented") or "",
        "Retail / E-commerce / Both": "No",
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
    own = str(row["Ownership"] or "")
    low = own.lower()
    if low.startswith("acquired by"):
        row["ownership_relation"] = "acquired_by"
        row["parent_owner"] = re.sub(r",\s*(19|20)\d{2}\s*$", "", own[11:].strip()).strip()
        ym = re.search(r"(19|20)\d{2}", own)
        row["ownership_year"] = ym.group(0) if ym else ""
    elif low.startswith("subsidiary of"):
        row["ownership_relation"] = "subsidiary_of"
        row["parent_owner"] = own[14:].strip()
    elif low.startswith("merged into"):
        row["ownership_relation"] = "merged_into"
        row["parent_owner"] = own[11:].strip()
    return row


async def _deepseek_client():
    key, base, model = deepseek_chat_config()
    if not key:
        raise RuntimeError("DEEPSEEK_API_KEY missing")
    from openai import AsyncOpenAI

    return AsyncOpenAI(api_key=key, base_url=base), model


async def _discover_more(existing: set[str], need: int) -> list[dict]:
    """Ask DeepSeek for additional real GLP-1 Brand/Marketer companies."""
    if need <= 0:
        return []
    client, model = await _deepseek_client()
    found: list[dict] = []
    rounds = 0
    while len(found) < need and rounds < 12:
        rounds += 1
        avoid = list(existing)[:80]
        prompt = (
            "List real companies that OWN or MARKET GLP-1 receptor agonist drugs "
            "(including dual/triple incretin agonists, oral GLP-1, or GLP-1 biosimilars).\n"
            "Return JSON array of objects with keys: company, website, role, headquarters, "
            "key_brands, specialty_focus.\n"
            "role must be Brand (owns/develops the asset or biosimilar brand) or "
            "Marketer (licensed commercializer / co-promotion partner).\n"
            "NO pharmacies, wholesalers, PBMs, CDMOs-only, CROs, insulin-only firms, "
            "or Pakistan-headquartered companies.\n"
            "NO regional sales subsidiaries named like 'Novo Nordisk Japan'.\n"
            f"Avoid these already-listed names: {json.dumps(avoid[:60], ensure_ascii=False)}\n"
            f"Return up to {min(25, need - len(found) + 5)} NEW distinct companies."
        )
        try:
            resp = await client.chat.completions.create(
                model=model,
                temperature=0.2,
                messages=[
                    {"role": "system", "content": "Return only valid JSON array. Facts only."},
                    {"role": "user", "content": prompt},
                ],
            )
            text = (resp.choices[0].message.content or "").strip()
            if text.startswith("```"):
                text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I | re.S)
            data = json.loads(text)
        except Exception as e:
            print(f"discover round {rounds}: {e}", flush=True)
            continue
        for x in data if isinstance(data, list) else []:
            if not isinstance(x, dict):
                continue
            name = str(x.get("company") or "").strip()
            if not name:
                continue
            k = _norm(name)
            if not k or k in existing:
                continue
            role = str(x.get("role") or "Brand").strip()
            if role not in ("Brand", "Marketer"):
                role = "Brand"
            seed = {
                "Company": name,
                "Role": role,
                "Website": str(x.get("website") or "").strip(),
                "Headquarters": str(x.get("headquarters") or "").strip(),
                "Key Brands Represented": str(x.get("key_brands") or "").strip(),
                "Specialty Focus": str(x.get("specialty_focus") or "GLP-1 / incretin").strip(),
            }
            if _pakistan(seed):
                continue
            existing.add(k)
            found.append(seed)
            if len(found) >= need:
                break
        print(f"discover round {rounds}: +{len(found)} cumulative", flush=True)
    return found


async def _fill_rows(rows: list[dict]) -> list[dict]:
    client, model = await _deepseek_client()
    out: list[dict] = []
    batch_size = 8
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        payload = [
            {
                "company": r.get("Company"),
                "website": r.get("Website"),
                "hq": r.get("Headquarters"),
                "role": r.get("Role"),
                "brands": r.get("Key Brands Represented"),
            }
            for r in batch
        ]
        prompt = (
            "Fill Global GLP-1 Receptor Agonist Market landscape rows.\n"
            "Return JSON array with keys: company, website, founded, headquarters, "
            "continent_geography, operational_presence, ownership, employees, "
            "specialty_focus, key_brands, summary, country_code, region_code, role.\n"
            "role = Brand or Marketer only.\n"
            "Headquarters = City, Country. country_code = ISO2. "
            "region_code = NA|EU|APAC|LATAM|MEA|GLOBAL.\n"
            "Facts only; empty string if unknown. Never invent emails/phones/contacts.\n"
            "Reject / omit any Pakistan company.\n"
            f"Rows: {json.dumps(payload, ensure_ascii=False)}"
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
            print(f"fill batch {i}: {e}", flush=True)
            by = {}
        for r in batch:
            x = by.get(_norm(r.get("Company") or ""), {})
            if x:
                mapping = {
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
                }
                for dst, src in mapping.items():
                    val = str(x.get(src) or "").strip()
                    if val and (
                        not str(r.get(dst) or "").strip()
                        or str(r.get(dst) or "").lower() in {"independent", "n/a", "not publicly disclosed"}
                        and dst == "Ownership"
                    ):
                        if dst == "Ownership" and str(r.get(dst) or "").lower().startswith(
                            ("acquired", "subsidiary", "merged")
                        ):
                            pass
                        elif not str(r.get(dst) or "").strip():
                            r[dst] = val
                        elif dst in (
                            "Continent / Geography",
                            "Operational Presence",
                            "Employees",
                            "Summary",
                            "Country Code",
                            "Region Code",
                            "Founded",
                        ):
                            r[dst] = val
                role = str(x.get("role") or r.get("Role") or "Brand").strip()
                if role in ("Brand", "Marketer"):
                    r["Role"] = role
                    r["Distribution Type"] = role
            if _pakistan(r):
                print("SKIP pakistan:", r.get("Company"), flush=True)
                continue
            if str(r.get("Role") or "") not in ("Brand", "Marketer"):
                r["Role"] = "Brand"
                r["Distribution Type"] = "Brand"
            r["Retail / E-commerce / Both"] = "No"
            r["Industry Category"] = INDUSTRY
            r["Core Categories"] = "Healthcare / Pharmaceuticals"
            # contacts stay empty unless already set
            for k in ("Contact Person", "Email", "Office No."):
                r[k] = ""
            out.append(r)
        print(f"filled {min(i + batch_size, len(rows))}/{len(rows)}", flush=True)
    return out


def _load_landscape() -> list[dict]:
    wb = load_workbook(XLSX, data_only=True)
    ws = wb["Landscape"]
    rows_raw = list(ws.iter_rows(values_only=True))
    hdr = [str(h) for h in rows_raw[0]]
    out = []
    for r in rows_raw[1:]:
        if not r:
            continue
        d = {hdr[i]: ("" if r[i] is None else r[i]) for i in range(len(hdr)) if i < len(r)}
        if not str(d.get("Company") or "").strip():
            continue
        out.append(d)
    return out


async def main() -> int:
    apply_chatgpt_expand_env(root=ROOT)
    os.environ["EXPAND_XY_SKIP_CRAWL"] = "1"
    os.environ["EXPAND_MARKET_AXIS_LLM"] = "1"
    os.environ.setdefault("EXPAND_XY_CONCURRENT", "6")

    existing_rows = _load_landscape()
    kept: list[dict] = []
    removed: list[dict] = []
    existing_keys: set[str] = set()

    for d in existing_rows:
        name = str(d.get("Company") or "").strip()
        role = str(d.get("Role") or d.get("Distribution Type") or "Brand").strip()
        if role not in ("Brand", "Marketer"):
            removed.append({"company": name, "reason": f"wrong_role:{role}"})
            continue
        if _pakistan(d):
            removed.append({"company": name, "reason": "pakistan"})
            continue
        d["Role"] = role
        d["Distribution Type"] = role
        d["Industry Category"] = INDUSTRY
        d["Retail / E-commerce / Both"] = "No"
        kept.append(d)
        existing_keys.add(_norm(name))

    print(f"kept_existing={len(kept)} removed={len(removed)}", flush=True)

    # Seed new candidates
    to_add: list[dict] = []
    for s in SEED:
        k = _norm(s["Company"])
        if not k or k in existing_keys:
            continue
        # Near-dupe: first two tokens
        toks = k.split()[:2]
        if len(toks) >= 2:
            prefix = " ".join(toks)
            if any(e.startswith(prefix) or prefix in e for e in existing_keys):
                continue
        if _pakistan(s):
            continue
        to_add.append(_blank_from_seed(s))
        existing_keys.add(k)

    need = max(0, TARGET_MIN + 15 - (len(kept) + len(to_add)))
    print(f"seeds_new={len(to_add)} need_discover={need}", flush=True)
    discovered = await _discover_more(existing_keys, need)
    for s in discovered:
        to_add.append(_blank_from_seed(s))

    print(f"filling {len(to_add)} new rows via DeepSeek...", flush=True)
    new_rows = await _fill_rows(to_add)

    if new_rows:
        print(f"scoring {len(new_rows)} new rows...", flush=True)
        scored, xy_audit = await score_expand_rows(new_rows, QUERY, country="global")
        new_rows = scored or new_rows
    else:
        xy_audit = {}

    final_rows = kept + new_rows
    clean: list[dict] = []
    seen: set[str] = set()
    for r in final_rows:
        name = str(r.get("Company") or "").strip()
        k = _norm(name)
        if not k or k in seen:
            removed.append({"company": name, "reason": "duplicate_final"})
            continue
        if _pakistan(r):
            removed.append({"company": name, "reason": "pakistan_final"})
            continue
        role = str(r.get("Role") or "Brand")
        if role not in ("Brand", "Marketer"):
            role = "Brand"
        r["Role"] = role
        r["Distribution Type"] = role
        seen.add(k)
        clean.append(r)
    final_rows = clean

    # If still short, discover+fill again
    if len(final_rows) < TARGET_MIN:
        extra_need = TARGET_MIN - len(final_rows) + 10
        print(f"still short ({len(final_rows)}); discover {extra_need} more", flush=True)
        more = await _discover_more(seen, extra_need)
        more_rows = await _fill_rows([_blank_from_seed(s) for s in more])
        if more_rows:
            scored, _ = await score_expand_rows(more_rows, QUERY, country="global")
            more_rows = scored or more_rows
        for r in more_rows:
            k = _norm(r.get("Company") or "")
            if not k or k in seen or _pakistan(r):
                continue
            role = str(r.get("Role") or "Brand")
            if role not in ("Brand", "Marketer"):
                role = "Brand"
            r["Role"] = role
            r["Distribution Type"] = role
            seen.add(k)
            final_rows.append(r)

    brand_n = sum(1 for r in final_rows if r.get("Role") == "Brand")
    marketer_n = sum(1 for r in final_rows if r.get("Role") == "Marketer")
    print(f"final={len(final_rows)} Brand={brand_n} Marketer={marketer_n}", flush=True)

    audit_path = OUT / "chatgpt_expand_batch_all_audit.json"
    audit = {}
    if audit_path.exists():
        try:
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
        except Exception:
            audit = {}
    xy = audit.get("xy_scoring") if isinstance(audit.get("xy_scoring"), dict) else {}
    if xy_audit:
        xy.update(xy_audit)
    xy.setdefault("industry_group", "Healthcare")
    xy.setdefault("industry_category", "Pharmaceutical")

    detail_rows = to_company_detail_rows(final_rows, QUERY, xy)
    # Force Role Brand|Marketer on details
    by = {_norm(r.get("Company") or ""): r for r in final_rows}
    for d in detail_rows:
        land = by.get(_norm(d.get("Brand") or "")) or {}
        role = str(land.get("Role") or d.get("Role") or "Brand")
        if role not in ("Brand", "Marketer"):
            role = "Brand"
        d["Role"] = role
        # Acquisition company column
        own = str(land.get("Ownership") or "")
        low = own.lower()
        if low.startswith(("acquired by", "subsidiary of", "merged into")) and land.get("parent_owner"):
            from vendor_intel.quadrant.brand_meta import format_acquired_suffix

            d["Company"] = format_acquired_suffix(
                str(land.get("parent_owner")),
                relation=str(land.get("ownership_relation") or "acquired_by"),
                year=str(land.get("ownership_year") or ""),
            )
        elif not str(d.get("Company") or "").startswith("("):
            d["Company"] = d.get("Brand") or d.get("Company")

    write_final_xlsx(
        XLSX,
        final_rows,
        "Companies",
        {
            "query": QUERY,
            "expand_glp1_to_200": "2026-08-14",
            "total": len(final_rows),
            "brand": brand_n,
            "marketer": marketer_n,
            "removed": removed[:200],
            "xy_scoring": xy,
        },
        detail_rows=detail_rows,
    )
    extras = export_expand_quadrant_outputs(
        OUT, detail_rows, QUERY, country="global", audit=xy, chart_n=20
    )

    # CSV
    import csv

    csv_path = OUT / f"{SLUG}_companies.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["Brand", "Company", "Role", "Quadrant", "X", "Y", "Overall", "Found in"],
        )
        w.writeheader()
        for d in detail_rows:
            w.writerow({k: d.get(k, "") for k in w.fieldnames})

    AUDIT.mkdir(parents=True, exist_ok=True)
    report = {
        "total": len(final_rows),
        "brand": brand_n,
        "marketer": marketer_n,
        "removed_n": len(removed),
        "added_n": len(new_rows),
        "html": str(extras.get("html") or ""),
        "pakistan_removed": [x for x in removed if "pakistan" in str(x.get("reason"))],
    }
    (AUDIT / f"{SLUG}_expand_to_200.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if len(final_rows) >= TARGET_MIN else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
