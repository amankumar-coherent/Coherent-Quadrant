"""Web-search expand: find channel companies via live search, merge into FINAL Excel.

Used by ``run_web_expand.py``. You only run the CLI; this module does the web search.
"""
from __future__ import annotations

import ast
import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from vendor_intel.export.landscape_slim import SLIM_COLUMNS

HEADERS = list(SLIM_COLUMNS)

WIDTHS = {
    "Brand": 28,
    "Company": 32,
    "Role": 18,
    "Quadrant": 18,
    "X": 10,
    "Y": 10,
    "Overall": 12,
    "Founded in": 16,
    "Website": 26,
    "Headquarters": 26,
    "Continent / Geography": 36,
    "Operational Presence": 28,
    "Key Brands Represented": 32,
    "Specialty Focus": 28,
    "Core Categories": 28,
    "Summary": 42,
    "Retail / E-commerce / Both": 18,
    "Distribution Type": 20,
    "X Score": 12,
    "Y Score": 12,
    "Overall Score": 14,
    "Industry Category": 28,
    "Contact Person": 18,
    "Email": 24,
    "LinkedIn": 26,
    "Office No.": 14,
    "Country Code": 10,
    "Region Code": 10,
}

GEO_POOL = [
    "India",
    "United States",
    "United Kingdom",
    "Germany",
    "France",
    "UAE",
    "Saudi Arabia",
    "Singapore",
    "Australia",
    "Brazil",
    "Mexico",
    "South Africa",
    "Japan",
    "South Korea",
    "Canada",
    "Netherlands",
    "Poland",
    "Indonesia",
    "Malaysia",
    "Thailand",
    "Vietnam",
    "Turkey",
    "Italy",
    "Spain",
    "Nordics",
    "Chile",
    "Colombia",
    "Nigeria",
    "Egypt",
    "Philippines",
]

OEM_BY_HINT: dict[str, set[str]] = {
    "firewall": {
        "palo alto networks",
        "fortinet",
        "check point",
        "cisco",
        "juniper networks",
        "zscaler",
        "sophos",
        "watchguard",
        "sonicwall",
        "barracuda",
        "forcepoint",
        "crowdstrike",
    },
    "smartwatch": {
        "apple",
        "samsung",
        "garmin",
        "fitbit",
        "huawei",
        "xiaomi",
        "amazfit",
        "google",
        "fossil",
    },
    "green": {
        "exxonmobil",
        "shell plc",
        "bp plc",
        "chevron",
        "saudi aramco",
        "sinopec",
        "basf se",
        "dow chemical",
    },
}

MARKET_DEFAULTS: dict[str, dict[str, str]] = {
    "avocado": {
        "Core Categories": "Avocado Oil; Edible Oils; Specialty Oils",
        "Specialty Focus": "Avocado oil distribution / wholesale / retail channel",
        "Key Brands Represented": "Private label; Regional avocado oil brands",
        "Distribution Type": "Broadline Distributor",
        "Retail / E-commerce / Both": "Both",
    },
    "firewall": {
        "Core Categories": "Network Firewalls; NGFW; SASE; Secure SD-WAN; Cybersecurity",
        "Specialty Focus": "Network security and firewall channel distribution",
        "Key Brands Represented": "Cisco; Fortinet; Palo Alto Networks; Check Point; Sophos",
        "Distribution Type": "Value-Added Distributor",
        "Retail / E-commerce / Both": "No",
    },
    "smartwatch": {
        "Core Categories": "Smartwatches; Wearables; Fitness Trackers; Connected Devices",
        "Specialty Focus": "Smartwatch and wearable device channel distribution / retail",
        "Key Brands Represented": "Apple Watch; Samsung Galaxy Watch; Garmin; Fitbit; Amazfit",
        "Distribution Type": "Broadline Distributor",
        "Retail / E-commerce / Both": "Both",
    },
    "green": {
        "Core Categories": "Bio-based Chemicals; Green Solvents; Specialty Ingredients; Sustainable Polymers",
        "Specialty Focus": "Green and specialty chemical distribution",
        "Key Brands Represented": "Bio-based solvents; Green surfactants; Specialty additives",
        "Distribution Type": "Specialty Distributor",
        "Retail / E-commerce / Both": "No",
    },
    "general": {
        "Core Categories": "Not publicly disclosed",
        "Specialty Focus": "Channel / distribution for this market",
        "Key Brands Represented": "Not publicly disclosed",
        "Distribution Type": "Distributor",
        "Retail / E-commerce / Both": "No",
    },
}


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def slugify(query: str, country: str = "global") -> str:
    raw = f"{query}_{country}".lower()
    raw = re.sub(r"[^a-z0-9]+", "_", raw).strip("_")
    return raw[:80] or "market"


