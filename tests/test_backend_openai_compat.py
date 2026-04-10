"""Unit tests for OpenAIChatBackend.

These tests do NOT hit cliproxyapi — they mock the openai SDK layer and
assert the adapter's translation behavior.
"""
from __future__ import annotations

import types
from typing import Any
from unittest.mock import MagicMock

import pytest

from bitgn_contest_agent.backend.base import Message, TransientBackendError
from bitgn_contest_agent.backend.openai_compat import OpenAIChatBackend
from bitgn_contest_agent.schemas import NextStep


def _sample_step_json() -> str:
    return (
        '{"current_state":"read AGENTS.md",'
        '"plan_remaining_steps_brief":["read","report"],'
        '"identity_verified":true,'
        '"function":{"tool":"read","path":"AGENTS.md"}}'
    )


def test_structured_path_returns_parsed_next_step(mocker: Any) -> None:
    fake_client = MagicMock()
    fake_parsed = NextStep.model_validate_json(_sample_step_json())
    completion = MagicMock()
    completion.choices = [
        MagicMock(message=MagicMock(parsed=fake_parsed, content=_sample_step_json()))
    ]
    fake_client.beta.chat.completions.parse.return_value = completion

    backend = OpenAIChatBackend(
        client=fake_client,
        model="gpt-5.3-codex",
        reasoning_effort="medium",
        use_structured_output=True,
    )

    out = backend.next_step(
        messages=[Message(role="system", content="sys"), Message(role="user", content="t")],
        response_schema=NextStep,
        timeout_sec=30.0,
    )
    assert isinstance(out, NextStep)
    assert out.function.tool == "read"
    fake_client.beta.chat.completions.parse.assert_called_once()


def test_fallback_path_parses_content_json(mocker: Any) -> None:
    fake_client = MagicMock()
    completion = MagicMock()
    completion.choices = [MagicMock(message=MagicMock(content=_sample_step_json()))]
    fake_client.chat.completions.create.return_value = completion

    backend = OpenAIChatBackend(
        client=fake_client,
        model="gpt-5.3-codex",
        reasoning_effort="medium",
        use_structured_output=False,
    )

    out = backend.next_step(
        messages=[Message(role="user", content="t")],
        response_schema=NextStep,
        timeout_sec=30.0,
    )
    assert isinstance(out, NextStep)
    fake_client.chat.completions.create.assert_called_once()


def test_rate_limit_is_remapped_to_transient_backend_error() -> None:
    import openai

    fake_client = MagicMock()
    fake_client.beta.chat.completions.parse.side_effect = openai.RateLimitError(
        message="slow down",
        response=MagicMock(status_code=429),
        body=None,
    )
    backend = OpenAIChatBackend(
        client=fake_client,
        model="gpt-5.3-codex",
        reasoning_effort="medium",
        use_structured_output=True,
    )
    with pytest.raises(TransientBackendError):
        backend.next_step([Message(role="user", content="t")], NextStep, 30.0)


def test_timeout_is_remapped_to_transient_backend_error() -> None:
    import openai

    fake_client = MagicMock()
    fake_client.beta.chat.completions.parse.side_effect = openai.APITimeoutError(
        request=MagicMock()
    )
    backend = OpenAIChatBackend(
        client=fake_client,
        model="gpt-5.3-codex",
        reasoning_effort="medium",
        use_structured_output=True,
    )
    with pytest.raises(TransientBackendError):
        backend.next_step([Message(role="user", content="t")], NextStep, 30.0)
