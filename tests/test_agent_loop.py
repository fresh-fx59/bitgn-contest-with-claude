"""Agent loop scaffold — happy path + enforcer retry path."""
from __future__ import annotations

from pathlib import Path
from typing import Sequence
from unittest.mock import MagicMock

import pytest

from bitgn_contest_agent.agent import AgentLoop, AgentLoopResult
from bitgn_contest_agent.adapter.pcm import PcmAdapter, ToolResult
from bitgn_contest_agent.backend.base import Backend, Message, NextStepResult, TransientBackendError
from bitgn_contest_agent.schemas import NextStep
from bitgn_contest_agent.session import Session
from bitgn_contest_agent.trace_schema import TRACE_SCHEMA_VERSION, TraceMeta
from bitgn_contest_agent.trace_writer import TraceWriter


def _mk_step(function: dict) -> NextStep:
    return NextStep(
        current_state="x",
        plan_remaining_steps_brief=["do", "report"],
        identity_verified=True,
        function=function,
    )


class _ScriptedBackend(Backend):
    def __init__(self, scripted: list[NextStep]) -> None:
        self._steps = list(scripted)
        self.calls = 0

    def next_step(self, messages: Sequence[Message], response_schema, timeout_sec):  # type: ignore[override]
        self.calls += 1
        return NextStepResult(
            parsed=self._steps.pop(0),
            prompt_tokens=0,
            completion_tokens=0,
            reasoning_tokens=0,
        )


def _mk_writer(tmp_path: Path) -> TraceWriter:
    w = TraceWriter(path=tmp_path / "trace.jsonl")
    w.write_meta(
        TraceMeta(
            agent_version="0.0.7",
            agent_commit="t",
            model="gpt-5.3-codex",
            backend="openai_compat",
            reasoning_effort="medium",
            benchmark="bitgn/pac1-dev",
            task_id="t1",
            task_index=0,
            started_at="2026-04-10T00:00:00Z",
            trace_schema_version=TRACE_SCHEMA_VERSION,
        )
    )
    return w


def _mk_adapter_mock(tool_result_content: str = "AGENTS.md contents") -> MagicMock:
    adapter = MagicMock(spec=PcmAdapter)
    adapter.run_prepass = MagicMock()
    adapter.dispatch.return_value = ToolResult(
        ok=True,
        content=tool_result_content,
        refs=("AGENTS.md",),
        error=None,
        error_code=None,
        wall_ms=5,
    )
    adapter.submit_terminal.return_value = ToolResult(
        ok=True, content="", refs=(), error=None, error_code=None, wall_ms=3
    )
    return adapter


def _fake_prepass(session: Session) -> None:
    session.identity_loaded = True
    session.rulebook_loaded = True
    session.seen_refs.add("AGENTS.md")


def test_agent_loop_happy_path_read_then_report(tmp_path: Path) -> None:
    backend = _ScriptedBackend(
        [
            _mk_step({"tool": "read", "path": "AGENTS.md"}),
            _mk_step(
                {
                    "tool": "report_completion",
                    "message": "done",
                    "grounding_refs": ["AGENTS.md"],
                    "rulebook_notes": "n",
                    "outcome_justification": "AGENTS.md was read",
                    "completed_steps_laconic": ["read AGENTS.md"],
                    "outcome": "OUTCOME_OK",
                }
            ),
        ]
    )
    adapter = _mk_adapter_mock()
    adapter.run_prepass.side_effect = lambda *, session, trace_writer: _fake_prepass(session)
    writer = _mk_writer(tmp_path)

    loop = AgentLoop(
        backend=backend,
        adapter=adapter,
        writer=writer,
        max_steps=10,
        llm_http_timeout_sec=30.0,
    )
    result: AgentLoopResult = loop.run(task_id="t1", task_text="answer from AGENTS.md")

    assert result.terminated_by == "report_completion"
    assert result.reported == "OUTCOME_OK"
    assert result.enforcer_bypassed is False
    adapter.submit_terminal.assert_called_once()
    writer.close()


def test_agent_loop_enforcer_rejects_fabricated_ref_then_retries(tmp_path: Path) -> None:
    backend = _ScriptedBackend(
        [
            _mk_step(
                {
                    "tool": "report_completion",
                    "message": "done",
                    "grounding_refs": ["imaginary.py"],  # R1 will reject
                    "rulebook_notes": "n",
                    "outcome_justification": "j",
                    "completed_steps_laconic": ["thought about it"],
                    "outcome": "OUTCOME_OK",
                }
            ),
            _mk_step(
                {
                    "tool": "report_completion",
                    "message": "done",
                    "grounding_refs": ["AGENTS.md"],
                    "rulebook_notes": "n",
                    "outcome_justification": "read AGENTS.md",
                    "completed_steps_laconic": ["read AGENTS.md"],
                    "outcome": "OUTCOME_OK",
                }
            ),
        ]
    )
    adapter = _mk_adapter_mock()
    adapter.run_prepass.side_effect = lambda *, session, trace_writer: _fake_prepass(session)
    writer = _mk_writer(tmp_path)

    loop = AgentLoop(
        backend=backend,
        adapter=adapter,
        writer=writer,
        max_steps=10,
        llm_http_timeout_sec=30.0,
    )
    result = loop.run(task_id="t1", task_text="do it")

    assert result.terminated_by == "report_completion"
    assert result.reported == "OUTCOME_OK"
    assert result.enforcer_bypassed is False
    assert backend.calls == 2  # one rejection + one accepted retry
    adapter.submit_terminal.assert_called_once()
    writer.close()


