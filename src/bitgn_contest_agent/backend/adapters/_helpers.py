"""Salvage helpers usable by concrete adapters.

Each helper accepts a content ``str`` and returns ``NextStep | None``. All
guards are preserved from the pre-adapter ``_try_salvage_from_content`` — see
docs/superpowers/specs/2026-04-19-local-model-adapters-design.md §6.
"""
from __future__ import annotations

from typing import Optional

from pydantic import ValidationError

from bitgn_contest_agent.schemas import NextStep


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
            try:
                return _build_next_step(tool_name, merged)
            except ValidationError:
                return None
    return _maybe_salvage_envelope_terminal(obj)