def market_family(query: str, family: str | None = None) -> str:
    """Map a market query to a layout family. Prefer explicit family; never
    hardcode one demo market for 10k-scale runs (bare 'chemical'/'fmcg' are NOT matched).
    """
    if family and str(family).strip():
        return str(family).strip().lower()
    q = (query or "").lower()
    if "firewall" in q or "network security" in q or "ngfw" in q:
        return "firewall"
    if "smartwatch" in q or "wearable" in q:
        return "smartwatch"
    if "avocado oil" in q or "edible oil" in q:
        return "avocado"
    if "green chemical" in q or "bio-based chemical" in q or "sustainable chem" in q:
        return "green"
    if any(
        t in q
        for t in (
            "renewable",
            "solar",
            "photovoltaic",
            "wind energy",
            "wind turbine",
            "energy storage",
            "inverter",
        )
    ):
        return "renewable"
    return "general"


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def load_discovery_queries(query: str, country: str = "global") -> list[str]:
    from vendor_intel.pipeline.run_and_export import auto_discovery_queries

    curated = auto_discovery_queries(query, country)
    family = market_family(query)
    topic = re.sub(r"\bglobal\b|\bmarket\b", "", query, flags=re.I).strip() or query

    landscape = (os.getenv("EXPAND_LANDSCAPE_MODE") or "vendors").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
        "channel",
    )
    if landscape:
        from vendor_intel.quadrant.brand_meta import company_display_mode

        tech = company_display_mode(query) == "solution_provider" or family in {
            "firewall",
            "smartwatch",
        }
        if tech:
            role_terms = [
                "solution providers",
                "technology vendors",
                "key players",
                "companies",
            ]
        else:
            role_terms = [
                "brands",
                "marketers",
                "brand owners",
                "key players",
            ]
    else:
        role_terms = {
            "firewall": [
                "distributor",
                "value added distributor",
                "authorized distributor",
                "channel partner",
                "VAR",
                "MSSP",
                "reseller",
            ],
            "smartwatch": [
                "distributor",
                "wholesale",
                "authorized distributor",
                "retailer",
                "channel partner",
            ],
            "green": [
                "chemical distributor",
                "specialty chemical distributor",
                "ingredients distributor",
                "authorized distributor",
            ],
            "general": ["distributor", "wholesaler", "channel partner", "reseller"],
        }[family if family in {"firewall", "smartwatch", "green"} else "general"]

    generated: list[str] = []
    for role in role_terms:
        generated.append(f"{topic} {role}")
        for geo in GEO_POOL:
            generated.append(f"{topic} {role} {geo}")

    if landscape:
        if tech:
            site_qs = (
                f"{topic} solution providers site:linkedin.com/company",
                f"{topic} vendors site:linkedin.com/company",
                f"site:wikipedia.org {topic} companies",
            )
        else:
            site_qs = (
                f"{topic} brands site:linkedin.com/company",
                f"{topic} companies site:linkedin.com/company",
                f"site:wikipedia.org {topic} brands",
            )
    else:
        site_qs = (
            f"{topic} distributor site:linkedin.com/company",
            f"{topic} channel partner site:linkedin.com/company",
            f"site:kompass.com {topic} distributor",
            f"site:thomasnet.com {topic} distributor",
        )
    for site_q in site_qs:
        generated.append(site_q)

    return list(dict.fromkeys([*curated, *generated]))


