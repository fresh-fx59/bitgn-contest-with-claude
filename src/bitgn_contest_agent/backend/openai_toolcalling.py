"""Native OpenAI tool-calling backend for local models.

Used when ``AGENT_TOOLCALLING=1``. Each ``Req_*`` variant and
``ReportTaskCompletion`` is exposed as a separate OpenAI tool whose
parameter schema inlines the ``NextStep`` envelope (``current_state``,
``plan_remaining_steps_brief``, ``identity_verified``, ``observation``,
``outcome_leaning``) alongside the tool's own fields.

Why per-tool flat schemas rather than a single nested ``function``
discriminated union: the ``openai_compat`` backend ships with
``use_structured_output=False`` precisely because upstream (cliproxyapi /
Codex) rejects schemas containing ``oneOf`` nodes. Flat per-tool schemas
avoid ``oneOf`` entirely, which is exactly what LM Studio / llama.cpp
tool-calling implementations handle best.

The agent loop is unchanged: this backend still produces a ``NextStep``
and ``NextStepResult`` with the same fields as ``OpenAIChatBackend``. Only
the transport differs.
"""
from __future__ import annotations

import json as _json
from typing import Any, Dict, List, Sequence, Tuple

import httpx
import openai
from openai import OpenAI
from pydantic import ValidationError

from bitgn_contest_agent.backend.base import (
    Backend,
    Message,
    NextStepResult,
    TransientBackendError,
)
from bitgn_contest_agent.schemas import (
    NextStep,
    REQ_MODELS,
    ReportTaskCompletion,
)


_TRANSIENT_EXCEPTIONS: tuple[type[Exception], ...] = (
    openai.RateLimitError,
    openai.APITimeoutError,
    openai.APIConnectionError,
    openai.InternalServerError,
    httpx.ReadTimeout,
    httpx.RemoteProtocolError,
)


_ENVELOPE_FIELDS: Tuple[str, ...] = (
    "current_state",
    "plan_remaining_steps_brief",
    "identity_verified",
    "observation",
    "outcome_leaning",
)

_OUTCOME_LEANING_VALUES: Tuple[str, ...] = (
    "GATHERING_INFORMATION",
    "OUTCOME_OK",
    "OUTCOME_DENIED_SECURITY",
    "OUTCOME_NONE_CLARIFICATION",
    "OUTCOME_NONE_UNSUPPORTED",
)


def _envelope_schema_fragment() -> Dict[str, Any]:
    """Return the JSONSchema object fragment shared by every tool.

    Properties + required subset the planner must fill before acting.
    """
    return {
        "current_state": {
            "type": "string",
            "minLength": 1,
            "description": "Your reasoning scratchpad — what's the state, what have you tried.",
        },
        "plan_remaining_steps_brief": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "maxItems": 5,
            "description": "1-5 upcoming actions you plan to take.",
        },
        "identity_verified": {
            "type": "boolean",
            "description": "True only after AGENTS.md and context() have been read.",
        },
        "observation": {
            "type": "string",
            "minLength": 1,
            "description": "What this step revealed — a factual statement, not a plan.",
        },
        "outcome_leaning": {
            "type": "string",
            "enum": list(_OUTCOME_LEANING_VALUES),
            "description": "Current lean on the task outcome.",
        },
    }


def _tool_spec_for_req(model_cls: type) -> Dict[str, Any]:
    """Build one OpenAI tool spec from a Req_* pydantic model.

    The envelope fields are inlined as required parameters alongside the
    tool's own fields (everything except the ``tool`` discriminator).
    """
    raw = model_cls.model_json_schema()
    # Pull the Req_* own fields (minus the literal 'tool' discriminator)
    own_props: Dict[str, Any] = {}
    own_required: List[str] = []
    for name, schema in (raw.get("properties") or {}).items():
        if name == "tool":
            continue
        own_props[name] = schema
    for name in raw.get("required") or []:
        if name != "tool":
            own_required.append(name)

    envelope = _envelope_schema_fragment()
    combined_props: Dict[str, Any] = {**envelope, **own_props}
    combined_required = list(_ENVELOPE_FIELDS) + own_required

    tool_name = raw.get("properties", {}).get("tool", {}).get("const") \
        or raw.get("properties", {}).get("tool", {}).get("enum", [None])[0]
    if tool_name is None:
        raise RuntimeError(f"cannot determine tool name for {model_cls!r}")

    description = (model_cls.__doc__ or raw.get("title") or tool_name).strip().splitlines()[0]
    return {
        "type": "function",
        "function": {
            "name": tool_name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": combined_props,
                "required": combined_required,
                "additionalProperties": False,
            },
        },
    }


