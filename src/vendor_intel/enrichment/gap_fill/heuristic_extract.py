"""Regex/heuristic field extraction from search/scrape text — no LLM / OpenAI SDK."""
from __future__ import annotations

import re
from typing import Any


_FOUNDED_RE = re.compile(
    r"(?:founded|established|incorporated|started)\s+(?:in\s+)?((?:19|20)\d{2})\b",
    re.I,
)
_HQ_RE = re.compile(
    r"(?:headquartered\s+in|headquarters\s+(?:in|at|:)|based\s+in|hq\s*(?:in|:))\s*"
    r"([A-Z][A-Za-z.'\-]+(?:\s+[A-Z][A-Za-z.'\-]+){0,2}"
    r"(?:,\s*[A-Z][A-Za-z.'\-]+(?:\s+[A-Z][A-Za-z.'\-]+){0,2}){0,2})",
)
_EMP_RE = re.compile(
    r"(?:(?:about|approximately|approx\.?|over|more than|~)\s*)?"
    r"([\d,]{2,7})\+?\s*(?:employees|staff|people|workers)\b",
    re.I,
)
_EMP_RANGE_RE = re.compile(
    r"(?:employees?|staff)\s*(?:of|:)?\s*([\d,]{1,6}\s*[-–—]\s*[\d,]{1,6})",
    re.I,
)
_REV_RE = re.compile(
    r"(?:revenue|turnover|sales)\s*(?:of|about|approximately|approx\.?|:)?\s*"
    r"(\$?\s*[\d]+(?:[.,]\d+)?\s*(?:[-–—]\s*\$?\s*[\d]+(?:[.,]\d+)?\s*)?"
    r"(?:billion|million|bn|mn|m|b)\b)",
    re.I,
)
_LINKEDIN_RE = re.compile(
    r"(https?://(?:www\.)?linkedin\.com/(?:company|in)/[A-Za-z0-9\-_%]+)",
    re.I,
)
_SALES_TITLE = (
    r"(?:Head of Sales|VP Sales|Vice President of Sales|Sales Director|"
    r"Director of Sales|Commercial Director|Chief Commercial Officer|"
    r"Chief Revenue Officer|Chief Sales Officer|Head of Procurement|"
    r"Procurement Director|Purchasing Director|Head of Purchasing|"
    r"National Sales|Channel Sales)"
)
_SALES_COMMA_RE = re.compile(
    rf"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){{1,3}})\s*,\s*{_SALES_TITLE}",
    re.I,
)
_SALES_REV_RE = re.compile(
    rf"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){{1,3}})\s*"
    rf"(?:is\s+)?(?:the\s+)?{_SALES_TITLE}",
    re.I,
)
_SALES_TITLE_RE = re.compile(_SALES_TITLE, re.I)


def heuristic_extract_fields(text: str, *, company: str = "") -> dict[str, Any]:
    """Pull firmographic fields from raw markdown/snippets without an LLM."""
    if not (text or "").strip():
        return {}
    blob = text[:12000]
    out: dict[str, Any] = {}

    m = _FOUNDED_RE.search(blob)
    if m:
        out["founded_year"] = m.group(1)

    m = _HQ_RE.search(blob)
    if m:
        hq = re.sub(r"\s+", " ", m.group(1)).strip(" .,;:")
        # Drop trailing junk words that sometimes leak past the city/country
        stop = {"it", "has", "with", "and", "the", "a", "an", "is", "was", "of"}
        parts = [p for p in re.split(r",\s*|\s+", hq) if p]
        cleaned: list[str] = []
        for p in parts:
            tok = p.strip(" .,;:")
            if not tok or tok.lower() in stop:
                break
            cleaned.append(tok)
        hq = ", ".join(cleaned) if cleaned else hq.strip(" .,;:")
        if len(hq) >= 3:
            out["headquarters"] = hq

    m = _EMP_RANGE_RE.search(blob)
    if m:
        out["employee_count"] = re.sub(r"\s+", "", m.group(1).replace("—", "-").replace("–", "-"))
    else:
        m = _EMP_RE.search(blob)
        if m:
            out["employee_count"] = m.group(1).replace(",", "")

    m = _REV_RE.search(blob)
    if m:
        out["revenue"] = re.sub(r"\s+", " ", m.group(1)).strip()

    m = _LINKEDIN_RE.search(blob)
    if m:
        out["linkedin_url"] = m.group(1).rstrip("/")

    m = _SALES_COMMA_RE.search(blob) or _SALES_REV_RE.search(blob)
    if m:
        person = m.group(1).strip().rstrip(".")
        if company and person.lower() == company.lower():
            pass
        elif len(person.split()) >= 2:
            out["contact_person"] = person
            role_m = _SALES_TITLE_RE.search(blob[max(0, m.start() - 10) : m.end() + 80])
            if role_m:
                out["contact_role"] = role_m.group(0)

    return out