def split_batch(queries: list[str], batch: str) -> list[str]:
    b = (batch or "all").lower()
    if b in {"all", "a+b", "ab"}:
        return queries
    mid = max(1, len(queries) // 2)
    if b == "a":
        return queries[:mid]
    if b == "b":
        return queries[mid:]
    return queries


async def web_harvest_candidates(
    query: str,
    *,
    country: str = "global",
    batch: str = "all",
    max_queries: int = 80,
    hits_per_query: int = 8,
) -> list[dict[str, str]]:
    """Live web search → candidate {name, domain, website, snippet, source_query}."""
    from vendor_intel.clients.search_router import FreeSearchRouter
    from vendor_intel.config import Settings
    from vendor_intel.discovery.candidate_quality import is_junk_candidate_name
    from vendor_intel.discovery.entity_extract import (
        clean_title_as_name,
        is_blocked_domain,
        is_junk_url,
    )
    from vendor_intel.utils.domains import domain_from_url

    settings = Settings()
    router = FreeSearchRouter(settings)
    family = market_family(query)
    oem = OEM_BY_HINT.get(family, set())
    topic = re.sub(r"\bglobal\b|\bmarket\b", "", query, flags=re.I).strip() or query

    queries = split_batch(load_discovery_queries(query, country), batch)[:max_queries]
    print(f"  [web_expand] market={query!r} family={family} batch={batch}", flush=True)
    print(f"  [web_expand] running {len(queries)} web search queries…", flush=True)

    found: dict[str, dict[str, str]] = {}
    for i, q in enumerate(queries, 1):
        try:
            results = await router.search(
                q,
                geo=country if country != "global" else "",
                discovery_mode=True,
                search_topic=topic,
            )
        except Exception as exc:
            print(f"  [web_expand] search fail ({i}/{len(queries)}): {exc}", flush=True)
            continue
        added = 0
        for r in results[:hits_per_query]:
            link = getattr(r, "link", None) or getattr(r, "url", "") or ""
            title = getattr(r, "title", "") or ""
            snippet = getattr(r, "snippet", "") or getattr(r, "body", "") or ""
            if not link or is_junk_url(link):
                continue
            dom = domain_from_url(link)
            if not dom or is_blocked_domain(dom):
                continue
            name = clean_title_as_name(title) or ""
            if not name or is_junk_candidate_name(name, dom):
                continue
            if _norm(name) in oem:
                continue
            key = dom.lower()
            if key in found:
                continue
            found[key] = {
                "name": name,
                "domain": dom,
                "website": f"https://{dom}" if not str(link).startswith("http") else str(link).split("?")[0],
                "snippet": str(snippet)[:280],
                "source_query": q,
                "discovery_source": "web_expand",
            }
            added += 1
        print(
            f"  [web_expand] {i}/{len(queries)} q={q[:60]!r} hits={len(results)} new={added} total={len(found)}",
            flush=True,
        )
        if i == 1 or i % 10 == 0 or i == len(queries):
            try:
                from vendor_intel.pipeline import openai_cost

                openai_cost.heartbeat(
                    "web_search",
                    web_query_i=i,
                    web_queries_total=len(queries),
                    web_candidates=len(found),
                )
            except Exception:
                pass

    print(f"  [web_expand] harvest done: {len(found)} unique domains", flush=True)
    return list(found.values())


def _blank_row(name: str, website: str, family: str, source: str) -> dict[str, str]:
    from vendor_intel.export.landscape_slim import (
        country_and_region_codes,
        format_continent_geography,
        operational_presence_text,
    )

    d = MARKET_DEFAULTS.get(family, MARKET_DEFAULTS["general"]).copy()
    row = {h: "" for h in HEADERS}
    row.update(d)
    row["Company"] = name
    row["Website"] = website or ""
    row["Founded"] = "Not publicly disclosed"
    row["Headquarters"] = "Not publicly disclosed"
    row["Ownership"] = "Not publicly disclosed"
    row["Employees"] = "Not publicly disclosed"
    # Contact / office stay empty unless later filled with evidence
    for c in ("Contact Person", "Role", "Email", "LinkedIn", "Office No."):
        row[c] = ""
    row["Continent / Geography"] = ""
    row["Operational Presence"] = ""
    row["Country Code"] = ""
    row["Region Code"] = ""
    row["Summary"] = f"{name} — channel participant ({source})."
    row["Data Sources"] = source  # not exported in slim; kept for internal merges
    return row


def read_final_rows(xlsx: Path) -> list[dict[str, str]]:
    if not xlsx.exists():
        return []
    wb = load_workbook(xlsx, read_only=True, data_only=True)
    # Prefer Landscape sheet so resume/fill still works when sheet 1 is Company Details
    if "Landscape" in wb.sheetnames:
        ws = wb["Landscape"]
    else:
        skip = {"company details", "web expand audit", "audit"}
        pick = next(
            (n for n in wb.sheetnames if n.strip().lower() not in skip),
            wb.sheetnames[0],
        )
        ws = wb[pick]
    rows_raw = list(ws.iter_rows(values_only=True))
    wb.close()
    hi = next((i for i, r in enumerate(rows_raw) if r and str(r[0]) == "Company"), None)
    if hi is None:
        return []
    headers = [str(h).strip() if h else f"c{j}" for j, h in enumerate(rows_raw[hi])]
    out: list[dict[str, str]] = []
    for r in rows_raw[hi + 1 :]:
        if not r or not str(r[0] or "").strip():
            continue
        d = {h: "" for h in HEADERS}
        for i, h in enumerate(headers):
            if h in d:
                v = r[i] if i < len(r) else None
                s = "" if v is None else str(v).strip()
                if s.startswith("[") and s.endswith("]"):
                    try:
                        parsed = ast.literal_eval(s)
                        if isinstance(parsed, (list, tuple)):
                            s = "; ".join(str(x) for x in parsed)
                    except Exception:
                        pass
                d[h] = s
        out.append(d)
    return out


def merge_candidates(
    existing: list[dict[str, str]],
    candidates: list[dict[str, str]],
    *,
    family: str,
    target: int,
) -> list[dict[str, str]]:
    by_name: dict[str, dict[str, str]] = {}
    by_domain: set[str] = set()

    def _dom(url: str) -> str:
        try:
            host = urlparse(url if "://" in url else f"https://{url}").netloc.lower()
            return host[4:] if host.startswith("www.") else host
        except Exception:
            return ""

    for row in existing:
        n = _norm(row.get("Company", ""))
        if not n:
            continue
        by_name[n] = row
        d = _dom(row.get("Website", ""))
        if d:
            by_domain.add(d)

    oem = OEM_BY_HINT.get(family, set())
    added = 0
    for c in candidates:
        name = (c.get("name") or "").strip()
        if not name or _norm(name) in oem:
            continue
        n = _norm(name)
        d = (c.get("domain") or _dom(c.get("website", ""))).lower()
        if n in by_name or (d and d in by_domain):
            continue
        row = _blank_row(
            name,
            c.get("website") or (f"https://{d}" if d else ""),
            family,
            "web_expand_harvest",
        )
        sq = c.get("source_query", "")
        for geo in GEO_POOL:
            if geo.lower() in sq.lower():
                # Do not put bare country into Headquarters (Found in must be City, Country).
                from vendor_intel.export.landscape_slim import (
                    country_and_region_codes,
                    format_continent_geography,
                    operational_presence_text,
                )

                row["Continent / Geography"] = format_continent_geography([geo])
                row["Operational Presence"] = operational_presence_text(geo)
                cc, rc = country_and_region_codes(geo)
                row["Country Code"] = cc
                row["Region Code"] = rc
                break
        by_name[n] = row
        if d:
            by_domain.add(d)
        added += 1
        if len(by_name) >= target:
            break

    print(f"  [web_expand] merged +{added}; total unique={len(by_name)} (target={target})", flush=True)
    return list(by_name.values())


def _style_header_row(ws, headers: list[str], header_fill, header_font, thin) -> None:
    ws.append(headers)
    for i, h in enumerate(headers, 1):
        cell = ws.cell(1, i)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
        cell.border = thin
        ws.column_dimensions[get_column_letter(i)].width = float(WIDTHS.get(h, 16))
    ws.row_dimensions[1].height = 32
    ws.freeze_panes = "A2"


def write_final_xlsx(
    path: Path,
    rows: list[dict[str, str]],
    sheet_name: str,
    audit: dict[str, Any],
    *,
    detail_rows: list[dict[str, Any]] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()

    header_fill = PatternFill("solid", fgColor="1F4E79")
    header_font = Font(bold=True, color="FFFFFF", name="Calibri", size=10)
    cell_font = Font(name="Calibri", size=9)
    thin = Border(
        left=Side(style="thin", color="D9D9D9"),
        right=Side(style="thin", color="D9D9D9"),
        top=Side(style="thin", color="D9D9D9"),
        bottom=Side(style="thin", color="D9D9D9"),
    )
    wrap = Alignment(wrap_text=True, vertical="top", horizontal="left")
    wrap_c = Alignment(wrap_text=True, vertical="center", horizontal="center")

    from vendor_intel.pipeline.expand_quadrant_score import DETAIL_COLUMNS, SCORE_COLUMNS

    if detail_rows:
        ws = wb.active
        ws.title = "Company Details"
        _style_header_row(ws, list(DETAIL_COLUMNS), header_fill, header_font, thin)
        detail_center = {"Role", "Quadrant", "X", "Y", "Overall", "Found in", "Founded in"}
        for row in detail_rows:
            ws.append([row.get(h, "") for h in DETAIL_COLUMNS])
            r = ws.max_row
            for i, h in enumerate(DETAIL_COLUMNS, 1):
                cell = ws.cell(r, i)
                cell.font = cell_font
                cell.border = thin
                cell.alignment = wrap_c if h in detail_center else wrap
            ws.row_dimensions[r].height = 28
        last = get_column_letter(len(DETAIL_COLUMNS))
        ws.auto_filter.ref = f"A1:{last}{ws.max_row}"
        ws = wb.create_sheet("Landscape")
    else:
        ws = wb.active
        ws.title = sheet_name[:31] or "Companies"

    headers = list(HEADERS)
    if any(any(str(r.get(h) or "").strip() for r in rows) for h in SCORE_COLUMNS):
        for h in SCORE_COLUMNS:
            if h not in headers:
                headers.append(h)

    _style_header_row(ws, headers, header_fill, header_font, thin)

    center_cols = {
        "Founded",
        "Retail / E-commerce / Both",
        "Country Code",
        "Region Code",
        "Office No.",
        "X Score",
        "Y Score",
        "Overall Score",
        "Quadrant",
    }

    for row in rows:
        values = [row.get(h, "") for h in headers]
        ws.append(values)
        r = ws.max_row
        for i, h in enumerate(headers, 1):
            cell = ws.cell(r, i)
            cell.font = cell_font
            cell.border = thin
            cell.alignment = wrap_c if h in center_cols else wrap
        ws.row_dimensions[r].height = 36

    last = get_column_letter(len(headers))
    ws.auto_filter.ref = f"A1:{last}{ws.max_row}"

    audit_ws = wb.create_sheet("Web Expand Audit")
    audit_ws.append(["Field", "Value"])
    for k, v in audit.items():
        audit_ws.append([k, json.dumps(v) if isinstance(v, (dict, list)) else v])
    for col in ("A", "B"):
        audit_ws.column_dimensions[col].width = 40
        for cell in audit_ws[col]:
            cell.alignment = wrap

    wb.save(path)


def default_output_dir(query: str, country: str = "global") -> Path:
    slug = slugify(query, country)
    folder = (os.getenv("EXPAND_OUTPUT_FOLDER") or "chatgpt_expand").strip() or "chatgpt_expand"
    return _project_root() / "output" / folder / slug


def resolve_final_path(
    query: str, country: str, out_dir: Path | None, final_path: str | None
) -> Path:
    """Per-market FINAL path under output/web_expand/<slug>/ (no demo-market hardcoding).

    Set EXPAND_USE_LEGACY_FINAL=true to optionally reuse legacy run4 paths for a
    few known demos when those files already exist.
    """
    if final_path:
        return Path(final_path)
    base = out_dir or default_output_dir(query, country)
    generic = base / f"{slugify(query, country)}_FINAL.xlsx"
    if os.getenv("EXPAND_USE_LEGACY_FINAL", "").strip().lower() in ("1", "true", "yes", "on"):
        family = market_family(query)
        known = {
            "firewall": _project_root()
            / "output"
            / "run4"
            / "global_firewall_market_global"
            / "global_firewall_market_FINAL.xlsx",
            "smartwatch": _project_root()
            / "output"
            / "run4"
            / "global_smartwatch_market_global"
            / "global_smartwatch_market_FINAL.xlsx",
            "green": _project_root()
            / "output"
            / "run4"
            / "global_green_chemical_market_global"
            / "global_green_chemical_market_FINAL.xlsx",
        }
        if family in known and known[family].exists():
            return known[family]
    return generic


async def run_web_expand(
    query: str,
    *,
    country: str = "global",
    target: int = 320,
    batch: str = "all",
    max_queries: int = 80,
    merge_existing: bool = True,
    final_path: str | None = None,
    out_dir: str | None = None,
) -> dict[str, Any]:
    family = market_family(query)
    out = Path(out_dir) if out_dir else default_output_dir(query, country)
    out.mkdir(parents=True, exist_ok=True)
    xlsx = resolve_final_path(query, country, out, final_path)

    existing = read_final_rows(xlsx) if merge_existing and xlsx.exists() else []
    print(f"  [web_expand] existing rows in {xlsx.name}: {len(existing)}", flush=True)

    candidates = await web_harvest_candidates(
        query,
        country=country,
        batch=batch,
        max_queries=max_queries,
    )
    harvest_path = out / f"harvest_batch_{batch.lower()}.json"
    harvest_path.write_text(json.dumps(candidates, indent=2, ensure_ascii=False), encoding="utf-8")

    merged = merge_candidates(existing, candidates, family=family, target=target)
    merged.sort(key=lambda r: _norm(r.get("Company", "")))

    sheet = {
        "firewall": "Firewall Companies",
        "smartwatch": "Smartwatch Companies",
        "green": "Green Chemical Companies",
    }.get(family, "Companies")

    audit = {
        "query": query,
        "country": country,
        "batch": batch,
        "family": family,
        "target": target,
        "existing_before": len(existing),
        "harvested": len(candidates),
        "total_after": len(merged),
        "xlsx": str(xlsx),
        "harvest_json": str(harvest_path),
        "mode": "web_search_own",
    }
    write_final_xlsx(xlsx, merged, sheet, audit)
    (out / f"web_expand_batch_{batch.lower()}_audit.json").write_text(
        json.dumps(audit, indent=2), encoding="utf-8"
    )
    print(f"  [web_expand] wrote {len(merged)} rows → {xlsx}", flush=True)
    return audit
