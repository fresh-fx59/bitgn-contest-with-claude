"""Orchestrator: thread pool + cooperative cancel + per-task deadline."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from unittest.mock import MagicMock

import pytest

from bitgn_contest_agent.orchestrator import (
    Orchestrator,
    TaskSpec,
    TaskExecutionResult,
)


@dataclass
class _FakeTrial:
    task_id: str
    instruction: str


def _mk_runner(returns: TaskExecutionResult, *, sleep_s: float = 0.0) -> Callable:
    def runner(task: TaskSpec, cancel_event: threading.Event) -> TaskExecutionResult:
        if sleep_s:
            deadline = time.monotonic() + sleep_s
            while time.monotonic() < deadline:
                if cancel_event.is_set():
                    return TaskExecutionResult(
                        task_id=task.task_id,
                        score=0.0,
                        terminated_by="cancel",
                        error_kind="CANCELLED",
                        error_msg=None,
                    )
                time.sleep(0.01)
        return returns
    return runner


def test_orchestrator_runs_all_tasks_and_returns_results() -> None:
    tasks = [
        TaskSpec(task_id=f"t{i}", task_index=i, task_text=f"task {i}")
        for i in range(4)
    ]
    runner = _mk_runner(
        TaskExecutionResult(task_id="", score=1.0, terminated_by="report_completion", error_kind=None, error_msg=None)
    )
    orch = Orchestrator(runner=runner, max_parallel_tasks=2, task_timeout_sec=0)
    results = orch.run(tasks)
    assert len(results) == 4
    assert all(r.terminated_by == "report_completion" for r in results)


def test_orchestrator_cancels_long_running_task_after_deadline() -> None:
    tasks = [TaskSpec(task_id="slow", task_index=0, task_text="...")]
    runner = _mk_runner(
        TaskExecutionResult(task_id="slow", score=1.0, terminated_by="report_completion", error_kind=None, error_msg=None),
        sleep_s=2.0,
    )
    orch = Orchestrator(
        runner=runner,
        max_parallel_tasks=1,
        task_timeout_sec=1,      # 1s deadline
        task_timeout_grace_sec=1,
    )
    t0 = time.monotonic()
    results = orch.run(tasks)
    elapsed = time.monotonic() - t0
    assert len(results) == 1
    assert results[0].terminated_by == "cancel"
    assert elapsed < 2.5  # cancel fired before natural completion


def test_orchestrator_isolation_one_failure_does_not_abort_others() -> None:
    tasks = [
        TaskSpec(task_id="good", task_index=0, task_text="..."),
        TaskSpec(task_id="bad", task_index=1, task_text="..."),
    ]
    def runner(task, cancel_event):
        if task.task_id == "bad":
            raise RuntimeError("synthetic boom")
        return TaskExecutionResult(
            task_id=task.task_id, score=1.0,
            terminated_by="report_completion", error_kind=None, error_msg=None,
        )
    orch = Orchestrator(runner=runner, max_parallel_tasks=2, task_timeout_sec=0)
    results = orch.run(tasks)
    assert len(results) == 2
    by_id = {r.task_id: r for r in results}
    assert by_id["good"].terminated_by == "report_completion"
    assert by_id["bad"].terminated_by == "error"
    assert by_id["bad"].error_kind == "INTERNAL_CRASH"
