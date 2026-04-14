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


def test_stale_gathering_disabled() -> None:
    """Stale gathering rule was disabled — Tier 2 progress check at 60%
    covers this with LLM judgment instead of a dumb threshold."""
    v = StepValidator()
    step = _mk_step(
        {"tool": "read", "path": "x"},
        observation="still looking",
        outcome_leaning="GATHERING_INFORMATION",
    )
    # Even past 40% threshold, no correction fires
    correction = v.check_step(step, Session(), step_idx=17, max_steps=40)
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


# === Tier 2 trigger structure tests ===

def test_trigger_first_transition_fires_once(monkeypatch) -> None:
    """First transition from GATHERING fires at most once."""
    import bitgn_contest_agent.classifier as cls_mod

    calls = []
    def fake_classify(*, system, user):
        calls.append(1)
        return {"category": "PREMATURE", "confidence": 0.8}

    monkeypatch.setattr(cls_mod, "classify", fake_classify)

    v = StepValidator()
    # Step 1: still gathering
    s1 = _mk_step({"tool": "read", "path": "x"}, observation="exploring", outcome_leaning="GATHERING_INFORMATION")
    v.check_step(s1, Session(), step_idx=3, max_steps=40)

    # Step 2: transitions to OK — should trigger
    s2 = _mk_step({"tool": "read", "path": "x"}, observation="found it", outcome_leaning="OUTCOME_OK")
    corr = v.check_step(s2, Session(), step_idx=4, max_steps=40)
    assert corr is not None
    assert "committed" in corr.lower()
    assert len(calls) == 1

    # Step 3: another transition — should NOT trigger again
    s3 = _mk_step({"tool": "read", "path": "x"}, observation="re-exploring", outcome_leaning="GATHERING_INFORMATION")
    v.check_step(s3, Session(), step_idx=5, max_steps=40)
    s4 = _mk_step({"tool": "read", "path": "x"}, observation="found again", outcome_leaning="OUTCOME_OK")
    v.check_step(s4, Session(), step_idx=6, max_steps=40)
    assert len(calls) == 1  # no second call


def test_trigger_classifier_failure_is_swallowed(monkeypatch) -> None:
    """Classifier errors don't crash the validator."""
    import bitgn_contest_agent.classifier as cls_mod

    def fail_classify(*, system, user):
        raise RuntimeError("classifier down")

    monkeypatch.setattr(cls_mod, "classify", fail_classify)

    v = StepValidator()
    s1 = _mk_step({"tool": "read", "path": "x"}, observation="exploring", outcome_leaning="GATHERING_INFORMATION")
    v.check_step(s1, Session(), step_idx=3, max_steps=40)
    s2 = _mk_step({"tool": "read", "path": "x"}, observation="found", outcome_leaning="OUTCOME_OK")
    corr = v.check_step(s2, Session(), step_idx=4, max_steps=40)
    assert corr is None  # error swallowed, no correction


def test_observation_window_limited_to_5() -> None:
    """Observations window stays at most 5 entries."""
    v = StepValidator()
    for i in range(10):
        step = _mk_step(
            {"tool": "read", "path": "x"},
            observation=f"obs {i}",
            outcome_leaning="GATHERING_INFORMATION",
        )
        v.check_step(step, Session(), step_idx=i + 1, max_steps=40)
    assert len(v._observations) == 5
    assert v._observations[0] == "obs 5"


def test_r4_mutation_mismatch_rejects(monkeypatch) -> None:
    """R4: agent claims 2 deletes but session only has 1 → reject."""
    import bitgn_contest_agent.classifier as cls_mod

    def fake_classify(*, system, user):
        return {"category": "MISMATCH", "confidence": 0.9}

    monkeypatch.setattr(cls_mod, "classify", fake_classify)

    session = Session()
    session.seen_refs.add("AGENTS.md")
    session.seen_refs.add("50_finance/receipt_a.md")
    session.mutations.append(("delete", "50_finance/receipt_a.md"))

    step = NextStep(
        current_state="done",
        plan_remaining_steps_brief=["report"],
        identity_verified=True,
        observation="deleted both receipts",
        outcome_leaning="OUTCOME_OK",
        function=ReportTaskCompletion(
            tool="report_completion",
            message="deleted both",
            grounding_refs=["AGENTS.md", "50_finance/receipt_a.md"],
            rulebook_notes="n",
            outcome_justification="deleted receipt_a and receipt_b",
            completed_steps_laconic=[
                "read receipt_a", "delete receipt_a",
                "read receipt_b", "delete receipt_b",
            ],
            outcome="OUTCOME_OK",
        ),
    )
    v = StepValidator()
    verdict = v.check_terminal(session, step)
    assert not verdict.ok
    assert any("mutation" in r.lower() for r in verdict.reasons)


def test_r4_skipped_when_no_mutations_claimed(monkeypatch) -> None:
    """R4 should not fire when there are no mutations at all."""
    import bitgn_contest_agent.classifier as cls_mod

    calls = []
    def fake_classify(*, system, user):
        calls.append(1)
        return {"category": "CONSISTENT", "confidence": 0.9}

    monkeypatch.setattr(cls_mod, "classify", fake_classify)

    session = Session()
    session.seen_refs.add("AGENTS.md")

    step = _mk_terminal("OUTCOME_OK", ["AGENTS.md"])
    v = StepValidator()
    verdict = v.check_terminal(session, step)
    assert verdict.ok
    assert len(calls) == 0  # no LLM call — no mutations to check


def test_r4_passes_when_mutations_consistent(monkeypatch) -> None:
    """R4 accepts when claimed steps match actual mutations."""
    import bitgn_contest_agent.classifier as cls_mod

    def fake_classify(*, system, user):
        return {"category": "CONSISTENT", "confidence": 0.9}

    monkeypatch.setattr(cls_mod, "classify", fake_classify)

    session = Session()
    session.seen_refs.add("AGENTS.md")
    session.mutations.append(("delete", "50_finance/receipt.md"))

    step = NextStep(
        current_state="done",
        plan_remaining_steps_brief=["report"],
        identity_verified=True,
        observation="deleted receipt",
        outcome_leaning="OUTCOME_OK",
        function=ReportTaskCompletion(
            tool="report_completion",
            message="deleted receipt",
            grounding_refs=["AGENTS.md"],
            rulebook_notes="n",
            outcome_justification="deleted the receipt",
            completed_steps_laconic=["read receipt", "delete receipt"],
            outcome="OUTCOME_OK",
        ),
    )
    v = StepValidator()
    verdict = v.check_terminal(session, step)
    assert verdict.ok
