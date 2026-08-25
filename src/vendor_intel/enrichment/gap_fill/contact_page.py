"""Fetch Contact Us / leadership pages and extract email, phone, and named contacts."""
from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Any
from urllib.parse import urljoin

from vendor_intel.enrichment.gap_fill.gaps import domain_from_row, norm

_EMAIL = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_PHONE = re.compile(r"(?:\+?\d[\d\s().-]{7,}\d)")
_WHATSAPP = re.compile(r"(?:wa\.me/[\d+]+|whatsapp[:\s]+[\d+\s()-]{8,})", re.I)

_JUNK_EMAIL = re.compile(
    r"(noreply|no-reply|donotreply|privacy|sentry|wixpress|example\.com|\.png|\.jpg|\.gif|@2x)",
    re.I,
)

CONTACT_PATHS = (
    "/contact",
    "/contact-us",
    "/contactus",
    "/get-in-touch",
    "/en/contact",
    "/en/contact-us",
    "/contact.html",
    "/pages/contact",
)

LEADERSHIP_PATHS = (
    "/about",
    "/about-us",
    "/leadership",
    "/team",
    "/management",
    "/our-team",
    "/company/leadership",
    "/en/about",
    "/en/about-us",
)

CEO_TITLE = re.compile(
    r"\b(ceo|chief executive|founder|co-founder|managing director|president|owner)\b",
    re.I,
)


def _base_url(domain: str) -> str:
    dom = domain.strip().lower().removeprefix("www.")
    return f"https://{dom}/"


def _candidate_urls(domain: str, paths: tuple[str, ...]) -> list[str]:
    base = _base_url(domain)
    return [urljoin(base, p.lstrip("/")) for p in paths]


def _pick_email(text: str, *, existing: str = "") -> str:
    if existing and not _JUNK_EMAIL.search(existing):
        return existing
    for match in _EMAIL.finditer(text or ""):
        email = match.group(0).strip().lower()
        if not _JUNK_EMAIL.search(email):
            return email
    return ""


def _pick_phone(text: str, *, existing: str = "") -> str:
    if existing and len(re.sub(r"\D", "", existing)) >= 8:
        return existing.strip()
    for match in _PHONE.finditer(text or ""):
        phone = match.group(0).strip()
        if len(re.sub(r"\D", "", phone)) >= 8:
            return phone
    wm = _WHATSAPP.search(text or "")
    if wm:
        return wm.group(0).strip()
    return ""


async def _fetch_page_text(url: str) -> tuple[str, str]:
    """Return (text, final_url). Empty text on failure."""
    from vendor_intel.integrations.page_fetch import fetch_page_text

    return await fetch_page_text(url)


async def _find_contact_url(domain: str) -> tuple[str, str]:
    """Try common paths; return (text, url) from first page with email or phone."""
    best_text, best_url = "", ""
    for url in _candidate_urls(domain, CONTACT_PATHS):
        text, final_url = await _fetch_page_text(url)
        if not text:
            continue
        if _pick_email(text) or _pick_phone(text):
            return text, final_url
        if len(text) > len(best_text):
            best_text, best_url = text, final_url
    if best_text:
        return best_text, best_url

    home_text, home_url = await _fetch_page_text(_base_url(domain))
    if home_text and (_pick_email(home_text) or _pick_phone(home_text)):
        return home_text, home_url
    return home_text[:14000], home_url if home_text else ""


async def _find_leadership_text(domain: str) -> tuple[str, str]:
    best_text, best_url = "", ""
    for url in _candidate_urls(domain, LEADERSHIP_PATHS):
        text, final_url = await _fetch_page_text(url)
        if not text:
            continue
        if CEO_TITLE.search(text):
            return text, final_url
        if len(text) > len(best_text):
            best_text, best_url = text, final_url
    return best_text, best_url


