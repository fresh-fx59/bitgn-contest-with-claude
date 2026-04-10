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
