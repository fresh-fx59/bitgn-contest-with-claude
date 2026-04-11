"""Trace schema — single source of truth per §6.5.

Both the writer (trace_writer.py) and any future reader (scripts/*.py)
MUST import these models. The Pydantic models use extra="ignore" so old
traces with fewer fields and future traces with more fields both parse.

Additive-only evolution within a major version:
- New fields are Optional[...] = None.
- Existing fields are never renamed, retyped, or removed.
- Major bump = commit a new fixture + grow test_version_compat.py.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


TRACE_SCHEMA_VERSION = "1.0.0"


ERROR_KIND_VALUES: frozenset[Optional[str]] = frozenset(
    {
        None,
        "BACKEND_ERROR",
        "SUBMISSION_FAILED",
        "CONTEXT_OVERFLOW",
        "INTERNAL_CRASH",
        "MAX_STEPS",
        "CANCELLED",
    }
)

EVENT_KIND_VALUES: frozenset[str] = frozenset(
    {
        "validation_retry",
        "loop_nudge",
        "rate_limit_backoff",
        "timeout_cancel",
        "enforcer_reject",
    }
)

TERMINATED_BY_VALUES: frozenset[str] = frozenset(
    {"report_completion", "error", "cancel", "exhausted"}
)

ERROR_CODE_VALUES: frozenset[Optional[str]] = frozenset(
    {None, "RPC_DEADLINE", "RPC_UNAVAILABLE", "PCM_ERROR", "INVALID_ARG", "UNKNOWN"}
)


class _BaseRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")


class TraceMeta(_BaseRecord):
    kind: Literal["meta"] = "meta"
    agent_version: str
    agent_commit: str
    model: str
    backend: str
    reasoning_effort: str
    benchmark: str
    task_id: str
    task_index: int
    started_at: str
    trace_schema_version: str
    harness_url: Optional[str] = None
    cancelled: bool = False


class TraceTask(_BaseRecord):
    kind: Literal["task"] = "task"
    task_id: str
    task_text: str


class TracePrepass(_BaseRecord):
    kind: Literal["prepass"] = "prepass"
    cmd: str
    ok: bool
    bytes: int = 0
    wall_ms: int = 0
    error: Optional[str] = None
    error_code: Optional[str] = None


class StepLLMStats(_BaseRecord):
    latency_ms: int
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int = 0
    retry_count: int = 0
    reasoning_tokens: int = 0


class StepToolResult(_BaseRecord):
    ok: bool
    bytes: int = 0
    wall_ms: int = 0
    truncated: bool = False
    original_bytes: int = 0
    error: Optional[str] = None
    error_code: Optional[str] = None


class StepSessionAfter(_BaseRecord):
    seen_refs_count: int
    identity_loaded: bool
    rulebook_loaded: bool


class TraceStep(_BaseRecord):
    kind: Literal["step"] = "step"
    step: int
    wall_ms: int
    llm: StepLLMStats
    next_step: dict[str, Any]
    tool_result: StepToolResult
    session_after: StepSessionAfter
    enforcer_verdict: Optional[List[str]] = None
    enforcer_action: Optional[str] = None


class TraceEvent(_BaseRecord):
    kind: Literal["event"] = "event"
    at_step: int
    event_kind: str
    wait_ms: Optional[int] = None
    attempt: Optional[int] = None
    details: Optional[str] = None
    repeated_tuple: Optional[List[str]] = None


class TraceOutcome(_BaseRecord):
    kind: Literal["outcome"] = "outcome"
    terminated_by: str
    reported: Optional[str] = None
    enforcer_bypassed: bool = False
    error_kind: Optional[str] = None
    error_msg: Optional[str] = None
    total_steps: int
    total_llm_calls: int
    total_prompt_tokens: int
    total_completion_tokens: int
    total_cached_tokens: int = 0
    total_reasoning_tokens: int = 0
    score: Optional[float] = None


TraceRecord = Union[TraceMeta, TraceTask, TracePrepass, TraceStep, TraceEvent, TraceOutcome]


_KIND_TO_MODEL: dict[str, type[_BaseRecord]] = {
    "meta": TraceMeta,
    "task": TraceTask,
    "prepass": TracePrepass,
    "step": TraceStep,
    "event": TraceEvent,
    "outcome": TraceOutcome,
}


def load_jsonl(path: Path) -> Iterator[TraceRecord]:
    """Parse a JSONL trace file into typed records. Unknown kinds raise."""
    with Path(path).open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            raw = json.loads(line)
            kind = raw.get("kind")
            model = _KIND_TO_MODEL.get(kind)
            if model is None:
                raise ValueError(f"unknown trace record kind: {kind!r}")
            yield model.model_validate(raw)  # type: ignore[misc]
