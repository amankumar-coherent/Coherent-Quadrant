"""OpenAI usage + estimated cost tracker for ChatGPT expand runs."""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# USD per 1M tokens (override via env)
_DEFAULT_RATES: dict[str, dict[str, float]] = {
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o-mini-2024-07-18": {"input": 0.15, "output": 0.60},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-2024-08-06": {"input": 2.50, "output": 10.00},
    "gpt-4.1-mini": {"input": 0.40, "output": 1.60},
    "gpt-4.1": {"input": 2.00, "output": 8.00},
    "o4-mini": {"input": 1.10, "output": 4.40},
    # DeepSeek official API, off-peak cache-miss list prices (see
    # deepseek_tracker.py for the full cache-hit/peak-aware rate table that
    # actually backs output/cost_dashboard/deepseek_calls.jsonl; these flat
    # rates remain only as the fallback used by legacy CallRecord.estimated_cost_usd).
    "deepseek-chat": {"input": 0.28, "output": 0.42},
    "deepseek-reasoner": {"input": 0.55, "output": 2.19},
    "deepseek-v4-flash": {"input": 0.22, "output": 0.66},
    "deepseek-v4-pro": {"input": 0.66, "output": 1.98},
    "deepseek-v4-flash-vision-exp": {"input": 0.22, "output": 0.66},
}


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def cost_dir() -> Path:
    d = _project_root() / "output" / "cost_dashboard"
    d.mkdir(parents=True, exist_ok=True)
    return d


def rates_for_model(model: str) -> dict[str, float]:
    m = (model or "").strip()
    if m in _DEFAULT_RATES:
        return _DEFAULT_RATES[m]
    # prefix match
    for key, rates in _DEFAULT_RATES.items():
        if m.startswith(key):
            return rates
    # env override fallback
    inp = float(os.getenv("OPENAI_USD_PER_1M_INPUT", "0.15"))
    out = float(os.getenv("OPENAI_USD_PER_1M_OUTPUT", "0.60"))
    return {"input": inp, "output": out}


def estimate_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    rates = rates_for_model(model)
    return (prompt_tokens / 1_000_000.0) * rates["input"] + (
        completion_tokens / 1_000_000.0
    ) * rates["output"]


@dataclass
class CallRecord:
    ts: str
    run_id: str
    label: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost_usd: float
    market: str = ""
    step: str = ""


@dataclass
class RunCostSession:
    run_id: str
    market: str
    model: str
    started_at: str
    calls: list[CallRecord] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    ended_at: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def add_usage(
        self,
        *,
        label: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        step: str = "",
    ) -> CallRecord:
        cost = estimate_cost_usd(model, prompt_tokens, completion_tokens)
        rec = CallRecord(
            ts=datetime.now(timezone.utc).isoformat(),
            run_id=self.run_id,
            label=label,
            model=model,
            prompt_tokens=int(prompt_tokens or 0),
            completion_tokens=int(completion_tokens or 0),
            total_tokens=int(prompt_tokens or 0) + int(completion_tokens or 0),
            estimated_cost_usd=round(cost, 6),
            market=self.market,
            step=step,
        )
        self.calls.append(rec)
        self.prompt_tokens += rec.prompt_tokens
        self.completion_tokens += rec.completion_tokens
        self.total_tokens += rec.total_tokens
        self.estimated_cost_usd = round(self.estimated_cost_usd + cost, 6)
        return rec

    def summary(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "market": self.market,
            "model": self.model,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "calls": len(self.calls),
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "estimated_cost_usd": self.estimated_cost_usd,
            "meta": self.meta,
        }


_lock = threading.Lock()
_CURRENT: RunCostSession | None = None


def start_run(market: str, model: str, **meta: Any) -> RunCostSession:
    global _CURRENT
    session = RunCostSession(
        run_id=str(uuid.uuid4())[:8],
        market=market,
        model=model,
        started_at=datetime.now(timezone.utc).isoformat(),
        meta=dict(meta),
    )
    with _lock:
        _CURRENT = session
    # Write immediately so the dashboard is not empty at run start
    _write_live_snapshot(session, status="RUNNING", phase="started")
    return session


def get_session() -> RunCostSession | None:
    return _CURRENT


def heartbeat(phase: str, **extra: Any) -> None:
    """Update live.json during long non-OpenAI steps (e.g. web search)."""
    session = _CURRENT
    if session is None:
        return
    session.meta.update(extra)
    _write_live_snapshot(session, status="RUNNING", phase=phase)


def _usage_tokens(usage: Any) -> tuple[int, int]:
    if usage is None:
        return 0, 0
    if isinstance(usage, dict):
        pt = usage.get("prompt_tokens") or usage.get("input_tokens") or 0
        ct = usage.get("completion_tokens") or usage.get("output_tokens") or 0
        return int(pt), int(ct)
    pt = getattr(usage, "prompt_tokens", None)
    ct = getattr(usage, "completion_tokens", None)
    if pt is None:
        pt = getattr(usage, "input_tokens", None)
    if ct is None:
        ct = getattr(usage, "output_tokens", None)
    if pt is None and hasattr(usage, "model_dump"):
        try:
            d = usage.model_dump()
            pt = d.get("prompt_tokens") or d.get("input_tokens") or 0
            ct = d.get("completion_tokens") or d.get("output_tokens") or 0
            return int(pt), int(ct)
        except Exception:
            pass
    return int(pt or 0), int(ct or 0)


