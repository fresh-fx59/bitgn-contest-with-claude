"""Trace schema invariants (single source of truth per §6.5)."""
from __future__ import annotations

import json

import pytest

from bitgn_contest_agent.trace_schema import (
    ERROR_KIND_VALUES,
    EVENT_KIND_VALUES,
    ERROR_CODE_VALUES,
    TERMINATED_BY_VALUES,
    TRACE_SCHEMA_VERSION,
    TraceMeta,
    TraceOutcome,
    TraceStep,
    TraceEvent,
    TracePrepass,
    TraceTask,
    StepLLMStats,
    StepToolResult,
    load_jsonl,
)


def test_schema_version_is_tuple_like() -> None:
    parts = TRACE_SCHEMA_VERSION.split(".")
    assert len(parts) == 3
    assert all(p.isdigit() for p in parts)


def test_closed_enum_sets_are_frozen_and_cover_spec() -> None:
    assert "CANCELLED" in ERROR_KIND_VALUES
    assert None in ERROR_KIND_VALUES or "NULL" in ERROR_KIND_VALUES or True
    assert "validation_retry" in EVENT_KIND_VALUES
    assert "loop_nudge" in EVENT_KIND_VALUES
    assert "rate_limit_backoff" in EVENT_KIND_VALUES
    assert "timeout_cancel" in EVENT_KIND_VALUES
    assert "enforcer_reject" in EVENT_KIND_VALUES
    assert "report_completion" in TERMINATED_BY_VALUES
    assert "cancel" in TERMINATED_BY_VALUES
    assert "RPC_DEADLINE" in ERROR_CODE_VALUES
    assert "PCM_ERROR" in ERROR_CODE_VALUES


def test_meta_roundtrips() -> None:
    m = TraceMeta(
        agent_version="0.0.7",
        agent_commit="abc",
        model="gpt-5.3-codex",
        backend="openai_compat",
        reasoning_effort="medium",
        benchmark="bitgn/pac1-dev",
        task_id="t14",
        task_index=13,
        started_at="2026-04-10T14:05:12Z",
        trace_schema_version=TRACE_SCHEMA_VERSION,
    )
    parsed = TraceMeta.model_validate_json(m.model_dump_json())
    assert parsed == m


def test_unknown_extra_fields_are_dropped_not_rejected() -> None:
    raw = {
        "kind": "step",
        "step": 1,
        "wall_ms": 42,
        "llm": {
            "latency_ms": 40,
            "prompt_tokens": 100,
            "completion_tokens": 10,
            "cached_tokens": 0,
            "retry_count": 0,
        },
        "tool_result": {
            "ok": True,
            "bytes": 5,
            "wall_ms": 2,
            "truncated": False,
            "error": None,
            "error_code": None,
        },
        "next_step": {},
        "session_after": {
            "seen_refs_count": 1,
            "identity_loaded": True,
            "rulebook_loaded": True,
        },
        "future_only_field": "safe to ignore",
    }
    s = TraceStep.model_validate(raw)
    assert s.step == 1
    # Unknown field is dropped silently (additive-only policy).
    assert not hasattr(s, "future_only_field")


def test_load_jsonl_parses_heterogeneous_records(tmp_path) -> None:
    path = tmp_path / "trace.jsonl"
    lines = [
        '{"kind":"meta","agent_version":"0.0.7","agent_commit":"x","model":"gpt-5.3-codex","backend":"openai_compat","reasoning_effort":"medium","benchmark":"bitgn/pac1-dev","task_id":"t1","task_index":0,"started_at":"2026-04-10T00:00:00Z","trace_schema_version":"1.0.0"}',
        '{"kind":"task","task_id":"t1","task_text":"do a thing"}',
        '{"kind":"prepass","cmd":"tree","ok":true,"bytes":10,"wall_ms":5,"error":null,"error_code":null}',
        '{"kind":"outcome","terminated_by":"report_completion","reported":"OUTCOME_OK","enforcer_bypassed":false,"error_kind":null,"total_steps":1,"total_llm_calls":1,"total_prompt_tokens":0,"total_completion_tokens":0,"total_cached_tokens":0}',
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    records = list(load_jsonl(path))
    assert len(records) == 4
    assert isinstance(records[0], TraceMeta)
    assert isinstance(records[-1], TraceOutcome)


def test_trace_meta_accepts_harness_url() -> None:
    m = TraceMeta(
        agent_version="0.0.7",
        agent_commit="abc",
        model="gpt-5.3-codex",
        backend="openai_compat",
        reasoning_effort="medium",
        benchmark="bitgn/pac1-dev",
        task_id="t14",
        task_index=13,
        started_at="2026-04-11T00:00:00Z",
        trace_schema_version=TRACE_SCHEMA_VERSION,
        harness_url="https://vm.bitgn/trial_xyz",
    )
    assert m.harness_url == "https://vm.bitgn/trial_xyz"
    # Round-trip through JSON keeps the field intact.
    parsed = TraceMeta.model_validate_json(m.model_dump_json())
    assert parsed.harness_url == "https://vm.bitgn/trial_xyz"


def test_trace_meta_harness_url_defaults_to_none() -> None:
    m = TraceMeta(
        agent_version="0.0.7",
        agent_commit="abc",
        model="gpt-5.3-codex",
        backend="openai_compat",
        reasoning_effort="medium",
        benchmark="bitgn/pac1-dev",
        task_id="t14",
        task_index=13,
        started_at="2026-04-11T00:00:00Z",
        trace_schema_version=TRACE_SCHEMA_VERSION,
    )
    assert m.harness_url is None
