"""Adapter for qwen3.5-35b-a3b (Heretic MXFP4, LM Studio).

Chain: standard tool_calls → envelope salvage → bare-answer salvage.

Envelope salvage handles qwen's structured content-only replies —
the full NextStep envelope emitted as free-text when the server
declines ``tool_choice="required"`` (observed 2026-04-19 20:09 on
PROD t000: envelope with ``"function": {"tool": "read", ...}`` as
content body).

Bare-answer salvage handles qwen's habit of emitting a short
literal terminal answer as plain content — numbers ("1170"),
dates ("03-02-2026"), short file-path lists. 12 cases observed in
the 2026-04-19 PROD run; 6 were in failed tasks that the circuit
breaker closed with OUTCOME_NONE_UNSUPPORTED. Strong guards (see
``_helpers.try_qwen_bare_answer``) keep this from hijacking a
GATHERING_INFORMATION turn.

``shape_request`` prepends a terse system nudge addressing the
empty-content failure mode: in 196/211 salvage_misses (93%) on
the 2026-04-19 run qwen returned ``content=""`` and
``tool_calls=None`` — correlating with ``reasoning_tokens=0`` on
~30% of steps. Reminding the model that its only valid output
shape is one tool_call reduces these empty returns.

``reasoning_effort="high"`` matches the env-override used during
the 2026-04-19 run. The pre-adapter default was ``medium`` but
was never measured; aligning so the default IS the tested config
(reproducibility over speculation).

Concurrency stays at 2 — no LM Studio slot crashes observed at
that level; 0 task_timeouts in the 104-task run.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from bitgn_contest_agent.schemas import NextStep

from .base import ModelAdapter, ModelProfile
from ._helpers import try_envelope, try_qwen_bare_answer


_QWEN_SYSTEM_NUDGE = (
    "Output discipline: every turn you MUST emit exactly one OpenAI "
    "tool_call. Never reply with empty content or free prose. If you "
    "are terminating, call report_completion. Otherwise call one of "
    "the read/list/tree/search/context tools. Content-only replies "
    "will be rejected."
)


class QwenA3bAdapter(ModelAdapter):
    def __init__(self) -> None:
        super().__init__(
            name="qwen3.5-35b-a3b",
            profile=ModelProfile(
                task_timeout_sec=1800,
                llm_http_timeout_sec=600,
                classifier_timeout_sec=300,
                max_parallel_tasks=2,
                max_inflight_llm=2,
                reasoning_effort="high",
            ),
        )

    def shape_request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        messages = list(payload.get("messages") or [])
        nudge = {"role": "system", "content": _QWEN_SYSTEM_NUDGE}
        return {**payload, "messages": [nudge, *messages]}

    def extract_next_step(self, message: Any) -> Optional[NextStep]:
        result = super().extract_next_step(message)
        if result is not None:
            return result
        content = getattr(message, "content", None) or ""
        parsed = try_envelope(content)
        if parsed is not None:
            return parsed
        return try_qwen_bare_answer(content)
