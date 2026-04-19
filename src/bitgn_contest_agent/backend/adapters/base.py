"""Base classes for per-model adapters.

Each local model exhibits distinct quirks (content-only replies, chat-template
leakage, memory footprint, reasoning support). Adapters isolate those quirks
so the tool-calling backend stays model-agnostic.

See docs/superpowers/specs/2026-04-19-local-model-adapters-design.md for
the architectural rationale.
"""
from __future__ import annotations

import json as _json
from dataclasses import dataclass
from typing import Any, Dict, Optional

from pydantic import ValidationError

from bitgn_contest_agent.schemas import NextStep


@dataclass(frozen=True, slots=True)
class ModelProfile:
    """Per-model defaults for timeouts, concurrency, and reasoning_effort.

    NOTE: Deliberately conflates three scopes (orchestrator concurrency, HTTP
    timeouts, per-call model knobs). Fine at this size. Split trigger: past
    ~8 fields, or a caller needs to override one knob (e.g. classifier wants
    reasoning_effort="low" while agent wants "high") without replacing the
    whole profile.
    """
    task_timeout_sec: int
    llm_http_timeout_sec: int
    classifier_timeout_sec: int
    max_parallel_tasks: int
    max_inflight_llm: int
    reasoning_effort: str  # "low" | "medium" | "high"


class ModelAdapter:
    """Base adapter. Override ``extract_next_step`` to chain model-specific
    fallbacks after the standard OpenAI tool_calls path.

    ``shape_request`` is a passthrough by default; override for system-message
    injection or tool-schema trimming.
    """

    name: str
    profile: ModelProfile

    def __init__(self, name: str, profile: ModelProfile) -> None:
        self.name = name
        self.profile = profile

    def shape_request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Default: passthrough. Override to mutate the outbound OpenAI payload."""
        return payload

    def extract_next_step(self, message: Any) -> Optional[NextStep]:
        """Standard OpenAI tool_calls[0] → NextStep path.

        Returns ``None`` on any failure (no tool_calls, invalid JSON args,
        schema validation). The backend translates ``None`` into the caller-
        visible ``ValidationError``.
        """
        from bitgn_contest_agent.backend.openai_toolcalling import _build_next_step

        tool_calls = getattr(message, "tool_calls", None) or []
        if not tool_calls:
            return None
        call = tool_calls[0]
        fn = getattr(call, "function", None)
        if fn is None:
            return None
        raw_args = getattr(fn, "arguments", None) or "{}"
        try:
            args = _json.loads(raw_args)
        except _json.JSONDecodeError:
            return None
        try:
            return _build_next_step(getattr(fn, "name", ""), args)
        except ValidationError:
            return None
