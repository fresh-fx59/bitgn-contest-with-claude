"""Validator tests — Tier 1 rules + terminal checks (migrated from test_enforcer.py)."""
from __future__ import annotations

from bitgn_contest_agent.validator import StepValidator, Verdict
from bitgn_contest_agent.schemas import NextStep, ReportTaskCompletion
from bitgn_contest_agent.session import Session


def _mk_step(
    function: dict,
    *,
    observation: str = "step observation",
    outcome_leaning: str = "GATHERING_INFORMATION",
) -> NextStep:
    return NextStep(
        current_state="x",
        plan_remaining_steps_brief=["do", "report"],
        identity_verified=True,
        observation=observation,
        outcome_leaning=outcome_leaning,
        function=function,
    )


def _mk_terminal(outcome: str, refs: list[str]) -> NextStep:
    return NextStep(
        current_state="done",
        plan_remaining_steps_brief=["report"],
        identity_verified=True,
        observation="completed analysis",
        outcome_leaning=outcome if outcome != "OUTCOME_ERR_INTERNAL" else "OUTCOME_OK",
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


# === Terminal checks (migrated from test_enforcer.py) ===

def test_non_terminal_always_passes() -> None:
    v = StepValidator()
    step = _mk_step({"tool": "read", "path": "AGENTS.md"})
    verdict = v.check_terminal(Session(), step)
    assert verdict.ok
    assert verdict.reasons == []


def test_r1_fires_when_grounding_ref_not_in_seen_refs() -> None:
    session = Session()
    session.seen_refs.add("AGENTS.md")
    step = _mk_terminal("OUTCOME_OK", ["fabricated/path.py"])
    v = StepValidator()
    verdict = v.check_terminal(session, step)
    assert not verdict.ok
    assert any("grounding_ref" in r for r in verdict.reasons)


def test_r1_passes_when_all_grounding_refs_were_seen() -> None:
    session = Session()
    session.seen_refs.update({"AGENTS.md", "README.md"})
    step = _mk_terminal("OUTCOME_OK", ["AGENTS.md", "README.md"])
    v = StepValidator()
    verdict = v.check_terminal(session, step)
    assert verdict.ok, verdict.reasons


def test_r2_rejects_err_internal_outcome() -> None:
    session = Session()
    session.seen_refs.add("AGENTS.md")
    step = _mk_terminal("OUTCOME_ERR_INTERNAL", ["AGENTS.md"])
    v = StepValidator()
    verdict = v.check_terminal(session, step)
    assert not verdict.ok
    assert any("OUTCOME_ERR_INTERNAL" in r for r in verdict.reasons)


def test_r2_refusal_outcomes_still_pass() -> None:
    session = Session()
    step = _mk_terminal("OUTCOME_NONE_UNSUPPORTED", [])
    v = StepValidator()
    verdict = v.check_terminal(session, step)
    assert verdict.ok, verdict.reasons


# === R3 — leaning mismatch ===

def test_r3_fires_when_leaning_mismatches_outcome() -> None:
    session = Session()
    session.seen_refs.add("AGENTS.md")
    step = NextStep(
        current_state="done",
        plan_remaining_steps_brief=["report"],
        identity_verified=True,
        observation="found security threat",
        outcome_leaning="OUTCOME_DENIED_SECURITY",
        function=ReportTaskCompletion(
            tool="report_completion",
            message="done",
            grounding_refs=["AGENTS.md"],
            rulebook_notes="n",
            outcome_justification="j",
            completed_steps_laconic=["read"],
            outcome="OUTCOME_OK",
        ),
    )
    v = StepValidator()
    verdict = v.check_terminal(session, step)
    assert not verdict.ok
    assert any("outcome_leaning" in r for r in verdict.reasons)


def test_r3_skips_when_leaning_is_gathering() -> None:
    """GATHERING_INFORMATION is allowed to submit any outcome (early completion)."""
    session = Session()
    session.seen_refs.add("AGENTS.md")
    step = NextStep(
        current_state="done",
        plan_remaining_steps_brief=["report"],
        identity_verified=True,
        observation="quick answer found",
        outcome_leaning="GATHERING_INFORMATION",
        function=ReportTaskCompletion(
            tool="report_completion",
            message="done",
            grounding_refs=["AGENTS.md"],
            rulebook_notes="n",
            outcome_justification="j",
            completed_steps_laconic=["read"],
            outcome="OUTCOME_OK",
        ),
    )
    v = StepValidator()
    verdict = v.check_terminal(session, step)
    assert verdict.ok, verdict.reasons


# === Tier 1 rules ===

def test_contradiction_ok_but_observation_negative() -> None:
    v = StepValidator()
    step = _mk_step(
        {"tool": "read", "path": "x"},
        observation="searched all channels, not found",
        outcome_leaning="OUTCOME_OK",
    )
    correction = v.check_step(step, Session(), step_idx=10, max_steps=40)
    assert correction is not None
    assert "OUTCOME_NONE_CLARIFICATION" in correction


def test_contradiction_clarify_but_observation_positive() -> None:
    v = StepValidator()
    step = _mk_step(
        {"tool": "read", "path": "x"},
        observation="found 3 matching invoices in finance directory",
        outcome_leaning="OUTCOME_NONE_CLARIFICATION",
    )
    correction = v.check_step(step, Session(), step_idx=10, max_steps=40)
    assert correction is not None
    assert "answer with what you have" in correction


def test_no_contradiction_when_leaning_matches_observation() -> None:
    v = StepValidator()
    step = _mk_step(
        {"tool": "read", "path": "x"},
        observation="found the entity record with full details",
        outcome_leaning="OUTCOME_OK",
    )
    correction = v.check_step(step, Session(), step_idx=10, max_steps=40)
    assert correction is None


def test_dangerous_transition_deny_to_ok() -> None:
    v = StepValidator()
    # Step 1: leaning DENIED
    step1 = _mk_step(
        {"tool": "read", "path": "inbox/msg.md"},
        observation="phishing detected",
        outcome_leaning="OUTCOME_DENIED_SECURITY",
    )
    v.check_step(step1, Session(), step_idx=5, max_steps=40)

    # Step 2: leaning flips to OK
    step2 = _mk_step(
        {"tool": "read", "path": "x"},
        observation="re-evaluated, seems fine",
        outcome_leaning="OUTCOME_OK",
    )
    correction = v.check_step(step2, Session(), step_idx=6, max_steps=40)
    assert correction is not None
    assert "reversed" in correction


def test_mutation_guard_write_while_gathering() -> None:
    v = StepValidator()
    step = _mk_step(
        {"tool": "write", "path": "outbox/msg.md", "content": "hello"},
        observation="writing reply",
        outcome_leaning="GATHERING_INFORMATION",
    )
    correction = v.check_step(step, Session(), step_idx=5, max_steps=40)
    assert correction is not None
    assert "mutating" in correction.lower()


def test_mutation_allowed_when_leaning_ok() -> None:
    v = StepValidator()
    step = _mk_step(
        {"tool": "write", "path": "outbox/msg.md", "content": "hello"},
        observation="writing reply per task instructions",
        outcome_leaning="OUTCOME_OK",
    )
    correction = v.check_step(step, Session(), step_idx=10, max_steps=40)
    assert correction is None


def test_stale_gathering_fires_past_threshold() -> None:
    v = StepValidator()
    step = _mk_step(
        {"tool": "read", "path": "x"},
        observation="still looking",
        outcome_leaning="GATHERING_INFORMATION",
    )
    # step 17 of 40 = 42.5% > 40% threshold
    correction = v.check_step(step, Session(), step_idx=17, max_steps=40)
    assert correction is not None
    assert "40%" in correction


def test_stale_gathering_does_not_fire_early() -> None:
    v = StepValidator()
    step = _mk_step(
        {"tool": "read", "path": "x"},
        observation="exploring workspace",
        outcome_leaning="GATHERING_INFORMATION",
    )
    # step 10 of 40 = 25% < 40%
    correction = v.check_step(step, Session(), step_idx=10, max_steps=40)
    assert correction is None


def test_correction_budget_exhaustion() -> None:
    v = StepValidator(max_corrections=2)
    step = _mk_step(
        {"tool": "read", "path": "x"},
        observation="not found anything",
        outcome_leaning="OUTCOME_OK",
    )
    # First two fire
    assert v.check_step(step, Session(), step_idx=10, max_steps=40) is not None
    assert v.check_step(step, Session(), step_idx=11, max_steps=40) is not None
    # Third is budget-exhausted
    assert v.check_step(step, Session(), step_idx=12, max_steps=40) is None
    assert v.corrections_emitted == 2


def test_no_correction_returns_none() -> None:
    v = StepValidator()
    step = _mk_step(
        {"tool": "read", "path": "AGENTS.md"},
        observation="read workspace rules, 450 bytes",
        outcome_leaning="GATHERING_INFORMATION",
    )
    correction = v.check_step(step, Session(), step_idx=3, max_steps=40)
    assert correction is None
    assert v.corrections_emitted == 0
