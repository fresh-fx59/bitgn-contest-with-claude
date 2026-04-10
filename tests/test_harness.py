"""Harness wrapper — translates the benchmark 3-step flow."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from bitgn_contest_agent.harness import BitgnHarness, StartedTask


def test_list_tasks_calls_get_benchmark_and_returns_task_ids() -> None:
    fake_client = MagicMock()
    fake_task = MagicMock()
    fake_task.task_id = "t1"
    fake_task.preview = "do stuff"
    fake_client.get_benchmark.return_value = MagicMock(tasks=[fake_task])

    h = BitgnHarness(
        harness_client=fake_client,
        runtime_client_factory=MagicMock(),
        benchmark="bitgn/pac1-dev",
    )
    task_ids = h.list_task_ids()
    assert task_ids == ["t1"]
    call = fake_client.get_benchmark.call_args.args[0]
    assert call.benchmark_id == "bitgn/pac1-dev"


def test_start_task_calls_start_playground_and_builds_runtime_client() -> None:
    fake_client = MagicMock()
    playground = MagicMock()
    playground.trial_id = "trial-xyz"
    playground.task_id = "t1"
    playground.benchmark_id = "bitgn/pac1-dev"
    playground.instruction = "solve it"
    playground.harness_url = "https://vm.bitgn/t1"
    fake_client.start_playground.return_value = playground

    runtime_factory = MagicMock()
    runtime_factory.return_value = MagicMock(name="runtime")

    h = BitgnHarness(
        harness_client=fake_client,
        runtime_client_factory=runtime_factory,
        benchmark="bitgn/pac1-dev",
    )
    started = h.start_task("t1")
    assert isinstance(started, StartedTask)
    assert started.trial_id == "trial-xyz"
    assert started.instruction == "solve it"
    runtime_factory.assert_called_once_with(playground.harness_url)


def test_end_task_calls_end_trial_and_returns_score() -> None:
    fake_client = MagicMock()
    fake_client.end_trial.return_value = MagicMock(score=0.75, score_detail=[])
    h = BitgnHarness(
        harness_client=fake_client,
        runtime_client_factory=MagicMock(),
        benchmark="bitgn/pac1-dev",
    )
    started = StartedTask(
        trial_id="trial-xyz",
        task_id="t1",
        benchmark_id="bitgn/pac1-dev",
        instruction="...",
        harness_url="...",
        runtime_client=MagicMock(),
    )
    score, detail = h.end_task(started)
    assert score == 0.75
    assert detail == []
    call = fake_client.end_trial.call_args.args[0]
    assert call.trial_id == "trial-xyz"
