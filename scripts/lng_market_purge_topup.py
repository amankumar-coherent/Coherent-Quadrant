#!/usr/bin/env python3
"""LNG market: purge off-market/Pakistan, keep Brand|Marketer only, top up to 200+.

Uses DeepSeek (.env) to fill landscape columns + score new rows (skip crawl).
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

SLUG = "global_liquefied_natural_gas_market_global"
QUERY = "Global Liquefied Natural Gas Market"
OUT = ROOT / "output" / "chatgpt_expand" / SLUG
XLSX = OUT / f"{SLUG}_FINAL.xlsx"
AUDIT = ROOT / "output" / "chatgpt_expand" / "_audit"
INDUSTRY = "Energy / Liquefied Natural Gas"
TARGET_MIN = 200

PAKISTAN_RE = re.compile(
    r"pakistan|islamabad|karachi|\bsngpl\b|\bssgc\b|sui southern|"
    r"mari petroleum|engro elengy|pakistan lng",
    re.I,
)

CITY_GAS_RE = re.compile(
    r"companhia de g[aáà]s|comg[aáà]s|bahiag[aáà]s|gasmig|scg[aáà]s|ceg[aáà]s|compagas|"
    r"gujarat gas|indraprastha gas|mahanagar gas|sabarmati gas|torrent gas|"
    r"indian oil[- ]adani gas|\bioagpl\b|adani total gas|"
    r"nippon gas|keiyo gas|hiroshima gas|hokkaido gas|saibu gas|shizuoka gas|toho gas|"
    r"beijing gas|shenzhen gas|china gas holdings|towngas|"
    r"fortisbc|bayerngas",
    re.I,
)

# Exact normalized names / unique multi-word stems (NOT bare "lng limited")
DROP_EXACT = {
    "dominion energy",
    "national grid plc",
    "national grid",
    "koch industries",
    "bhp group",
    "contact energy ltd",
    "contact energy",
    "todd energy",
    "new zealand oil gas ltd",
    "new zealand oil gas",
    "cooper energy",
    "pieridae energy",
    "steelhead lng",
    "bear head lng",
    "tree energy solutions tes",
    "tree energy solutions",
    "noble resources",
    "h energy",
    "swan energy limited",
    "swan energy",
    "ancap",
    "petroperu",
    "philippine national oil company pnoc",
    "philippine national oil company",
    "bangladesh oil gas and mineral corporation petrobangla",
    "petrobangla",
    "gs caltex",
    "cosmo energy holdings",
    "cosmo energy",
    "idemitsu kosan",
    "jx nippon oil gas exploration",
    "perenco",
    "antero resources",
    "canadian natural resources limited",
    "canadian natural resources",
    "tourmaline oil corp",
    "tourmaline oil",
    "beach energy",
    "ecopetrol",
    "ypf",
    "sasol",
    "sembcorp industries",
    "keppel corporation",
    "taiwan power company taipower",
    "taiwan power company",
    "korea midland power co ltd komipo",
    "korea midland power",
    "korea east west power co ltd ewp",
    "korea east west power",
    "korea southern power co ltd kospo",
    "korea southern power",
    "korea western power co ltd wp",
    "korea western power",
    "hokkaido electric power company",
    "tohoku electric power company",
    "kyushu electric power company",
    "sse plc",
    "iberdrola",
    "enel",
    "endesa",
    "edf electricite de france",
    "edf",
    "enbw energie baden wurttemberg ag",
    "enbw",
    "ewe ag",
    "axpo",
    "vng handel vertrieb gmbh",
    "pakistan lng limited pll",
    "pakistan lng limited",
    "jordan cove lng",
    "rasgas",
    "qatar gas",
    "prelude flng shell operated",
    "prelude flng",
    "lng limited",  # Australian LNGL only — exact
    "zeta energy",
    "fox petroleum",
    "indra gas",
    "zodiac energy ltd",
    "zodiac energy",
    "goldeneye lng",
    "stx lng",
}

# New LNG Brand / Marketer candidates (web-verified relevant). Role Brand unless Marketer.
NEW_CANDIDATES: list[dict] = [
    {"Company": "LNG Canada", "Role": "Brand", "Website": "https://www.lngcanada.ca", "Headquarters": "Kitimat, Canada", "Ownership": "Joint venture (Shell 40%, Petronas 25%, PetroChina 15%, Mitsubishi 15%, KOGAS 5%)", "Founded": "2018", "Specialty Focus": "LNG liquefaction export (Kitimat)", "Summary": "Canadian west-coast LNG export joint venture; first cargo mid-2025."},
    {"Company": "Cameron LNG", "Role": "Brand", "Website": "https://cameronlng.com", "Headquarters": "Hackberry, Louisiana, United States", "Ownership": "Joint venture (Sempra Infrastructure, TotalEnergies, Mitsui, Mitsubishi, NYK)", "Founded": "2014", "Specialty Focus": "US Gulf Coast LNG export", "Summary": "Operating LNG liquefaction and export terminal in Cameron Parish, Louisiana."},
    {"Company": "Nigeria LNG Limited (NLNG)", "Role": "Brand", "Website": "https://www.nlng.com", "Headquarters": "Bonny Island, Nigeria", "Ownership": "Joint venture (NNPC, Shell, TotalEnergies, Eni)", "Founded": "1989", "Specialty Focus": "LNG liquefaction and export", "Summary": "Major African LNG producer operating multiple trains at Bonny Island."},
    {"Company": "Gate terminal", "Role": "Brand", "Website": "https://www.gateterminal.com", "Headquarters": "Rotterdam, Netherlands", "Ownership": "Joint venture (Gasunie 50%, Vopak 50%)", "Founded": "2011", "Specialty Focus": "LNG import / regasification hub", "Summary": "Europe’s Gate LNG import terminal on the Maasvlakte, Rotterdam."},
    {"Company": "Elengy", "Role": "Brand", "Website": "https://www.elengy.com", "Headquarters": "Paris, France", "Ownership": "subsidiary of Engie", "Founded": "2008", "Specialty Focus": "LNG terminal operations (Montoir, Fos)", "Summary": "Engie subsidiary operating France’s main LNG receiving terminals."},
    {"Company": "Grain LNG", "Role": "Brand", "Website": "https://grainlng.com", "Headquarters": "Isle of Grain, United Kingdom", "Ownership": "subsidiary of National Grid", "Founded": "2005", "Specialty Focus": "UK LNG import terminal", "Summary": "UK’s largest LNG import terminal on the Isle of Grain."},
    {"Company": "Gasunie", "Role": "Brand", "Website": "https://www.gasunie.nl", "Headquarters": "Groningen, Netherlands", "Ownership": "State-owned (Netherlands)", "Founded": "1963", "Specialty Focus": "Gas TSO; Gate terminal / EemsEnergyTerminal LNG", "Summary": "Dutch gas infrastructure company; co-owner of Gate LNG and EemsEnergyTerminal FSRU."},
    {"Company": "Vopak", "Role": "Brand", "Website": "https://www.vopak.com", "Headquarters": "Rotterdam, Netherlands", "Ownership": "Public", "Founded": "1999", "Specialty Focus": "LNG / energy storage terminals", "Summary": "Global tank storage company; 50% owner of Gate LNG terminal."},
    {"Company": "Deutsche Energy Terminal (DET)", "Role": "Brand", "Website": "https://www.deutsche-energy-terminal.de", "Headquarters": "Germany", "Ownership": "Owned by Federal Republic of Germany", "Founded": "2022", "Specialty Focus": "German LNG import terminals / FSRUs", "Summary": "German state LNG terminal company operating Wilhelmshaven and other import sites."},
    {"Company": "SNAM", "Role": "Brand", "Website": "https://www.snam.it", "Headquarters": "San Donato Milanese, Italy", "Ownership": "Public", "Founded": "1941", "Specialty Focus": "Gas TSO; LNG terminals (Panigaglia, Adriatic interests)", "Summary": "Italian gas infrastructure group with LNG import and FSRU interests."},
    {"Company": "Adriatic LNG", "Role": "Brand", "Website": "https://www.adriaticlng.it", "Headquarters": "Porto Viro, Italy", "Ownership": "Joint venture (ExxonMobil, QatarEnergy, SNAM)", "Founded": "2005", "Specialty Focus": "Offshore LNG regasification terminal", "Summary": "Italy’s Adriatic offshore LNG receiving terminal."},
    {"Company": "OLT Offshore LNG Toscana", "Role": "Brand", "Website": "https://www.oltoffshore.it", "Headquarters": "Livorno, Italy", "Ownership": "Private / consortium", "Founded": "2006", "Specialty Focus": "FSRU LNG import", "Summary": "Floating LNG terminal off Tuscany serving the Italian market."},
    {"Company": "BOTAŞ", "Role": "Brand", "Website": "https://www.botas.gov.tr", "Headquarters": "Ankara, Turkey", "Ownership": "State-owned (Turkey)", "Founded": "1974", "Specialty Focus": "LNG import / gas transmission", "Summary": "Turkish state pipeline and LNG import company."},
    {"Company": "Nakilat", "Role": "Brand", "Website": "https://www.nakilat.com", "Headquarters": "Doha, Qatar", "Ownership": "Public (Qatar state-linked)", "Founded": "2004", "Specialty Focus": "LNG shipping / Q-Max Q-Flex fleet", "Summary": "Qatar’s LNG shipping company operating the world’s largest LNG carrier fleet."},
    {"Company": "NYK Line", "Role": "Brand", "Website": "https://www.nyk.com", "Headquarters": "Tokyo, Japan", "Ownership": "Public", "Founded": "1885", "Specialty Focus": "LNG carriers / shipping", "Summary": "Major Japanese shipping line with a large LNG carrier fleet and Cameron LNG stake."},
    {"Company": "Kawasaki Kisen Kaisha (\"K\" Line)", "Role": "Brand", "Website": "https://www.kline.co.jp", "Headquarters": "Tokyo, Japan", "Ownership": "Public", "Founded": "1919", "Specialty Focus": "LNG shipping", "Summary": "Japanese shipping major active in LNG transportation."},
    {"Company": "COSCO SHIPPING Energy Transportation", "Role": "Brand", "Website": "https://energy.coscoshipping.com", "Headquarters": "Shanghai, China", "Ownership": "Public (COSCO group)", "Founded": "1997", "Specialty Focus": "LNG / energy shipping", "Summary": "Chinese energy shipping company with growing LNG carrier fleet."},
    {"Company": "Flex LNG", "Role": "Brand", "Website": "https://www.flexlng.com", "Headquarters": "Hamilton, Bermuda / Oslo", "Ownership": "Public", "Founded": "2006", "Specialty Focus": "LNG carriers", "Summary": "LNG shipping company listed in Oslo/NYSE specializing in modern LNG carriers."},
    {"Company": "GasLog Ltd.", "Role": "Brand", "Website": "https://www.gaslogltd.com", "Headquarters": "Piraeus, Greece", "Ownership": "Private (BlackRock consortium acquired 2022)", "Founded": "2003", "Specialty Focus": "LNG shipping", "Summary": "LNG carrier owner-operator serving global LNG trade."},
    {"Company": "Seapeak", "Role": "Brand", "Website": "https://www.seapeak.com", "Headquarters": "Bermuda / Houston", "Ownership": "Private (Stonepeak)", "Founded": "2004", "Specialty Focus": "LNG / LPG shipping (ex-Teekay LNG)", "Summary": "Former Teekay LNG Partners; LNG and gas carrier owner now branded Seapeak."},
    {"Company": "Cool Company Ltd. (CoolCo)", "Role": "Brand", "Website": "https://www.coolcoltd.com", "Headquarters": "London, United Kingdom", "Ownership": "Public", "Founded": "2018", "Specialty Focus": "LNG carriers", "Summary": "LNG shipping spin-out focused on modern LNG carrier fleet."},
    {"Company": "BW LNG", "Role": "Brand", "Website": "https://www.bw-group.com", "Headquarters": "Oslo / Singapore", "Ownership": "subsidiary of BW Group", "Founded": "2010", "Specialty Focus": "LNG shipping / FSRU", "Summary": "BW Group’s LNG shipping and floating LNG solutions business."},
    {"Company": "Nigeria National Petroleum Company (NNPC) Limited", "Role": "Brand", "Website": "https://nnpcgroup.com", "Headquarters": "Abuja, Nigeria", "Ownership": "State-owned", "Founded": "1977", "Specialty Focus": "NOC; NLNG shareholder", "Summary": "Nigerian national oil company and NLNG joint-venture partner."},
    {"Company": "Sonangol", "Role": "Brand", "Website": "https://www.sonangol.co.ao", "Headquarters": "Luanda, Angola", "Ownership": "State-owned", "Founded": "1976", "Specialty Focus": "NOC; Angola LNG partner", "Summary": "Angolan national oil company; partner in Angola LNG."},
    {"Company": "Egypt LNG (ELNG)", "Role": "Brand", "Website": "https://www.egyptianlng.com", "Headquarters": "Idku, Egypt", "Ownership": "Joint venture (EGAS, Shell, Petronas)", "Founded": "2001", "Specialty Focus": "LNG liquefaction", "Summary": "Egyptian LNG liquefaction plant at Idku."},
    {"Company": "SEGAS (Spanish Egyptian Gas Company)", "Role": "Brand", "Website": "https://www.segas.com.eg", "Headquarters": "Damietta, Egypt", "Ownership": "Joint venture (Eni, EGAS, others)", "Founded": "2001", "Specialty Focus": "Damietta LNG", "Summary": "Damietta LNG liquefaction plant operator in Egypt."},
    {"Company": "Mozambique LNG (TotalEnergies)", "Role": "Brand", "Website": "https://totalenergies.com", "Headquarters": "Cabo Delgado, Mozambique / Paris", "Ownership": "Operated by TotalEnergies (consortium)", "Founded": "2010", "Specialty Focus": "LNG liquefaction mega-project", "Summary": "Large onshore Mozambique LNG project led by TotalEnergies."},
    {"Company": "Coral South FLNG", "Role": "Brand", "Website": "https://www.eni.com", "Headquarters": "Mozambique / Milan", "Ownership": "Operated by Eni (Area 4 JV)", "Founded": "2017", "Specialty Focus": "FLNG production", "Summary": "Eni-operated floating LNG facility offshore Mozambique."},
    {"Company": "Greater Tortue Ahmeyim (GTA) FLNG", "Role": "Brand", "Website": "https://www.bp.com", "Headquarters": "Mauritania / Senegal", "Ownership": "bp-operated JV (bp, Kosmos, PETROSEN, SMH)", "Founded": "2016", "Specialty Focus": "FLNG export", "Summary": "bp-led FLNG development on the Mauritania–Senegal maritime border; first exports 2025."},
    {"Company": "Cameroon FLNG (Hilll Episeyo)", "Role": "Brand", "Website": "https://www.golarlng.com", "Headquarters": "Kribi, Cameroon", "Ownership": "Golar / Perenco / SNH project", "Founded": "2018", "Specialty Focus": "FLNG", "Summary": "First African FLNG project using Golar’s Hilli Episeyo vessel offshore Cameroon."},
    {"Company": "Energy Transfer", "Role": "Brand", "Website": "https://www.energytransfer.com", "Headquarters": "Dallas, Texas, United States", "Ownership": "Public", "Founded": "1996", "Specialty Focus": "Lake Charles LNG development / midstream", "Summary": "US midstream major developing Lake Charles LNG export project."},
    {"Company": "Berkshire Hathaway Energy", "Role": "Brand", "Website": "https://www.brkenergy.com", "Headquarters": "Des Moines, Iowa, United States", "Ownership": "subsidiary of Berkshire Hathaway", "Founded": "1999", "Specialty Focus": "Cove Point LNG (majority owner/operator)", "Summary": "Owns ~75% of Cove Point LNG after acquiring Dominion’s stake in 2023."},
    {"Company": "Cove Point LNG", "Role": "Brand", "Website": "https://www.covepointlng.com", "Headquarters": "Lusby, Maryland, United States", "Ownership": "Berkshire Hathaway Energy ~75%, Brookfield ~25%", "Founded": "1972", "Specialty Focus": "LNG export / import terminal", "Summary": "Maryland bidirectional LNG facility now majority-owned by Berkshire Hathaway Energy."},
    {"Company": "Elba Island LNG", "Role": "Brand", "Website": "https://www.kindermorgan.com", "Headquarters": "Savannah, Georgia, United States", "Ownership": "subsidiary of Kinder Morgan", "Founded": "1978", "Specialty Focus": "LNG liquefaction / export", "Summary": "Kinder Morgan’s Elba Island LNG facility near Savannah, Georgia."},
    {"Company": "Port Arthur LNG", "Role": "Brand", "Website": "https://semprainfrastructure.com", "Headquarters": "Port Arthur, Texas, United States", "Ownership": "Sempra Infrastructure Partners project", "Founded": "2019", "Specialty Focus": "LNG liquefaction export", "Summary": "Sempra Infrastructure’s Port Arthur LNG export project on the Texas Gulf Coast."},
    {"Company": "Delfin LNG", "Role": "Brand", "Website": "https://delfinlng.com", "Headquarters": "Houston, Texas, United States", "Ownership": "Private", "Founded": "2014", "Specialty Focus": "Deepwater FLNG / floating liquefaction", "Summary": "US deepwater port FLNG project planned in the Gulf of Mexico."},
    {"Company": "Texas LNG Brownsville", "Role": "Brand", "Website": "https://www.texaslng.com", "Headquarters": "Brownsville, Texas, United States", "Ownership": "Glenfarne / Alder Midstream", "Founded": "2014", "Specialty Focus": "LNG export development", "Summary": "Proposed LNG export terminal on the Brownsville Ship Channel (Glenfarne)."},
    {"Company": "Woodside Louisiana LNG", "Role": "Brand", "Website": "https://www.woodside.com", "Headquarters": "Louisiana, United States", "Ownership": "subsidiary of Woodside Energy (ex-Tellurian Driftwood)", "Founded": "2024", "Specialty Focus": "LNG liquefaction development", "Summary": "Woodside’s US Gulf Coast LNG development formerly Tellurian’s Driftwood LNG."},
    {"Company": "LNG Japan Corporation", "Role": "Brand", "Website": "https://www.lngjapan.com", "Headquarters": "Tokyo, Japan", "Ownership": "Owned by Sojitz / others (trading house LNG arm)", "Founded": "2002", "Specialty Focus": "LNG procurement / marketing", "Summary": "Japanese LNG procurement and marketing company serving utilities and industry."},
    {"Company": "Sumitomo Corporation", "Role": "Brand", "Website": "https://www.sumitomocorp.com", "Headquarters": "Tokyo, Japan", "Ownership": "Public", "Founded": "1919", "Specialty Focus": "LNG project equity / trading", "Summary": "Japanese sogo shosha with LNG project stakes and offtake marketing."},
    {"Company": "Itochu Corporation", "Role": "Brand", "Website": "https://www.itochu.co.jp", "Headquarters": "Tokyo, Japan", "Ownership": "Public", "Founded": "1858", "Specialty Focus": "LNG trading / project investments", "Summary": "Japanese trading house active in LNG offtake and upstream gas investments."},
    {"Company": "Sojitz Corporation", "Role": "Brand", "Website": "https://www.sojitz.com", "Headquarters": "Tokyo, Japan", "Ownership": "Public", "Founded": "2003", "Specialty Focus": "LNG marketing (LNG Japan)", "Summary": "Japanese trading company with LNG Japan and project interests."},
    {"Company": "JAPEX (Japan Petroleum Exploration)", "Role": "Brand", "Website": "https://www.japex.co.jp", "Headquarters": "Tokyo, Japan", "Ownership": "Public", "Founded": "1955", "Specialty Focus": "E&P / LNG projects", "Summary": "Japanese E&P company with LNG project participation and domestic gas."},
    {"Company": "Hanwha Corporation / Hanwha Energy", "Role": "Brand", "Website": "https://www.hanwha.com", "Headquarters": "Seoul, South Korea", "Ownership": "Private conglomerate", "Founded": "1952", "Specialty Focus": "LNG offtake / power", "Summary": "Korean conglomerate with LNG procurement for power and industrial use."},
    {"Company": "Castleton Commodities International", "Role": "Marketer", "Website": "https://www.cci.com", "Headquarters": "Stamford, Connecticut, United States", "Ownership": "Private", "Founded": "1997", "Specialty Focus": "LNG / gas trading", "Summary": "Global energy merchant active in natural gas and LNG marketing."},
    {"Company": "Hartree Partners", "Role": "Marketer", "Website": "https://www.hartreepartners.com", "Headquarters": "New York, United States", "Ownership": "Private", "Founded": "1997", "Specialty Focus": "Energy / LNG trading", "Summary": "Commodity merchant trading natural gas, power and LNG."},
    {"Company": "BB Energy", "Role": "Marketer", "Website": "https://www.bbenergy.com", "Headquarters": "Geneva / Dubai", "Ownership": "Private", "Founded": "1981", "Specialty Focus": "Oil & LNG trading", "Summary": "Independent energy trading house with LNG and oil products marketing."},
    {"Company": "Freepoint Commodities", "Role": "Marketer", "Website": "https://www.freepoint.com", "Headquarters": "Stamford, Connecticut, United States", "Ownership": "Private", "Founded": "2011", "Specialty Focus": "Gas / LNG merchant trading", "Summary": "US-based commodity merchant active in natural gas and LNG."},
    {"Company": "EemsEnergyTerminal", "Role": "Brand", "Website": "https://www.eemsenergyterminal.nl", "Headquarters": "Eemshaven, Netherlands", "Ownership": "Gasunie / Groningen Seaports related", "Founded": "2022", "Specialty Focus": "FSRU LNG import", "Summary": "Dutch FSRU-based LNG import terminal at Eemshaven opened 2022."},
    {"Company": "Deutsche ReGas", "Role": "Brand", "Website": "https://deutsche-regas.de", "Headquarters": "Germany", "Ownership": "Private", "Founded": "2022", "Specialty Focus": "German FSRU LNG terminals (Lubmin)", "Summary": "German LNG terminal developer/operator of Lubmin FSRU import capacity."},
    {"Company": "Gastrade", "Role": "Brand", "Website": "https://www.gastrade.gr", "Headquarters": "Athens, Greece", "Ownership": "Private / consortium", "Founded": "2010", "Specialty Focus": "Alexandroupolis FSRU", "Summary": "Developer/operator of the Alexandroupolis FSRU LNG import project in Greece."},
    {"Company": "DESFA", "Role": "Brand", "Website": "https://www.desfa.gr", "Headquarters": "Athens, Greece", "Ownership": "Private (Senfluga consortium)", "Founded": "2007", "Specialty Focus": "Greek gas TSO; Revithoussa LNG", "Summary": "Greek gas transmission operator of the Revithoussa LNG terminal."},
    {"Company": "Revithoussa LNG Terminal", "Role": "Brand", "Website": "https://www.desfa.gr", "Headquarters": "Revithoussa, Greece", "Ownership": "Operated by DESFA", "Founded": "2000", "Specialty Focus": "LNG import / regasification", "Summary": "Greece’s onshore LNG receiving terminal on Revithoussa island."},
    {"Company": "Azule Energy", "Role": "Brand", "Website": "https://www.azuleenergy.com", "Headquarters": "Luanda, Angola / London", "Ownership": "JV bp and Eni (50/50)", "Founded": "2022", "Specialty Focus": "Angola upstream / Angola LNG partner", "Summary": "bp–Eni Angolan JV; partner in Angola LNG."},
    {"Company": "Petrosen", "Role": "Brand", "Website": "https://www.petrosen.sn", "Headquarters": "Dakar, Senegal", "Ownership": "State-owned", "Founded": "1981", "Specialty Focus": "NOC; Greater Tortue Ahmeyim partner", "Summary": "Senegalese national oil company; partner in GTA FLNG."},
    {"Company": "SMH (Société Mauritanienne des Hydrocarbures)", "Role": "Brand", "Website": "https://www.smh.mr", "Headquarters": "Nouakchott, Mauritania", "Ownership": "State-owned", "Founded": "2004", "Specialty Focus": "NOC; GTA FLNG partner", "Summary": "Mauritanian hydrocarbons company; partner in Greater Tortue Ahmeyim."},
    {"Company": "EGAS (Egyptian Natural Gas Holding Company)", "Role": "Brand", "Website": "https://www.egas.com.eg", "Headquarters": "Cairo, Egypt", "Ownership": "State-owned", "Founded": "2001", "Specialty Focus": "LNG import/export coordination; ELNG partner", "Summary": "Egyptian state gas company managing LNG and domestic gas portfolio."},
    {"Company": "QatarEnergy Trading", "Role": "Marketer", "Website": "https://www.qatarenergy.qa", "Headquarters": "Doha, Qatar", "Ownership": "subsidiary of QatarEnergy", "Founded": "2021", "Specialty Focus": "LNG marketing / trading", "Summary": "QatarEnergy’s international LNG marketing and trading arm."},
    {"Company": "Petronas LNG", "Role": "Brand", "Website": "https://www.petronas.com", "Headquarters": "Kuala Lumpur, Malaysia", "Ownership": "subsidiary of Petronas", "Founded": "1983", "Specialty Focus": "MLNG / LNG production marketing", "Summary": "Petronas LNG production and marketing franchise including MLNG trains."},
    {"Company": "MLNG (Malaysia LNG)", "Role": "Brand", "Website": "https://www.petronas.com", "Headquarters": "Bintulu, Malaysia", "Ownership": "Petronas-led JV", "Founded": "1983", "Specialty Focus": "LNG liquefaction", "Summary": "Bintulu LNG complex — one of the world’s largest LNG production hubs."},
    {"Company": "Atlantic LNG", "Role": "Brand", "Website": "https://www.atlanticlng.com", "Headquarters": "Point Fortin, Trinidad and Tobago", "Ownership": "Joint venture (Shell, bp, and partners)", "Founded": "1995", "Specialty Focus": "LNG liquefaction", "Summary": "Trinidad and Tobago’s Atlantic LNG liquefaction trains."},
    {"Company": "Cheniere Corpus Christi Liquefaction", "Role": "Brand", "Website": "https://www.cheniere.com", "Headquarters": "Corpus Christi, Texas, United States", "Ownership": "subsidiary of Cheniere Energy", "Founded": "2015", "Specialty Focus": "LNG liquefaction export", "Summary": "Cheniere’s Corpus Christi LNG export trains on the Texas Gulf Coast."},
    {"Company": "Sabine Pass LNG", "Role": "Brand", "Website": "https://www.cheniere.com", "Headquarters": "Cameron Parish, Louisiana, United States", "Ownership": "subsidiary of Cheniere Energy", "Founded": "2008", "Specialty Focus": "LNG liquefaction export", "Summary": "Cheniere’s Sabine Pass LNG facility — among the largest US LNG export hubs."},
    {"Company": "Freeport LNG Development", "Role": "Brand", "Website": "https://freeportlng.com", "Headquarters": "Quintana, Texas, United States", "Ownership": "Private (Michael Smith majority; JERA, Osaka Gas interests)", "Founded": "2002", "Specialty Focus": "LNG liquefaction export", "Summary": "Operating Freeport LNG export terminal on Quintana Island, Texas."},
    {"Company": "Qatargas Operating Company", "Role": "Brand", "Website": "https://www.qatarenergylng.qa", "Headquarters": "Doha, Qatar", "Ownership": "merged into QatarEnergy LNG", "Founded": "1984", "Specialty Focus": "LNG production operations", "Summary": "Historic Qatargas operating company now integrated under QatarEnergy LNG."},
]

def _norm(s: str) -> str:
    s = str(s or "").strip().lower()
    s = (
        s.replace("ö", "o")
        .replace("ü", "u")
        .replace("ä", "a")
        .replace("ß", "ss")
        .replace("÷", "o")
    )
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _drop_reason(name: str, hq: str = "", ownership: str = "") -> str | None:
    blob = f"{name} {hq} {ownership}"
    if PAKISTAN_RE.search(blob):
        return "pakistan"
    if CITY_GAS_RE.search(name):
        return "city_gas_distributor"
    n = _norm(name)
    if n in DROP_EXACT:
        return f"off_market:{n}"
    for stem in sorted(DROP_EXACT, key=len, reverse=True):
        if len(stem.split()) >= 2 and (n == stem or n.startswith(stem + " ")):
            return f"off_market:{stem}"
        # single-token exact only
        if len(stem.split()) == 1 and n == stem:
            return f"off_market:{stem}"
    return None


def _blank_row(seed: dict) -> dict:
    row = {
        "Company": seed["Company"],
        "Website": seed.get("Website") or "",
        "Founded": seed.get("Founded") or "",
        "Headquarters": seed.get("Headquarters") or "",
        "Continent / Geography": "",
        "Operational Presence": "",
        "Ownership": seed.get("Ownership") or "",
        "Employees": "",
        "Core Categories": "Liquefied Natural Gas",
        "Specialty Focus": seed.get("Specialty Focus") or "LNG",
        "Key Brands Represented": seed["Company"],
        "Retail / E-commerce / Both": "N/A",
        "Distribution Type": seed["Role"],
        "Contact Person": "",
        "Role": seed["Role"],
        "Email": "",
        "LinkedIn": "",
        "Office No.": "",
        "Country Code": "",
        "Region Code": "",
        "Summary": seed.get("Summary") or "",
        "Industry Category": INDUSTRY,
    }
    # ownership_relation for Company Details
    own = str(row["Ownership"] or "")
    low = own.lower()
    if low.startswith("acquired by"):
        row["ownership_relation"] = "acquired_by"
        row["parent_owner"] = own[11:].strip()
    elif low.startswith("subsidiary of"):
        row["ownership_relation"] = "subsidiary_of"
        row["parent_owner"] = own[14:].strip()
    elif low.startswith("merged into"):
        row["ownership_relation"] = "merged_into"
        row["parent_owner"] = own[11:].strip()
    elif low.startswith("owned by") or low.startswith("joint venture"):
        row["ownership_relation"] = "owned_by" if low.startswith("owned by") else ""
        if low.startswith("owned by"):
            row["parent_owner"] = own[8:].strip()
    return row


async def _deepseek_fill(rows: list[dict]) -> list[dict]:
    """Fill missing HQ/website/founded/summary/continent via DeepSeek JSON batches."""
    key, base, model = deepseek_chat_config()
    if not key:
        print("WARN: no DeepSeek key — skipping LLM fill", flush=True)
        return rows
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=key, base_url=base)
    out: list[dict] = []
    batch_size = 8
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        names = [str(r.get("Company") or "") for r in batch]
        prompt = (
            "You are filling a Global Liquefied Natural Gas market landscape table.\n"
            "For each company return JSON array of objects with keys:\n"
            "company, website, founded (year string), headquarters (City, Country),\n"
            "continent_geography, operational_presence (regions), ownership,\n"
            "employees (approx or blank), specialty_focus, summary (1-2 sentences),\n"
            "country_code (ISO2), role (Brand or Marketer).\n"
            "Brand = LNG producer, project company, NOC with LNG, terminal/FSRU operator, LNG shipper.\n"
            "Marketer = pure LNG/gas commodity trader.\n"
            "Facts only; if unknown use empty string. No Pakistan companies.\n"
            f"Companies: {json.dumps(names, ensure_ascii=False)}"
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
                    "Summary": "summary",
                    "Country Code": "country_code",
                }
                for dst, src in mapping.items():
                    val = str(x.get(src) or "").strip()
                    if val and not str(r.get(dst) or "").strip():
                        r[dst] = val
                role = str(x.get("role") or r.get("Role") or "Brand").strip()
                if role in ("Brand", "Marketer"):
                    r["Role"] = role
                    r["Distribution Type"] = role
            # Pakistan safety
            if PAKISTAN_RE.search(
                f"{r.get('Company')} {r.get('Headquarters')} {r.get('Ownership')}"
            ):
                print("SKIP pakistan from fill:", r.get("Company"), flush=True)
                continue
            out.append(r)
        print(f"filled {min(i+batch_size, len(rows))}/{len(rows)}", flush=True)
    return out


async def main() -> int:
    apply_chatgpt_expand_env(root=ROOT)
    os.environ["EXPAND_XY_SKIP_CRAWL"] = "1"
    os.environ["EXPAND_MARKET_AXIS_LLM"] = "1"
    os.environ.setdefault("EXPAND_XY_CONCURRENT", "6")

    wb = load_workbook(XLSX, data_only=True)
    ws = wb["Landscape"]
    rows_raw = list(ws.iter_rows(values_only=True))
    hdr = [str(h) for h in rows_raw[0]]

    kept: list[dict] = []
    removed: list[dict] = []
    existing: set[str] = set()

    for r in rows_raw[1:]:
        if not r:
            continue
        d = {hdr[i]: ("" if r[i] is None else r[i]) for i in range(len(hdr)) if i < len(r)}
        name = str(d.get("Company") or "").strip()
        if not name:
            continue
        role = str(d.get("Role") or d.get("Distribution Type") or "Brand").strip()
        reason = _drop_reason(
            name, str(d.get("Headquarters") or ""), str(d.get("Ownership") or "")
        )
        if role not in ("Brand", "Marketer"):
            reason = reason or f"wrong_role:{role}"
        if reason:
            removed.append({"company": name, "reason": reason})
            continue
        d["Role"] = role
        d["Distribution Type"] = role
        d["Industry Category"] = INDUSTRY
        # Clear FMCG-ish retail for energy
        if str(d.get("Retail / E-commerce / Both") or "").strip() in ("", "Both", "Retail"):
            d["Retail / E-commerce / Both"] = "N/A"
        kept.append(d)
        existing.add(_norm(name))

    print(f"kept={len(kept)} removed={len(removed)}", flush=True)

    # Add candidates until TARGET_MIN (+ buffer)
    to_add_seeds = []
    for c in NEW_CANDIDATES:
        key = _norm(c["Company"])
        if key in existing:
            continue
        # Skip near-duplicates of parents already present
        skip = False
        for stem in (
            "freeport lng",
            "cheniere",
            "qatarenergy",
            "qatargas",
            "petronas",
            "venture global",
            "sempra",
        ):
            if stem in key and any(stem in e for e in existing):
                # allow distinct project names unless exact parent brand already covers
                if key in ("freeport lng development",) or key.startswith("qatargas"):
                    skip = True
                    break
                if "cheniere" in key and any(e == "cheniere energy" or e.startswith("cheniere") for e in existing):
                    skip = True
                    break
        if skip:
            continue
        if _drop_reason(c["Company"], c.get("Headquarters") or "", c.get("Ownership") or ""):
            continue
        to_add_seeds.append(c)
        existing.add(key)
        if len(kept) + len(to_add_seeds) >= TARGET_MIN + 20:
            break

    print(f"adding {len(to_add_seeds)} new LNG Brand/Marketer rows", flush=True)
    new_rows = [_blank_row(s) for s in to_add_seeds]
    new_rows = await _deepseek_fill(new_rows)

    # Score only new rows (keep existing scores)
    if new_rows:
        print(f"Scoring {len(new_rows)} new rows via DeepSeek...", flush=True)
        scored, _xy_audit = await score_expand_rows(new_rows, QUERY, country="global")
        new_rows = scored or new_rows
        if _xy_audit:
            audit_path = OUT / "chatgpt_expand_batch_all_audit.json"
            # merge later into write audit

    final_rows = kept + new_rows
    # Final Pakistan + role sweep
    clean: list[dict] = []
    for r in final_rows:
        name = str(r.get("Company") or "")
        if PAKISTAN_RE.search(
            f"{name} {r.get('Headquarters') or ''} {r.get('Ownership') or ''}"
        ):
            removed.append({"company": name, "reason": "pakistan_final"})
            continue
        role = str(r.get("Role") or "Brand")
        if role not in ("Brand", "Marketer"):
            r["Role"] = "Brand"
            r["Distribution Type"] = "Brand"
        else:
            r["Distribution Type"] = role
        clean.append(r)
    final_rows = clean

    brand_n = sum(1 for r in final_rows if str(r.get("Role")) == "Brand")
    marketer_n = sum(1 for r in final_rows if str(r.get("Role")) == "Marketer")
    print(f"final={len(final_rows)} Brand={brand_n} Marketer={marketer_n}", flush=True)

    audit_path = OUT / "chatgpt_expand_batch_all_audit.json"
    audit: dict = {}
    if audit_path.exists():
        audit = json.loads(audit_path.read_text(encoding="utf-8")).get("xy_scoring") or {}

    detail_rows = to_company_detail_rows(final_rows, QUERY, audit)
    by_co = {_norm(str(r.get("Company") or "")): str(r.get("Role") or "Brand") for r in final_rows}
    for d in detail_rows:
        role = by_co.get(_norm(d.get("Brand") or ""))
        if role in ("Brand", "Marketer"):
            d["Role"] = role

    write_final_xlsx(
        XLSX,
        final_rows,
        "Companies",
        {
            "query": QUERY,
            "purge_topup": "2026-08-14",
            "removed": len(removed),
            "added": len(new_rows),
            "brand": brand_n,
            "marketer": marketer_n,
            "xy_scoring": audit,
        },
        detail_rows=detail_rows,
    )
    extras = export_expand_quadrant_outputs(
        OUT, detail_rows, QUERY, country="global", audit=audit, chart_n=20
    )

    report = {
        "before": len(rows_raw) - 1,
        "after": len(final_rows),
        "removed": removed,
        "added": [r.get("Company") for r in new_rows],
        "brand": brand_n,
        "marketer": marketer_n,
        "html": str(extras.get("html") or ""),
    }
    AUDIT.mkdir(parents=True, exist_ok=True)
    (AUDIT / f"{SLUG}_purge_topup.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps({k: report[k] for k in ("before", "after", "brand", "marketer") if k in report}))
    print("removed", len(removed), "added", len(new_rows))
    print("html", extras.get("html"))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