def test_agent_loop_submits_anyway_after_exhausted_enforcer_retry(tmp_path: Path) -> None:
    # Both the initial and the retry emit the same bad terminal.
    bad_terminal = _mk_step(
        {
            "tool": "report_completion",
            "message": "done",
            "grounding_refs": ["still_fake.py"],
            "rulebook_notes": "n",
            "outcome_justification": "j",
            "completed_steps_laconic": ["-"],
            "outcome": "OUTCOME_OK",
        }
    )
    backend = _ScriptedBackend([bad_terminal, bad_terminal])
    adapter = _mk_adapter_mock()
    adapter.run_prepass.side_effect = lambda *, session, trace_writer: _fake_prepass(session)
    writer = _mk_writer(tmp_path)

    loop = AgentLoop(backend=backend, adapter=adapter, writer=writer, max_steps=5, llm_http_timeout_sec=30.0)
    result = loop.run(task_id="t1", task_text="do it")

    assert result.terminated_by == "report_completion"
    assert result.enforcer_bypassed is True   # submit_anyway path
    adapter.submit_terminal.assert_called_once()
    writer.close()


def test_agent_loop_hits_max_steps_and_fails(tmp_path: Path) -> None:
    # Backend keeps emitting read steps forever — never reaches terminal.
    read_step = _mk_step({"tool": "read", "path": "AGENTS.md"})
    backend = _ScriptedBackend([read_step] * 10)
    adapter = _mk_adapter_mock()
    adapter.run_prepass.side_effect = lambda *, session, trace_writer: _fake_prepass(session)
    writer = _mk_writer(tmp_path)

    loop = AgentLoop(backend=backend, adapter=adapter, writer=writer, max_steps=3, llm_http_timeout_sec=30.0)
    result = loop.run(task_id="t1", task_text="do it")

    assert result.terminated_by == "exhausted"
    assert result.error_kind == "MAX_STEPS"
    writer.close()


class _FlakyBackend(Backend):
    """Raises TransientBackendError once, then returns the canned step."""

    def __init__(self, step: NextStep, raise_times: int = 1) -> None:
        self._step = step
        self._remaining_raises = raise_times
        self.calls = 0

    def next_step(self, messages, response_schema, timeout_sec):  # type: ignore[override]
        self.calls += 1
        if self._remaining_raises > 0:
            self._remaining_raises -= 1
            raise TransientBackendError("429", attempt=self.calls)
        return NextStepResult(
            parsed=self._step,
            prompt_tokens=0,
            completion_tokens=0,
            reasoning_tokens=0,
        )


def test_agent_loop_retries_on_transient_backend_error(tmp_path: Path, monkeypatch) -> None:
    # Replace time.sleep so tests stay fast.
    monkeypatch.setattr("bitgn_contest_agent.agent.time.sleep", lambda s: None)
    backend = _FlakyBackend(
        _mk_step(
            {
                "tool": "report_completion",
                "message": "done",
                "grounding_refs": ["AGENTS.md"],
                "rulebook_notes": "n",
                "outcome_justification": "read",
                "completed_steps_laconic": ["read AGENTS.md"],
                "outcome": "OUTCOME_OK",
            }
        ),
        raise_times=2,
    )
    adapter = _mk_adapter_mock()
    adapter.run_prepass.side_effect = lambda *, session, trace_writer: _fake_prepass(session)
    writer = _mk_writer(tmp_path)

    loop = AgentLoop(
        backend=backend,
        adapter=adapter,
        writer=writer,
        max_steps=5,
        llm_http_timeout_sec=30.0,
        backend_backoff_ms=(1, 1, 1, 1),
    )
    result = loop.run(task_id="t1", task_text="do it")

    assert result.terminated_by == "report_completion"
    assert backend.calls == 3  # 2 transient failures + 1 success
    writer.close()


def test_agent_loop_fails_task_after_backend_exhaustion(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("bitgn_contest_agent.agent.time.sleep", lambda s: None)

    class _AlwaysFlaky(Backend):
        def next_step(self, messages, response_schema, timeout_sec):  # type: ignore[override]
            raise TransientBackendError("no capacity")

    adapter = _mk_adapter_mock()
    adapter.run_prepass.side_effect = lambda *, session, trace_writer: _fake_prepass(session)
    writer = _mk_writer(tmp_path)

    loop = AgentLoop(
        backend=_AlwaysFlaky(),
        adapter=adapter,
        writer=writer,
        max_steps=5,
        llm_http_timeout_sec=30.0,
        backend_backoff_ms=(1, 1, 1, 1),
    )
    result = loop.run(task_id="t1", task_text="do it")
    assert result.terminated_by == "error"
    assert result.error_kind == "BACKEND_ERROR"
    writer.close()
