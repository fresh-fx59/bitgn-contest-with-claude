"""CLI argument parsing — no live API calls."""
from __future__ import annotations

import pytest

from bitgn_contest_agent.cli import build_parser


def test_parser_run_task_requires_task_id() -> None:
    parser = build_parser()
    ns = parser.parse_args(["run-task", "--task-id", "t14"])
    assert ns.command == "run-task"
    assert ns.task_id == "t14"


def test_parser_run_benchmark_defaults() -> None:
    parser = build_parser()
    ns = parser.parse_args(["run-benchmark"])
    assert ns.command == "run-benchmark"
    assert ns.runs == 1
    assert ns.max_parallel is None  # falls through to config default


def test_parser_run_benchmark_accepts_output_path() -> None:
    parser = build_parser()
    ns = parser.parse_args(
        ["run-benchmark", "--runs", "3", "--output", "artifacts/bench/out.json"]
    )
    assert ns.runs == 3
    assert ns.output == "artifacts/bench/out.json"


def test_parser_rejects_unknown_command() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["run-quarantine"])
