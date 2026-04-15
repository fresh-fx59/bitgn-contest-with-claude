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
    _strip_harmony,
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


def test_tool_catalog_includes_filesystem_and_preflight_tools() -> None:
    cat = build_tool_catalog()
    names = {t["function"]["name"] for t in cat}
    expected = {
        "read", "write", "delete", "mkdir", "move",
        "list", "tree", "find", "search", "context",
        "preflight_schema", "preflight_inbox", "preflight_finance",
        "preflight_entity", "preflight_project", "preflight_doc_migration",
        "report_completion",
    }
    assert names == expected


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
    assert len(kwargs.get("tools")) == len(build_tool_catalog())


def test_next_step_model_reloaded_400_is_transient() -> None:
    """LM Studio returns 400 'Model reloaded.' to in-flight requests when
    it swaps weights. That blast-radius (one event hitting all parallel
    tasks at once) must be a transient retry, not a hard crash."""
    import openai as _openai
    fake_client = MagicMock()
    fake_response = MagicMock(status_code=400)
    fake_response.json = MagicMock(return_value={"error": "Model reloaded."})
    fake_response.text = '{"error": "Model reloaded."}'
    err = _openai.BadRequestError(
        message="Error code: 400 - {'error': 'Model reloaded.'}",
        response=fake_response,
        body={"error": "Model reloaded."},
    )
    fake_client.chat.completions.create.side_effect = err
    backend = OpenAIToolCallingBackend(
        client=fake_client, model="local-model", reasoning_effort="medium",
    )
    from bitgn_contest_agent.backend.base import TransientBackendError
    with pytest.raises(TransientBackendError):
        backend.next_step(
            [Message(role="user", content="t")], NextStep, 30.0,
        )


def test_next_step_model_crashed_400_is_transient() -> None:
    """LM Studio returns 400 'The model has crashed without additional
    information. (Exit code: null)' when the model slot dies (OOM or
    server-side segfault). Like 'Model reloaded', it hits every in-flight
    request at once — must be reclassified as transient so the retry loop
    waits out the slot restart instead of killing the parallel cohort."""
    import openai as _openai
    fake_client = MagicMock()
    fake_response = MagicMock(status_code=400)
    crash_body = {
        "error": "The model has crashed without additional information. (Exit code: null)"
    }
    fake_response.json = MagicMock(return_value=crash_body)
    fake_response.text = json.dumps(crash_body)
    err = _openai.BadRequestError(
        message=f"Error code: 400 - {crash_body}",
        response=fake_response,
        body=crash_body,
    )
    fake_client.chat.completions.create.side_effect = err
    backend = OpenAIToolCallingBackend(
        client=fake_client, model="local-model", reasoning_effort="medium",
    )
    with pytest.raises(TransientBackendError):
        backend.next_step(
            [Message(role="user", content="t")], NextStep, 30.0,
        )


def test_next_step_other_400_still_raises_bad_request() -> None:
    """Other 400s (genuine bad payloads) must surface as BadRequestError,
    not be silently retried."""
    import openai as _openai
    fake_client = MagicMock()
    fake_response = MagicMock(status_code=400)
    fake_response.json = MagicMock(return_value={"error": "bad request"})
    fake_response.text = '{"error": "bad request"}'
    err = _openai.BadRequestError(
        message="Error code: 400 - {'error': 'bad request'}",
        response=fake_response,
        body={"error": "bad request"},
    )
    fake_client.chat.completions.create.side_effect = err
    backend = OpenAIToolCallingBackend(
        client=fake_client, model="local-model", reasoning_effort="medium",
    )
    with pytest.raises(_openai.BadRequestError):
        backend.next_step(
            [Message(role="user", content="t")], NextStep, 30.0,
        )


def test_next_step_no_tool_calls_is_validation_error() -> None:
    """Content-only replies that cannot be salvaged (no JSON) surface as
    ValidationError so the agent's P3 critique retry kicks in."""
    fake_client = MagicMock()
    msg = MagicMock()
    msg.tool_calls = []
    msg.content = ""
    completion = MagicMock()
    completion.choices = [MagicMock(message=msg)]
    completion.usage = MagicMock(prompt_tokens=1, completion_tokens=0,
                                 completion_tokens_details=None)
    fake_client.chat.completions.create.return_value = completion
    backend = OpenAIToolCallingBackend(
        client=fake_client, model="local-model", reasoning_effort="medium",
    )
    with pytest.raises(ValidationError) as ei:
        backend.next_step(
            [Message(role="user", content="t")], NextStep, 30.0,
        )
    assert "tool_calls" in str(ei.value)


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


