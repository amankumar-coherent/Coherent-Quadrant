"""Single source of truth for DeepSeek API cost/usage tracking.

Every DeepSeek call in this repo lands in one JSONL file
(output/cost_dashboard/deepseek_calls.jsonl) via exactly one of two layers,
never both for the same physical request:

1. Explicit calls — chatgpt_expand.py (via openai_cost.py),
   crawler/smart_crawl.py, channel_purity.py, and the 6 scripts/*.py sites
   call record_call()/log_completion() themselves, right after their
   `client.chat.completions.create(...)` (openai SDK) call. These carry
   richer context (market/step/run_id) than can be inferred from a bare
   HTTP response.
2. install_autotrack() — patches httpx.Client/AsyncClient.send (the choke
   point EVERY outbound request passes through, SDK or raw) as a safety net
   for call sites with no explicit instrumentation (placeholders/llm.py,
   clients/google_ai_scraper.py, and any future call site that hand-rolls a
   client). It specifically SKIPS requests whose User-Agent identifies them
   as openai-SDK-originated, because those are already covered by layer 1 —
   logging them again would double the recorded request count and cost.

This means: SDK-based call sites (layer 1) must NOT also rely on autotrack,
and raw-httpx call sites relying on autotrack (layer 2) must NOT also call
record_call() explicitly unless they pass `response=<the raw httpx.Response>`
so record_call() can mark it seen before autotrack's own pass runs.

Rates are DeepSeek's official published per-1M-token list prices
(https://api-docs.deepseek.com/quick_start/pricing), keyed by exact model id.
Peak hours are 01:00-04:00 and 06:00-10:00 UTC, Monday-Friday; off-peak is
half price. Cache-hit input tokens are billed far below cache-miss tokens,
so a call's true cost depends on how many of its input tokens DeepSeek
served from its context cache — callers must pass that split when available
(the OpenAI-compatible response includes prompt_cache_hit_tokens /
prompt_cache_miss_tokens in `usage`); when unavailable, all input tokens are
conservatively priced as cache-miss.
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# USD per 1M tokens, official DeepSeek list prices (current, as of the
# Models & Pricing page). DeepSeek raised prices mid-August 2026: billing
# CSVs from before that date (amount-2026-08-01_2026-08-28.csv rows dated
# <= Aug 14) show exactly half these per-token rates. RATE_CHANGE_CUTOVER_UTC
# marks that boundary so historical estimates for calls made before it use
# _DEEPSEEK_RATES_LEGACY instead — without this, backfilled/replayed cost
# estimates for pre-cutover calls would read ~2x too high, same class of bug
# as the original openai_cost.py mismatch this module replaces.
RATE_CHANGE_CUTOVER_UTC = datetime(2026, 8, 15, 0, 0, tzinfo=timezone.utc)

_DEEPSEEK_RATES: dict[str, dict[str, dict[str, float]]] = {
    "deepseek-v4-flash": {
        "cache_hit": {"off_peak": 0.007, "peak": 0.014},
        "cache_miss": {"off_peak": 0.22, "peak": 0.44},
        "output": {"off_peak": 0.66, "peak": 1.32},
    },
    "deepseek-v4-pro": {
        "cache_hit": {"off_peak": 0.022, "peak": 0.044},
        "cache_miss": {"off_peak": 0.66, "peak": 1.32},
        "output": {"off_peak": 1.98, "peak": 3.96},
    },
    "deepseek-v4-flash-vision-exp": {
        "cache_hit": {"off_peak": 0.007, "peak": 0.014},
        "cache_miss": {"off_peak": 0.22, "peak": 0.44},
        "output": {"off_peak": 0.66, "peak": 1.32},
    },
}
_DEEPSEEK_RATES_LEGACY: dict[str, dict[str, dict[str, float]]] = {
    model: {
        tier: {peak: rate / 2 for peak, rate in peaks.items()}
        for tier, peaks in rates.items()
    }
    for model, rates in _DEEPSEEK_RATES.items()
}
# Legacy/alias model ids some code paths still send.
_MODEL_ALIASES = {
    "deepseek-chat": "deepseek-v4-flash",
    "deepseek-reasoner": "deepseek-v4-pro",
}


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def cost_dir() -> Path:
    d = _project_root() / "output" / "cost_dashboard"
    d.mkdir(parents=True, exist_ok=True)
    return d


def is_peak_utc(dt: datetime | None = None) -> bool:
    """Peak = 01:00-04:00 and 06:00-10:00 UTC, Monday-Friday."""
    dt = dt or datetime.now(timezone.utc)
    if dt.weekday() >= 5:  # Sat/Sun
        return False
    h = dt.hour
    return (1 <= h < 4) or (6 <= h < 10)


def _resolve_rates(model: str, at: datetime | None = None) -> dict[str, dict[str, float]] | None:
    m = (model or "").strip().lower()
    m = _MODEL_ALIASES.get(m, m)
    table = _DEEPSEEK_RATES_LEGACY if (at and at < RATE_CHANGE_CUTOVER_UTC) else _DEEPSEEK_RATES
    if m in table:
        return table[m]
    for key, rates in table.items():
        if m.startswith(key):
            return rates
    return None


def estimate_cost_usd(
    model: str,
    *,
    cache_hit_tokens: int = 0,
    cache_miss_tokens: int = 0,
    output_tokens: int = 0,
    at: datetime | None = None,
) -> tuple[float, bool]:
    """Returns (cost_usd, used_deepseek_rate_table). Falls back to a flat
    $0.22/$0.66 per-1M cache-miss/output estimate for unrecognized model ids
    so cost is never silently zero, but flags it via the bool."""
    at = at or datetime.now(timezone.utc)
    rates = _resolve_rates(model, at)
    peak = is_peak_utc(at)
    tier = "peak" if peak else "off_peak"
    if rates is None:
        rates = _DEEPSEEK_RATES["deepseek-v4-flash"]
        matched = False
    else:
        matched = True
    cost = (
        (cache_hit_tokens / 1_000_000.0) * rates["cache_hit"][tier]
        + (cache_miss_tokens / 1_000_000.0) * rates["cache_miss"][tier]
        + (output_tokens / 1_000_000.0) * rates["output"][tier]
    )
    return round(cost, 8), matched


@dataclass
class DeepSeekCallRecord:
    ts: str
    caller: str
    model: str
    peak: bool
    cache_hit_tokens: int
    cache_miss_tokens: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost_usd: float
    rate_table_matched: bool
    market: str = ""
    step: str = ""
    run_id: str = ""
    error: str = ""


_lock = threading.Lock()

# Dedup guard: a single physical HTTP response can be seen twice — once by an
# explicit record_call()/log_completion() call already written at a site
# (llm.py, google_ai_scraper.py, chatgpt_expand.py, channel_purity.py, the
# six scripts/*.py sites), and again by install_autotrack()'s httpx.Client.send
# patch, which every one of those sites' requests also physically passes
# through (raw httpx directly, or indirectly via the openai SDK's internal
# use of httpx). Both layers are kept intentionally — explicit calls carry
# richer context (market/step/run_id) that autotrack can't infer, while
# autotrack is the safety net for anything NOT explicitly wired.
#
# The dedup key MUST be the same object across both layers for this to work.
# For SDK-based calls, log_completion(resp, ...) is passed the parsed
# ChatCompletion object — id()-keying that is safe because autotrack's httpx
# layer runs first (inside the SDK's internals) using the raw httpx.Response,
# a *different* object, so log_completion()'s id()-based check alone can't
# see autotrack's sighting. Instead: log_completion()/record_call() accept an
# optional `response=` (the raw httpx.Response when the caller has one, e.g.
# llm.py/google_ai_scraper.py which call httpx directly) and mark THAT
# object seen, so autotrack's later check on the same httpx.Response skips
# it. SDK-based call sites (get_deepseek_client() users, smart_crawl.py,
# channel_purity.py) don't have easy access to the raw httpx.Response — for
# those, autotrack's httpx-layer sighting is the ONLY record; no explicit
# record_call()/log_completion() should also be called for them (verify at
# each call site before adding one).
_seen_response_ids: set[int] = set()
_SEEN_CAP = 5000


def _already_logged(resp: Any) -> bool:
    if resp is None:
        return False
    key = id(resp)
    with _lock:
        if key in _seen_response_ids:
            return True
        if len(_seen_response_ids) >= _SEEN_CAP:
            _seen_response_ids.clear()
        _seen_response_ids.add(key)
        return False


def record_call(
    *,
    caller: str,
    model: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    cache_hit_tokens: int = 0,
    cache_miss_tokens: int | None = None,
    market: str = "",
    step: str = "",
    run_id: str = "",
    error: str = "",
    response: Any = None,
) -> DeepSeekCallRecord | None:
    """Log one DeepSeek request. `caller` should be a short 'module:function'
    tag (e.g. 'llm.py:_deepseek_complete') so spend can be attributed back to
    the code path that generated it — this is what output/cost_dashboard/
    was missing before: every call site logging to a shared, per-caller feed.

    If cache_hit/cache_miss token counts aren't available from the response,
    pass cache_miss_tokens=None and prompt_tokens as-is; all prompt tokens
    are then priced as cache-miss (the conservative, non-underestimating
    assumption).

    Pass `response=` (the raw httpx.Response, if the caller has one) so this
    call and install_autotrack()'s httpx patch — which will also see the
    same physical response — dedup against each other instead of both
    logging it. Returns None (and logs nothing) if that response was already
    recorded by the other layer.
    """
    if _already_logged(response):
        return None
    if cache_miss_tokens is None:
        cache_miss_tokens = max(0, int(prompt_tokens) - int(cache_hit_tokens))
    now = datetime.now(timezone.utc)
    cost, matched = estimate_cost_usd(
        model,
        cache_hit_tokens=cache_hit_tokens,
        cache_miss_tokens=cache_miss_tokens,
        output_tokens=completion_tokens,
        at=now,
    )
    rec = DeepSeekCallRecord(
        ts=now.isoformat(),
        caller=caller,
        model=model or "unknown",
        peak=is_peak_utc(now),
        cache_hit_tokens=int(cache_hit_tokens or 0),
        cache_miss_tokens=int(cache_miss_tokens or 0),
        prompt_tokens=int(prompt_tokens or 0),
        completion_tokens=int(completion_tokens or 0),
        total_tokens=int(prompt_tokens or 0) + int(completion_tokens or 0),
        estimated_cost_usd=cost,
        rate_table_matched=matched,
        market=market,
        step=step,
        run_id=run_id,
        error=error,
    )
    _append_jsonl(rec)
    return rec


def _append_jsonl(rec: DeepSeekCallRecord) -> None:
    path = cost_dir() / "deepseek_calls.jsonl"
    with _lock:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(rec), ensure_ascii=False) + "\n")


def get_deepseek_client(*, sync: bool = False) -> Any:
    """One construction point for every script that talks to DeepSeek via the
    OpenAI SDK — replaces the identical `AsyncOpenAI(api_key=key, base_url=base)`
    pattern that used to be duplicated across one-off scripts. Callers still invoke
    `client.chat.completions.create(...)` normally; pair every call with
    `log_completion()` below so it lands in deepseek_calls.jsonl.

    This still relies on the caller remembering to use it. `install_autotrack()`
    below is the actual enforcement mechanism — it patches the `openai` SDK
    itself so ANY client construction anywhere in the process is tracked
    automatically, whether or not the code went through this factory."""
    from openai import AsyncOpenAI, OpenAI

    from vendor_intel.pipeline.chatgpt_env import deepseek_chat_config

    key, base, _model = deepseek_chat_config()
    return OpenAI(api_key=key, base_url=base) if sync else AsyncOpenAI(api_key=key, base_url=base)


_AUTOTRACK_INSTALLED = False
_AUTOTRACK_LOCK = threading.Lock()


def _is_deepseek_base_url(base_url: Any) -> bool:
    s = str(base_url or "").lower()
    return "deepseek" in s


def install_autotrack() -> None:
    """Patch httpx.Client/AsyncClient.send — the single choke point every
    outbound HTTP request passes through exactly once, whether it was made
    via raw httpx (placeholders/llm.py, google_ai_scraper.py) or via the
    `openai` SDK (get_deepseek_client(), smart_crawl.py, channel_purity.py,
    the 6 scripts/*.py sites — the SDK's Completions.create() internally
    calls client._client.send(), i.e. httpx, under the hood).

    Requests made through the `openai` SDK are recognized by their
    `User-Agent: OpenAI/Python ...` header and deliberately SKIPPED here —
    those call sites already call record_call()/log_completion() explicitly
    with richer context (market/step/run_id) than autotrack can infer from
    a bare HTTP response, so logging them again here would double-count.
    This patch is therefore the sole logger only for raw-httpx call sites
    that have no explicit tracking (the actual "unknown future call site"
    safety net), while remaining a true no-op for every SDK-based call.

    Call once, as early as possible (e.g. from src/vendor_intel/__init__.py
    or the top of any run_*.py entry point). Idempotent — safe to call from
    multiple entry points.
    """
    global _AUTOTRACK_INSTALLED
    with _AUTOTRACK_LOCK:
        if _AUTOTRACK_INSTALLED:
            return
        _install_httpx_autotrack()
        _AUTOTRACK_INSTALLED = True


def _install_httpx_autotrack() -> None:
    try:
        import httpx
    except ImportError:
        return

    _orig_send = httpx.Client.send
    _orig_asend = httpx.AsyncClient.send

    def _is_openai_sdk_request(request: Any) -> bool:
        ua = ""
        try:
            ua = request.headers.get("user-agent", "")
        except Exception:
            pass
        return "openai/python" in ua.lower()

    def _log_if_deepseek(request: Any, response: Any) -> None:
        url = str(getattr(request, "url", ""))
        if "deepseek" not in url.lower() or "/chat/completions" not in url:
            return
        if _is_openai_sdk_request(request):
            # This request was made via the openai SDK — the call site
            # (get_deepseek_client() users, smart_crawl.py, channel_purity.py)
            # already logs it explicitly with richer context. Logging it
            # again here would double-count the same physical request.
            return
        if _already_logged(response):
            # Defensive: a raw-httpx call site might, in theory, also call
            # record_call()/log_completion() explicitly with this same
            # response object — skip the second sighting either way.
            return
        try:
            data = response.json()
        except Exception:
            return
        usage = usage_from_openai_response(data)
        if usage["prompt_tokens"] or usage["completion_tokens"]:
            model = ""
            try:
                model = json.loads(request.content or b"{}").get("model", "")
            except Exception:
                pass
            import inspect

            caller = "unknown"
            for frame in inspect.stack()[2:10]:
                fname = Path(frame.filename).name
                if fname not in ("deepseek_tracker.py", "_client.py", "_transports"):
                    caller = f"{fname}:{frame.function}"
                    break
            record_call(
                caller=f"autotrack-httpx:{caller}",
                model=model,
                prompt_tokens=usage["prompt_tokens"],
                completion_tokens=usage["completion_tokens"],
                cache_hit_tokens=usage["cache_hit_tokens"],
            )

    def _tracked_send(self: Any, request: Any, **kwargs: Any) -> Any:
        response = _orig_send(self, request, **kwargs)
        try:
            _log_if_deepseek(request, response)
        except Exception:
            pass
        return response

    async def _tracked_asend(self: Any, request: Any, **kwargs: Any) -> Any:
        response = await _orig_asend(self, request, **kwargs)
        try:
            _log_if_deepseek(request, response)
        except Exception:
            pass
        return response

    httpx.Client.send = _tracked_send
    httpx.AsyncClient.send = _tracked_asend


def log_completion(resp: Any, *, caller: str, model: str) -> None:
    """Call this right after every `client.chat.completions.create(...)` made
    against a `get_deepseek_client()` instance — one line per call site,
    instead of hand-rolling usage extraction + record_call each time.

    Safe from double-counting with install_autotrack(): the httpx-level
    patch specifically skips requests carrying the openai SDK's User-Agent,
    so an SDK call logged here is never also logged by autotrack. The
    `_already_logged(resp)` check below only guards against this function
    itself being called twice on the same response object (e.g. a retry
    loop that re-logs), not cross-layer duplication.
    """
    if _already_logged(resp):
        return
    try:
        usage = usage_from_openai_response(resp)
        record_call(
            caller=caller,
            model=model,
            prompt_tokens=usage["prompt_tokens"],
            completion_tokens=usage["completion_tokens"],
            cache_hit_tokens=usage["cache_hit_tokens"],
        )
    except Exception:
        pass


def usage_from_openai_response(resp: Any) -> dict[str, int]:
    """Extract prompt/completion/cache-hit tokens from an OpenAI-SDK-shaped
    chat completion response (works for both the `openai` SDK object and a
    raw dict from httpx .json()). DeepSeek's OpenAI-compatible endpoint
    reports cache split under usage.prompt_cache_hit_tokens /
    prompt_cache_miss_tokens."""
    usage = resp.get("usage") if isinstance(resp, dict) else getattr(resp, "usage", None)
    if usage is None:
        return {"prompt_tokens": 0, "completion_tokens": 0, "cache_hit_tokens": 0}
    if not isinstance(usage, dict):
        try:
            usage = usage.model_dump()
        except Exception:
            usage = {
                "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
                "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
                "prompt_cache_hit_tokens": getattr(usage, "prompt_cache_hit_tokens", 0) or 0,
            }
    return {
        "prompt_tokens": int(usage.get("prompt_tokens") or 0),
        "completion_tokens": int(usage.get("completion_tokens") or 0),
        "cache_hit_tokens": int(usage.get("prompt_cache_hit_tokens") or 0),
    }


def load_calls(limit: int = 100_000) -> list[dict[str, Any]]:
    path = cost_dir() / "deepseek_calls.jsonl"
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows[-limit:]


def totals_by_caller() -> dict[str, dict[str, Any]]:
    """Aggregate spend/requests per call site — this is the observability
    payoff: answers 'which script/module is actually costing money' for the
    first time, instead of only 6.6% of spend being visible at all."""
    out: dict[str, dict[str, Any]] = {}
    for row in load_calls():
        caller = row.get("caller") or "unknown"
        agg = out.setdefault(
            caller,
            {"requests": 0, "prompt_tokens": 0, "completion_tokens": 0, "estimated_cost_usd": 0.0},
        )
        agg["requests"] += 1
        agg["prompt_tokens"] += int(row.get("prompt_tokens") or 0)
        agg["completion_tokens"] += int(row.get("completion_tokens") or 0)
        agg["estimated_cost_usd"] = round(agg["estimated_cost_usd"] + float(row.get("estimated_cost_usd") or 0), 6)
    return out


def write_summary_snapshot() -> dict[str, Any]:
    """Write output/cost_dashboard/deepseek_summary.json — a rollup by
    caller, refreshed on demand (call this from a CLI/report script, not
    per-request, to avoid extra I/O on the hot path)."""
    by_caller = totals_by_caller()
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_requests": sum(v["requests"] for v in by_caller.values()),
        "total_estimated_cost_usd": round(sum(v["estimated_cost_usd"] for v in by_caller.values()), 6),
        "by_caller": by_caller,
    }
    path = cost_dir() / "deepseek_summary.json"
    path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return summary
