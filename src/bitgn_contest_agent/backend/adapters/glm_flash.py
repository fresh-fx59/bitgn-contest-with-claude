"""Adapter for GLM-4.7-Flash-MLX (LM Studio).

Critical: NO content-based salvage. GLM's content-only replies are
chat-template leakage (``</tool_call>``, ``<|channel|>``, etc.), never a
real answer. Applying the gpt-oss bare-value salvage here on 2026-04-19
packaged stray template tokens as task answers and scored 0/2. Empty
``tool_calls`` → ``None`` → backend raises → agent's critique/retry
path handles it.

Concurrency pinned to 1: GLM-4.7-Flash's memory footprint causes LM
Studio model-slot crashes at concurrency >1. MAX_PARALLEL_TASKS=3 has
been a live footgun — the profile makes safe concurrency the default.
"""
from __future__ import annotations

from .base import ModelAdapter, ModelProfile


class GlmFlashAdapter(ModelAdapter):
    def __init__(self) -> None:
        super().__init__(
            name="glm-4.7-flash-mlx",
            profile=ModelProfile(
                task_timeout_sec=3600,
                llm_http_timeout_sec=900,
                classifier_timeout_sec=600,
                max_parallel_tasks=1,
                max_inflight_llm=1,
                reasoning_effort="medium",
            ),
        )

    # extract_next_step inherited: standard tool_calls path only.
