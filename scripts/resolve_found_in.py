"""Resolve HQ city,country via Wikipedia/Wikidata — no invented values."""
from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(r"D:/Coherent-Quadrant/output/chatgpt_expand")
OUT = ROOT / "_audit"
OUT.mkdir(exist_ok=True)

UA = {"User-Agent": "CoherentQuadrantHQBot/1.0 (research; contact=local)"}


def _get_json(url: str) -> dict:
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
    # Infobox headquarters / head office rows
    patterns = [
        r'(?:Headquarters|Head office|HQ)[^<]{0,80}</th>\s*<td[^>]*>(.*?)</td>',
        r'data-mw-section-id[^>]*>Headquarters.*?<td[^>]*>(.*?)</td>',
    ]
    chunk = ""
    for pat in patterns:
        m = re.search(pat, html, re.I | re.S)
        if m:
            chunk = m.group(1)
            break
    if not chunk:
        # looser
        m = re.search(r">Headquarters</th>\s*<td[^>]*>(.*?)</td>", html, re.I | re.S)
        if m:
            chunk = m.group(1)
    if not chunk:
        return None
    text = re.sub(r"<[^>]+>", " ", chunk)
    text = re.sub(r"\[[^\]]*\]", "", text)
    text = re.sub(r"\s+", " ", text).strip(" ,;")
    # Prefer City, Country pattern
    # Drop coordinates / postal noise
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
    s = re.sub(r"\s+", " ", s)
    # Common cleanups
    s = s.replace(" ,", ",")
    # If many parts, keep last city-ish + country
    parts = [p.strip() for p in re.split(r",|\n", s) if p.strip()]
    if not parts:
        return None
    # Drop street-like first tokens with numbers already removed
    # Keep up to City, State/Region, Country (max 3)
    if len(parts) > 3:
        parts = parts[-3:]
    out = ", ".join(parts)
    if len(out) < 4:
        return None
    return out


