"""Unit tests for resume.plan_resume / finalize_resume.

The fake harness mimics the subset of BitgnHarness used by resume.py:
- get_run(run_id)   -> GetRunResponse-shaped object
- get_trial(tid)    -> GetTrialResponse-shaped object
- submit_run(run_id, *, force) -> state string
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

import pytest

from bitgn.harness_pb2 import (
    TRIAL_STATE_NEW,
    TRIAL_STATE_RUNNING,
    TRIAL_STATE_DONE,
    TRIAL_STATE_ERROR,
)

from bitgn_contest_agent.resume import (
    ResumePlan,
    ResumedTrial,
    plan_resume,
    finalize_resume,
)


@dataclass
class _FakeTrialHead:
    trial_id: str
    task_id: str
    state: int
    score: float = 0.0
    error: str = ""


@dataclass
class _FakeGetRunResponse:
    run_id: str
    benchmark_id: str
    trials: List[_FakeTrialHead] = field(default_factory=list)


@dataclass
class _FakeGetTrialResponse:
    trial_id: str
    task_id: str = ""
    instruction: str = ""


class _FakeHarness:
    def __init__(self, run_resp: _FakeGetRunResponse, trials: dict | None = None):
        self._run_resp = run_resp
        self._trials = trials or {}
        self.submit_calls: list[tuple[str, bool]] = []

    def get_run(self, run_id: str):
        assert run_id == self._run_resp.run_id
        return self._run_resp

    def get_trial(self, trial_id: str):
        return self._trials[trial_id]

    def submit_run(self, run_id: str, *, force: bool = False) -> str:
        self.submit_calls.append((run_id, force))
        return "RUN_STATE_EVALUATED"


def test_plan_resume_buckets_new_done_error():
    h = _FakeHarness(_FakeGetRunResponse(
        run_id="run-abc",
        benchmark_id="bitgn/pac1-prod",
        trials=[
            _FakeTrialHead("t-new-1",  "task-1", TRIAL_STATE_NEW),
            _FakeTrialHead("t-new-2",  "task-2", TRIAL_STATE_NEW),
            _FakeTrialHead("t-done-1", "task-3", TRIAL_STATE_DONE,  score=1.0),
            _FakeTrialHead("t-err-1",  "task-4", TRIAL_STATE_ERROR, error="boom"),
        ],
    ))

    plan = plan_resume(h, "run-abc")

    assert plan.run_id == "run-abc"
    assert plan.benchmark_id == "bitgn/pac1-prod"
    assert plan.done_count == 1
    assert plan.error_count == 1
    assert [t.trial_id for t in plan.pending] == ["t-new-1", "t-new-2"]
    assert [t.task_id for t in plan.pending] == ["task-1", "task-2"]
    assert all(t.instruction == "" for t in plan.pending)
    assert plan.stuck == []
