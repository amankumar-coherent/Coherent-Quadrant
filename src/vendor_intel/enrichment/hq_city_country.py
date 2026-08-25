"""Resolve headquarters as ``City, Country`` for Company Details Found in.

Never invents. Prefer existing City, Country → known map → Wikipedia infobox.
Country-only values (USA, Germany, …) are treated as incomplete.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

# Well-known public HQs (Wikipedia / company filings). Longest-stem match.
_KNOWN_HQ: dict[str, str] = {
    "taiwan semiconductor manufacturing": "Hsinchu, Taiwan",
    "tsmc": "Hsinchu, Taiwan",
    "asml holding": "Veldhoven, Netherlands",
    "asml": "Veldhoven, Netherlands",
    "intel corporation": "Santa Clara, California, USA",
    "intel": "Santa Clara, California, USA",
    "nvidia": "Santa Clara, California, USA",
    "advanced micro devices": "Santa Clara, California, USA",
    "amd": "Santa Clara, California, USA",
    "samsung electronics": "Suwon, South Korea",
    "samsung electro-mechanics": "Suwon, South Korea",
    "broadcom": "San Jose, California, USA",
    "qualcomm": "San Diego, California, USA",
    "mediatek": "Hsinchu, Taiwan",
    "sk hynix": "Icheon, South Korea",
    "micron technology": "Boise, Idaho, USA",
    "kioxia": "Tokyo, Japan",
    "texas instruments": "Dallas, Texas, USA",
    "analog devices": "Wilmington, Massachusetts, USA",
    "infineon technologies": "Neubiberg, Germany",
    "infineon": "Neubiberg, Germany",
    "nxp semiconductors": "Eindhoven, Netherlands",
    "nxp": "Eindhoven, Netherlands",
    "stmicroelectronics": "Geneva, Switzerland",
    "renesas electronics": "Tokyo, Japan",
    "renesas": "Tokyo, Japan",
    "on semiconductor": "Phoenix, Arizona, USA",
    "onsemi": "Phoenix, Arizona, USA",
    "microchip technology": "Chandler, Arizona, USA",
    "rohm semiconductor": "Kyoto, Japan",
    "rohm": "Kyoto, Japan",
    "arm holdings": "Cambridge, United Kingdom",
    "globalfoundries": "Malta, New York, USA",
    "smic": "Shanghai, China",
    "umc": "Hsinchu, Taiwan",
    "united microelectronics": "Hsinchu, Taiwan",
    "tower semiconductor": "Migdal HaEmek, Israel",
    "applied materials": "Santa Clara, California, USA",
    "lam research": "Fremont, California, USA",
    "kla corporation": "Milpitas, California, USA",
    "tokyo electron": "Tokyo, Japan",
    "asm international": "Almere, Netherlands",
    "ase technology": "Kaohsiung, Taiwan",
    "amkor technology": "Tempe, Arizona, USA",
    "jcet": "Jiangyin, Jiangsu, China",
    "cadence design": "San Jose, California, USA",
    "synopsys": "Sunnyvale, California, USA",
    "siemens eda": "Wilsonville, Oregon, USA",
    "mentor graphics": "Wilsonville, Oregon, USA",
    "apple": "Cupertino, California, USA",
    "marvell technology": "Santa Clara, California, USA",
    "marvell": "Santa Clara, California, USA",
    "western digital": "San Jose, California, USA",
    "murata manufacturing": "Nagaokakyo, Kyoto, Japan",
    "murata": "Nagaokakyo, Kyoto, Japan",
    "sony semiconductor": "Atsugi, Kanagawa, Japan",
    "bosch sensortec": "Reutlingen, Germany",
    "robert bosch": "Gerlingen, Germany",
    "qorvo": "Greensboro, North Carolina, USA",
    "nexperia": "Nijmegen, Netherlands",
    "wolfspeed": "Durham, North Carolina, USA",
    "siltronic": "Munich, Germany",
    "globalwafers": "Hsinchu, Taiwan",
    "nordic semiconductor": "Trondheim, Norway",
    "lattice semiconductor": "Hillsboro, Oregon, USA",
    "vishay intertechnology": "Malvern, Pennsylvania, USA",
    "vishay": "Malvern, Pennsylvania, USA",
    "teradyne": "North Reading, Massachusetts, USA",
    "advantest": "Tokyo, Japan",
    "disco corporation": "Tokyo, Japan",
    "mitsubishi electric": "Tokyo, Japan",
    "rohde & schwarz": "Munich, Germany",
    "realtek": "Hsinchu, Taiwan",
    "winbond": "Taichung, Taiwan",
    "nanya technology": "New Taipei City, Taiwan",
    "hua hong": "Shanghai, China",
    "powerchip": "Hsinchu, Taiwan",
    "mobileye": "Jerusalem, Israel",
    "cerebras": "Sunnyvale, California, USA",
    "graphcore": "Bristol, United Kingdom",
    "sambanova": "Palo Alto, California, USA",
    "ampere computing": "Santa Clara, California, USA",
    "pragmatic semiconductor": "Cambridge, United Kingdom",
    "iqe plc": "Cardiff, United Kingdom",
    "iqe": "Cardiff, United Kingdom",
    "cyient": "Hyderabad, Telangana, India",
    "tata electronics": "Mumbai, Maharashtra, India",
    "dexcom": "San Diego, California, USA",
    "abbott laboratories": "Abbott Park, Illinois, USA",
    "medtronic": "Dublin, Ireland",
    "masimo": "Irvine, California, USA",
    "philips": "Amsterdam, Netherlands",
    "omron healthcare": "Kyoto, Japan",
    "siemens healthineers": "Erlangen, Germany",
    "amcor": "Zurich, Switzerland",
    "berry global": "Evansville, Indiana, USA",
    "constantia flexibles": "Vienna, Austria",
    "huhtamaki": "Espoo, Finland",
    "uflex": "Noida, Uttar Pradesh, India",
    "sealed air": "Charlotte, North Carolina, USA",
}

_COUNTRY_ONLY = frozenset(
    {
        "usa",
        "us",
        "u.s.",
        "u.s.a.",
        "united states",
        "united states of america",
        "uk",
        "u.k.",
        "united kingdom",
        "great britain",
        "england",
        "scotland",
        "wales",
        "india",
        "japan",
        "china",
        "germany",
        "france",
        "italy",
        "spain",
        "canada",
        "australia",
        "brazil",
        "mexico",
        "switzerland",
        "netherlands",
        "belgium",
        "austria",
        "sweden",
        "norway",
        "denmark",
        "finland",
        "ireland",
        "israel",
        "singapore",
        "malaysia",
        "thailand",
        "taiwan",
        "south korea",
        "korea",
        "south africa",
        "uae",
        "united arab emirates",
        "saudi arabia",
        "qatar",
        "chile",
        "argentina",
        "indonesia",
        "vietnam",
        "philippines",
        "poland",
        "portugal",
        "turkey",
        "egypt",
        "kenya",
        "nigeria",
        "luxembourg",
        "hong kong",
        "new zealand",
        "russia",
        "global",
        "worldwide",
        "n/a",
        "na",
        "unknown",
        "not publicly disclosed",
    }
)

_UA = {"User-Agent": "CoherentQuadrantHQBot/1.0 (research; local pipeline)"}
_CACHE: dict[str, str] | None = None


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _cache_path() -> Path:
    override = (os.getenv("FOUND_IN_HQ_CACHE") or "").strip()
    if override:
        return Path(override)
    return _repo_root() / "data" / "hq_city_country_cache.json"


def _load_cache() -> dict[str, str]:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    path = _cache_path()
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                _CACHE = {str(k).lower(): str(v) for k, v in raw.items() if v}
                return _CACHE
        except Exception:
            pass
    _CACHE = {}
    return _CACHE


def _save_cache() -> None:
    if _CACHE is None:
        return
    path = _cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_CACHE, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _norm_name(s: str) -> str:
    s = str(s or "").strip().lower()
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"[^\w\s&+.-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def is_country_only(text: str) -> bool:
    """True when value is a bare country / placeholder (not City, Country)."""
    s = re.sub(r"\s+", " ", str(text or "").strip())
    if not s:
        return True
    low = s.lower().strip(".")
    if low in _COUNTRY_ONLY:
        return True
    # No comma → not City, Country format for Found in
    if "," not in s:
        return True
    return False


def is_city_country(text: str) -> bool:
    """True when text looks like City, Country (has comma, not year-only)."""
    s = re.sub(r"\s+", " ", str(text or "").strip())
    if not s or "," not in s:
        return False
    if s.isdigit() and len(s) == 4:
        return False
    parts = [p.strip() for p in s.split(",") if p.strip()]
    if len(parts) < 2:
        return False
    if len(s) < 5 or len(s) > 120:
        return False
    # Reject if entire string is somehow still a country list without a city
    if s.lower() in _COUNTRY_ONLY:
        return False
    return True


def normalize_city_country(raw: str) -> str:
    """Clean a HQ string into City, Country when possible; else ''."""
    s = str(raw or "").strip()
    if not s or is_country_only(s):
        return ""
    s = s.replace("U.S.A.", "USA").replace("U.S.", "USA").replace("United States of America", "USA")
    s = s.replace("United States", "USA")
    s = re.sub(r"\s+", " ", s).replace(" ,", ",")
    parts = [p.strip() for p in re.split(r",|\n", s) if p.strip()]
    if len(parts) < 2:
        return ""
    if len(parts) > 3:
        parts = parts[-3:]
    out = ", ".join(parts)
    return out if is_city_country(out) else ""


def lookup_known_hq(company: str) -> str:
    name = _norm_name(company)
    if not name:
        return ""
    if name in _KNOWN_HQ:
        return _KNOWN_HQ[name]
    best = ""
    best_len = 0
    for stem, hq in _KNOWN_HQ.items():
        stem_n = stem.strip()
        if len(stem_n) < 3:
            continue
        if name == stem_n or name.startswith(stem_n + " ") or f" {stem_n} " in f" {name} ":
            if len(stem_n) > best_len:
                best = hq
                best_len = len(stem_n)
    return best


def _wiki_search(name: str) -> str | None:
    q = urllib.parse.quote(name)
    url = (
        "https://en.wikipedia.org/w/api.php?action=opensearch&limit=1&namespace=0"
        f"&search={q}&format=json"
    )
    try:
        req = urllib.request.Request(url, headers=_UA)
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        if isinstance(data, list) and len(data) > 1 and data[1]:
            return str(data[1][0])
    except Exception:
        return None
    return None


def _wiki_hq(title: str) -> str:
    q = urllib.parse.quote(title.replace(" ", "_"))
    url = f"https://en.wikipedia.org/api/rest_v1/page/html/{q}"
    try:
        req = urllib.request.Request(url, headers=_UA)
        with urllib.request.urlopen(req, timeout=20) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception:
        return ""
    m = re.search(r">Headquarters</th>\s*<td[^>]*>(.*?)</td>", html, re.I | re.S)
    if not m:
        m = re.search(
            r"(?:Headquarters|Head office)[^<]{0,80}</th>\s*<td[^>]*>(.*?)</td>",
            html,
            re.I | re.S,
        )
    if not m:
        return ""
    text = re.sub(r"<[^>]+>", " ", m.group(1))
    text = re.sub(r"\[[^\]]*\]", "", text)
    text = re.sub(r"\d{4,}", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" ,;")
    return normalize_city_country(text)


def _wiki_enabled() -> bool:
    return (os.getenv("FOUND_IN_WIKI_RESOLVE") or "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def feature_enabled() -> bool:
    return (os.getenv("FOUND_IN_CITY_COUNTRY") or "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def resolve_hq_city_country(
    company: str,
    current: str = "",
    *,
    allow_wiki: bool = True,
) -> tuple[str, str]:
    """Return (City, Country or '', source). Never invents."""
    cur = normalize_city_country(current)
    if cur:
        return cur, "existing"
    known = lookup_known_hq(company)
    if known:
        return known, "known_map"
    cache = _load_cache()
    key = _norm_name(company)
    if key and key in cache:
        hit = normalize_city_country(cache[key])
        if hit:
            return hit, "cache"
    if not allow_wiki or not _wiki_enabled():
        return "", "unresolved"
    clean = re.sub(r"\([^)]*\)", "", str(company or "")).strip(" ,/")
    clean = re.sub(r"\s+", " ", clean)
    if len(clean) < 3:
        return "", "skip"
    title = _wiki_search(clean)
    if not title and len(clean.split()) >= 2:
        title = _wiki_search(" ".join(clean.split()[:3]))
    if not title:
        return "", "wiki_miss"
    hq = _wiki_hq(title)
    if hq:
        cache[key] = hq
        _save_cache()
        return hq, f"wikipedia:{title}"
    return "", f"wiki_no_hq:{title}"


def enrich_rows_city_country_hq(
    rows: list[dict[str, Any]],
    *,
    company_keys: tuple[str, ...] = ("Company", "Brand", "name"),
    hq_keys: tuple[str, ...] = ("Headquarters", "hq_location", "Found in", "Founded location"),
    allow_wiki: bool | None = None,
    sleep_s: float = 0.12,
    log: Any = None,
) -> dict[str, int]:
    """Fill/upgrade Headquarters on landscape rows to City, Country.

    Leaves blank when unverified. Returns counts.
    """
    if not feature_enabled():
        return {"filled": 0, "kept": 0, "blank": len(rows), "skipped": len(rows)}
    if allow_wiki is None:
        allow_wiki = _wiki_enabled()
    filled = kept = blank = 0
    for row in rows:
        company = ""
        for k in company_keys:
            company = str(row.get(k) or "").strip()
            if company:
                break
        current = ""
        for k in hq_keys:
            current = str(row.get(k) or "").strip()
            if current:
                break
        if current and not is_city_country(current):
            current = ""
        loc, src = resolve_hq_city_country(company, current, allow_wiki=allow_wiki)
        if loc:
            row["Headquarters"] = loc
            if src == "existing":
                kept += 1
            else:
                filled += 1
            if allow_wiki and str(src).startswith("wikipedia"):
                time.sleep(sleep_s)
        else:
            if row.get("Headquarters") and not is_city_country(str(row.get("Headquarters"))):
                row["Headquarters"] = ""
            blank += 1
            if log and company:
                log(f"    → [found-in] blank {company[:40]!r} ({src})")
    if allow_wiki:
        _save_cache()
    return {"filled": filled, "kept": kept, "blank": blank, "total": len(rows)}
