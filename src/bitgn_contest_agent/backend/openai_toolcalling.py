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
import logging
from typing import Any, Dict, List, Sequence, Tuple

import httpx
import openai
from openai import OpenAI
from pydantic import ValidationError

_LOG = logging.getLogger(__name__)

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

# Defaults injected when a small local model omits the envelope fields
# despite being listed in the tool schema. Keeps the NextStep valid and
# lets the validator operate without envelope-filling becoming a blocker
# on every turn. Good models (that fill the envelope) get the full
# benefit; sloppy models still drive the benchmark.
_ENVELOPE_DEFAULTS: Dict[str, Any] = {
    "current_state": "(not provided by model)",
    "plan_remaining_steps_brief": ["continue task"],
    "identity_verified": False,
    "observation": "(not provided by model)",
    "outcome_leaning": "GATHERING_INFORMATION",
}

# Matches the maxItems=5 constraint the schema fragment advertises.
# Sloppy local models routinely emit longer lists (e.g. one plan entry per
# file they intend to touch on a "delete all captured cards" task).
# Instead of losing the turn to too_long validation, keep the first 5.
_PLAN_MAX_ITEMS: int = 5


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
    # Envelope fields are advertised as properties on every tool so good
    # models fill them, but only the tool's own fields are REQUIRED. Small
    # local models routinely ignore ``required`` on every field, and we'd
    # rather default-fill the envelope than lose every turn to
    # double-validation failure.
    combined_required = own_required

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
    """Construct a NextStep from a tool_call's (name, arguments).

    Envelope fields missing or empty in ``args`` are default-filled from
    ``_ENVELOPE_DEFAULTS``. This keeps small local models (which
    frequently ignore JSON-schema ``required`` on anything beyond the
    tool's own parameters) from losing every turn to validation failure.
    """
    env, rest = _split_envelope(args)
    for k, default in _ENVELOPE_DEFAULTS.items():
        val = env.get(k)
        if val is None or (isinstance(val, str) and val.strip() == "") \
                or (isinstance(val, list) and len(val) == 0):
            env[k] = default
    plan = env.get("plan_remaining_steps_brief")
    if isinstance(plan, list) and len(plan) > _PLAN_MAX_ITEMS:
        env["plan_remaining_steps_brief"] = plan[:_PLAN_MAX_ITEMS]
    leaning = env.get("outcome_leaning")
    if leaning not in _OUTCOME_LEANING_VALUES:
        env["outcome_leaning"] = _ENVELOPE_DEFAULTS["outcome_leaning"]
    function_payload = {"tool": tool_name, **rest}
    return NextStep.model_validate(
        {
            **env,
            "function": function_payload,
        }
    )


def _extract_first_json_object(text: str) -> Dict[str, Any] | None:
    """Find and parse the first balanced ``{...}`` JSON object in ``text``.

    Small local models sometimes wrap their JSON in prose or code fences.
    Scan for a brace-balanced object and attempt ``json.loads`` on it. If
    no scan reaches depth 0 (the response was cut mid-JSON by an
    upstream token cap), fall back to ``_repair_truncated_json`` on the
    suffix starting at the first ``{``.
    """
    if not text:
        return None
    start = text.find("{")
    while start != -1:
        depth = 0
        in_str = False
        escape = False
        for i in range(start, len(text)):
            ch = text[i]
            if escape:
                escape = False
                continue
            if ch == "\\" and in_str:
                escape = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start:i + 1]
                    try:
                        obj = _json.loads(candidate)
                    except _json.JSONDecodeError:
                        break
                    if isinstance(obj, dict):
                        return obj
                    break
        start = text.find("{", start + 1)
    first = text.find("{")
    if first == -1:
        return None
    return _repair_truncated_json(text[first:])