def test_salvage_returns_none_when_envelope_function_fails_validation() -> None:
    payload = {**_envelope_copy(), "function": {"tool": "read"}}  # no path
    content = json.dumps(payload)
    assert _try_salvage_from_content(content) is None


def test_salvage_returns_none_for_envelope_missing_function_tool() -> None:
    """If function dict has no tool discriminator, salvage returns None."""
    payload = {**_envelope_copy(), "function": {"path": "x"}}
    assert _try_salvage_from_content(json.dumps(payload)) is None


def test_salvage_envelope_with_empty_strings_uses_defaults() -> None:
    """gpt-oss-20b emits envelope JSON with ``current_state=""`` and
    ``observation=""`` — both ``NonEmptyStr``. Salvage must route
    through ``_build_next_step`` so ``_ENVELOPE_DEFAULTS`` papers over
    the empties. Spec §Problem lines 14–17."""
    payload = {
        "current_state": "",
        "plan_remaining_steps_brief": ["read", "report"],
        "identity_verified": False,
        "observation": "",
        "outcome_leaning": "GATHERING_INFORMATION",
        "function": {"tool": "read", "path": "AGENTS.md"},
    }
    content = json.dumps(payload)
    ns = _try_salvage_from_content(content)
    assert ns is not None
    assert ns.function.tool == "read"
    assert ns.function.path == "AGENTS.md"
    # Defaults kicked in for empty envelope fields.
    assert ns.current_state == "(not provided by model)"
    assert ns.observation == "(not provided by model)"


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


def _mk_content_only_completion(*, content: str,
                                prompt_tokens: int = 4,
                                completion_tokens: int = 2) -> MagicMock:
    msg = MagicMock()
    msg.tool_calls = []
    msg.content = content
    completion = MagicMock()
    completion.choices = [MagicMock(message=msg)]
    completion.usage = MagicMock(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        completion_tokens_details=MagicMock(reasoning_tokens=0),
    )
    return completion


def test_next_step_salvages_content_only_name_arguments_reply() -> None:
    """When tool_calls is empty but content holds a bare {name,arguments}
    object, the backend salvages it into a NextStep instead of raising."""
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = \
        _mk_content_only_completion(
            content='{"name": "read", "arguments": {"path": "AGENTS.md"}}',
        )
    backend = OpenAIToolCallingBackend(
        client=fake_client, model="local-model", reasoning_effort="medium",
    )
    out = backend.next_step(
        [Message(role="user", content="t")], NextStep, 30.0,
    )
    assert isinstance(out, NextStepResult)
    assert out.parsed.function.tool == "read"
    assert out.parsed.function.path == "AGENTS.md"
    assert out.prompt_tokens == 4
    assert out.completion_tokens == 2


def test_next_step_raises_validation_error_when_salvage_fails() -> None:
    """Empty content (no JSON to salvage) must still surface ValidationError."""
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = \
        _mk_content_only_completion(content="I don't know what to do.")
    backend = OpenAIToolCallingBackend(
        client=fake_client, model="local-model", reasoning_effort="medium",
    )
    with pytest.raises(ValidationError):
        backend.next_step([Message(role="user", content="t")], NextStep, 30.0)


def test_valid_tool_names_matches_built_tool_catalog() -> None:
    """Drift guard: if a new Req_* is added to schemas.py, either
    _VALID_TOOL_NAMES must be updated alongside it or this test fails
    loudly. Protects the salvage allowlist from silent widening."""
    from bitgn_contest_agent.backend.openai_toolcalling import (
        _VALID_TOOL_NAMES,
    )
    catalog_names = {t["function"]["name"] for t in build_tool_catalog()}
    assert catalog_names == _VALID_TOOL_NAMES


