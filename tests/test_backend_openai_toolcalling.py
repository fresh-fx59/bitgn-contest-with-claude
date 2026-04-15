"""Unit tests for OpenAIToolCallingBackend.

Mock-backed — no network. Asserts tool catalog shape, tool_call→NextStep
adaptation, and that transient OpenAI errors are remapped to
``TransientBackendError`` so the agent's P2 retry wrapper kicks in.
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from bitgn_contest_agent.backend.base import (
    Message,
    NextStepResult,
    TransientBackendError,
)
from bitgn_contest_agent.backend.openai_toolcalling import (
    OpenAIToolCallingBackend,
    _build_next_step,
    build_tool_catalog,
)
from bitgn_contest_agent.schemas import NextStep


_ENVELOPE = {
    "current_state": "reading rules",
    "plan_remaining_steps_brief": ["read", "report"],
    "identity_verified": False,
    "observation": "starting a task",
    "outcome_leaning": "GATHERING_INFORMATION",
}


def _envelope_copy() -> dict[str, Any]:
    return dict(_ENVELOPE)


def _mk_completion(*, tool_name: str, arguments: dict[str, Any] | str,
                   prompt_tokens: int = 10, completion_tokens: int = 5,
                   reasoning_tokens: int = 0) -> MagicMock:
    if isinstance(arguments, dict):
        arguments = json.dumps(arguments)
    tc = MagicMock()
    tc.function.name = tool_name
    tc.function.arguments = arguments
    msg = MagicMock()
    msg.tool_calls = [tc]
    completion = MagicMock()
    completion.choices = [MagicMock(message=msg)]
    completion.usage = MagicMock(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        completion_tokens_details=MagicMock(reasoning_tokens=reasoning_tokens),
    )
    return completion


def test_tool_catalog_has_all_eleven_tools() -> None:
    cat = build_tool_catalog()
    names = {t["function"]["name"] for t in cat}
    assert names == {
        "read", "write", "delete", "mkdir", "move",
        "list", "tree", "find", "search", "context",
        "report_completion",
    }


def test_tool_catalog_every_tool_has_envelope_fields_required() -> None:
    for t in build_tool_catalog():
        required = t["function"]["parameters"]["required"]
        for env in (
            "current_state",
            "plan_remaining_steps_brief",
            "identity_verified",
            "observation",
            "outcome_leaning",
        ):
            assert env in required, f"{t['function']['name']} missing {env}"


def test_tool_catalog_no_oneof_nodes() -> None:
    """Flat per-tool schemas — no oneOf anywhere. That's the whole point."""
    cat = build_tool_catalog()
    blob = json.dumps(cat)
    assert '"oneOf"' not in blob
    assert '"anyOf"' not in blob


def test_build_next_step_roundtrip_read() -> None:
    args = {**_envelope_copy(), "path": "AGENTS.md"}
    ns = _build_next_step("read", args)
    assert isinstance(ns, NextStep)
    assert ns.function.tool == "read"
    assert ns.function.path == "AGENTS.md"
    assert ns.observation == "starting a task"


def test_build_next_step_roundtrip_report_completion() -> None:
    args = {
        **_envelope_copy(),
        "message": "done",
        "grounding_refs": ["AGENTS.md"],
        "rulebook_notes": "ok",
        "outcome_justification": "evidence",
        "completed_steps_laconic": ["read", "report"],
        "outcome": "OUTCOME_OK",
    }
    ns = _build_next_step("report_completion", args)
    assert ns.function.tool == "report_completion"
    assert ns.function.outcome == "OUTCOME_OK"


def test_build_next_step_empty_envelope_raises() -> None:
    args = {"path": "AGENTS.md"}
    with pytest.raises(ValidationError):
        _build_next_step("read", args)


def test_next_step_happy_path_returns_result_with_tokens() -> None:
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _mk_completion(
        tool_name="read",
        arguments={**_envelope_copy(), "path": "AGENTS.md"},
        prompt_tokens=7, completion_tokens=11, reasoning_tokens=3,
    )
    backend = OpenAIToolCallingBackend(
        client=fake_client, model="local-model", reasoning_effort="medium",
    )
    out = backend.next_step(
        messages=[Message(role="user", content="t")],
        response_schema=NextStep,
        timeout_sec=30.0,
    )
    assert isinstance(out, NextStepResult)
    assert out.parsed.function.tool == "read"
    assert out.prompt_tokens == 7
    assert out.completion_tokens == 11
    assert out.reasoning_tokens == 3
    kwargs = fake_client.chat.completions.create.call_args.kwargs
    assert kwargs.get("tool_choice") == "required"
    assert kwargs.get("stream") in (None, False)
    assert len(kwargs.get("tools")) == 11


def test_next_step_no_tool_calls_is_validation_error() -> None:
    """Content-only replies (model didn't call any tool) must surface as
    ValidationError so the agent's P3 critique retry kicks in."""
    fake_client = MagicMock()
    msg = MagicMock()
    msg.tool_calls = []
    completion = MagicMock()
    completion.choices = [MagicMock(message=msg)]
    completion.usage = MagicMock(prompt_tokens=1, completion_tokens=0,
                                 completion_tokens_details=None)
    fake_client.chat.completions.create.return_value = completion
    backend = OpenAIToolCallingBackend(
        client=fake_client, model="local-model", reasoning_effort="medium",
    )
    with pytest.raises(ValidationError):
        backend.next_step(
            [Message(role="user", content="t")], NextStep, 30.0,
        )


def test_next_step_malformed_args_is_validation_error() -> None:
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _mk_completion(
        tool_name="read",
        arguments="not-json{",
    )
    backend = OpenAIToolCallingBackend(
        client=fake_client, model="local-model", reasoning_effort="medium",
    )
    with pytest.raises(ValidationError):
        backend.next_step(
            [Message(role="user", content="t")], NextStep, 30.0,
        )


def test_next_step_empty_envelope_in_args_is_validation_error() -> None:
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _mk_completion(
        tool_name="read",
        arguments={"path": "AGENTS.md"},  # no envelope fields at all
    )
    backend = OpenAIToolCallingBackend(
        client=fake_client, model="local-model", reasoning_effort="medium",
    )
    with pytest.raises(ValidationError):
        backend.next_step(
            [Message(role="user", content="t")], NextStep, 30.0,
        )


def test_rate_limit_is_remapped_to_transient_backend_error() -> None:
    import openai
    fake_client = MagicMock()
    fake_client.chat.completions.create.side_effect = openai.RateLimitError(
        message="slow down",
        response=MagicMock(status_code=429),
        body=None,
    )
    backend = OpenAIToolCallingBackend(
        client=fake_client, model="local-model", reasoning_effort="medium",
    )
    with pytest.raises(TransientBackendError):
        backend.next_step([Message(role="user", content="t")], NextStep, 30.0)


def test_timeout_is_remapped_to_transient_backend_error() -> None:
    import openai
    fake_client = MagicMock()
    fake_client.chat.completions.create.side_effect = openai.APITimeoutError(
        request=MagicMock()
    )
    backend = OpenAIToolCallingBackend(
        client=fake_client, model="local-model", reasoning_effort="medium",
    )
    with pytest.raises(TransientBackendError):
        backend.next_step([Message(role="user", content="t")], NextStep, 30.0)