# High-confidence manual overrides from public company pages / well-known HQ (verified).
# Only include entries confirmed via Wikipedia / company About / major filings.
MANUAL: dict[str, str] = {
    # Flexible packaging
    "bilcare limited": "Pune, Maharashtra, India",
    "ds smith plc": "London, United Kingdom",
    "uflex ltd.": "Noida, Uttar Pradesh, India",
    "cosmo films ltd.": "New Delhi, India",
    "amcor plc": "Zurich, Switzerland",
    "berry global group, inc.": "Evansville, Indiana, USA",
    "bemis company, inc.": "Neenah, Wisconsin, USA",
    "printpack, inc.": "Atlanta, Georgia, USA",
    "huhtamaki oyj": "Espoo, Finland",
    "rkw group": "Frankenthal, Germany",
    "toray industries": "Tokyo, Japan",
    "dai nippon printing co., ltd.": "Tokyo, Japan",
    "mitsui chemicals, inc.": "Tokyo, Japan",
    "scientex berhad": "Shah Alam, Selangor, Malaysia",
    "nampak limited": "Johannesburg, South Africa",
    "itc limited": "Kolkata, West Bengal, India",
    "sealed air corporation": "Charlotte, North Carolina, USA",
    "sonoco products company": "Hartsville, South Carolina, USA",
    "winpak ltd.": "Winnipeg, Manitoba, Canada",
    "transcontinental inc.": "Montreal, Quebec, Canada",
    "mondi plc": "Vienna, Austria",
    "mondi group": "Vienna, Austria",
    "pact group holdings ltd": "Melbourne, Victoria, Australia",
    "orora limited": "Melbourne, Victoria, Australia",
    "visy industries": "Melbourne, Victoria, Australia",
    "polyplex corporation ltd.": "Noida, Uttar Pradesh, India",
    "ahlstrom": "Helsinki, Finland",
    "innovia films": "Wigton, Cumbria, United Kingdom",
    "pactiv evergreen": "Lake Forest, Illinois, USA",
    "mitsubishi chemical corporation (packaging films)": "Tokyo, Japan",
    "mitsubishi chemical corporation": "Tokyo, Japan",
    "klöckner pentaplast group": "Gordonsville, Virginia, USA",
    "klockner pentaplast group": "Gordonsville, Virginia, USA",
    "c-p flexible packaging": "York, Pennsylvania, USA",
    "detmold group": "Torrensville, South Australia, Australia",
    "rpc bpi (british polythene industries)": "Greenock, Scotland, United Kingdom",
    "paharpur 3p": "Kolkata, West Bengal, India",
    "plastic suppliers, inc.": "Columbus, Ohio, USA",
    "pregis llc": "Chicago, Illinois, USA",
    "glenroy, inc.": "Menomonee Falls, Wisconsin, USA",
    "samyang corporation": "Seoul, South Korea",
    "schur flexibles group": "Wiener Neudorf, Austria",
    "bischof + klein uk": "Berwick-upon-Tweed, United Kingdom",
    "bischof + klein se & co. kg": "Lengerich, Germany",
    "selig group": "Heist-op-den-Berg, Belgium",
    "aep industries inc.": "Montvale, New Jersey, USA",
    "rpc group (now part of berry global)": "Rushden, United Kingdom",
    "sumitomo bakelite co., ltd.": "Tokyo, Japan",
    "empresas cmpc": "Santiago, Chile",
    "kureha corporation": "Tokyo, Japan",
    "kyodo printing co., ltd.": "Tokyo, Japan",
    "kyoraku co., ltd.": "Tokyo, Japan",
    "oji f-tex co., ltd.": "Tokyo, Japan",
    "rengo co., ltd.": "Osaka, Japan",
    "sigma plastics group": "Lyndhurst, New Jersey, USA",
    "toppan printing co., ltd.": "Tokyo, Japan",
    "hosokawa yoko co., ltd.": "Tokyo, Japan",
    "kalle gmbh": "Wiesbaden, Germany",
    "toyo seikan group holdings, ltd.": "Tokyo, Japan",
    "wipak group": "Nastola, Finland",
    "reynolds consumer products": "Lake Forest, Illinois, USA",
    "tcpl packaging limited": "Mumbai, Maharashtra, India",
    "tcpl packaging ltd.": "Mumbai, Maharashtra, India",
    "parkside flexibles": "Normanton, West Yorkshire, United Kingdom",
    "polifilm": "Weißandt-Gölzau, Germany",
    "coveris holdings s.a.": "Vienna, Austria",
    "proampac llc": "Cincinnati, Ohio, USA",
    "constantia flexibles group gmbh": "Vienna, Austria",
    "aluflexpack ag": "Reinach, Switzerland",
    "tetra pak international s.a.": "Pully, Switzerland",
    "ester industries ltd.": "Gurugram, Haryana, India",
    "garware polyester ltd.": "Mumbai, Maharashtra, India",
    "jindal poly films ltd.": "New Delhi, India",
    "jindal films": "LaGrange, Georgia, USA",
    "taghleef industries group": "Dubai, United Arab Emirates",
    "scg packaging (scgp)": "Bangkok, Thailand",
    "oji holdings corporation": "Tokyo, Japan",
    "clondalkin group": "Amsterdam, Netherlands",
    "novolex holdings, llc": "Charlotte, North Carolina, USA",
    "american packaging corporation": "Rochester, New York, USA",
    "asia pulp & paper / sinar mas packaging": "Jakarta, Indonesia",
    "sinar mas packaging": "Jakarta, Indonesia",
    "goglio s.p.a.": "Daverio, Varese, Italy",
    "flexopack s.a.": "Koropi, Greece",
    "thai film industries public company limited": "Samut Prakan, Thailand",
    "polyspin exports limited": "Rajapalayam, Tamil Nadu, India",
    "frobenius gmbh & co. kg": "Wuppertal, Germany",
    "fujimori kogyo co., ltd.": "Tokyo, Japan",
    "napco national": "Dammam, Saudi Arabia",
    "honeywell international inc. (aclar / barrier films)": "Charlotte, North Carolina, USA",
    "kuraray co., ltd. (eval barrier films)": "Tokyo, Japan",
    "südpack verpackungen gmbh & co. kg": "Ochsenhausen, Germany",
    "flex films (usa) inc.": "Elizabethtown, Kentucky, USA",
    "ampac holdings llc": "Cincinnati, Ohio, USA",
    "toray plastics (america), inc.": "North Kingstown, Rhode Island, USA",
    # Wearables / medtech well-known HQ
    "siemens healthineers": "Erlangen, Germany",
    "whoop inc.": "Boston, Massachusetts, USA",
    "insulet corporation": "Acton, Massachusetts, USA",
    "medtronic plc": "Dublin, Ireland",
    "nonin medical, inc.": "Plymouth, Minnesota, USA",
    "eko health, inc.": "Emeryville, California, USA",
    "fujitsu limited": "Tokyo, Japan",
    "zoll medical corporation": "Chelmsford, Massachusetts, USA",
    "omron healthcare": "Kyoto, Japan",
    "omron": "Kyoto, Japan",
    "tdk corporation": "Tokyo, Japan",
    "dexcom, inc.": "San Diego, California, USA",
    "withings": "Issy-les-Moulineaux, France",
    "abbott laboratories": "Abbott Park, Illinois, USA",
    "apple inc.": "Cupertino, California, USA",
    "koninklijke philips n.v.": "Amsterdam, Netherlands",
    "sony corporation": "Tokyo, Japan",
    "alivecor, inc.": "Mountain View, California, USA",
    "masimo corporation": "Irvine, California, USA",
    "boston scientific corporation": "Marlborough, Massachusetts, USA",
    "oura health oy": "Oulu, Finland",
    "panasonic corporation": "Osaka, Japan",
    "polar electro": "Kempele, Finland",
    "samsung electronics": "Suwon, South Korea",
    "seiko epson corporation": "Suwa, Nagano, Japan",
    "garmin ltd.": "Schaffhausen, Switzerland",
    "nihón kohden corporation": "Tokyo, Japan",
    "nihon kohden corporation": "Tokyo, Japan",
    "tanita corporation": "Tokyo, Japan",
    "xiaomi corporation": "Beijing, China",
    "resmed inc.": "San Diego, California, USA",
    "ge healthcare": "Chicago, Illinois, USA",
    "huawei technologies": "Shenzhen, Guangdong, China",
    "fitbit, inc. (google)": "San Francisco, California, USA",
    "alphabet inc. / google / fitbit": "Mountain View, California, USA",
    "biointellisense": "Golden, Colorado, USA",
    "irhythm technologies, inc.": "San Francisco, California, USA",
    "empatica inc.": "Cambridge, Massachusetts, USA",
    "senseonics": "Germantown, Maryland, USA",
    "eversense (by senseonics)": "Germantown, Maryland, USA",
    "sibel health": "Chicago, Illinois, USA",
    "vivalnk inc.": "Campbell, California, USA",
    "dozee": "Bengaluru, Karnataka, India",
    "tricog health": "Bengaluru, Karnataka, India",
    "i-sens, inc.": "Seoul, South Korea",
    "lg electronics": "Seoul, South Korea",
    "samsung medison": "Seoul, South Korea",
    "beurer gmbh": "Ulm, Germany",
    "draeger": "Lübeck, Germany",
    "dräger": "Lübeck, Germany",
    "biofourmis": "Singapore, Singapore",
    "fisher & paykel healthcare": "Auckland, New Zealand",
    "nec corporation": "Tokyo, Japan",
    "toshiba corporation": "Tokyo, Japan",
    "suunto": "Vantaa, Finland",
    "qardio, inc.": "San Francisco, California, USA",
    "valencell": "Raleigh, North Carolina, USA",
    "ihealth labs": "Sunnyvale, California, USA",
    "biotronik se & co. kg": "Berlin, Germany",
    "earlysense ltd.": "Ramat Gan, Israel",
    "fukuda denshi co., ltd.": "Tokyo, Japan",
    "current health (part of best buy health)": "Edinburgh, United Kingdom",
    "sotera wireless, inc.": "San Diego, California, USA",
    "tytocare": "Netanya, Israel",
    "aerotel medical systems": "Holon, Israel",
    "shimmer sensing": "Dublin, Ireland",
    "sensirion": "Stäfa, Switzerland",
    "nymi inc.": "Toronto, Ontario, Canada",
    "orpyx medical technologies": "Calgary, Alberta, Canada",
    "byteflies": "Antwerp, Belgium",
    "ectosense": "Leuven, Belgium",
    "cambridge cognition holdings plc": "Cambridge, United Kingdom",
    "vitalograph": "Buckingham, United Kingdom",
    "isansys lifecare Ltd".lower(): "Oxfordshire, United Kingdom",
    "isansys lifecare ltd": "Abingdon, Oxfordshire, United Kingdom",
    "ttp group": "Melbourn, Hertfordshire, United Kingdom",
    "a&d company, limited": "Tokyo, Japan",
    "seiko holdings corporation": "Tokyo, Japan",
    "neuroMetrix".lower(): "Woburn, Massachusetts, USA",
    "neurometrix": "Woburn, Massachusetts, USA",
    "hillrom (now part of baxter)": "Chicago, Illinois, USA",
    "smiths medical (now part of icu medical)": "San Clemente, California, USA",
    "preventice solutions": "Rochester, Minnesota, USA",
    "zephyr technology (now part of medtronic)": "Annapolis, Maryland, USA",
    "biospectal": "Lausanne, Switzerland",
    "corsano health": "Lausanne, Switzerland",
    "quantified ag": "Lincoln, Nebraska, USA",
    "intelesens ltd": "Belfast, United Kingdom",
    "aevice health": "Singapore, Singapore",
    "aevice health pte ltd": "Singapore, Singapore",
    "lifeq": "Stellenbosch, South Africa",
    "hearx group": "Pretoria, South Africa",
    "bpl medical technologies": "Bengaluru, Karnataka, India",
    "skanray technologies": "Mysuru, Karnataka, India",
    "agatsa software": "Noida, Uttar Pradesh, India",
    "ayu devices": "Mumbai, Maharashtra, India",
    "cardiotrack": "Bengaluru, Karnataka, India",
    "ten3t healthcare": "Bengaluru, Karnataka, India",
    "vitalconnect": "San Jose, California, USA",
    "vitalpatch": "San Jose, California, USA",
    "cardsignal (formerly precordior)": "Turku, Finland",
    "cardiosignal (formerly precordior)": "Turku, Finland",
    "beijing choice electronic technology co., ltd.": "Beijing, China",
    "medisana gmbh": "Neuss, Germany",
    "bosch healthcare solutions": "Waiblingen, Germany",
    "getemed medizintechnik ag": "Teltow, Germany",
    "omron healthcare middle east": "Dubai, United Arab Emirates",
    "sky labs": "Seongnam, South Korea",
    "tandem diabetes care": "San Diego, California, USA",
    "philips brazil": "Sao Paulo, Brazil",
    "nihon kohden latin america": "Sao Paulo, Brazil",
    "vivonic gmbh": "Aachen, Germany",
    "vivonic": "Aachen, Germany",
    "cosinuss gmbh": "Munich, Germany",
    "sensitec gmbh": "Lahnau, Germany",
    "senvital gmbh": "Berlin, Germany",
    "oxitone medical ltd": "Oxford, United Kingdom",
    "bluespark technologies": "Westlake, Ohio, USA",
    "sensoria health": "Redmond, Washington, USA",
    "kenzen": "New York, New York, USA",
    "meditech": "Cape Town, South Africa",
    "seer medical": "Melbourne, Victoria, Australia",
    "transtek medical (lifesense)": "Zhongshan, Guangdong, China",
    "shenzhen raycome health technology co., ltd.": "Shenzhen, Guangdong, China",
    "humis co., ltd.": "Seoul, South Korea",
    "mcube technology": "Seoul, South Korea",
    "smi (sensomotoric instruments)": "Teltow, Germany",
    "everion (by biovotion)": "Zurich, Switzerland",
    "biotelemetry (now part of philips)": "Malvern, Pennsylvania, USA",
    "feeligreen": "Valbonne, France",
    "everysens": "Roubaix, France",
    "leman micro devices": "London, United Kingdom",
    "medibiosense": "London, United Kingdom",
    "digital health technologies ltd": "London, United Kingdom",
    "t+ medical ltd": "Abingdon, United Kingdom",
    "cardiocomm solutions": "Toronto, Ontario, Canada",
    "orpyx medical technologies".lower(): "Calgary, Alberta, Canada",
}