def test_salvage_envelope_missing_entirely_uses_defaults() -> None:
    """Bare {"function": {...}} content — no envelope keys at all — must
    default-fill every envelope field via _build_next_step."""
    payload = {"function": {"tool": "read", "path": "x"}}
    ns = _try_salvage_from_content(json.dumps(payload))
    assert ns is not None
    assert ns.function.tool == "read"
    assert ns.function.path == "x"
    assert ns.current_state == "(not provided by model)"
    assert ns.observation == "(not provided by model)"
    assert ns.plan_remaining_steps_brief == ["continue task"]
    assert ns.identity_verified is False
    assert ns.outcome_leaning == "GATHERING_INFORMATION"


def test_salvage_recovers_truncated_envelope_missing_closing_braces() -> None:
    """When LM Studio cuts the response at max_tokens mid-JSON, the envelope
    ends with open braces/brackets (no string-mid truncation). Salvage must
    still recover something usable by appending the missing closers."""
    # Valid envelope with function but closing braces stripped off.
    payload = {
        "current_state": "reading rules",
        "plan_remaining_steps_brief": ["read", "report"],
        "identity_verified": False,
        "observation": "starting",
        "outcome_leaning": "GATHERING_INFORMATION",
        "function": {"tool": "read", "path": "AGENTS.md"},
    }
    full = json.dumps(payload)
    # Simulate mid-structure truncation: drop the trailing "}}"
    truncated = full[:-2]
    ns = _try_salvage_from_content(truncated)
    assert ns is not None
    assert ns.function.tool == "read"
    assert ns.function.path == "AGENTS.md"


def test_salvage_recovers_truncated_envelope_mid_string() -> None:
    """Truncation inside a string value: close the string and the object."""
    # Envelope truncated mid-string (inside the last path value).
    truncated = (
        '{"current_state":"reading","plan_remaining_steps_brief":["a"],'
        '"identity_verified":false,"observation":"obs",'
        '"outcome_leaning":"GATHERING_INFORMATION",'
        '"function":{"tool":"read","path":"02_distill/cards/very-long-file-na'
    )
    ns = _try_salvage_from_content(truncated)
    assert ns is not None
    assert ns.function.tool == "read"
    # Path is whatever we could recover before the cut.
    assert ns.function.path.startswith("02_distill/cards/")


def test_extract_first_json_object_repairs_simple_truncation() -> None:
    """Direct _extract_first_json_object check: truncated input still yields
    a parseable dict via the repair pass."""
    truncated = '{"a": 1, "b": [1, 2'
    obj = _extract_first_json_object(truncated)
    assert obj is not None
    assert obj["a"] == 1
    assert obj["b"] == [1, 2]


def test_build_next_step_caps_plan_remaining_steps_brief_at_5() -> None:
    """Real repro: gpt-oss-20b emits a valid envelope with 9 delete plan
    items, which violates maxItems=5 and fails NextStep validation.
    _build_next_step must truncate to the first 5 items so the step
    goes through instead of cascading to double-validation failure."""
    from bitgn_contest_agent.backend.openai_toolcalling import _build_next_step
    args = {
        "current_state": "ready to delete",
        "plan_remaining_steps_brief": [
            "delete a.md", "delete b.md", "delete c.md",
            "delete d.md", "delete e.md", "delete f.md",
            "delete g.md", "delete h.md", "delete i.md",
        ],
        "identity_verified": True,
        "observation": "Identity verified",
        "outcome_leaning": "GATHERING_INFORMATION",
        "path": "a.md",
    }
    ns = _build_next_step("delete", args)
    assert len(ns.plan_remaining_steps_brief) == 5
    assert ns.plan_remaining_steps_brief[0] == "delete a.md"
    assert ns.function.tool == "delete"
    assert ns.function.path == "a.md"


def test_build_next_step_normalizes_invalid_outcome_leaning() -> None:
    """If the model emits a string not in the enum, fall back to
    GATHERING_INFORMATION instead of failing validation."""
    from bitgn_contest_agent.backend.openai_toolcalling import _build_next_step
    args = {
        "current_state": "s",
        "plan_remaining_steps_brief": ["step"],
        "identity_verified": False,
        "observation": "o",
        "outcome_leaning": "OUTCOME_MAYBE_OK",  # not in enum
        "path": "x",
    }
    ns = _build_next_step("read", args)
    assert ns.outcome_leaning == "GATHERING_INFORMATION"


