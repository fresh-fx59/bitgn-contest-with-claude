"""Pre-pass best-effort identity bootstrap."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from bitgn.vm import pcm_pb2

from bitgn_contest_agent.adapter.pcm import PcmAdapter
from bitgn_contest_agent.session import Session


class _FakeTraceWriter:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def append_prepass(self, *, cmd: str, ok: bool, **kwargs: object) -> None:
        self.events.append({"cmd": cmd, "ok": ok, **kwargs})


def test_prepass_runs_tree_read_context_and_marks_loaded() -> None:
    runtime = MagicMock()
    runtime.tree.return_value = pcm_pb2.TreeResponse()
    runtime.read.return_value = pcm_pb2.ReadResponse(content="rules")
    runtime.context.return_value = pcm_pb2.ContextResponse()

    adapter = PcmAdapter(runtime=runtime, max_tool_result_bytes=16384)
    session = Session()
    writer = _FakeTraceWriter()
    adapter.run_prepass(session=session, trace_writer=writer)

    # Three pre-pass calls attempted.
    assert runtime.tree.call_count == 1
    assert runtime.read.call_count == 1
    assert runtime.context.call_count == 1

    # On ANY success, identity_loaded flips true.
    assert session.identity_loaded is True
    assert "AGENTS.md" in session.seen_refs
    assert len(writer.events) == 3
    assert all(e["ok"] for e in writer.events)


def test_prepass_is_best_effort_one_failure_does_not_abort_others() -> None:
    runtime = MagicMock()
    runtime.tree.side_effect = RuntimeError("tree failed")
    runtime.read.return_value = pcm_pb2.ReadResponse(content="rules")
    runtime.context.return_value = pcm_pb2.ContextResponse()

    adapter = PcmAdapter(runtime=runtime, max_tool_result_bytes=16384)
    session = Session()
    writer = _FakeTraceWriter()
    adapter.run_prepass(session=session, trace_writer=writer)

    assert runtime.tree.call_count == 1
    assert runtime.read.call_count == 1
    assert runtime.context.call_count == 1
    assert session.identity_loaded is True  # still true — read + context succeeded
    assert len(writer.events) == 3
    assert writer.events[0]["ok"] is False
    assert writer.events[1]["ok"] is True
    assert writer.events[2]["ok"] is True
