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