def test_salvage_envelope_with_9_plan_items_succeeds() -> None:
    """End-to-end salvage path: envelope-shape content with over-long
    plan list must be recovered (not returned as None) by virtue of the
    cap applied inside _build_next_step."""
    import json as _json
    content = _json.dumps({
        "current_state": "ready",
        "plan_remaining_steps_brief": [f"delete {i}" for i in range(9)],
        "identity_verified": True,
        "observation": "ok",
        "outcome_leaning": "GATHERING_INFORMATION",
        "function": {"tool": "delete", "path": "a.md"},
    })
    ns = _try_salvage_from_content(content)
    assert ns is not None
    assert len(ns.plan_remaining_steps_brief) == 5
    assert ns.function.path == "a.md"


def test_next_step_sets_max_tokens_on_completion_call() -> None:
    """Guard: backend MUST pass a non-trivial max_tokens to the server so
    LM Studio's default cap does not truncate a long envelope reply."""
    fake = MagicMock()
    fake.chat.completions.create.return_value = _mk_completion(
        tool_name="read",
        arguments={**_envelope_copy(), "path": "AGENTS.md"},
    )
    backend = OpenAIToolCallingBackend(
        client=fake, model="m", reasoning_effort="medium",
    )
    backend.next_step([Message(role="user", content="t")], NextStep, 30.0)
    _, kwargs = fake.chat.completions.create.call_args
    assert "max_tokens" in kwargs
    assert kwargs["max_tokens"] >= 2048


# --- gpt-oss harmony stripper tests --------------------------------------
#
# LM Studio's chat template parser for openai/gpt-oss-20b occasionally
# routes "harmony" channel markers into the content field instead of into
# tool_calls / reasoning_content. Four shapes were observed in v9-v11 PROD
# logs; salvage must recover all four without regressing the existing
# bare-JSON shapes.


def test_strip_harmony_returns_content_unchanged_when_no_header() -> None:
    body = '{"name": "read", "arguments": {"path": "x"}}'
    tool, stripped = _strip_harmony(body)
    assert tool is None
    assert stripped == body


def test_strip_harmony_captures_tool_from_commentary_header() -> None:
    content = (
        '<|channel|>commentary to=functions.read '
        '<|constrain|>json<|message|>{"path": "AGENTS.md"}<|call|>'
    )
    tool, stripped = _strip_harmony(content)
    assert tool == "read"
    assert stripped == '{"path": "AGENTS.md"}'


def test_strip_harmony_strips_final_channel_without_tool() -> None:
    content = (
        '<|channel|>final <|constrain|>json<|message|>'
        '{"current_state": "ok"}<|end|>'
    )
    tool, stripped = _strip_harmony(content)
    assert tool is None
    assert stripped == '{"current_state": "ok"}'


def test_strip_harmony_strips_return_and_end_sentinels() -> None:
    content = (
        '<|channel|>final<|message|>{"a": 1}<|return|>'
    )
    tool, stripped = _strip_harmony(content)
    assert tool is None
    assert stripped == '{"a": 1}'


def test_salvage_commentary_harmony_with_bare_arguments() -> None:
    """Complete harmony commentary shape: body is bare arguments for the
    target tool; envelope defaults must fill in the NextStep envelope."""
    content = (
        '<|channel|>commentary to=functions.read '
        '<|constrain|>json<|message|>'
        '{"path": "AGENTS.md"}<|call|>'
    )
    ns = _try_salvage_from_content(content)
    assert ns is not None
    assert ns.function.tool == "read"
    assert ns.function.path == "AGENTS.md"
    # Envelope defaults (not supplied in the harmony body) must be applied.
    assert ns.current_state == "(not provided by model)"


def test_salvage_final_harmony_with_full_envelope() -> None:
    """Complete harmony final shape: body is a full NextStep envelope —
    salvage must parse it via the existing shape-3 path."""
    inner = json.dumps({
        "current_state": "ready",
        "plan_remaining_steps_brief": ["read"],
        "identity_verified": True,
        "observation": "ok",
        "outcome_leaning": "GATHERING_INFORMATION",
        "function": {"tool": "read", "path": "AGENTS.md"},
    })
    content = (
        f'<|channel|>final <|constrain|>json<|message|>{inner}<|end|>'
    )
    ns = _try_salvage_from_content(content)
    assert ns is not None
    assert ns.function.tool == "read"
    assert ns.function.path == "AGENTS.md"
    assert ns.current_state == "ready"
    assert ns.identity_verified is True


