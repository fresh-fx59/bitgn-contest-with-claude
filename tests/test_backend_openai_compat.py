"""Unit tests for OpenAIChatBackend.

These tests do NOT hit cliproxyapi — they mock the openai SDK layer and
assert the adapter's translation behavior.
"""
from __future__ import annotations

import types
from typing import Any
from unittest.mock import MagicMock

import pytest

from bitgn_contest_agent.backend.base import Message, NextStepResult, TransientBackendError
from bitgn_contest_agent.backend.openai_compat import (
    OpenAIChatBackend,
    _extract_json_object,
)
from bitgn_contest_agent.schemas import NextStep


def _sample_step_json() -> str:
    return (
        '{"current_state":"read AGENTS.md",'
        '"plan_remaining_steps_brief":["read","report"],'
        '"identity_verified":true,'
        '"observation":"reading workspace rules",'
        '"outcome_leaning":"GATHERING_INFORMATION",'
        '"function":{"tool":"read","path":"AGENTS.md"}}'
    )


def test_structured_path_returns_parsed_next_step(mocker: Any) -> None:
    fake_client = MagicMock()
    fake_parsed = NextStep.model_validate_json(_sample_step_json())
    completion = MagicMock()
    completion.choices = [
        MagicMock(message=MagicMock(parsed=fake_parsed, content=_sample_step_json()))
    ]
    completion.usage = MagicMock(
        prompt_tokens=10,
        completion_tokens=5,
        completion_tokens_details=MagicMock(reasoning_tokens=2),
    )
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
    assert isinstance(out, NextStepResult)
    assert out.parsed.function.tool == "read"
    fake_client.beta.chat.completions.parse.assert_called_once()


def test_fallback_path_concatenates_streamed_deltas(mocker: Any) -> None:
    """The fallback path streams and concatenates delta.content across chunks
    (cliproxyapi only emits message body via streaming, not via non-stream
    chat completions — T24 observation)."""
    fake_client = MagicMock()
    full_json = _sample_step_json()
    # Split into 4 arbitrary chunks to exercise concatenation ordering.
    splits = [0, 12, 40, 80, len(full_json)]
    chunks: list[Any] = []
    for lo, hi in zip(splits, splits[1:]):
        chunk = MagicMock()
        chunk.choices = [MagicMock(delta=MagicMock(content=full_json[lo:hi]))]
        chunk.usage = None
        chunks.append(chunk)
    # Usage chunk (mirrors OpenAI's usage-only tail with empty choices).
    usage_chunk = MagicMock()
    usage_chunk.choices = []
    usage_chunk.usage = MagicMock(
        prompt_tokens=10,
        completion_tokens=5,
        completion_tokens_details=MagicMock(reasoning_tokens=2),
    )
    chunks.append(usage_chunk)
    # Terminal chunk with empty delta (mirrors OpenAI's finish-only tail).
    tail = MagicMock()
    tail.choices = [MagicMock(delta=MagicMock(content=None))]
    tail.usage = None
    chunks.append(tail)
    fake_client.chat.completions.create.return_value = iter(chunks)

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
    assert isinstance(out, NextStepResult)
    assert out.parsed.function.tool == "read"
    # stream=True must be passed to the SDK
    kwargs = fake_client.chat.completions.create.call_args.kwargs
    assert kwargs.get("stream") is True
    # stream_options with include_usage must be passed to capture token counts.
    assert kwargs.get("stream_options") == {"include_usage": True}
    # response_format must NOT be passed — it breaks cliproxyapi's conversion.
    assert "response_format" not in kwargs


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


def test_httpx_readtimeout_from_stream_iteration_is_remapped_to_transient() -> None:
    """T24 observation: the openai SDK's retry wrapper only covers the
    initial request, so httpx.ReadTimeout raised *while iterating* a
    streaming response escapes as-is. _TRANSIENT_EXCEPTIONS must
    catch it so the P2 backoff in AgentLoop can retry."""
    import httpx

    def _raise_midstream() -> Any:
        yield MagicMock(choices=[MagicMock(delta=MagicMock(content='{"x":'))])
        raise httpx.ReadTimeout("timed out", request=MagicMock())

    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _raise_midstream()
    backend = OpenAIChatBackend(
        client=fake_client,
        model="gpt-5.3-codex",
        reasoning_effort="medium",
        use_structured_output=False,
    )
    with pytest.raises(TransientBackendError):
        backend.next_step([Message(role="user", content="t")], NextStep, 30.0)


def test_extract_json_object_strips_markdown_fences() -> None:
    raw = '```json\n{"tool":"tree","root":"/"}\n```'
    assert _extract_json_object(raw) == '{"tool":"tree","root":"/"}'


def test_extract_json_object_slices_to_outermost_braces() -> None:
    raw = 'Sure, here is the NextStep: {"current_state":"x","f":{"a":1}} end'
    assert _extract_json_object(raw) == '{"current_state":"x","f":{"a":1}}'


def test_extract_json_object_handles_braces_inside_strings() -> None:
    raw = '{"msg":"contains } brace","ok":true}'
    assert _extract_json_object(raw) == raw


def test_extract_json_object_returns_original_when_no_braces() -> None:
    assert _extract_json_object("plain text") == "plain text"


def test_next_step_returns_result_wrapper_with_tokens(mocker: Any) -> None:
    """Structured path must return NextStepResult with token counts from usage."""
    fake_client = MagicMock()
    fake_parsed = NextStep.model_validate_json(_sample_step_json())
    completion = MagicMock()
    completion.choices = [
        MagicMock(message=MagicMock(parsed=fake_parsed, content=_sample_step_json()))
    ]
    completion.usage = MagicMock(
        prompt_tokens=10,
        completion_tokens=5,
        completion_tokens_details=MagicMock(reasoning_tokens=2),
    )
    fake_client.beta.chat.completions.parse.return_value = completion

    backend = OpenAIChatBackend(
        client=fake_client,
        model="gpt-5.3-codex",
        reasoning_effort="medium",
        use_structured_output=True,
    )

    result = backend.next_step(
        messages=[Message(role="system", content="sys"), Message(role="user", content="t")],
        response_schema=NextStep,
        timeout_sec=30.0,
    )
    assert isinstance(result, NextStepResult)
    assert isinstance(result.parsed, NextStep)
    assert result.parsed.function.tool == "read"
    assert result.prompt_tokens == 10
    assert result.completion_tokens == 5
    assert result.reasoning_tokens == 2
