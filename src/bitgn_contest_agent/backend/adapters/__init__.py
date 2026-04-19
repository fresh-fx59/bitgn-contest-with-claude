"""Per-model adapter registry.

``get_adapter(model)`` returns the ``ModelAdapter`` for the given exact
model string, or raises ``ConfigError`` listing the registered keys. The
registry is only consulted from ``OpenAIToolCallingBackend.from_config``,
which itself is only reached when ``AGENT_TOOLCALLING=1``. The frontier
path (``OpenAIChatBackend``) never calls ``get_adapter``.
"""
from __future__ import annotations

from typing import Dict, Type

from bitgn_contest_agent.config import ConfigError

from .base import ModelAdapter, ModelProfile
from .glm_flash import GlmFlashAdapter
from .gpt_oss import GptOssAdapter
from .lfm2 import Lfm2Adapter
from .qwen_a3b import QwenA3bAdapter


ADAPTERS: Dict[str, Type[ModelAdapter]] = {
    "openai/gpt-oss-20b": GptOssAdapter,
    "glm-4.7-flash-mlx": GlmFlashAdapter,
    "liquid/lfm2-24b-a2b": Lfm2Adapter,
    "qwen3.5-35b-a3b": QwenA3bAdapter,
}


def get_adapter(model: str) -> ModelAdapter:
    """Return the adapter for ``model``, fail-fast on unknown."""
    cls = ADAPTERS.get(model)
    if cls is None:
        raise ConfigError(
            f"No adapter registered for AGENT_MODEL={model!r}. "
            f"Registered: {sorted(ADAPTERS)}. "
            f"Add one in src/bitgn_contest_agent/backend/adapters/."
        )
    return cls()


__all__ = [
    "ADAPTERS",
    "ModelAdapter",
    "ModelProfile",
    "get_adapter",
]