def build_tool_catalog() -> List[Dict[str, Any]]:
    """Construct the full tool catalog sent on every request.

    Covers the 10 ``Req_*`` action tools plus ``ReportTaskCompletion``.
    """
    catalog: List[Dict[str, Any]] = []
    for model_cls in REQ_MODELS:
        catalog.append(_tool_spec_for_req(model_cls))
    catalog.append(_tool_spec_for_req(ReportTaskCompletion))
    return catalog


def _split_envelope(
    args: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Split a tool-call arguments dict into (envelope, tool_specific)."""
    env = {k: args[k] for k in _ENVELOPE_FIELDS if k in args}
    rest = {k: v for k, v in args.items() if k not in _ENVELOPE_FIELDS}
    return env, rest


def _build_next_step(tool_name: str, args: Dict[str, Any]) -> NextStep:
    """Construct a NextStep from a tool_call's (name, arguments)."""
    env, rest = _split_envelope(args)
    function_payload = {"tool": tool_name, **rest}
    return NextStep.model_validate(
        {
            **env,
            "function": function_payload,
        }
    )


class OpenAIToolCallingBackend(Backend):
    """Backend that uses native OpenAI tool-calling instead of free-text JSON."""

    def __init__(
        self,
        *,
        client: OpenAI,
        model: str,
        reasoning_effort: str,
    ) -> None:
        self._client = client
        self._model = model
        self._reasoning_effort = reasoning_effort
        self._tools = build_tool_catalog()

    @classmethod
    def from_config(
        cls,
        base_url: str,
        api_key: str,
        model: str,
        reasoning_effort: str,
    ) -> "OpenAIToolCallingBackend":
        client = OpenAI(base_url=base_url, api_key=api_key)
        return cls(
            client=client,
            model=model,
            reasoning_effort=reasoning_effort,
        )

    def next_step(
        self,
        messages: Sequence[Message],
        response_schema: type[NextStep],
        timeout_sec: float,
    ) -> NextStepResult:
        payload = [{"role": m.role, "content": m.content} for m in messages]
        try:
            completion = self._client.chat.completions.create(
                model=self._model,
                messages=payload,
                tools=self._tools,
                tool_choice="required",
                timeout=timeout_sec,
            )
        except _TRANSIENT_EXCEPTIONS as exc:
            raise TransientBackendError(str(exc)) from exc

        choice = completion.choices[0]
        tool_calls = getattr(choice.message, "tool_calls", None) or []
        if not tool_calls:
            # Model returned content-only — treat as validation failure so
            # the agent's P3 critique path can push it toward a tool call.
            raise ValidationError.from_exception_data(
                "NextStep",
                [
                    {
                        "type": "missing",
                        "loc": ("function",),
                        "input": {},
                    }
                ],
            )
        call = tool_calls[0]
        raw_args = call.function.arguments or "{}"
        try:
            args = _json.loads(raw_args)
        except _json.JSONDecodeError as exc:
            raise ValidationError.from_exception_data(
                "NextStep",
                [
                    {
                        "type": "json_invalid",
                        "loc": ("function",),
                        "input": raw_args,
                        "ctx": {"error": str(exc)},
                    }
                ],
            )
        parsed = _build_next_step(call.function.name, args)

        usage = getattr(completion, "usage", None)
        prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
        completion_tokens = getattr(usage, "completion_tokens", 0) or 0
        details = getattr(usage, "completion_tokens_details", None)
        reasoning_tokens = getattr(details, "reasoning_tokens", 0) or 0
        return NextStepResult(
            parsed=parsed,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            reasoning_tokens=reasoning_tokens,
        )