def test_salvage_truncated_commentary_harmony() -> None:
    """Harmony commentary header with truncated JSON body (max_tokens cut).
    Expect the repair pass to close the missing braces and recover."""
    content = (
        '<|channel|>commentary to=functions.read '
        '<|constrain|>json<|message|>'
        '{"path": "02_distill/cards/very-long-file-'
    )
    ns = _try_salvage_from_content(content)
    assert ns is not None
    assert ns.function.tool == "read"
    assert ns.function.path.startswith("02_distill/cards/")


def test_salvage_truncated_final_harmony() -> None:
    """Harmony final header with truncated envelope body; shape-3 salvage
    via repair pass must still produce a valid NextStep."""
    partial_inner = (
        '{"current_state":"reading","plan_remaining_steps_brief":["a"],'
        '"identity_verified":false,"observation":"o",'
        '"outcome_leaning":"GATHERING_INFORMATION",'
        '"function":{"tool":"read","path":"AGENTS.md"'
    )
    content = (
        f'<|channel|>final <|constrain|>json<|message|>{partial_inner}'
    )
    ns = _try_salvage_from_content(content)
    assert ns is not None
    assert ns.function.tool == "read"
    assert ns.function.path == "AGENTS.md"


def test_strip_harmony_captures_tool_via_final_nested_commentary() -> None:
    """v12 shape: ``<|channel|>final <|constrain|>commentary to=functions.X``
    — the tool target appears after the channel name but inside a nested
    ``<|constrain|>`` block. Stripper must still extract the tool."""
    content = (
        '<|channel|>final <|constrain|>commentary '
        'to=functions.preflight_doc_migration <|constrain|>json<|message|>'
        '{"entities_root": "01_entity"}<|end|>'
    )
    tool, stripped = _strip_harmony(content)
    assert tool == "preflight_doc_migration"
    assert stripped == '{"entities_root": "01_entity"}'


def test_strip_harmony_captures_tool_via_bare_constrain() -> None:
    """v12 shape: ``<|channel|>final <|constrain|>report_completion<|message|>``
    — no ``to=functions.`` prefix; tool name is the sole word inside
    ``<|constrain|>``. Must match because report_completion is valid."""
    content = (
        '<|channel|>final <|constrain|>report_completion<|message|>'
        '{"outcome": "OUTCOME_OK"}<|end|>'
    )
    tool, stripped = _strip_harmony(content)
    assert tool == "report_completion"
    assert stripped == '{"outcome": "OUTCOME_OK"}'


def test_strip_harmony_bare_constrain_ignores_json_marker() -> None:
    """Guard: ``<|constrain|>json<|message|>`` must NOT be treated as a tool
    name — json isn't a valid tool. The stripper falls through to the
    generic final-header match and returns no tool."""
    content = (
        '<|channel|>final <|constrain|>json<|message|>'
        '{"current_state": "x"}<|end|>'
    )
    tool, stripped = _strip_harmony(content)
    assert tool is None
    assert stripped == '{"current_state": "x"}'


def test_salvage_truncated_final_nested_commentary_harmony() -> None:
    """v12 shape end-to-end: nested-commentary header with truncated body
    that still holds enough tool-specific args to validate. Tool must be
    captured from the header and the body repaired via closers."""
    content = (
        '<|channel|>final <|constrain|>commentary '
        'to=functions.read <|constrain|>json<|message|>'
        '{"path": "01_entity/companies/ACME.md"'
    )
    ns = _try_salvage_from_content(content)
    assert ns is not None
    assert ns.function.tool == "read"
    assert ns.function.path == "01_entity/companies/ACME.md"


def test_salvage_harmony_analysis_channel_then_commentary() -> None:
    """LM Studio sometimes emits an analysis channel as prelude before the
    commentary tool call. _strip_harmony matches the commentary header
    (the first header with a tool target), dropping the analysis prose."""
    content = (
        '<|channel|>analysis<|message|>Let me think about this.<|end|>'
        '<|channel|>commentary to=functions.read '
        '<|constrain|>json<|message|>'
        '{"path": "AGENTS.md"}<|call|>'
    )
    ns = _try_salvage_from_content(content)
    assert ns is not None
    assert ns.function.tool == "read"
    assert ns.function.path == "AGENTS.md"
