"""Adapter for openai/gpt-oss-20b (LM Studio MLX)."""
from __future__ import annotations

from typing import Any, Optional

from bitgn_contest_agent.schemas import NextStep

from .base import ModelAdapter, ModelProfile
from ._helpers import try_gpt_oss_full_chain


class GptOssAdapter(ModelAdapter):
    """Full legacy salvage chain: harmony → bare-name → envelope → terminal → bare-value.

    Delegates content-based fallback to the pre-adapter helper so the
    existing test corpus stays green byte-for-byte.
    """

    def __init__(self) -> None:
        super().__init__(
            name="openai/gpt-oss-20b",
            profile=ModelProfile(
                task_timeout_sec=2400,
                llm_http_timeout_sec=600,
                classifier_timeout_sec=300,
                max_parallel_tasks=4,
                max_inflight_llm=4,
                reasoning_effort="high",
            ),
        )

    def extract_next_step(self, message: Any) -> Optional[NextStep]:
        result = super().extract_next_step(message)
        if result is not None:
            return result
        content = getattr(message, "content", None) or ""
        return try_gpt_oss_full_chain(content)
