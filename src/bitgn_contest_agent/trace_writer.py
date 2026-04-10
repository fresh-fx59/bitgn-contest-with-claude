"""Incremental JSONL writer. Thread-safe per instance.

Each worker creates one TraceWriter, writes records as the run
progresses, and calls close() at the end. On unhandled exception the
worker calls write_crash_sidecar() before re-raising.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Optional

from bitgn_contest_agent.trace_schema import (
    StepLLMStats,
    StepSessionAfter,
    StepToolResult,
    TraceEvent,
    TraceMeta,
    TraceOutcome,
    TracePrepass,
    TraceStep,
    TraceTask,
)


class TraceWriter:
    def __init__(self, *, path: Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._fh = self._path.open("a", encoding="utf-8", buffering=1)

    @property
    def path(self) -> Path:
        return self._path

    # -- individual record writers ---------------------------------------

    def write_meta(self, meta: TraceMeta) -> None:
        self._write(meta.model_dump(mode="json"))

    def append_task(self, *, task_id: str, task_text: str) -> None:
        rec = TraceTask(task_id=task_id, task_text=task_text)
        self._write(rec.model_dump(mode="json"))

    def append_prepass(
        self,
        *,
        cmd: str,
        ok: bool,
        bytes: int = 0,
        wall_ms: int = 0,
        error: Optional[str] = None,
        error_code: Optional[str] = None,
    ) -> None:
        rec = TracePrepass(
            cmd=cmd,
            ok=ok,
            bytes=bytes,
            wall_ms=wall_ms,
            error=error,
            error_code=error_code,
        )
        self._write(rec.model_dump(mode="json"))

    def append_step(
        self,
        *,
        step: int,
        wall_ms: int,
        llm: StepLLMStats,
        next_step: dict[str, Any],
        tool_result: StepToolResult,
        session_after: StepSessionAfter,
        enforcer_verdict: list[str] | None = None,
        enforcer_action: str | None = None,
    ) -> None:
        rec = TraceStep(
            step=step,
            wall_ms=wall_ms,
            llm=llm,
            next_step=next_step,
            tool_result=tool_result,
            session_after=session_after,
            enforcer_verdict=enforcer_verdict,
            enforcer_action=enforcer_action,
        )
        self._write(rec.model_dump(mode="json"))

    def append_event(
        self,
        *,
        at_step: int,
        event_kind: str,
        wait_ms: Optional[int] = None,
        attempt: Optional[int] = None,
        details: Optional[str] = None,
        repeated_tuple: Optional[list[str]] = None,
    ) -> None:
        rec = TraceEvent(
            at_step=at_step,
            event_kind=event_kind,
            wait_ms=wait_ms,
            attempt=attempt,
            details=details,
            repeated_tuple=repeated_tuple,
        )
        self._write(rec.model_dump(mode="json"))

    def append_outcome(self, outcome: TraceOutcome) -> None:
        self._write(outcome.model_dump(mode="json"))

    def close(self) -> None:
        with self._lock:
            if not self._fh.closed:
                self._fh.flush()
                self._fh.close()

    def write_crash_sidecar(self, error: str, *, traceback_text: str) -> None:
        """Write <trace>_CRASHED.json. Uses a separate I/O path so a broken
        main handle does not lose the crash info."""
        sidecar = self._path.with_name(
            self._path.name.replace(".jsonl", "_CRASHED.json")
        )
        payload = {
            "error": error,
            "traceback": traceback_text,
            "partial_trace": str(self._path),
        }
        sidecar.write_text(json.dumps(payload), encoding="utf-8")

    # -- internals -------------------------------------------------------

    def _write(self, payload: dict[str, Any]) -> None:
        line = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        with self._lock:
            if self._fh.closed:
                raise RuntimeError("TraceWriter already closed")
            self._fh.write(line)
            self._fh.write("\n")
            self._fh.flush()
