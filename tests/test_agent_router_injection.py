"""End-to-end check that bitgn skill bodies are injected into the message
sequence when the router hits."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from bitgn_contest_agent.router import load_router


FIX = Path(__file__).parent / "fixtures" / "router_skills"


def test_router_decision_shape_for_known_task() -> None:
    r = load_router(skills_dir=FIX)
    decision = r.route("Please TEST-ROUTE this")
    assert decision.skill_name == "test-valid"


def test_skill_body_retrievable_by_name() -> None:
    r = load_router(skills_dir=FIX)
    body = r.skill_body_for("test-valid")
    assert body is not None
    assert "# Test Valid Skill" in body


def test_agent_loop_injects_skill_body_when_router_hits() -> None:
    """When router.route() returns a non-UNKNOWN decision, the agent
    loop prepends a user message with the skill body before the
    existing task_hints injection."""
    from bitgn_contest_agent.agent import _build_initial_messages

    r = load_router(skills_dir=FIX)
    task_text = "Please TEST-ROUTE this"
    messages = _build_initial_messages(task_text=task_text, router=r)
    # Expected message sequence:
    #   [0] system (system_prompt)
    #   [1] user   (task_text)
    #   [2] user   (skill body, prefixed with "SKILL CONTEXT ...")
    assert len(messages) == 3
    assert messages[0].role == "system"
    assert messages[1].role == "user"
    assert messages[1].content == task_text
    assert messages[2].role == "user"
    assert "SKILL CONTEXT" in messages[2].content
    assert "test-valid" in messages[2].content
    assert "# Test Valid Skill" in messages[2].content


def test_agent_loop_no_injection_on_unknown() -> None:
    from bitgn_contest_agent.agent import _build_initial_messages

    r = load_router(skills_dir=FIX)
    task_text = "Totally unrelated task"
    # Patch classifier to raise — router degrades to UNKNOWN.
    with patch(
        "bitgn_contest_agent.classifier.classify",
        side_effect=RuntimeError("network"),
    ):
        messages = _build_initial_messages(task_text=task_text, router=r)
    # Only system + task text; no skill injection.
    assert len(messages) == 2
    assert messages[0].role == "system"
    assert messages[1].content == task_text