async def _llm_contact_extract(
    company: str,
    domain: str,
    page_text: str,
    *,
    mode: str,
) -> dict[str, Any]:
    if not page_text.strip():
        return {}
    from backend.config import get_settings, sync_opencode_to_openai_env
    from openai import AsyncOpenAI

    sync_opencode_to_openai_env()
    cfg = get_settings()
    if not cfg.openai_api_key:
        return {}
    client = AsyncOpenAI(api_key=cfg.openai_api_key)
    model = (os.getenv("OPENAI_MODEL") or cfg.model_extract or "gpt-4o-mini").strip()

    if mode == "leadership":
        fields = (
            "contact_person (full name of CEO, Founder, Managing Director, or top executive if listed), "
            "contact_role (their exact title as written on the page). "
        )
        keys = "contact_person, contact_role, source_note"
    else:
        fields = (
            "email (business contact email), phone (main phone or WhatsApp), "
            "contact_address (postal/office address if shown), "
            "contact_person (named sales/contact rep if shown — not CEO unless on contact page). "
        )
        keys = "email, phone, contact_address, contact_person, contact_role, source_note"

    prompt = (
        f"Company: {company}\nDomain: {domain}\n\n"
        f"Extract ONLY facts explicitly stated in the page text below. {fields}\n"
        f"Return JSON with keys: {keys}. Use empty string for unknown. Do not invent or guess.\n\n"
        f"{page_text[:10000]}"
    )
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0,
        )
        text = (resp.choices[0].message.content or "").strip()
        data = json.loads(text) if text else {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _pick_leader_from_text(text: str) -> tuple[str, str]:
    """Heuristic: lines like 'Jane Doe, CEO' or 'CEO: Jane Doe'."""
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or len(line) > 120:
            continue
        if not CEO_TITLE.search(line):
            continue
        m = re.match(r"^([A-Z][a-z]+(?:\s+[A-Z][a-z'.-]+){1,3})\s*[,–—-]\s*(.+)$", line)
        if m:
            return m.group(1).strip(), m.group(2).strip()
        m = re.match(r"^(CEO|Chief Executive|Managing Director|Founder|President)\s*[:\-]\s*(.+)$", line, re.I)
        if m:
            return m.group(2).strip(), m.group(1).strip()
    return "", ""


async def extract_contact_from_website(row: dict[str, Any]) -> dict[str, Any]:
    """Contact Us page: email, phone, address."""
    domain = domain_from_row(row)
    if not domain:
        return {}
    company = norm(row.get("company") or row.get("brand"))
    text, source_url = await _find_contact_url(domain)
    if not text:
        return {}

    crawl = row.get("_crawl") if isinstance(row.get("_crawl"), dict) else {}
    email = _pick_email(text, existing=norm(crawl.get("email")))
    phone = _pick_phone(text, existing=norm(crawl.get("phone")))

    extracted = await _llm_contact_extract(company, domain, text, mode="contact")
    if not email:
        email = _pick_email(extracted.get("email") or "")
    if not phone:
        phone = _pick_phone(extracted.get("phone") or "")

    out: dict[str, Any] = {}
    if email:
        out["email"] = email
    if phone:
        out["phone"] = phone
    addr = norm(extracted.get("contact_address"))
    if addr:
        out["contact_address"] = addr
    person = norm(extracted.get("contact_person"))
    role = norm(extracted.get("contact_role"))
    if person:
        out["contact_person"] = person
    if role:
        out["contact_role"] = role
    if source_url:
        out["contact_source_url"] = source_url
    return out


async def extract_leadership_from_website(row: dict[str, Any]) -> dict[str, Any]:
    """About / leadership pages: CEO name and title."""
    domain = domain_from_row(row)
    if not domain:
        return {}
    company = norm(row.get("company") or row.get("brand"))
    text, source_url = await _find_leadership_text(domain)
    if not text:
        return {}

    extracted = await _llm_contact_extract(company, domain, text, mode="leadership")
    person = norm(extracted.get("contact_person"))
    role = norm(extracted.get("contact_role"))
    if not person:
        person, role = _pick_leader_from_text(text)

    out: dict[str, Any] = {}
    if person:
        out["contact_person"] = person
    if role:
        out["contact_role"] = role
    if source_url:
        out["leadership_source_url"] = source_url
    return out
