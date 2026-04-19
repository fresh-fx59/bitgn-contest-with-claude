"""Adapter for qwen3.5-35b-a3b (Heretic MXFP4, LM Studio).

Pessimistic default: standard tool_calls path only. We have not run this
model end-to-end; grow the chain on evidence rather than speculation.
"""
from __future__ import annotations

from .base import ModelAdapter, ModelProfile


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

    # extract_next_step inherited: standard tool_calls path only.
