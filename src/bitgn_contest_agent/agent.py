"""Core agent step loop (§2.7).

~120 LoC. Responsibilities:
1. Build initial messages (system prompt + task description).
2. Run pre-pass via adapter.
3. Step loop up to max_steps:
   - Call backend.next_step(...).
   - ValidationError → P3 one-shot retry with critique; re-raise if retry fails.
   - Loop detector → P4 inject nudge on next turn, continue.
   - Dispatch tool via adapter. On failure feed error back to model (P1).
   - If terminal → run enforcer. On retry-exhausted failure → submit anyway.
4. Append everything to the trace.
5. Submit final outcome via adapter.submit_terminal.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import List, Optional

from pydantic import ValidationError

from bitgn_contest_agent.adapter.pcm import PcmAdapter, ToolResult
from bitgn_contest_agent.backend.base import Backend, Message, NextStepResult, TransientBackendError
from bitgn_contest_agent.bench.run_metrics import RunMetrics
from bitgn_contest_agent.enforcer import Verdict, check_terminal
from bitgn_contest_agent.prompts import critique_injection, loop_nudge, system_prompt
from bitgn_contest_agent.schemas import NextStep, ReportTaskCompletion
from bitgn_contest_agent.session import Session
from bitgn_contest_agent.task_hints import hint_for_task
from bitgn_contest_agent.trace_schema import (
    StepLLMStats,
    StepSessionAfter,
    StepToolResult,
    TraceOutcome,
)
from bitgn_contest_agent.trace_writer import TraceWriter


_MAX_NUDGES = 2
_DEFAULT_BACKOFF_MS: tuple[int, ...] = (500, 1500, 4000, 10000)


@dataclass(frozen=True, slots=True)
class AgentLoopResult:
    terminated_by: str
    reported: Optional[str]
    enforcer_bypassed: bool
    error_kind: Optional[str]
    error_msg: Optional[str]
    total_steps: int
    total_llm_calls: int
    total_prompt_tokens: int
    total_completion_tokens: int
    total_cached_tokens: int
    total_reasoning_tokens: int


class AgentLoop:
    def __init__(
        self,
        *,
        backend: Backend,
        adapter: PcmAdapter,
        writer: TraceWriter,
        max_steps: int,
        llm_http_timeout_sec: float,
        cancel_event: Optional[threading.Event] = None,
        backend_backoff_ms: tuple[int, ...] = _DEFAULT_BACKOFF_MS,
        inflight_semaphore: Optional[threading.Semaphore] = None,
        metrics: Optional[RunMetrics] = None,
    ) -> None:
        self._backend = backend
        self._adapter = adapter
        self._writer = writer
        self._max_steps = max_steps
        self._llm_http_timeout_sec = llm_http_timeout_sec
        self._cancel_event = cancel_event
        self._backoff_ms = backend_backoff_ms
        self._inflight_semaphore = inflight_semaphore
        self._metrics = metrics

    def run(self, *, task_id: str, task_text: str) -> AgentLoopResult:
        session = Session()
        messages: List[Message] = [
            Message(role="system", content=system_prompt()),
            Message(role="user", content=task_text),
        ]

        # Task-local hints — pattern-gated hardcode fixes for known PROD
        # failure modes. Injected as a third user message so the system
        # prompt and task-text messages stay bit-identical (provider-side
        # cache remains hot). hint_for_task() returns None for tasks
        # that don't match any pattern; in that case no message is
        # added and the loop behaves exactly as before.
        task_hint = hint_for_task(task_text)
        if task_hint is not None:
            messages.append(Message(role="user", content=task_hint))

        # Pre-pass (best effort).
        self._adapter.run_prepass(session=session, trace_writer=self._writer)
        self._writer.append_task(task_id=task_id, task_text=task_text)

        totals = _Totals()
        pending_critique: Optional[str] = None
        pending_nudge: Optional[str] = None

        for step_idx in range(1, self._max_steps + 1):
            if self._cancel_event is not None and self._cancel_event.is_set():
                return self._finish_cancelled(totals, step_idx - 1)

            session.step = step_idx
            step_start = time.monotonic()
            if pending_critique is not None:
                messages.append(Message(role="user", content=pending_critique))
                pending_critique = None
            if pending_nudge is not None:
                messages.append(Message(role="user", content=pending_nudge))
                pending_nudge = None

            # Backend call + P2 transient retry + P3 validation retry.
            step_result: NextStepResult
            try:
                maybe_step = self._call_backend_with_retry(
                    messages, at_step=step_idx
                )
                if maybe_step is None:
                    return self._finish_error(
                        totals,
                        step_idx,
                        error_kind="BACKEND_ERROR",
                        error_msg="transient backend exhausted",
                    )
                step_result = maybe_step
                totals.prompt_tokens += maybe_step.prompt_tokens
                totals.completion_tokens += maybe_step.completion_tokens
                totals.reasoning_tokens += maybe_step.reasoning_tokens
                step_obj = maybe_step.parsed
            except ValidationError as exc:
                self._writer.append_event(
                    at_step=step_idx,
                    event_kind="validation_retry",
                    details=str(exc)[:500],
                )
                retry_messages = list(messages) + [
                    Message(
                        role="user",
                        content=critique_injection([f"ValidationError: {exc}"]),
                    )
                ]
                try:
                    maybe_retry = self._call_backend_with_retry(
                        retry_messages, at_step=step_idx
                    )
                    if maybe_retry is None:
                        return self._finish_error(
                            totals,
                            step_idx,
                            error_kind="BACKEND_ERROR",
                            error_msg="transient backend exhausted on validation retry",
                        )
                    step_result = maybe_retry
                    totals.prompt_tokens += maybe_retry.prompt_tokens
                    totals.completion_tokens += maybe_retry.completion_tokens
                    totals.reasoning_tokens += maybe_retry.reasoning_tokens
                    step_obj = maybe_retry.parsed
                except ValidationError as exc2:
                    return self._finish_error(
                        totals,
                        step_idx,
                        error_kind="BACKEND_ERROR",
                        error_msg=f"double validation failure: {exc2}",
                    )
            totals.llm_calls += 1

            # Dispatch.
            fn = step_obj.function
            tool_result: ToolResult
            enforcer_verdict: list[str] | None = None
            enforcer_action: str | None = None

            if isinstance(fn, ReportTaskCompletion):
                verdict = check_terminal(session, step_obj)
                if verdict.ok:
                    tool_result = self._adapter.submit_terminal(fn)
                    enforcer_action = "accept"
                else:
                    enforcer_verdict = list(verdict.reasons)
                    self._writer.append_event(
                        at_step=step_idx,
                        event_kind="enforcer_reject",
                        details="; ".join(verdict.reasons)[:500],
                    )
                    # Attempt one retry by injecting critique on next turn.
                    retry_messages = list(messages) + [
                        Message(
                            role="user",
                            content=critique_injection(verdict.reasons),
                        )
                    ]
                    try:
                        maybe_retry_step = self._call_backend_with_retry(
                            retry_messages, at_step=step_idx
                        )
                        if maybe_retry_step is None:
                            retry_step = step_obj  # fall through to submit_anyway
                        else:
                            totals.prompt_tokens += maybe_retry_step.prompt_tokens
                            totals.completion_tokens += maybe_retry_step.completion_tokens
                            totals.reasoning_tokens += maybe_retry_step.reasoning_tokens
                            retry_step = maybe_retry_step.parsed
                            totals.llm_calls += 1
                    except ValidationError:
                        retry_step = step_obj  # fall through to submit_anyway
                    retry_fn = retry_step.function
                    if isinstance(retry_fn, ReportTaskCompletion):
                        retry_verdict = check_terminal(session, retry_step)
                        if retry_verdict.ok:
                            tool_result = self._adapter.submit_terminal(retry_fn)
                            enforcer_action = "accept_after_retry"
                            fn = retry_fn
                        else:
                            tool_result = self._adapter.submit_terminal(retry_fn)
                            enforcer_action = "submit_anyway"
                            enforcer_verdict = list(retry_verdict.reasons)
                            fn = retry_fn
                    else:
                        # Retry returned a non-terminal; submit the original anyway.
                        tool_result = self._adapter.submit_terminal(fn)
                        enforcer_action = "submit_anyway"

                self._log_step(
                    step_idx,
                    step_start,
                    step_obj,
                    tool_result,
                    session,
                    prompt_tokens=step_result.prompt_tokens,
                    completion_tokens=step_result.completion_tokens,
                    reasoning_tokens=step_result.reasoning_tokens,
                    enforcer_verdict=enforcer_verdict,
                    enforcer_action=enforcer_action,
                )
                totals.steps += 1
                return self._finish_report(
                    totals,
                    reported=fn.outcome,
                    enforcer_bypassed=(enforcer_action == "submit_anyway"),
                )

            # Non-terminal: dispatch and loop-detect.
            call_tuple = _canonical_call(fn)
            if session.loop_nudge_needed(call_tuple):
                if session.nudge_budget_remaining(max_nudges=_MAX_NUDGES) > 0:
                    session.nudges_emitted += 1
                    pending_nudge = loop_nudge(call_tuple)
                    self._writer.append_event(
                        at_step=step_idx,
                        event_kind="loop_nudge",
                        repeated_tuple=list(call_tuple),
                    )
                else:
                    return self._finish_error(
                        totals,
                        step_idx,
                        error_kind="INTERNAL_CRASH",
                        error_msg="loop nudge budget exhausted",
                    )

            tool_result = self._adapter.dispatch(fn)
            if tool_result.ok:
                for ref in tool_result.refs:
                    session.seen_refs.add(ref)

            # Feed the tool result back to the planner.
            #
            # T24 observation: cliproxyapi translates OpenAI chat-completions
            # into Codex /v1/responses items. A `role="tool"` message is
            # mapped to a `function_call_output` item that requires a
            # matching `call_id`, but our assistant messages are plain JSON
            # content — not OpenAI `tool_calls` — so cliproxyapi emits an
            # empty call_id string and Codex rejects the request with
            # `Invalid 'input[N].call_id': empty string`. Wrap the tool
            # result in a `role="user"` message so it round-trips as plain
            # text, sidestepping the function-call translation entirely.
            messages.append(
                Message(
                    role="assistant",
                    content=step_obj.model_dump_json(),
                )
            )
            tool_body = (
                tool_result.content
                if tool_result.ok
                else f"ERROR ({tool_result.error_code}): {tool_result.error}"
            )
            messages.append(
                Message(
                    role="user",
                    content=f"Tool result:\n{tool_body}",
                )
            )

            self._log_step(
                step_idx,
                step_start,
                step_obj,
                tool_result,
                session,
                prompt_tokens=step_result.prompt_tokens,
                completion_tokens=step_result.completion_tokens,
                reasoning_tokens=step_result.reasoning_tokens,
            )
            totals.steps += 1

        # Exhausted max_steps.
        return self._finish_error(
            totals,
            self._max_steps,
            error_kind="MAX_STEPS",
            error_msg=f"exceeded max_steps={self._max_steps}",
        )

    # -- helpers ---------------------------------------------------------

    def _call_backend_with_retry(
        self,
        messages: List[Message],
        *,
        at_step: int,
    ) -> Optional[NextStepResult]:
        """P2 — bounded exponential backoff on TransientBackendError.

        Returns NextStepResult on success, or None if all attempts exhausted
        (caller should then finish with BACKEND_ERROR). ValidationError
        propagates to the caller's P3 handler. When an inflight_semaphore is
        configured, the entire retry loop runs inside an acquire — a rate-
        limited request keeps its slot across backoffs so the remote has a
        chance to cool down before another caller tries.
        """
        def _do_retry_loop() -> Optional[NextStepResult]:
            last_exc: Optional[Exception] = None
            for attempt, wait_ms in enumerate([0, *self._backoff_ms], start=0):
                if wait_ms > 0:
                    self._writer.append_event(
                        at_step=at_step,
                        event_kind="rate_limit_backoff",
                        wait_ms=wait_ms,
                        attempt=attempt,
                    )
                    time.sleep(wait_ms / 1000.0)
                try:
                    result = self._backend.next_step(
                        messages=messages,
                        response_schema=NextStep,
                        timeout_sec=self._llm_http_timeout_sec,
                    )
                    return result
                except TransientBackendError as exc:
                    last_exc = exc
                    if self._metrics is not None:
                        self._metrics.on_rate_limit_error()
                    continue
            if last_exc is not None:
                return None
            return None

        # Metrics observe the full call cycle (queue wait + semaphore + retries)
        if self._metrics is not None:
            self._metrics.on_call_start()
        try:
            if self._inflight_semaphore is not None:
                with self._inflight_semaphore:
                    return _do_retry_loop()
            return _do_retry_loop()
        finally:
            if self._metrics is not None:
                self._metrics.on_call_end()

    def _log_step(
        self,
        step_idx: int,
        step_start: float,
        step_obj: NextStep,
        tool_result: ToolResult,
        session: Session,
        *,
        prompt_tokens: int,
        completion_tokens: int,
        reasoning_tokens: int,
        enforcer_verdict: list[str] | None = None,
        enforcer_action: str | None = None,
    ) -> None:
        wall_ms = int((time.monotonic() - step_start) * 1000)
        self._writer.append_step(
            step=step_idx,
            wall_ms=wall_ms,
            llm=StepLLMStats(
                latency_ms=wall_ms,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                reasoning_tokens=reasoning_tokens,
                cached_tokens=0,
                retry_count=0,
            ),
            next_step=step_obj.model_dump(),
            tool_result=StepToolResult(
                ok=tool_result.ok,
                bytes=tool_result.bytes,
                wall_ms=tool_result.wall_ms,
                truncated=tool_result.truncated,
                original_bytes=tool_result.original_bytes,
                error=tool_result.error,
                error_code=tool_result.error_code,
            ),
            session_after=StepSessionAfter(
                seen_refs_count=len(session.seen_refs),
                identity_loaded=session.identity_loaded,
                rulebook_loaded=session.rulebook_loaded,
            ),
            enforcer_verdict=enforcer_verdict,
            enforcer_action=enforcer_action,
        )

    def _finish_report(
        self,
        totals: "_Totals",
        *,
        reported: str,
        enforcer_bypassed: bool,
    ) -> AgentLoopResult:
        outcome = TraceOutcome(
            terminated_by="report_completion",
            reported=reported,
            enforcer_bypassed=enforcer_bypassed,
            error_kind=None,
            total_steps=totals.steps,
            total_llm_calls=totals.llm_calls,
            total_prompt_tokens=totals.prompt_tokens,
            total_completion_tokens=totals.completion_tokens,
            total_cached_tokens=totals.cached_tokens,
            total_reasoning_tokens=totals.reasoning_tokens,
        )
        self._writer.append_outcome(outcome)
        return AgentLoopResult(
            terminated_by="report_completion",
            reported=reported,
            enforcer_bypassed=enforcer_bypassed,
            error_kind=None,
            error_msg=None,
            total_steps=totals.steps,
            total_llm_calls=totals.llm_calls,
            total_prompt_tokens=totals.prompt_tokens,
            total_completion_tokens=totals.completion_tokens,
            total_cached_tokens=totals.cached_tokens,
            total_reasoning_tokens=totals.reasoning_tokens,
        )

    def _finish_error(
        self,
        totals: "_Totals",
        step_idx: int,
        *,
        error_kind: str,
        error_msg: str,
    ) -> AgentLoopResult:
        outcome = TraceOutcome(
            terminated_by="error" if error_kind != "MAX_STEPS" else "exhausted",
            reported=None,
            enforcer_bypassed=False,
            error_kind=error_kind,
            error_msg=error_msg,
            total_steps=totals.steps,
            total_llm_calls=totals.llm_calls,
            total_prompt_tokens=totals.prompt_tokens,
            total_completion_tokens=totals.completion_tokens,
            total_cached_tokens=totals.cached_tokens,
            total_reasoning_tokens=totals.reasoning_tokens,
        )
        self._writer.append_outcome(outcome)
        return AgentLoopResult(
            terminated_by=outcome.terminated_by,
            reported=None,
            enforcer_bypassed=False,
            error_kind=error_kind,
            error_msg=error_msg,
            total_steps=totals.steps,
            total_llm_calls=totals.llm_calls,
            total_prompt_tokens=totals.prompt_tokens,
            total_completion_tokens=totals.completion_tokens,
            total_cached_tokens=totals.cached_tokens,
            total_reasoning_tokens=totals.reasoning_tokens,
        )

    def _finish_cancelled(self, totals: "_Totals", step_idx: int) -> AgentLoopResult:
        # Synthetic cancel-path terminal. BYPASSES the enforcer — written
        # directly by the worker per §3.2.
        outcome = TraceOutcome(
            terminated_by="cancel",
            reported="OUTCOME_ERR_INTERNAL",
            enforcer_bypassed=True,
            error_kind="CANCELLED",
            error_msg="cancelled:timeout",
            total_steps=totals.steps,
            total_llm_calls=totals.llm_calls,
            total_prompt_tokens=totals.prompt_tokens,
            total_completion_tokens=totals.completion_tokens,
            total_cached_tokens=totals.cached_tokens,
            total_reasoning_tokens=totals.reasoning_tokens,
        )
        self._writer.append_outcome(outcome)
        return AgentLoopResult(
            terminated_by="cancel",
            reported="OUTCOME_ERR_INTERNAL",
            enforcer_bypassed=True,
            error_kind="CANCELLED",
            error_msg="cancelled:timeout",
            total_steps=totals.steps,
            total_llm_calls=totals.llm_calls,
            total_prompt_tokens=totals.prompt_tokens,
            total_completion_tokens=totals.completion_tokens,
            total_cached_tokens=totals.cached_tokens,
            total_reasoning_tokens=totals.reasoning_tokens,
        )


@dataclass(slots=True)
class _Totals:
    steps: int = 0
    llm_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    reasoning_tokens: int = 0


def _canonical_call(fn: object) -> tuple[str, ...]:
    """Produce a stable (tool, sorted-args) tuple for the loop detector."""
    if hasattr(fn, "tool"):
        tool = getattr(fn, "tool")
    else:
        tool = type(fn).__name__
    # Use model_dump so every Req_* turns into a dict of primitives.
    if hasattr(fn, "model_dump"):
        data = fn.model_dump()  # type: ignore[attr-defined]
    else:
        data = {}
    parts = [tool] + [f"{k}={data[k]!r}" for k in sorted(data.keys()) if k != "tool"]
    return tuple(parts)
