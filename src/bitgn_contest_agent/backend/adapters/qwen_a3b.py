"""Adapter for qwen3.5-35b-a3b (Heretic MXFP4, LM Studio).

Chain: standard tool_calls → envelope salvage. Same pattern as GLM: qwen
emits the full NextStep envelope as free-text content (with a valid
``function.tool``) when it declines ``tool_choice="required"``. Observed
2026-04-19 20:09 on PROD t000 — the first LLM reply was the complete
envelope with ``"function": {"tool": "read", "path": "AGENTS.md"}``.

No bare-value salvage: qwen's reasoning-mode responses may include
free prose that would be mis-captured as answers (same GLM guard).
Envelope salvage is safe because it requires a parseable JSON object
with a ``function.tool`` that matches a registered tool.
"""
from __future__ import annotations

from typing import Any, Optional

from bitgn_contest_agent.schemas import NextStep

from .base import ModelAdapter, ModelProfile
from ._helpers import try_envelope


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
                reasoning_effort="medium",
            ),
        )

    def extract_next_step(self, message: Any) -> Optional[NextStep]:
        result = super().extract_next_step(message)
        if result is not None:
            return result
        content = getattr(message, "content", None) or ""
        return try_envelope(content)
