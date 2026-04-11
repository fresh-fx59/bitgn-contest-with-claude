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


def test_system_prompt_has_task_classification_section() -> None:
    """Plan B-prime: the prompt must frame category rules as a one-time
    classification step, not as per-turn imperatives (the phase-3 mistake)."""
    p = prompts.system_prompt()
    assert "Task classification" in p, "missing Task classification section heading"


def test_system_prompt_classification_names_all_five_categories() -> None:
    """Every conditional category must be explicitly named so the model
    can pattern-match the task against them."""
    p = prompts.system_prompt()
    for tag in ["FINANCE", "DOCUMENT", "INBOX", "SECURITY", "EXCEPTION"]:
        assert tag in p, f"classification section missing {tag} category"


def test_system_prompt_classification_uses_conditional_framing() -> None:
    """Phase-3 failed because rules were always-apply imperatives.
    This variant must use IF/only-if framing so the model prunes
    inapplicable procedures. Also, no [ALWAYS] paragraph ever says 'MUST'
    inside the classification block — the enforcement moves to the
    tagging step itself."""
    p = prompts.system_prompt()
    # Locate the classification section.
    start = p.index("Task classification")
    # End at the next top-level section, which exists because we place
    # classification BEFORE tool workflow.
    end = p.index("Tool workflow", start)
    section = p[start:end]
    # IF-then framing must dominate the category list.
    assert section.count("[IF ") >= 5, (
        "each category must start with an [IF ...] trigger; counted "
        f"only {section.count('[IF ')}"
    )


def test_system_prompt_classification_references_softener() -> None:
    """The EXCEPTION category must cross-reference the existing
    OUTCOME_NONE_CLARIFICATION softener — this is the one rule
    phase-3 proved load-bearing."""
    p = prompts.system_prompt()
    start = p.index("EXCEPTION")
    end = p.index("\n\n", start)
    exception_block = p[start:end]
    assert "OUTCOME_NONE_CLARIFICATION" in exception_block, (
        "EXCEPTION category must cross-reference the softener"
    )


def test_system_prompt_instructs_agent_to_record_tags_in_current_state() -> None:
    """The classification step only reduces instruction-weight competition
    if the agent does it explicitly as its first cognitive action. The
    contract is: record applicable tags in current_state."""
    p = prompts.system_prompt()
    start = p.index("Task classification")
    end = p.index("Tool workflow", start)
    section = p[start:end]
    assert "current_state" in section, (
        "classification section must instruct agent to record tags "
        "in current_state (or document why not)"
    )


def test_system_prompt_stays_bit_identical_for_cache_hits() -> None:
    """Architectural invariant: the system prompt must not vary per task.
    Two calls without HINT must return byte-identical strings, proving
    the classification step is instructional, not runtime-injected."""
    import os as _os
    _os.environ.pop("HINT", None)
    a = prompts.system_prompt()
    b = prompts.system_prompt()
    assert a == b
    # And no Python string-format placeholders leaked through.
    assert "{" not in a or "}" not in a or "current_state" in a, (
        "suspicious brace pattern suggests runtime interpolation"
    )