def record_response_usage(
    resp: Any,
    *,
    label: str,
    model: str,
    step: str = "",
) -> CallRecord | None:
    """Pull usage from an OpenAI chat completion response."""
    session = _CURRENT
    if session is None:
        # Still try to start a dangling session so UI is not blank
        session = start_run(market="(unknown)", model=model or "unknown")
    usage = getattr(resp, "usage", None)
    pt, ct = _usage_tokens(usage)
    if pt == 0 and ct == 0:
        # Some responses omit usage — keep a breadcrumb so UI updates
        content = ""
        try:
            content = resp.choices[0].message.content or ""
        except Exception:
            content = getattr(resp, "output_text", None) or ""
        # rough fallback estimate (~4 chars/token)
        ct = max(1, len(content) // 4)
        pt = max(1, ct // 2)
    rec = session.add_usage(
        label=label,
        model=model or session.model,
        prompt_tokens=pt,
        completion_tokens=ct,
        step=step,
    )
    _append_jsonl(rec)
    _write_live_snapshot(session, status="RUNNING", phase=step or label)
    try:
        from vendor_intel.pipeline.deepseek_tracker import (
            record_call,
            usage_from_openai_response,
        )

        cache_hit = usage_from_openai_response(resp)["cache_hit_tokens"]
        record_call(
            caller=f"chatgpt_expand.py:{label}",
            model=rec.model,
            prompt_tokens=rec.prompt_tokens,
            completion_tokens=rec.completion_tokens,
            cache_hit_tokens=cache_hit,
            market=session.market,
            step=step,
            run_id=session.run_id,
        )
    except Exception:
        pass
    return rec


def finish_run(**meta: Any) -> dict[str, Any]:
    global _CURRENT
    session = _CURRENT
    if session is None:
        return {}
    session.ended_at = datetime.now(timezone.utc).isoformat()
    session.meta.update(meta)
    summary = session.summary()
    # persist run summary
    runs_path = cost_dir() / "runs.jsonl"
    with _lock:
        with runs_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(summary, ensure_ascii=False) + "\n")
        detail = cost_dir() / f"run_{session.run_id}.json"
        detail.write_text(
            json.dumps(
                {
                    **summary,
                    "calls": [asdict(c) for c in session.calls],
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        _write_live_snapshot(session)
        _CURRENT = None
    return summary


def _append_jsonl(rec: CallRecord) -> None:
    path = cost_dir() / "calls.jsonl"
    with _lock:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(rec), ensure_ascii=False) + "\n")


def _write_live_snapshot(
    session: RunCostSession,
    *,
    status: str | None = None,
    phase: str | None = None,
) -> None:
    live = cost_dir() / "live.json"
    payload = {
        **session.summary(),
        "status": status
        or ("finished" if session.ended_at else "RUNNING"),
        "phase": phase or session.meta.get("phase") or "",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "last_call": asdict(session.calls[-1]) if session.calls else None,
        "cost_dir": str(cost_dir()),
    }
    if phase:
        session.meta["phase"] = phase
    tmp = live.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(live)


def load_runs(limit: int = 200) -> list[dict[str, Any]]:
    path = cost_dir() / "runs.jsonl"
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


def load_calls(limit: int = 2000) -> list[dict[str, Any]]:
    path = cost_dir() / "calls.jsonl"
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


def totals() -> dict[str, Any]:
    runs = load_runs(10_000)
    calls = load_calls(100_000)
    return {
        "runs": len(runs),
        "calls": len(calls),
        "prompt_tokens": sum(int(r.get("prompt_tokens") or 0) for r in runs),
        "completion_tokens": sum(int(r.get("completion_tokens") or 0) for r in runs),
        "total_tokens": sum(int(r.get("total_tokens") or 0) for r in runs),
        "estimated_cost_usd": round(
            sum(float(r.get("estimated_cost_usd") or 0) for r in runs), 6
        ),
        "cost_dir": str(cost_dir()),
    }


def print_session_summary(summary: dict[str, Any]) -> None:
    if not summary:
        return
    print("", flush=True)
    print("=== OpenAI cost (this run) ===", flush=True)
    print(f"  run_id : {summary.get('run_id')}", flush=True)
    print(f"  market : {summary.get('market')}", flush=True)
    print(f"  model  : {summary.get('model')}", flush=True)
    print(f"  calls  : {summary.get('calls')}", flush=True)
    print(
        f"  tokens : in={summary.get('prompt_tokens')} "
        f"out={summary.get('completion_tokens')} "
        f"total={summary.get('total_tokens')}",
        flush=True,
    )
    print(f"  est $  : ${float(summary.get('estimated_cost_usd') or 0):.4f}", flush=True)
    print(f"  log    : {cost_dir()}", flush=True)
