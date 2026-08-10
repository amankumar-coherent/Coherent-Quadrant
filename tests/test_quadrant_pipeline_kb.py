"""Pipeline evidence_snapshot → quadrant KB (no outreach search)."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from vendor_intel.quadrant.company_kb import build_company_kb
from vendor_intel.quadrant.snapshot import (
    build_evidence_snapshot,
    extract_discovery_snippets,
    extract_page_text,
)


def test_extract_page_text_from_ssc_pages():
    smart = {
        "source": "ssc",
        "domain": "acme.com",
        "data": {"company": {"name": "Acme", "website": "acme.com"}},
        "pages": [{"url": "https://acme.com/", "text": "Acme makes dental chairs and sterilizers for clinics worldwide. " * 5}],
    }
    text = extract_page_text(smart)
    assert "dental chairs" in text
    assert len(text) > 40


def test_extract_discovery_snippets():
    row = {
        "discovery_snippets": [
            {"title": "Acme Dental", "url": "https://news.example/a", "snippet": "Leading dental OEM"},
            {"title": "", "url": "", "snippet": ""},
        ]
    }
    sn = extract_discovery_snippets(row)
    assert len(sn) == 1
    assert sn[0]["snippet"] == "Leading dental OEM"


def test_build_evidence_snapshot_packs_ssc_and_snippets():
    smart = {
        "source": "ddgs_extract",
        "domain": "acme.com",
        "data": {
            "company": {"name": "Acme", "website": "acme.com"},
            "intel": {"summary": "Homepage summary about medical devices."},
        },
        "pages": [
            {
                "url": "https://acme.com/",
                "text": "Acme manufactures dental imaging systems and sells across Africa and Europe.",
            }
        ],
    }
    company = {
        "name": "Acme",
        "domain": "acme.com",
        "discovery_snippets": [
            {"title": "Acme wins tender", "url": "https://x.test", "snippet": "African dental tender 2024"}
        ],
    }
    verdict = {
        "summary": "Manufacturer of dental imaging systems.",
        "role_description": "Manufacturer of dental imaging for clinics",
        "key_products": "CBCT, sensors",
        "role": "Manufacturer",
        "domain": "acme.com",
    }
    snap = build_evidence_snapshot(smart, company_row=company, classify_verdict=verdict)
    assert snap["domain"] == "acme.com"
    assert snap["source"] == "ddgs_extract"
    assert "dental imaging" in snap["page_text"]
    assert snap["discovery_snippets"][0]["snippet"].startswith("African")
    assert snap["classify"]["summary"].startswith("Manufacturer")
    assert "company" in snap["data"]
    assert "media" not in snap["data"] or snap["data"].get("media") is not None


def test_build_company_kb_from_snapshot_has_chunks():
    row = {
        "company": "Acme",
        "domain": "acme.com",
        "summary": "Dental equipment maker",
        "evidence_snapshot": {
            "source": "ssc",
            "domain": "acme.com",
            "data": {
                "company": {"name": "Acme"},
                "business": {"products": [{"name": "Chair"}]},
                "financials": {"revenue": "$100 M"},
            },
            "page_text": "Acme is a global supplier of dental chairs and autoclaves with ISO certification.",
            "discovery_snippets": [
                {"title": "Acme", "url": "https://hit.test", "snippet": "Acme expands in Africa"}
            ],
            "classify": {"summary": "Manufacturer of dental chairs"},
        },
    }
    kb = asyncio.run(build_company_kb(row, market="dental", do_search=True))
    assert kb["source"] == "pipeline_evidence_snapshot"
    assert len(kb["chunks"]) >= 3
    origins = {c["origin"] for c in kb["chunks"]}
    assert "page_text" in origins or "crawl" in origins
    assert "discovery" in origins or "classify" in origins
    blob = " ".join(c["text"] for c in kb["chunks"])
    assert "100" in blob or "Chair" in blob


def test_build_company_kb_never_calls_search_router():
    row = {
        "company": "NoSearchCo",
        "domain": "nosearch.test",
        "evidence_snapshot": {
            "domain": "nosearch.test",
            "data": {"intel": {"summary": "Enough text about product portfolio and certifications here."}},
            "page_text": "",
            "discovery_snippets": [],
            "classify": {},
        },
    }

    async def _run():
        with patch(
            "vendor_intel.clients.search_router.FreeSearchRouter",
            autospec=True,
        ) as mock_cls:
            mock_cls.return_value.search = AsyncMock(return_value=[])
            kb = await build_company_kb(row, market="dental equipment", do_search=True)
            mock_cls.assert_not_called()
            assert kb["chunks"]
            return kb

    asyncio.run(_run())
