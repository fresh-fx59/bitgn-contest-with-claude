"""Agent loop scaffold — happy path + enforcer retry path."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence
from unittest.mock import MagicMock

import pytest

from bitgn_contest_agent.agent import AgentLoop, AgentLoopResult
from bitgn_contest_agent.adapter.pcm import PcmAdapter, ToolResult
from bitgn_contest_agent.backend.base import Backend, Message, NextStepResult, TransientBackendError
from bitgn_contest_agent.schemas import NextStep, ReportTaskCompletion
from bitgn_contest_agent.session import Session
from bitgn_contest_agent.trace_schema import TRACE_SCHEMA_VERSION, TraceMeta
from bitgn_contest_agent.trace_writer import TraceWriter


def _mk_step(
    function: dict,
    *,
    observation: str = "step observation",
    outcome_leaning: str = "GATHERING_INFORMATION",
) -> NextStep:
    return NextStep(
        current_state="x",
        plan_remaining_steps_brief=["do", "report"],
        identity_verified=True,
        observation=observation,
        outcome_leaning=outcome_leaning,
        function=function,
    )


def _wrap(step: NextStep) -> NextStepResult:
    """Wrap a NextStep with zero tokens for backward compatibility."""
    return NextStepResult(parsed=step, prompt_tokens=0, completion_tokens=0, reasoning_tokens=0)


class _ScriptedBackend(Backend):
    def __init__(self, scripted: list[NextStepResult]) -> None:
        self._steps = list(scripted)
        self.calls = 0

    def next_step(self, messages: Sequence[Message], response_schema, timeout_sec):  # type: ignore[override]
        self.calls += 1
        return self._steps.pop(0)


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
            _wrap(_mk_step({"tool": "read", "path": "AGENTS.md"})),
            _wrap(_mk_step(
                {
                    "tool": "report_completion",
                    "message": "done",
                    "grounding_refs": ["AGENTS.md"],
                    "rulebook_notes": "n",
                    "outcome_justification": "AGENTS.md was read",
                    "completed_steps_laconic": ["read AGENTS.md"],
                    "outcome": "OUTCOME_OK",
                },
                observation="task complete",
                outcome_leaning="OUTCOME_OK",
            )),
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
            _wrap(_mk_step(
                {
                    "tool": "report_completion",
                    "message": "done",
                    "grounding_refs": ["imaginary.py"],  # R1 will reject
                    "rulebook_notes": "n",
                    "outcome_justification": "j",
                    "completed_steps_laconic": ["thought about it"],
                    "outcome": "OUTCOME_OK",
                },
                observation="task complete",
                outcome_leaning="OUTCOME_OK",
            )),
            _wrap(_mk_step(
                {
                    "tool": "report_completion",
                    "message": "done",
                    "grounding_refs": ["AGENTS.md"],
                    "rulebook_notes": "n",
                    "outcome_justification": "read AGENTS.md",
                    "completed_steps_laconic": ["read AGENTS.md"],
                    "outcome": "OUTCOME_OK",
                },
                observation="task complete",
                outcome_leaning="OUTCOME_OK",
            )),
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
    bad_terminal = _wrap(_mk_step(
        {
            "tool": "report_completion",
            "message": "done",
            "grounding_refs": ["still_fake.py"],
            "rulebook_notes": "n",
            "outcome_justification": "j",
            "completed_steps_laconic": ["-"],
            "outcome": "OUTCOME_OK",
        },
        observation="task complete",
        outcome_leaning="OUTCOME_OK",
    ))
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
    read_step = _wrap(_mk_step({"tool": "read", "path": "AGENTS.md"}))
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
            },
            observation="task complete",
            outcome_leaning="OUTCOME_OK",
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


def test_routed_preflight_injects_message_before_first_llm_step(tmp_path: Path) -> None:
    """When the router picks a skill with a preflight binding and the
    prepass yields a usable WorkspaceSchema, the harness must dispatch
    that preflight and prepend its content as a PREFLIGHT user message
    BEFORE the first LLM step. The test captures the messages the
    backend sees on call #1 and asserts PREFLIGHT is present.
    """
    from bitgn_contest_agent.adapter.pcm import PrepassResult
    from bitgn_contest_agent.preflight.schema import WorkspaceSchema
    from bitgn_contest_agent.router import RoutingDecision
    from bitgn_contest_agent.schemas import Req_PreflightFinance
    from bitgn_contest_agent.skill_loader import BitgnSkill

    # Capture backend call #1 messages.
    captured: list[list[Message]] = []

    class _CapturingBackend(Backend):
        def __init__(self, step: NextStep) -> None:
            self._step = step
            self.calls = 0

        def next_step(self, messages, response_schema, timeout_sec):  # type: ignore[override]
            self.calls += 1
            if self.calls == 1:
                captured.append(list(messages))
            return NextStepResult(
                parsed=self._step,
                prompt_tokens=0,
                completion_tokens=0,
                reasoning_tokens=0,
            )

    report_step = _mk_step(
        {
            "tool": "report_completion",
            "message": "done",
            "grounding_refs": ["AGENTS.md"],
            "rulebook_notes": "n",
            "outcome_justification": "AGENTS.md was read",
            "completed_steps_laconic": ["read AGENTS.md"],
            "outcome": "OUTCOME_OK",
        },
        observation="task complete",
        outcome_leaning="OUTCOME_OK",
    )
    backend = _CapturingBackend(report_step)

    # Adapter mock — run_prepass returns a PrepassResult with a schema
    # that satisfies preflight_finance's builder (finance_roots + entities_root).
    adapter = MagicMock(spec=PcmAdapter)
    schema = WorkspaceSchema(
        inbox_root="inbox",
        entities_root="entities",
        finance_roots=["finance"],
        projects_root="projects",
        errors=(),
    )
    adapter.run_prepass.return_value = PrepassResult(
        bootstrap_content=["WORKSPACE SCHEMA ..."],
        schema=schema,
    )

    # The routed preflight dispatch returns content the harness must inject.
    preflight_result = ToolResult(
        ok=True,
        content='{"summary": {"hits": 1}, "data": {"vendor": "Datenspeicher"}}',
        refs=("finance/datenspeicher.md",),
        error=None,
        error_code=None,
        wall_ms=7,
    )

    def _dispatch_side_effect(req):
        # The terminal is submitted via submit_terminal, not dispatch,
        # so anything that reaches dispatch here is the preflight call.
        assert isinstance(req, Req_PreflightFinance)
        return preflight_result

    adapter.dispatch.side_effect = _dispatch_side_effect
    adapter.submit_terminal.return_value = ToolResult(
        ok=True, content="", refs=(), error=None, error_code=None, wall_ms=3
    )

    # Router mock — returns a FINANCE_LOOKUP decision with an extracted query
    # and exposes skills_by_name() with the preflight binding.
    router = MagicMock()
    router.route.return_value = RoutingDecision(
        category="FINANCE_LOOKUP",
        source="regex",
        confidence=1.0,
        extracted={"query": "Datenspeicher"},
        skill_name="finance_lookup",
    )
    router.skill_body_for.return_value = "skill body content"
    router.skills_by_name.return_value = {
        "finance_lookup": BitgnSkill(
            name="finance_lookup",
            description="finance lookup",
            type="rigid",
            category="FINANCE_LOOKUP",
            matcher_patterns=["finance"],
            body="skill body content",
            preflight="preflight_finance",
            preflight_query_field="query",
        ),
    }

    writer = _mk_writer(tmp_path)
    loop = AgentLoop(
        backend=backend,
        adapter=adapter,
        writer=writer,
        max_steps=5,
        llm_http_timeout_sec=30.0,
        router=router,
    )
    result = loop.run(task_id="t-routed", task_text="What was the total for Datenspeicher?")
    writer.close()

    assert result.terminated_by == "report_completion"
    assert captured, "backend was never called"
    first_call = captured[0]
    contents = [m.content for m in first_call]
    assert any("PREFLIGHT" in c for c in contents), (
        f"PREFLIGHT not found in initial messages: {contents!r}"
    )
    assert any("Datenspeicher" in c for c in contents), (
        "PREFLIGHT payload should reference the query"
    )
    # The adapter's preflight dispatch must have been invoked exactly once.
    adapter.dispatch.assert_called_once()


def test_agent_loop_writes_real_tokens_into_trace_and_totals(tmp_path: Path, monkeypatch) -> None:
    """Tokens from NextStepResult must end up in both the step record and
    the outcome's total fields. Verifies T1.6 plumbing end-to-end."""
    report_step = _mk_step(
        {
            "tool": "report_completion",
            "message": "done",
            "grounding_refs": ["AGENTS.md"],
            "rulebook_notes": "n",
            "outcome_justification": "AGENTS.md was read",
            "completed_steps_laconic": ["read AGENTS.md"],
            "outcome": "OUTCOME_OK",
        },
        observation="task complete",
        outcome_leaning="OUTCOME_OK",
    )
    backend = _ScriptedBackend([
        NextStepResult(parsed=report_step, prompt_tokens=137, completion_tokens=42, reasoning_tokens=9),
    ])
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
    result = loop.run(task_id="t1", task_text="x")
    writer.close()

    # Outcome totals:
    assert result.total_prompt_tokens == 137
    assert result.total_completion_tokens == 42
    assert result.total_reasoning_tokens == 9

    # Step record carries them too:
    trace_path = next(tmp_path.glob("*.jsonl"))
    records = [json.loads(line) for line in trace_path.read_text().splitlines()]
    step_records = [r for r in records if r.get("kind") == "step"]
    assert step_records, "no step record written"
    llm = step_records[0]["llm"]
    assert llm["prompt_tokens"] == 137
    assert llm["completion_tokens"] == 42
    assert llm["reasoning_tokens"] == 9