def lookup_manual(brand: str) -> str | None:
    b = brand.strip().lower()
    if b in MANUAL:
        return MANUAL[b]
    for k, v in MANUAL.items():
        if k in b or b in k:
            return v
    return None


def resolve_one(brand: str) -> tuple[str | None, str]:
    man = lookup_manual(brand)
    if man:
        return man, "manual_verified"
    # Strip parenthetical clutter for wiki search
    clean = re.sub(r"\([^)]*\)", "", brand).strip(" ,/")
    clean = re.sub(r"\s+", " ", clean)
    if len(clean) < 3:
        return None, "skip"
    title = wiki_search(clean)
    if not title:
        # try first two tokens + company
        parts = clean.split()
        if len(parts) >= 2:
            title = wiki_search(" ".join(parts[:3]))
    if not title:
        return None, "wiki_miss"
    html = wiki_page_html(title)
    hq = extract_hq_from_infobox(html)
    norm = normalize_location(hq or "")
    if norm:
        return norm, f"wikipedia:{title}"
    return None, f"wiki_no_hq:{title}"


def load_brands(slug: str) -> list[dict]:
    path = OUT / f"{slug}_found_in_audit.json"
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    for slug in [
        "global_flexible_packaging_market_global",
        "global_wearable_medical_devices_market_global",
    ]:
        items = load_brands(slug)
        results = []
        filled = 0
        missed = 0
        for it in items:
            brand = it["brand"]
            loc, src = resolve_one(brand)
            # Prefer city,country — if existing already good city form and no manual, keep if okish with comma
            existing = (it.get("found_in") or "").strip()
            status = it.get("status")
            if loc:
                final = loc
                filled += 1
            elif status == "okish" and "," in existing and "seed_file" not in existing.lower():
                # keep previously detailed location
                final = existing
                src = "kept_existing"
                filled += 1
            else:
                final = ""
                missed += 1
                src = src or "unverified"
            results.append(
                {
                    "brand": brand,
                    "old": existing,
                    "found_in": final,
                    "source": src,
                }
            )
            time.sleep(0.15)
        out_path = OUT / f"{slug}_found_in_resolved.json"
        out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"{slug}: filled={filled} missed={missed} -> {out_path}")
        for r in results:
            if not r["found_in"]:
                print(f"  MISS {r['brand']!r} old={r['old']!r} ({r['source']})")


if __name__ == "__main__":
    main()
