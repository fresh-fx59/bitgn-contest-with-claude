"""Provider-agnostic backend protocol.

The planner only ever talks to Backend.next_step — it never knows which
provider is in use. A second backend (anthropic_compat, etc.) is a new
file, not a refactor.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence, runtime_checkable

from bitgn_contest_agent.schemas import NextStep


@dataclass(frozen=True, slots=True)
class Message:
    role: str           # "system" | "user" | "assistant" | "tool"
    content: str


class TransientBackendError(Exception):
    """Rate limit, 5xx, or network timeout. Caller retries with backoff."""

    def __init__(self, message: str, *, attempt: int = 0) -> None:
        super().__init__(message)
        self.attempt = attempt


@runtime_checkable
class Backend(Protocol):
    def next_step(
        self,
        messages: Sequence[Message],
        response_schema: type[NextStep],
        timeout_sec: float,
    ) -> NextStep:
        ...
