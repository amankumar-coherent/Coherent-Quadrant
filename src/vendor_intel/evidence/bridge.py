"""Local HTTP bridge between the Chrome extension and the answer cache.

A Chrome extension cannot write to disk, and the pipeline cannot drive a
browser. This bridge is the seam: it owns the :class:`AiOverviewStore` on one
side and speaks HTTP to the extension on the other.

    Chrome extension  <--HTTP-->  bridge :15552  <--files-->  data/ai_overview_cache/
                                                                _pending.jsonl
                                                                answers/<key>.json

Run it::

    python run_ai_bridge.py                     # all markets
    python run_ai_bridge.py --market "Smartphone Market"

Endpoints
---------
``GET  /health``                  liveness + counts, used by the popup badge
``GET  /markets``                 every market with a cache dir
``GET  /pending?limit=25&market=`` questions still needing an answer
``POST /answers``                 one answer, or ``{"answers": [...]}`` in bulk
``GET  /stats?market=``           cache hit/miss counters

The extension is the only client, so CORS is wide open for
``chrome-extension://`` origins. Bind to loopback and this stays local.
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from vendor_intel.evidence.ai_overview import (
    AiOverviewStore,
    Question,
    default_cache_dir,
    market_slug,
)

DEFAULT_PORT = 15552

# One store per market, kept alive across requests. Read endpoints call
# reload_queue() first: the pipeline enqueues from a different process, so a
# cached in-memory queue would go stale the moment a run starts.
_stores: dict[str, AiOverviewStore] = {}

# Last heartbeat from the collector: {at, running, tabs, answered, missing, failed, last}
_hb: dict[str, Any] = {}


def get_store(market: str = "") -> AiOverviewStore:
    key = market_slug(market) if market else "_root"
    if key not in _stores:
        _stores[key] = AiOverviewStore(default_cache_dir(market))
    return _stores[key]


def known_markets() -> list[str]:
    base = default_cache_dir()
    if not base.is_dir():
        return []
    return sorted(p.name for p in base.iterdir() if p.is_dir() and not p.name.startswith("_"))


class Citation(BaseModel):
    title: str = ""
    url: str = ""


class AnswerIn(BaseModel):
    """One scraped answer. ``key`` alone is enough if the question is queued."""

    question: str = ""
    key: str = ""
    markdown: str = ""
    citations: list[Citation] = Field(default_factory=list)
    ai_overview_missing: bool = False
    error: str = ""
    market: str = ""
    source: str = "chrome"


class AnswerBatch(BaseModel):
    answers: list[AnswerIn] = Field(default_factory=list)


def create_app(market: str = "") -> FastAPI:
    """Build the bridge app. ``market`` pins a default for un-scoped requests."""
    app = FastAPI(title="Coherent Quadrant — AI Overview bridge", version="1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"chrome-extension://.*",
        allow_methods=["*"],
        allow_headers=["*"],
    )
    default_market = market

    def _store_for(requested: str) -> AiOverviewStore:
        return get_store(requested or default_market)

    @app.get("/health")
    def health() -> dict[str, Any]:
        store = _store_for("")
        store.reload_queue()
        return {
            "ok": True,
            "service": "coherent-quadrant-ai-overview-bridge",
            "default_market": default_market,
            "markets": known_markets(),
            "pending": len(store.pending()),
        }

    @app.get("/markets")
    def markets() -> dict[str, Any]:
        out = []
        for slug in known_markets():
            s = get_store(slug)
            s.reload_queue()
            out.append({"market": slug, "pending": len(s.pending()), **s.stats()})
        return {"markets": out}

    @app.get("/pending")
    def pending(limit: int = 25, market: str = "") -> dict[str, Any]:
        """Hand the extension its next batch of work, oldest first."""
        store = _store_for(market)
        store.reload_queue()  # the pipeline enqueues from another process
        store.clear_answered()
        rows = [q.to_dict() for q in store.pending(limit=max(0, limit))]
        return {"market": market or default_market, "count": len(rows), "questions": rows}

    @app.post("/answers")
    def answers(payload: AnswerIn | AnswerBatch) -> dict[str, Any]:
        """Accept one answer or a batch; both write through the same path."""
        rows = payload.answers if isinstance(payload, AnswerBatch) else [payload]
        saved, skipped = 0, 0
        for row in rows:
            store = _store_for(row.market)
            text = (row.question or "").strip()
            if not text and row.key:
                # The extension may echo only the key it was handed.
                match = next((q for q in store.pending() if q.key == row.key), None)
                text = match.text if match else ""
            if not text:
                skipped += 1
                continue
            store.put(
                text,
                row.markdown,
                citations=[c.model_dump() for c in row.citations],
                overview_missing=row.ai_overview_missing,
                error=row.error,
                source=row.source or "chrome",
            )
            saved += 1
        if not saved and skipped:
            raise HTTPException(400, "no answer carried a resolvable question or key")
        return {"saved": saved, "skipped": skipped}

    @app.post("/enqueue")
    def enqueue(q: Question | dict) -> dict[str, Any]:
        """Manual question injection — useful for testing without a pipeline run."""
        row = q if isinstance(q, dict) else q.to_dict()
        market = str(row.get("market") or default_market)
        store = _store_for(market)
        question = Question(
            text=str(row.get("text") or ""),
            layer=str(row.get("layer") or ""),
            purpose=str(row.get("purpose") or "manual"),
            subject=str(row.get("subject") or ""),
            market=market,
        )
        if not question.text.strip():
            raise HTTPException(400, "text is required")
        store.enqueue(question)
        return {"queued": question.to_dict()}

    @app.post("/heartbeat")
    def heartbeat(payload: dict) -> dict[str, Any]:
        """The collector reports it is alive and what it is doing.

        Added because "is the extension actually running?" was repeatedly
        unanswerable from the server side — a silent collector and a finished one
        look identical when you can only see the queue.
        """
        _hb.update(payload or {})
        _hb["at"] = time.time()
        return {"ok": True}

    @app.get("/heartbeat")
    def heartbeat_status() -> dict[str, Any]:
        age = time.time() - float(_hb.get("at") or 0)
        return {
            "alive": bool(_hb.get("at")) and age < 60,
            "seconds_since_last": round(age, 1) if _hb.get("at") else None,
            **{k: v for k, v in _hb.items() if k != "at"},
        }

    @app.get("/stats")
    def stats(market: str = "") -> dict[str, Any]:
        store = _store_for(market)
        store.reload_queue()
        return store.stats()

    return app


def main() -> None:
    import uvicorn

    p = argparse.ArgumentParser(description="AI Overview bridge for the Chrome extension")
    p.add_argument("--market", default="", help="Default market when a request omits one")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--host", default="127.0.0.1", help="Loopback by default — keep it local")
    args = p.parse_args()

    cache = default_cache_dir(args.market)
    print(f"AI Overview bridge  http://{args.host}:{args.port}")
    print(f"  cache: {cache}")
    print(f"  pending: {len(get_store(args.market).pending())}")
    print("  load extension/ in chrome://extensions (Developer mode -> Load unpacked)")
    uvicorn.run(create_app(args.market), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
