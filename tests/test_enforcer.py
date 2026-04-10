"""Enforcer sanity checks — R1 + R2 only (§2.4 minimum-confidence ruleset)."""
from __future__ import annotations

from bitgn_contest_agent.enforcer import Verdict, check_terminal
from bitgn_contest_agent.schemas import NextStep, ReportTaskCompletion
from bitgn_contest_agent.session import Session


def _mk_terminal(outcome: str, refs: list[str]) -> NextStep:
    return NextStep(
        current_state="done",
        plan_remaining_steps_brief=["report"],
        identity_verified=True,
        function=ReportTaskCompletion(
            tool="report_completion",
            message="all good",
            grounding_refs=refs,
            rulebook_notes="n",
            outcome_justification="j",
            completed_steps_laconic=["read AGENTS.md"],
            outcome=outcome,
        ),
    )


def test_non_terminal_always_passes() -> None:
    step = NextStep(
        current_state="reading",
        plan_remaining_steps_brief=["read", "report"],
        identity_verified=True,
        function={"tool": "read", "path": "AGENTS.md"},
    )
    v = check_terminal(Session(), step)
    assert v.ok
    assert v.reasons == []


def test_r1_fires_when_grounding_ref_not_in_seen_refs() -> None:
    session = Session()
    session.seen_refs.add("AGENTS.md")
    step = _mk_terminal("OUTCOME_OK", ["fabricated/path.py"])
    v = check_terminal(session, step)
    assert not v.ok
    assert any("grounding_ref" in r for r in v.reasons)


def test_r1_passes_when_all_grounding_refs_were_seen() -> None:
    session = Session()
    session.seen_refs.update({"AGENTS.md", "README.md"})
    step = _mk_terminal("OUTCOME_OK", ["AGENTS.md", "README.md"])
    v = check_terminal(session, step)
    assert v.ok, v.reasons


def test_r2_rejects_err_internal_outcome() -> None:
    session = Session()
    session.seen_refs.add("AGENTS.md")
    step = _mk_terminal("OUTCOME_ERR_INTERNAL", ["AGENTS.md"])
    v = check_terminal(session, step)
    assert not v.ok
    assert any("OUTCOME_ERR_INTERNAL" in r for r in v.reasons)


def test_r2_refusal_outcomes_still_pass() -> None:
    session = Session()
    # NONE_UNSUPPORTED is legitimate from task description alone — no refs required.
    step = _mk_terminal("OUTCOME_NONE_UNSUPPORTED", [])
    v = check_terminal(session, step)
    assert v.ok, v.reasons
