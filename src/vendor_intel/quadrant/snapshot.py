"""Build evidence_snapshot on landscape classify rows for quadrant KB reuse."""
from __future__ import annotations

from typing import Any

_PAGE_TEXT_MAX = 12000
_SNIPPET_MAX = 12
_INTEL_KEYS = (
    "company",
    "business",
    "financials",
    "relationships",
    "intel",
    "location",
    "media",
)


def _clip(text: str, n: int) -> str:
    t = " ".join(str(text or "").split())
    return t[:n]


def extract_page_text(smart_data: dict[str, Any] | None) -> str:
    """Pull plain page text from SSC / smart_crawl payloads."""
    if not isinstance(smart_data, dict) or smart_data.get("error"):
        return ""
    # SSC / crawl pages list
    pages = smart_data.get("pages")
    if isinstance(pages, list):
        parts: list[str] = []
        for p in pages:
            if isinstance(p, dict) and p.get("text"):
                parts.append(str(p["text"]))
            if sum(len(x) for x in parts) >= _PAGE_TEXT_MAX:
                break
        if parts:
            return _clip("\n".join(parts), _PAGE_TEXT_MAX)
    data = smart_data.get("data") if isinstance(smart_data.get("data"), dict) else {}
    intel = data.get("intel") if isinstance(data.get("intel"), dict) else {}
    for key in ("summary", "key_insights", "recent_developments"):
        val = intel.get(key)
        if isinstance(val, str) and len(val.strip()) >= 40:
            return _clip(val, _PAGE_TEXT_MAX)
        if isinstance(val, list) and val:
            return _clip(" ".join(str(x) for x in val), _PAGE_TEXT_MAX)
    return ""


def extract_discovery_snippets(company_row: dict[str, Any] | None) -> list[dict[str, str]]:
    """Normalize discovery snippet lists from a candidate company dict."""
    if not isinstance(company_row, dict):
        return []
    raw = (
        company_row.get("discovery_snippets")
        or company_row.get("snippets")
        or company_row.get("hits")
        or []
    )
    out: list[dict[str, str]] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str) and item.strip():
                out.append({"title": "", "url": "", "snippet": _clip(item, 400)})
            elif isinstance(item, dict):
                sn = str(
                    item.get("snippet")
                    or item.get("text")
                    or item.get("description")
                    or ""
                ).strip()
                title = str(item.get("title") or "").strip()
                url = str(item.get("url") or item.get("link") or item.get("source_url") or "").strip()
                if not sn and not title:
                    continue
                out.append(
                    {
                        "title": _clip(title, 200),
                        "url": url,
                        "snippet": _clip(sn, 400),
                    }
                )
            if len(out) >= _SNIPPET_MAX:
                break
    # Single-fields
    if not out:
        one = str(company_row.get("snippet") or company_row.get("description") or "").strip()
        if one:
            out.append({"title": "", "url": "", "snippet": _clip(one, 400)})
    return out[:_SNIPPET_MAX]


def build_evidence_snapshot(
    smart_data: dict[str, Any] | None,
    company_row: dict[str, Any] | None = None,
    classify_verdict: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Pack enrich + discovery + classify into an inline evidence_snapshot for quadrant.

    Stored on each company row during landscape classify; quadrant never re-searches.
    """
    smart_data = smart_data if isinstance(smart_data, dict) else {}
    company_row = company_row if isinstance(company_row, dict) else {}
    classify_verdict = classify_verdict if isinstance(classify_verdict, dict) else {}

    domain = str(
        company_row.get("domain")
        or smart_data.get("domain")
        or classify_verdict.get("domain")
        or ""
    ).strip()

    data_in = smart_data.get("data") if isinstance(smart_data.get("data"), dict) else {}
    data_out: dict[str, Any] = {}
    for k in _INTEL_KEYS:
        if data_in.get(k) is not None:
            data_out[k] = data_in[k]

    page_text = extract_page_text(smart_data)
    # Ensure SSC intel summary is available as structured data too
    if page_text and "intel" not in data_out:
        data_out["intel"] = {"summary": page_text[:5000]}
    elif page_text and isinstance(data_out.get("intel"), dict):
        intel = dict(data_out["intel"])
        if not intel.get("summary"):
            intel["summary"] = page_text[:5000]
            data_out["intel"] = intel

    snippets = extract_discovery_snippets(company_row)

    classify_block = {
        "summary": str(
            classify_verdict.get("summary")
            or classify_verdict.get("company_summary")
            or ""
        ).strip(),
        "role_description": str(classify_verdict.get("role_description") or "").strip(),
        "key_products": str(classify_verdict.get("key_products") or "").strip(),
        "role": str(classify_verdict.get("role") or "").strip(),
    }
    # Drop empties
    classify_block = {k: v for k, v in classify_block.items() if v}

    snap: dict[str, Any] = {
        "source": str(smart_data.get("source") or company_row.get("discovery_source") or ""),
        "domain": domain,
        "data": data_out,
        "page_text": page_text,
        "discovery_snippets": snippets,
        "classify": classify_block,
    }
    return snap
