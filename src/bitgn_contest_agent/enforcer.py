"""Terminal emission enforcer — policy checks only.

Runs only on terminal emission (NextStep.function is ReportTaskCompletion).
Never a correctness oracle; only checks policy invariants that must hold
regardless of the task.

v1 ruleset (minimum-confidence):
- R1: grounding-refs reachability (principle, uncalibrated)
- R2: OUTCOME_ERR_INTERNAL hard-gate (data, 473-run corpus: 82 catches @ 100% precision)

All other candidate rules are deferred per §2.4.1.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from bitgn_contest_agent.schemas import NextStep, ReportTaskCompletion
from bitgn_contest_agent.session import Session


@dataclass(frozen=True, slots=True)
class Verdict:
    ok: bool
    reasons: List[str] = field(default_factory=list)


def check_terminal(session: Session, step: NextStep) -> Verdict:
    fn = step.function
    if not isinstance(fn, ReportTaskCompletion):
        return Verdict(ok=True, reasons=[])

    reasons: List[str] = []

    # R1 — grounding-refs reachability.
    # Known false-positive: path normalization ("./foo.py" vs "foo.py").
    # Canonicalize both sides the first time a real false positive shows up.
    for ref in fn.grounding_refs:
        if ref not in session.seen_refs:
            reasons.append(f"grounding_ref {ref!r} never successfully read")

    # R2 — OUTCOME_ERR_INTERNAL hard-gate.
    if fn.outcome == "OUTCOME_ERR_INTERNAL":
        reasons.append(
            "OUTCOME_ERR_INTERNAL rejected: 100% historical failure rate on 473-run corpus"
        )

    return Verdict(ok=not reasons, reasons=reasons)
