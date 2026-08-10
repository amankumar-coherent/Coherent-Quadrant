"""Pipeline and data services for the Streamlit UI."""
from __future__ import annotations

import io
import json
import re
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ui.bootstrap import ROOT, init_env, output_dir, phase1_debug_dir


def slug(query: str, country: str) -> str:
    text = f"{query}_{country}".lower()
    return "".join(c if c.isalnum() else "_" for c in text).strip("_")[:80]


def parse_query_line(raw: str) -> tuple[str, str]:
    if "|" in raw:
        parts = raw.split("|", 1)
        return parts[0].strip(), (parts[1].strip() or "global")
    return raw.strip(), "global"


def load_queries_file(path: Path) -> list[tuple[str, str]]:
    if not path.exists():
        return []
    rows: list[tuple[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        rows.append(parse_query_line(line))
    return rows


def list_result_csvs() -> list[Path]:
    out = output_dir()
    files = sorted(out.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [p for p in files if p.name != "session_log.json"]


def load_session_log() -> list[dict]:
    log_path = output_dir() / "session_log.json"
    if not log_path.exists():
        return []
    try:
        return json.loads(log_path.read_text(encoding="utf-8"))
    except Exception:
        return []


def append_session_log(entry: dict) -> None:
    log = load_session_log()
    log.append(entry)
    out = output_dir()
    out.mkdir(parents=True, exist_ok=True)
    (out / "session_log.json").write_text(
        json.dumps(log, indent=2, default=str), encoding="utf-8"
    )


def _safe_stdout_write(stream: Any, data: str) -> None:
    """Windows consoles often use cp1252 — avoid crashing on ≤, →, etc."""
    try:
        stream.write(data)
    except UnicodeEncodeError:
        enc = getattr(stream, "encoding", None) or "utf-8"
        stream.write(data.encode(enc, errors="replace").decode(enc, errors="replace"))


@contextmanager
def capture_stdout(callback: Callable[[str], None]):
    buffer = io.StringIO()
    old_stdout = sys.stdout

    class Tee:
        def write(self, data: str) -> int:
            _safe_stdout_write(old_stdout, data)
            buffer.write(data)
            callback(data)
            return len(data)

        def flush(self) -> None:
            old_stdout.flush()

    sys.stdout = Tee()
    try:
        yield buffer
    finally:
        sys.stdout = old_stdout


def run_full_pipeline(
    query: str,
    country: str,
    profile: str,
    *,
    cap: str | None = None,
    brief: str = "",
    scope: dict[str, Any] | None = None,
    log_callback: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    from run_query import run_one_query, _parse_input

    from ui.bootstrap import load_settings, pipeline_caps

    init_env()
    settings = load_settings(profile)
    if cap:
        from vendor_intel.pipeline.cap_profiles import apply_cap

        settings = apply_cap(settings, cap)

    exclude: list[str] = []
    definition = ""
    if scope:
        # Pre-interpreted (and possibly user-edited) scope from the confirmation step.
        market = str(scope.get("market") or "")
        use_country = str(scope.get("geography") or country or "global")
        sections = list(scope.get("sections") or [])
        exclude = list(scope.get("exclude") or [])
        definition = str(scope.get("definition") or "")
    elif brief and brief.strip():
        # Detailed-brief mode: let the AI interpret what to include / exclude.
        from vendor_intel.funnel.brief_interpreter import interpret_brief

        spec = interpret_brief(brief, settings)
        market = spec["market"]
        use_country = (
            country.strip() if country and country.strip().lower() != "global" else spec["geography"]
        )
        sections = spec["sections"]
        exclude = spec["exclude"]
        definition = spec["definition"]
    else:
        # Let users type "Market | Country | Section A; Section B" in the query box.
        market, q_country, sections = _parse_input(query)
        use_country = (
            country.strip()
            if country and country.strip() and country.strip().lower() != "global"
            else q_country
        )
    classify_cap, enrich_cap = pipeline_caps(settings, country=use_country)

    def _noop(_: str) -> None:
        pass

    cb = log_callback or _noop
    with capture_stdout(cb):
        result = run_one_query(
            market,
            use_country,
            settings,
            enrich_limit=enrich_cap,
            classify_limit=classify_cap,
            sections=sections,
            exclude_segments=exclude,
            market_definition=definition,
        )
    return result


def run_phase1_preview(
    query: str,
    country: str,
    *,
    with_search: bool = False,
    log_callback: Callable[[str], None] | None = None,
) -> tuple[dict, str]:
    from test_phase1 import _full_query, build_report

    from vendor_intel.phase1.runner import run_phase1_sync, print_phase1_summary

    from ui.bootstrap import load_settings

    init_env()
    settings = load_settings("quality")
    full_query = _full_query(query, country)

    if not with_search:
        import vendor_intel.pipeline.geo_limits as geo_limits

        original = geo_limits.pipeline_limits

        def plan_only_limits(s, *, recall, country):
            lim = original(s, recall=recall, country=country)
            return {**lim, "smoke_prompts": 0}

        geo_limits.pipeline_limits = plan_only_limits

    def _noop(_: str) -> None:
        pass

    cb = log_callback or _noop
    with capture_stdout(cb):
        manifest = run_phase1_sync(full_query, settings)
        try:
            print_phase1_summary(manifest)
        except UnicodeEncodeError:
            pass

    report_md = build_report(query, country, manifest)
    debug = phase1_debug_dir()
    s = slug(query, country)
    (debug / f"{s}.md").write_text(report_md, encoding="utf-8")
    (debug / f"{s}.json").write_text(
        json.dumps(manifest, indent=2, default=str), encoding="utf-8"
    )
    return manifest, report_md


def shutdown_search_pool() -> None:
    try:
        from vendor_intel.clients.ddg_worker_pool import shutdown_ddg_pool

        shutdown_ddg_pool(wait=True)
    except Exception:
        pass


# One pipeline at a time — avoids duplicate DDG worker pools and search timeouts.
_pipeline_lock = threading.Lock()


def pipeline_is_busy() -> bool:
    return _pipeline_lock.locked()


class JobRunner:
    """Background thread runner with session-state friendly status dict."""

    def __init__(self, state_key: str = "active_job"):
        self.state_key = state_key

    def request_stop(self, session_state) -> None:
        """Ask the active job to stop (cooperative cancel + tear down search pool)."""
        from vendor_intel.pipeline.cancel import request_cancel

        job = session_state.get(self.state_key) or {}
        if not job.get("running"):
            return
        job["cancel_requested"] = True
        job["cancel_requested_at"] = time.time()
        request_cancel()
        # Unblock searches waiting in the DDG pool
        try:
            from vendor_intel.clients.ddg_worker_pool import shutdown_ddg_pool

            shutdown_ddg_pool(wait=False)
        except Exception:
            pass

    def force_finish_cancelled(self, session_state) -> None:
        """UI failsafe when the worker does not exit quickly after Stop."""
        from vendor_intel.pipeline.cancel import request_cancel

        job = session_state.get(self.state_key) or {}
        if not job.get("running"):
            return
        request_cancel()
        job["cancel_requested"] = True
        job["cancelled"] = True
        job["running"] = False
        job["error"] = None
        try:
            from vendor_intel.clients.ddg_worker_pool import shutdown_ddg_pool

            shutdown_ddg_pool(wait=False)
        except Exception:
            pass
        # Free the pipeline lock if the abandoned worker still holds it
        if _pipeline_lock.locked():
            try:
                _pipeline_lock.release()
            except RuntimeError:
                pass

    def start(
        self,
        session_state,
        *,
        job_type: str,
        query: str,
        country: str,
        profile: str = "quality",
        cap: str | None = None,
        with_search: bool = False,
        brief: str = "",
        scope: dict[str, Any] | None = None,
    ) -> bool:
        if session_state.get(self.state_key, {}).get("running") or pipeline_is_busy():
            return False

        from vendor_intel.pipeline.cancel import PipelineCancelled, clear_cancel, is_cancelled

        clear_cancel()

        # Mutable dict shared with worker — never read st.session_state from the thread.
        job: dict[str, Any] = {
            "running": True,
            "job_type": job_type,
            "query": query,
            "country": country,
            "profile": profile,
            "cap": cap,
            "log": "",
            "result": None,
            "error": None,
            "cancelled": False,
            "cancel_requested": False,
            "started_at": time.time(),
        }
        session_state[self.state_key] = job

        def worker() -> None:
            if not _pipeline_lock.acquire(blocking=False):
                job["running"] = False
                job["error"] = "Another pipeline is already running on this machine."
                return

            def on_log(chunk: str) -> None:
                job["log"] = (job.get("log") or "") + chunk
                if len(job["log"]) > 120_000:
                    job["log"] = job["log"][-100_000:]
                if is_cancelled() or job.get("cancel_requested"):
                    raise PipelineCancelled("Stopped by user.")

            market_label = query or (str((scope or {}).get("market") or "").strip())
            try:
                if job_type == "pipeline":
                    result = run_full_pipeline(
                        query, country, profile, cap=cap, brief=brief, scope=scope, log_callback=on_log
                    )
                    if is_cancelled() or job.get("cancel_requested"):
                        raise PipelineCancelled("Stopped by user.")
                    job["result"] = result
                    llm = result.get("llm_usage") or {}
                    elapsed = time.time() - job["started_at"]
                    append_session_log(
                        {
                            "query": market_label,
                            "country": country,
                            "status": "ok",
                            "companies_exported": len(result.get("relevant_companies") or []),
                            "elapsed_seconds": round(elapsed, 1),
                            "elapsed_minutes": round(elapsed / 60, 2),
                            "llm_calls": llm.get("llm_calls_total"),
                            "estimated_cost_usd": llm.get("estimated_cost_usd"),
                            "csv_file": result.get("_csv_path", ""),
                            "xlsx_file": result.get("_xlsx_path", ""),
                            "docx_file": result.get("_docx_path", ""),
                            "ran_at": datetime.now(timezone.utc).isoformat(),
                        }
                    )
                else:
                    manifest, report_md = run_phase1_preview(
                        query,
                        country,
                        with_search=with_search,
                        log_callback=on_log,
                    )
                    job["result"] = {"manifest": manifest, "report_md": report_md}
            except PipelineCancelled:
                job["cancelled"] = True
                job["error"] = None
                append_session_log(
                    {
                        "query": market_label,
                        "country": country,
                        "status": "cancelled",
                        "elapsed_seconds": round(time.time() - job["started_at"], 1),
                        "ran_at": datetime.now(timezone.utc).isoformat(),
                    }
                )
            except Exception as exc:
                if is_cancelled() or job.get("cancel_requested"):
                    job["cancelled"] = True
                    job["error"] = None
                    append_session_log(
                        {
                            "query": market_label,
                            "country": country,
                            "status": "cancelled",
                            "elapsed_seconds": round(time.time() - job["started_at"], 1),
                            "ran_at": datetime.now(timezone.utc).isoformat(),
                        }
                    )
                else:
                    job["error"] = str(exc)
                    if job_type == "pipeline":
                        append_session_log(
                            {
                                "query": market_label,
                                "country": country,
                                "status": "error",
                                "error": str(exc),
                                "elapsed_seconds": round(time.time() - job["started_at"], 1),
                                "ran_at": datetime.now(timezone.utc).isoformat(),
                            }
                        )
            finally:
                job["running"] = False
                clear_cancel()
                shutdown_search_pool()
                if _pipeline_lock.locked():
                    try:
                        _pipeline_lock.release()
                    except RuntimeError:
                        pass

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        return True

    @staticmethod
    def verdict_badge(manifest: dict) -> tuple[str, list[str]]:
        from test_phase1 import _verdict

        scope = manifest.get("scope") or {}
        return _verdict(scope, manifest)


def markdown_to_plain_preview(md: str, max_lines: int = 40) -> str:
    lines = md.splitlines()[:max_lines]
    text = "\n".join(lines)
    return re.sub(r"\*\*", "", text)
