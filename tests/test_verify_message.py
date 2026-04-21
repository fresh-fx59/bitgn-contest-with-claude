from bitgn_contest_agent.verify import (
    VerifyReason, WriteOp, build_verification_message,
)
from bitgn_contest_agent.schemas import NextStep, ReportTaskCompletion


def _completion(message: str, refs=None) -> NextStep:
    return NextStep(
        current_state="done",
        plan_remaining_steps_brief=["submit"],
        identity_verified=True,
        observation="ready",
        outcome_leaning="OUTCOME_OK",
        function=ReportTaskCompletion(
            tool="report_completion",
            message=message,
            grounding_refs=list(refs or []),
            rulebook_notes="n/a",
            outcome_justification="n/a",
            completed_steps_laconic=["done"],
            outcome="OUTCOME_OK",
        ),
    )


def test_message_has_missing_ref_section_with_gap_list():
    msg = build_verification_message(
        reasons=[VerifyReason.MISSING_REF],
        next_step=_completion(
            "cites 40_projects/hearthline/README.md",
            refs=["40_projects/hearthline/README.md"],
        ),
        read_cache={"00_inbox/foo.md": "x"},
        write_history=[],
        task_text="when did it start?",
    )
    assert "MISSING_REF" in msg
    assert "40_projects/hearthline/README.md" in msg
    assert "Before submitting" in msg or "Before the answer is accepted" in msg


def test_message_has_numeric_multiref_section_with_candidate_paths():
    msg = build_verification_message(
        reasons=[VerifyReason.NUMERIC_MULTIREF],
        next_step=_completion("12"),
        read_cache={
            "50_finance/purchases/bill_a.md": "amount: 6",
            "50_finance/purchases/bill_b.md": "amount: 6",
        },
        write_history=[],
        task_text="Number only.",
    )
    assert "NUMERIC_MULTIREF" in msg
    assert "50_finance/purchases/bill_a.md" in msg
    assert "50_finance/purchases/bill_b.md" in msg


def test_message_combines_multiple_reasons_in_one_message():
    msg = build_verification_message(
        reasons=[VerifyReason.MISSING_REF, VerifyReason.NUMERIC_MULTIREF],
        next_step=_completion(
            "12 (ref 40_projects/hearthline/README.md)",
            refs=["40_projects/hearthline/README.md"],
        ),
        read_cache={
            "50_finance/purchases/bill_a.md": "amount: 6",
            "50_finance/purchases/bill_b.md": "amount: 6",
        },
        write_history=[],
        task_text="Number only.",
    )
    # Both sections present, each with its own heading.
    assert msg.count("## ") >= 2
    assert "MISSING_REF" in msg and "NUMERIC_MULTIREF" in msg
