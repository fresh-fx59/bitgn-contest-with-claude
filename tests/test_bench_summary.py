"""bench_summary frozen-schema aggregator test."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.bench_summary import FROZEN_SCHEMA_KEYS, summarize


def _write_trace(path: Path, *, task_id: str, outcome: str, score: float, steps: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(
            {
                "kind": "meta",
                "agent_version": "0.0.7",
                "agent_commit": "x",
                "model": "gpt-5.3-codex",
                "backend": "openai_compat",
                "reasoning_effort": "medium",
                "benchmark": "bitgn/pac1-dev",
                "task_id": task_id,
                "task_index": 0,
                "started_at": "2026-04-10T00:00:00Z",
                "trace_schema_version": "1.0.0",
            }
        ),
        json.dumps({"kind": "task", "task_id": task_id, "task_text": "x"}),
        json.dumps(
            {
                "kind": "outcome",
                "terminated_by": "report_completion",
                "reported": outcome,
                "enforcer_bypassed": False,
                "error_kind": None,
                "total_steps": steps,
                "total_llm_calls": steps,
                "total_prompt_tokens": 100,
                "total_completion_tokens": 10,
                "total_cached_tokens": 0,
                "score": score,
            }
        ),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_summarize_reports_pass_rate_and_frozen_keys(tmp_path: Path) -> None:
    _write_trace(tmp_path / "t1__run0.jsonl", task_id="t1", outcome="OUTCOME_OK", score=1.0, steps=5)
    _write_trace(tmp_path / "t1__run1.jsonl", task_id="t1", outcome="OUTCOME_OK", score=1.0, steps=6)
    _write_trace(tmp_path / "t2__run0.jsonl", task_id="t2", outcome="OUTCOME_NONE_CLARIFICATION", score=0.0, steps=3)
    _write_trace(tmp_path / "t2__run1.jsonl", task_id="t2", outcome="OUTCOME_NONE_CLARIFICATION", score=0.0, steps=4)

    summary = summarize(logs_dir=tmp_path)
    assert set(summary.keys()) == set(FROZEN_SCHEMA_KEYS)
    assert summary["tasks"]["t1"]["runs"] == 2
    assert summary["tasks"]["t1"]["passes"] == 2
    assert summary["tasks"]["t1"]["median_steps"] in (5, 6)
    assert summary["tasks"]["t2"]["passes"] == 0
    assert summary["overall"]["pass_rate"] == pytest.approx(0.5)
    assert summary["overall"]["total_runs"] == 4


def test_summarize_is_stable_across_runs(tmp_path: Path) -> None:
    _write_trace(tmp_path / "t1__run0.jsonl", task_id="t1", outcome="OUTCOME_OK", score=1.0, steps=5)
    a = summarize(logs_dir=tmp_path)
    b = summarize(logs_dir=tmp_path)
    assert a == b


import pytest  # bottom import so tests above can use pytest.approx


def test_schema_version_is_1_1_0():
    from scripts.bench_summary import BENCH_SUMMARY_SCHEMA_VERSION
    assert BENCH_SUMMARY_SCHEMA_VERSION == "1.1.0"


def test_summarize_emits_v1_1_additive_fields(tmp_path: Path) -> None:
    """summarize() must emit all v1.1 additive fields in overall and per-task."""
    _write_trace(tmp_path / "t1__run0.jsonl", task_id="t1", outcome="OUTCOME_OK", score=1.0, steps=5)

    out = summarize(logs_dir=tmp_path)

    # schema version
    assert out["schema_version"] == "1.1.0"

    # overall v1.1 additive fields
    overall = out["overall"]
    for key in (
        "runs_per_task",
        "pass_rate_median",
        "pass_rate_min",
        "pass_rate_ci_lower",
        "pass_rate_ci_upper",
        "total_input_tokens",
        "total_output_tokens",
        "total_reasoning_tokens",
        "trace_dir",
        "divergence_count",
    ):
        assert key in overall, f"missing overall key: {key}"

    assert overall["total_input_tokens"] == 100
    assert overall["total_output_tokens"] == 10
    assert overall["total_reasoning_tokens"] == 0
    assert overall["divergence_count"] == 0
    assert overall["runs_per_task"] == 1

    # per-task v1.1 additive fields
    t1 = out["tasks"]["t1"]
    for key in ("passes_per_run", "input_tokens", "output_tokens", "reasoning_tokens", "harness_url", "divergence_steps"):
        assert key in t1, f"missing per-task key: {key}"

    assert t1["input_tokens"] == 100
    assert t1["output_tokens"] == 10
    assert t1["reasoning_tokens"] == 0
    assert t1["harness_url"] == ""
    assert t1["divergence_steps"] == []
    assert t1["passes_per_run"] == [1]


def test_summarize_populates_divergence_count_and_steps(tmp_path: Path) -> None:
    """bench_summary.summarize should populate overall.divergence_count and
    per-task divergence_steps from TraceStep.next_step.current_state."""
    path = tmp_path / "t1__run0.jsonl"
    lines = [
        json.dumps({
            "kind": "meta",
            "agent_version": "0.0.7",
            "agent_commit": "x",
            "model": "gpt-5.3-codex",
            "backend": "openai_compat",
            "reasoning_effort": "medium",
            "benchmark": "bitgn/pac1-dev",
            "task_id": "t1",
            "task_index": 0,
            "started_at": "2026-04-11T00:00:00Z",
            "trace_schema_version": "1.0.0",
        }),
        json.dumps({"kind": "task", "task_id": "t1", "task_text": "x"}),
        # Step 1 — contains a divergence keyword in current_state.
        json.dumps({
            "kind": "step",
            "step": 1,
            "wall_ms": 10,
            "llm": {"latency_ms": 10, "prompt_tokens": 1, "completion_tokens": 1, "cached_tokens": 0, "retry_count": 0},
            "next_step": {
                "current_state": "Reading AGENTS.md because user instruction contradicts it.",
                "plan_remaining_steps_brief": ["list", "report"],
                "identity_verified": True,
                "function": {"tool": "list", "name": "/"},
            },
            "tool_result": {"ok": True, "bytes": 0, "wall_ms": 0, "truncated": False, "original_bytes": 0, "error": None, "error_code": None},
            "session_after": {"seen_refs_count": 0, "identity_loaded": False, "rulebook_loaded": False},
        }),
        # Step 2 — benign, no keyword.
        json.dumps({
            "kind": "step",
            "step": 2,
            "wall_ms": 10,
            "llm": {"latency_ms": 10, "prompt_tokens": 1, "completion_tokens": 1, "cached_tokens": 0, "retry_count": 0},
            "next_step": {
                "current_state": "Listing the sandbox directory.",
                "plan_remaining_steps_brief": ["report"],
                "identity_verified": True,
                "function": {"tool": "list", "name": "/sandbox"},
            },
            "tool_result": {"ok": True, "bytes": 0, "wall_ms": 0, "truncated": False, "original_bytes": 0, "error": None, "error_code": None},
            "session_after": {"seen_refs_count": 0, "identity_loaded": False, "rulebook_loaded": False},
        }),
        json.dumps({
            "kind": "outcome",
            "terminated_by": "report_completion",
            "reported": "OUTCOME_OK",
            "enforcer_bypassed": False,
            "error_kind": None,
            "total_steps": 2,
            "total_llm_calls": 2,
            "total_prompt_tokens": 2,
            "total_completion_tokens": 2,
            "total_cached_tokens": 0,
            "total_reasoning_tokens": 0,
            "score": 1.0,
        }),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    summary = summarize(logs_dir=tmp_path)
    assert summary["tasks"]["t1"]["divergence_steps"] == [1]
    assert summary["overall"]["divergence_count"] == 1
