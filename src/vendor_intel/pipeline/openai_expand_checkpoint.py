"""Resume checkpoints for ChatGPT expand (per step / substep)."""
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CHECKPOINT_VERSION = 1


class ExpandCheckpoint:
    """Atomic JSON checkpoint so a killed run can resume mid-step."""

    def __init__(self, path: Path, state: dict[str, Any]):
        self.path = path
        self.state = state

    @classmethod
    def path_for(cls, out_dir: Path, batch: str) -> Path:
        return out_dir / f"chatgpt_checkpoint_batch_{batch.lower()}.json"

    @classmethod
    def create(
        cls,
        out_dir: Path,
        *,
        query: str,
        country: str,
        batch: str,
        target: int,
        meta: dict[str, Any] | None = None,
    ) -> ExpandCheckpoint:
        path = cls.path_for(out_dir, batch)
        state: dict[str, Any] = {
            "version": CHECKPOINT_VERSION,
            "query": query,
            "country": country,
            "batch": batch,
            "target": target,
            "status": "running",
            "step": "0_start",
            "substep": "init",
            "created_at": _now(),
            "updated_at": _now(),
            "completed": {},
            "progress": {},
            "data": {},
            "meta": meta or {},
            "history": [],
        }
        ckpt = cls(path, state)
        ckpt.save(note="created")
        return ckpt

    @classmethod
    def load(cls, path: Path) -> ExpandCheckpoint | None:
        if not path.exists():
            return None
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(state, dict):
            return None
        return cls(path, state)

    @classmethod
    def load_or_create(
        cls,
        out_dir: Path,
        *,
        query: str,
        country: str,
        batch: str,
        target: int,
        resume: bool,
        meta: dict[str, Any] | None = None,
        force: bool = False,
    ) -> tuple[ExpandCheckpoint, bool]:
        """Return (checkpoint, resumed).

        If a prior run finished (`status=done`) and resume=True and not force,
        return that checkpoint unchanged so callers can skip the whole market
        (critical for 10k-market batches).
        """
        path = cls.path_for(out_dir, batch)
        if resume and not force:
            existing = cls.load(path)
            if existing and (existing.state.get("query") or "").strip().lower() == query.strip().lower():
                if existing.state.get("status") == "done":
                    return existing, True
                existing.state["status"] = "running"
                existing.state["updated_at"] = _now()
                existing.save(note="resumed")
                return existing, True
        ckpt = cls.create(
            out_dir,
            query=query,
            country=country,
            batch=batch,
            target=target,
            meta=meta,
        )
        return ckpt, False

    def save(self, note: str = "") -> None:
        self.state["updated_at"] = _now()
        if note:
            hist = self.state.setdefault("history", [])
            hist.append({"at": _now(), "note": note, "step": self.state.get("step"), "substep": self.state.get("substep")})
            # keep last 400 history entries (every step + substep)
            if len(hist) > 400:
                self.state["history"] = hist[-400:]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.state, indent=2, ensure_ascii=False)
        # atomic replace
        fd, tmp_name = tempfile.mkstemp(
            prefix="ckpt_", suffix=".json", dir=str(self.path.parent)
        )
        tmp_path = Path(tmp_name)
        try:
            with open(fd, "w", encoding="utf-8") as f:
                f.write(payload)
            tmp_path.replace(self.path)
        except Exception:
            try:
                tmp_path.unlink(missing_ok=True)  # type: ignore[call-arg]
            except Exception:
                pass
            # fallback non-atomic
            self.path.write_text(payload, encoding="utf-8")

    def bump(
        self,
        step: str,
        substep: str,
        *,
        progress: dict[str, Any] | None = None,
        note: str = "",
        **data: Any,
    ) -> None:
        self.state["step"] = step
        self.state["substep"] = substep
        if progress:
            self.state.setdefault("progress", {}).update(progress)
        if data:
            self.state.setdefault("data", {}).update(data)
        self.save(note=note or f"{step}/{substep}")

    def begin(
        self,
        step: str,
        substep: str,
        *,
        note: str = "",
        progress: dict[str, Any] | None = None,
        **data: Any,
    ) -> None:
        """Persist that this step/substep has started (kill mid-work still resumes here)."""
        self.bump(
            step,
            substep,
            progress=progress,
            note=note or f"begin {step}/{substep}",
            **data,
        )

    def mark_step_done(self, step: str, **data: Any) -> None:
        self.state.setdefault("completed", {})[step] = True
        if data:
            self.state.setdefault("data", {}).update(data)
        self.bump(step, f"{step}_done", note=f"completed {step}")

    def is_step_done(self, step: str) -> bool:
        return bool(self.state.get("completed", {}).get(step))

    def data(self, key: str, default: Any = None) -> Any:
        return self.state.get("data", {}).get(key, default)

    def progress_get(self, key: str, default: Any = None) -> Any:
        return self.state.get("progress", {}).get(key, default)

    def mark_done(self) -> None:
        self.state["status"] = "done"
        self.state["step"] = "7_write"
        self.state["substep"] = "done"
        self.save(note="pipeline complete")

    def is_done(self) -> bool:
        return self.state.get("status") == "done"

    def summary_line(self) -> str:
        return (
            f"step={self.state.get('step')} substep={self.state.get('substep')} "
            f"status={self.state.get('status')} file={self.path}"
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
