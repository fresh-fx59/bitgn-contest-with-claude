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
    _extract_first_json_object,
    _try_salvage_from_content,
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


def test_tool_catalog_every_tool_exposes_envelope_fields_as_properties() -> None:
    """Envelope fields are advertised on every tool so good models fill them,
    but not listed as REQUIRED — small local models ignore required on
    everything except the tool's own fields, and we'd rather default-fill."""
    for t in build_tool_catalog():
        props = t["function"]["parameters"]["properties"]
        required = t["function"]["parameters"]["required"]
        for env in (
            "current_state",
            "plan_remaining_steps_brief",
            "identity_verified",
            "observation",
            "outcome_leaning",
        ):
            assert env in props, f"{t['function']['name']} missing {env} property"
            assert env not in required, \
                f"{t['function']['name']} should not REQUIRE {env} — defaults cover it"


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


def test_build_next_step_fills_envelope_defaults_when_missing() -> None:
    """Tool-specific args alone are enough — envelope fields default-fill."""
    ns = _build_next_step("read", {"path": "AGENTS.md"})
    assert ns.function.tool == "read"
    assert ns.function.path == "AGENTS.md"
    assert ns.current_state == "(not provided by model)"
    assert ns.observation == "(not provided by model)"
    assert ns.outcome_leaning == "GATHERING_INFORMATION"
    assert ns.plan_remaining_steps_brief == ["continue task"]
    assert ns.identity_verified is False


def test_build_next_step_empty_tool_args_still_raises() -> None:
    """Missing the tool's own required field (path) must still raise."""
    with pytest.raises(ValidationError):
        _build_next_step("read", {})


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


def test_next_step_missing_envelope_fields_defaults_and_succeeds() -> None:
    """Small local models commonly omit envelope fields. Defaults kick in
    so the agent can keep turning — trading observation quality for
    forward progress. Only missing tool-own fields fail."""
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _mk_completion(
        tool_name="read",
        arguments={"path": "AGENTS.md"},
    )
    backend = OpenAIToolCallingBackend(
        client=fake_client, model="local-model", reasoning_effort="medium",
    )
    out = backend.next_step(
        [Message(role="user", content="t")], NextStep, 30.0,
    )
    assert out.parsed.function.tool == "read"
    assert out.parsed.current_state == "(not provided by model)"


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


def test_extract_first_json_object_returns_none_for_empty_string() -> None:
    assert _extract_first_json_object("") is None


def test_extract_first_json_object_returns_none_when_no_braces() -> None:
    assert _extract_first_json_object("plain prose, nothing to parse") is None


def test_extract_first_json_object_parses_bare_object() -> None:
    assert _extract_first_json_object('{"a": 1}') == {"a": 1}


def test_extract_first_json_object_parses_object_wrapped_in_prose() -> None:
    text = 'Sure, here you go:\n{"name": "read", "arguments": {"path": "x"}}\nHope that helps.'
    assert _extract_first_json_object(text) == {
        "name": "read", "arguments": {"path": "x"},
    }


def test_extract_first_json_object_handles_braces_inside_strings() -> None:
    text = '{"s": "has { brace", "n": 1}'
    assert _extract_first_json_object(text) == {"s": "has { brace", "n": 1}


def test_extract_first_json_object_handles_nested_objects() -> None:
    text = '{"outer": {"inner": {"leaf": 1}}}'
    assert _extract_first_json_object(text) == {
        "outer": {"inner": {"leaf": 1}},
    }


def test_extract_first_json_object_skips_broken_first_object_and_finds_next() -> None:
    text = 'garbage {not-json:here} then {"ok": 1}'
    assert _extract_first_json_object(text) == {"ok": 1}


def test_salvage_parses_bare_name_arguments_shape() -> None:
    """lfm2 emits the OpenAI tool shape as free text. Salvage it."""
    content = '{"name": "read", "arguments": {"path": "AGENTS.md"}}'
    ns = _try_salvage_from_content(content)
    assert ns is not None
    assert ns.function.tool == "read"
    assert ns.function.path == "AGENTS.md"


def test_salvage_rejects_unknown_tool_name() -> None:
    content = '{"name": "rm_minus_rf", "arguments": {"path": "/"}}'
    assert _try_salvage_from_content(content) is None


def test_salvage_returns_none_on_empty_content() -> None:
    assert _try_salvage_from_content("") is None


def test_salvage_returns_none_when_arguments_missing() -> None:
    content = '{"name": "read"}'
    assert _try_salvage_from_content(content) is None


def test_salvage_parses_full_next_step_envelope_shape() -> None:
    """gpt-oss-20b sometimes emits the full envelope as free text."""
    payload = {
        **_envelope_copy(),
        "function": {"tool": "read", "path": "AGENTS.md"},
    }
    content = f"Sure thing:\n{json.dumps(payload)}\n"
    ns = _try_salvage_from_content(content)
    assert ns is not None
    assert ns.function.tool == "read"
    assert ns.function.path == "AGENTS.md"
    assert ns.current_state == "reading rules"


def test_salvage_returns_none_for_envelope_missing_function_tool() -> None:
    payload = {**_envelope_copy(), "function": {"tool": "read"}}  # no path
    content = json.dumps(payload)
    assert _try_salvage_from_content(content) is None


def test_salvage_prefers_name_arguments_shape_when_both_keys_present() -> None:
    """If content contains {name, arguments, function}, the name/arguments
    branch wins (it's the one small models emit — the envelope key is
    coincidental)."""
    content = json.dumps({
        "name": "read",
        "arguments": {"path": "A.md"},
        "function": {"tool": "write", "path": "B.md", "content": "x"},
    })
    ns = _try_salvage_from_content(content)
    assert ns is not None
    assert ns.function.tool == "read"
    assert ns.function.path == "A.md"
