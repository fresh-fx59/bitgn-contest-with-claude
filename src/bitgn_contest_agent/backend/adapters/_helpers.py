"""Salvage helpers usable by concrete adapters.

Each helper accepts a content ``str`` and returns ``NextStep | None``. All
guards are preserved from the pre-adapter ``_try_salvage_from_content`` — see
docs/superpowers/specs/2026-04-19-local-model-adapters-design.md §6.
"""
from __future__ import annotations

import logging
from typing import Optional, Tuple

from pydantic import ValidationError

from bitgn_contest_agent.schemas import NextStep

_LOG = logging.getLogger(__name__)

# Tokens that unambiguously indicate chat-template leakage or mid-reasoning
# output rather than a clean bare answer. Any match → refuse salvage.
# Covers: harmony channels, qwen/im tags, think-block tags, backticked
# code fences, and the `</tool_call>` fragment that caused the 2026-04-19
# GLM score=0 incident.
_UNSAFE_BARE_TOKENS: Tuple[str, ...] = (
    "<|", "</", "```",
    "<think>", "<think/>",
    "tool_call", "function_call",
)

# Lowercased substrings that suggest the model is still narrating its
# work, not terminating. If any are present the content is NOT a final
# answer and salvage must return None so the critique/retry path runs.
_BARE_ANSWER_CONTINUATION_MARKERS: Tuple[str, ...] = (
    "let me ", "let's ", "i need ", "i should ",
    "i'll ", "i will ", "first, ", "next, ",
    "next step", "thinking", "analysis:", "plan:",
)


def _sanitize_grounding_refs(merged: dict) -> None:
    """Strip non-path junk from ``merged["grounding_refs"]`` in-place.

    Envelope-salvage paths accept whatever the model emitted inside
    ``function.grounding_refs``. Local models occasionally pad the array
    with free-text tokens — the 2026-04-22 gpt-oss-120b PROD run saw
    t103 emit ``["AGENTS.MD", "...bill.md", "5", "5", "", "", ""]``.
    The grounding_ref validator then rejects the whole terminal on the
    junk tokens ("grounding_ref '5' never successfully read"), losing an
    otherwise-valid answer.

    Drop entries that are not strings, empty/whitespace, shorter than 3
    chars after strip, or contain neither ``/`` (path separator) nor
    ``.`` (extension). The remaining list is still validated later by
    ``verify.py`` against the actual read-success set.
    """
    refs = merged.get("grounding_refs")
    if not isinstance(refs, list):
        return
    cleaned = []
    for r in refs:
        if not isinstance(r, str):
            continue
        s = r.strip()
        if len(s) < 3:
            continue
        if "/" not in s and "." not in s:
            continue
        cleaned.append(s)
    merged["grounding_refs"] = cleaned


def try_gpt_oss_full_chain(content: str) -> Optional[NextStep]:
    """Delegate to the legacy ``_try_salvage_from_content``.

    Preserves byte-identical behavior for gpt-oss-20b (harmony → bare-name-
    arguments → envelope → envelope-terminal → bare-value) so the existing
    test corpus still passes. Consolidating into module-level functions is
    the next refactor; do it when we need another adapter that composes a
    subset of these branches beyond LFM2's bare-name-arguments case.
    """
    from bitgn_contest_agent.backend.openai_toolcalling import (
        _try_salvage_from_content,
    )

    return _try_salvage_from_content(content)


def try_bare_name_arguments(content: str) -> Optional[NextStep]:
    """Parse ``{"name": "<tool>", "arguments": {...}}`` from a content body.

    LFM2 is trained on the bare OpenAI tool-call shape and emits it as
    free text when the server doesn't honor ``tool_choice="required"``.
    Returns ``None`` for any other shape or on schema validation failure.
    """
    from bitgn_contest_agent.backend.openai_toolcalling import (
        _VALID_TOOL_NAMES,
        _build_next_step,
        _extract_first_json_object,
    )

    if not content:
        return None
    obj = _extract_first_json_object(content)
    if obj is None:
        return None
    name = obj.get("name")
    args = obj.get("arguments")
    if not isinstance(args, dict) or name not in _VALID_TOOL_NAMES:
        return None
    try:
        return _build_next_step(name, args)
    except ValidationError:
        return None


