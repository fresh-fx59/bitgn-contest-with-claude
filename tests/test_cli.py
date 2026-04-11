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


def _make_v1_1_summary_with_failures(failures: dict[str, str]) -> str:
    """Produce a minimal v1.1 bench_summary JSON string where each task_id
    in `failures` is crafted to classify_failure() into the named cluster.

    Clusters supported:
      - "inbox"        — step_texts includes "/inbox/"
      - "wrong_action" — OUTCOME_OK + step_texts mentions "instead of"
      - "false_refusal"— OUTCOME_DENIED_SECURITY, category="other"
      - "timeout"      — timed_out=True
      - "calendar"     — grader_failed + category="calendar"
      - "other"        — fallback, benign text
    """
    import json as _json

    cluster_to_task: dict[str, dict] = {
        "inbox": {
            "step_texts": ["forgot to check /inbox/identity.md"],
            "last_outcome": "OUTCOME_OK",
            "last_latency_ms": 2000,
            "timed_out": False,
            "category": "other",
        },
        "wrong_action": {
            "step_texts": ["writing email draft instead of the scheduler call"],
            "last_outcome": "OUTCOME_OK",
            "last_latency_ms": 2000,
            "timed_out": False,
            "category": "other",
        },
        "false_refusal": {
            "step_texts": ["refusing for safety"],
            "last_outcome": "OUTCOME_DENIED_SECURITY",
            "last_latency_ms": 500,
            "timed_out": False,
            "category": "other",
        },
        "timeout": {
            "step_texts": [],
            "last_outcome": "OUTCOME_ERR_INTERNAL",
            "last_latency_ms": 240_000,
            "timed_out": True,
            "category": "other",
        },
        "calendar": {
            "step_texts": ["scheduling the meeting"],
            "last_outcome": "OUTCOME_OK",
            "last_latency_ms": 2000,
            "timed_out": False,
            "category": "calendar",
        },
        "other": {
            "step_texts": ["random benign reasoning"],
            "last_outcome": "OUTCOME_OK",
            "last_latency_ms": 2000,
            "timed_out": False,
            "category": "other",
        },
    }

    tasks: dict[str, dict] = {}
    for tid, cluster in failures.items():
        t = {
            "runs": 1,
            "passes": 0,  # failure → passes < runs
            "median_steps": 1,
            "passes_per_run": [0],
            "input_tokens": 0,
            "output_tokens": 0,
            "reasoning_tokens": 0,
            "harness_url": "",
            "divergence_steps": [],
        }
        t.update(cluster_to_task[cluster])
        tasks[tid] = t

    summary = {
        "schema_version": "1.1.0",
        "overall": {
            "total_runs": len(tasks),
            "total_passes": 0,
            "pass_rate": 0.0,
            "runs_per_task": 1,
            "pass_rate_median": 0.0,
            "pass_rate_min": 0.0,
            "pass_rate_ci_lower": 0.0,
            "pass_rate_ci_upper": 0.0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_reasoning_tokens": 0,
            "trace_dir": "",
            "divergence_count": 0,
        },
        "tasks": tasks,
    }
    return _json.dumps(summary)


def test_triage_cli_single_summary(tmp_path, capsys):
    """triage <summary.json> prints cluster -> list of task_ids."""
    summary = tmp_path / "s.json"
    summary.write_text(_make_v1_1_summary_with_failures({
        "t02": "inbox", "t08": "false_refusal", "t30": "timeout",
    }))
    from bitgn_contest_agent.cli import main
    rc = main(["triage", str(summary)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "inbox" in out and "t02" in out
    assert "timeout" in out and "t30" in out


def test_triage_cli_diff_mode(tmp_path, capsys):
    """triage --before A.json --after B.json prints +/- changes per cluster."""
    before = tmp_path / "a.json"
    before.write_text(_make_v1_1_summary_with_failures({"t02": "inbox", "t08": "false_refusal"}))
    after = tmp_path / "b.json"
    after.write_text(_make_v1_1_summary_with_failures({"t08": "false_refusal", "t30": "timeout"}))
    from bitgn_contest_agent.cli import main
    rc = main(["triage", "--before", str(before), "--after", str(after)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "-t02" in out  # inbox cleared
    assert "+t30" in out  # timeout added


def test_smoke_tasks_are_fixed():
    from bitgn_contest_agent.bench.smoke import (
        SMOKE_TASKS,
        SMOKE_CEILING_SEC,
        SMOKE_MAX_PARALLEL,
        SMOKE_MAX_INFLIGHT_LLM,
    )
    assert SMOKE_TASKS == ["t02", "t42", "t41", "t15", "t43"]
    assert SMOKE_CEILING_SEC == 180
    assert SMOKE_MAX_PARALLEL == 5
    assert SMOKE_MAX_INFLIGHT_LLM == 8


def test_smoke_flag_forces_parameters(monkeypatch, tmp_path):
    """--smoke must override --max-parallel and --max-inflight-llm and
    force the hardcoded SMOKE_TASKS list."""
    # load_from_env requires these three env vars
    monkeypatch.setenv("BITGN_API_KEY", "fake")
    monkeypatch.setenv("CLIPROXY_BASE_URL", "http://fake")
    monkeypatch.setenv("CLIPROXY_API_KEY", "fake")

    captured: dict = {}

    def fake_runner(cfg, tasks, **kw):
        captured["cfg"] = cfg
        captured["tasks"] = tasks
        captured["kw"] = kw
        return []  # empty results; no summarize() path

    monkeypatch.setattr(
        "bitgn_contest_agent.cli._run_tasks_and_summarize", fake_runner
    )

    from bitgn_contest_agent.cli import main

    out_path = tmp_path / "x.json"
    rc = main([
        "run-benchmark",
        "--benchmark", "bitgn/pac1-dev",
        "--smoke",
        "--max-parallel", "99",
        "--max-inflight-llm", "99",
        "--output", str(out_path),
    ])
    # Fake returned empty → 0/0 pass rate → rc == 0
    assert rc == 0

    from bitgn_contest_agent.bench.smoke import (
        SMOKE_TASKS,
        SMOKE_MAX_PARALLEL,
        SMOKE_MAX_INFLIGHT_LLM,
    )
    # --smoke must override the CLI --max-parallel=99 / --max-inflight-llm=99
    assert captured["cfg"].max_parallel_tasks == SMOKE_MAX_PARALLEL
    assert captured["cfg"].max_inflight_llm == SMOKE_MAX_INFLIGHT_LLM
    # --smoke must force the task list to SMOKE_TASKS (TaskSpec objects ordered)
    # tasks is list[TaskSpec] — compare the task_id sequence
    assert [t.task_id for t in captured["tasks"]] == SMOKE_TASKS