def _repair_truncated_json(text: str) -> Dict[str, Any] | None:
    """Best-effort parse of a JSON object that was cut off mid-structure.

    Walks the input tracking string state, array/object depth, and escape
    sequences. On reaching the end with unclosed scopes, closes the open
    string (if any), drops any trailing ``,`` or ``:`` that would make
    the JSON invalid, closes any dangling partial-key, then appends the
    matching ``]``/``}`` closers in reverse order. If that yields a
    valid dict, returns it; otherwise ``None``.

    Only applied when the balanced-brace scanner found no complete
    object — the normal happy path is unchanged.
    """
    stack: List[str] = []
    in_str = False
    escape = False
    for ch in text:
        if escape:
            escape = False
            continue
        if ch == "\\" and in_str:
            escape = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            stack.append("}")
        elif ch == "[":
            stack.append("]")
        elif ch == "}" or ch == "]":
            if stack and stack[-1] == ch:
                stack.pop()
    repaired = text
    if in_str:
        repaired += '"'
    stripped = repaired.rstrip()

    def _try(payload: str) -> Dict[str, Any] | None:
        try:
            obj = _json.loads(payload)
        except _json.JSONDecodeError:
            return None
        return obj if isinstance(obj, dict) else None

    # Attempt 1: just close open scopes.
    attempt = stripped + "".join(reversed(stack))
    out = _try(attempt)
    if out is not None:
        return out

    # Attempt 2: drop a trailing ``,`` or ``:`` that would leave a dangling
    # pair, then close.
    while stripped and stripped[-1] in ",:":
        stripped = stripped[:-1].rstrip()
    attempt = stripped + "".join(reversed(stack))
    out = _try(attempt)
    if out is not None:
        return out

    # Attempt 3: walk back past the last ``,`` or ``{`` to drop a partial
    # or incomplete trailing pair entirely, then close.
    for cut in range(len(stripped) - 1, -1, -1):
        c = stripped[cut]
        if c == ',':
            candidate = stripped[:cut]
            break
        if c == '{':
            candidate = stripped[:cut + 1]
            break
    else:
        return None
    attempt = candidate + "".join(reversed(stack))
    return _try(attempt)


_VALID_TOOL_NAMES: frozenset[str] = frozenset({
    "read", "write", "delete", "mkdir", "move",
    "list", "tree", "find", "search", "context",
    "report_completion",
})


def _try_salvage_from_content(content: str) -> NextStep | None:
    """Attempt to build a NextStep from a content-only reply.

    Two shapes to handle:
      1. ``{"name": "<tool>", "arguments": {...}}`` — bare OpenAI tool
         shape emitted as free text (liquid/lfm2 trained behavior).
      2. ``{"current_state": ..., "function": {"tool": ..., ...}}`` — the
         full NextStep envelope that the OpenAIChatBackend expects.

    Returns the parsed ``NextStep`` on success, ``None`` otherwise.
    """
    obj = _extract_first_json_object(content)
    if obj is None:
        return None
    if "name" in obj and isinstance(obj.get("arguments"), dict):
        tool_name = obj.get("name")
        if tool_name in _VALID_TOOL_NAMES:
            try:
                return _build_next_step(tool_name, obj["arguments"])
            except ValidationError:
                return None
    if "function" in obj and isinstance(obj["function"], dict):
        func = obj["function"]
        tool_name = func.get("tool")
        if tool_name in _VALID_TOOL_NAMES:
            merged: Dict[str, Any] = {}
            for key in _ENVELOPE_FIELDS:
                if key in obj:
                    merged[key] = obj[key]
            for key, val in func.items():
                if key != "tool":
                    merged[key] = val
            try:
                return _build_next_step(tool_name, merged)
            except ValidationError:
                return None
    return None


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
                max_tokens=4096,
            )
        except _TRANSIENT_EXCEPTIONS as exc:
            raise TransientBackendError(str(exc)) from exc

        choice = completion.choices[0]
        tool_calls = getattr(choice.message, "tool_calls", None) or []
        content = getattr(choice.message, "content", None) or ""
        if not tool_calls:
            # LM Studio (and similar local servers) do not always honor
            # tool_choice="required" — small models may emit the OpenAI
            # tool shape {"name","arguments"} as free-text content, or
            # even a NextStep-like JSON blob. Try to salvage either shape
            # before giving up with a critique.
            salvaged = _try_salvage_from_content(content)
            if salvaged is not None:
                parsed = salvaged
            else:
                content_head = content[:200]
                # Log raw content preview so post-mortem can see what the
                # model sent. ValidationError below is the caller-visible
                # signal; this log is the debug trail.
                _LOG.warning(
                    "salvage_miss: content-only reply, no JSON object found; "
                    "content[:200]=%r",
                    content_head,
                )
                hint = (
                    "tool_calls missing: you replied with prose instead of "
                    "a tool call. You MUST call exactly one tool per turn "
                    "using the OpenAI tool_calls mechanism (not free text). "
                    f"Your content started with: {content_head!r}"
                )
                raise ValidationError.from_exception_data(
                    "NextStep",
                    [
                        {
                            "type": "value_error",
                            "loc": ("function",),
                            "input": content_head,
                            "ctx": {"error": ValueError(hint)},
                        }
                    ],
                )
        else:
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
