"""Prompt helpers — keep the static prompt cacheable across tasks."""
from __future__ import annotations

from bitgn_contest_agent import prompts


def test_system_prompt_is_deterministic_without_hint(monkeypatch) -> None:
    monkeypatch.delenv("HINT", raising=False)
    a = prompts.system_prompt()
    b = prompts.system_prompt()
    assert a == b
    # Cross-task caching requires bit-identical content.
    assert isinstance(a, str) and len(a) > 100


def test_system_prompt_includes_outcome_enum_semantics() -> None:
    p = prompts.system_prompt()
    for outcome in [
        "OUTCOME_OK",
        "OUTCOME_DENIED_SECURITY",
        "OUTCOME_NONE_CLARIFICATION",
        "OUTCOME_NONE_UNSUPPORTED",
        "OUTCOME_ERR_INTERNAL",
    ]:
        assert outcome in p, f"system prompt missing reference to {outcome}"


def test_hint_interpolation_only_happens_when_hint_is_set(monkeypatch) -> None:
    monkeypatch.delenv("HINT", raising=False)
    base = prompts.system_prompt()
    monkeypatch.setenv("HINT", "remember: paths are case-sensitive")
    with_hint = prompts.system_prompt()
    assert with_hint != base
    assert "remember: paths are case-sensitive" in with_hint


def test_critique_injection_formats_verdict_reasons() -> None:
    text = prompts.critique_injection(["reason A", "reason B"])
    assert "reason A" in text
    assert "reason B" in text
    assert "retry" in text.lower() or "revise" in text.lower()


def test_loop_nudge_references_repeated_tuple() -> None:
    text = prompts.loop_nudge(("read", "AGENTS.md"))
    assert "read" in text
    assert "AGENTS.md" in text