def try_envelope(content: str) -> Optional[NextStep]:
    """Parse the NextStep envelope shape from content body.

    Shape: ``{"current_state": ..., "function": {"tool": ..., ...}, ...}``.
    Observed on GLM-4.7-Flash when it declines ``tool_choice="required"``
    and emits the structured envelope as free-text content instead.

    Safe against chat-template leakage: requires a parseable JSON object
    with a ``function.tool`` that matches a registered tool name. Empty-
    string placeholder injection for ``rulebook_notes`` /
    ``outcome_justification`` / ``message`` preserves the guard from the
    pre-adapter envelope branch.

    Falls back to envelope-terminal synthesis when the envelope has a
    terminal ``outcome_leaning`` but no ``function`` key.
    """
    from bitgn_contest_agent.backend.openai_toolcalling import (
        _ENVELOPE_FIELDS,
        _VALID_TOOL_NAMES,
        _build_next_step,
        _extract_first_json_object,
        _maybe_salvage_envelope_terminal,
    )

    if not content:
        return None
    obj = _extract_first_json_object(content)
    if obj is None:
        return None
    if "function" in obj and isinstance(obj["function"], dict):
        func = obj["function"]
        tool_name = func.get("tool")
        if tool_name in _VALID_TOOL_NAMES:
            merged = {}
            for key in _ENVELOPE_FIELDS:
                if key in obj:
                    merged[key] = obj[key]
            for key, val in func.items():
                if key != "tool":
                    merged[key] = val
            for placeholder in ("rulebook_notes", "outcome_justification", "message"):
                if merged.get(placeholder) == "":
                    merged[placeholder] = "—"
            _sanitize_grounding_refs(merged)
            try:
                return _build_next_step(tool_name, merged)
            except ValidationError:
                return None
    return _maybe_salvage_envelope_terminal(obj)


def try_qwen_bare_answer(content: str) -> Optional[NextStep]:
    """Salvage a short bare-text content as a terminal report_completion.

    Evidence (2026-04-19 qwen3.5-35b-a3b PROD run): 12 cases where qwen
    emitted the final answer as plain text instead of a tool_call —
    numbers ("1170", "650", "380"), dates ("03-02-2026"), short file-
    path lists. 6 of those tasks failed because the content was not
    salvaged; the circuit breaker eventually fired OUTCOME_NONE_UNSUPPORTED.

    This helper synthesizes a ``report_completion(OUTCOME_OK)`` with the
    stripped content verbatim as ``message``. The grader decides correctness —
    a wrong bare answer still fails, but a right one passes instead of
    being lost to circuit-breaker synthesis.

    Guards (ALL must pass, else return None so the critique loop runs):
      - content is non-empty after strip
      - stripped length ≤ 500 chars (long enough for a short file list;
        too short for mid-exploration prose)
      - no JSON/array prefix (``{`` / ``[``): envelope/name-arguments
        salvage handles those shapes
      - no ``_UNSAFE_BARE_TOKENS`` (chat-template leakage guard — this is
        the 2026-04-19 GLM score=0 rule, inherited)
      - no ``_BARE_ANSWER_CONTINUATION_MARKERS`` (model is narrating,
        not terminating)

    Wired only from ``QwenA3bAdapter``. Other adapters must not chain
    this — GLM's content is chat-template leakage (never a real answer),
    and gpt-oss already owns the legacy bare-value branch with a
    different (tighter) guard set.
    """
    from bitgn_contest_agent.backend.openai_toolcalling import _build_next_step

    if not content:
        return None
    stripped = content.strip()
    if not stripped or len(stripped) > 500:
        return None
    if stripped[0] in "{[":
        return None
    if any(tok in stripped for tok in _UNSAFE_BARE_TOKENS):
        return None
    lowered = stripped.lower()
    if any(tok in lowered for tok in _BARE_ANSWER_CONTINUATION_MARKERS):
        return None
    try:
        ns = _build_next_step(
            "report_completion",
            {
                "message": stripped,
                "grounding_refs": [],
                "rulebook_notes": "—",
                "outcome_justification": "—",
                "completed_steps_laconic": [],
                "outcome": "OUTCOME_OK",
                "outcome_leaning": "OUTCOME_OK",
            },
        )
    except ValidationError:
        return None
    _LOG.info(
        "qwen_bare_answer_salvage: synthesized OUTCOME_OK from bare "
        "content=%r (len=%d)",
        stripped[:120],
        len(stripped),
    )
    return ns
