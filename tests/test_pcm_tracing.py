"""TracingPcmClient — wrapper that writes one pcm_op record per PCM call.

These tests cover the wrapper contract; test_trace_writer covers the
writer's append_pcm_op method.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from bitgn.vm import pcm_pb2

from bitgn_contest_agent.adapter.pcm_tracing import (
    TracingPcmClient,
    pcm_origin,
    set_pcm_origin,
)
from bitgn_contest_agent.trace_schema import TracePcmOp, load_jsonl
from bitgn_contest_agent.trace_writer import TraceWriter


def _mk_writer(tmp_path: Path) -> TraceWriter:
    return TraceWriter(path=tmp_path / "trace.jsonl")


def test_wrapper_emits_one_op_per_call_with_correct_op_and_path(tmp_path):
    runtime = MagicMock()
    runtime.tree.return_value = pcm_pb2.TreeResponse()
    runtime.read.return_value = pcm_pb2.ReadResponse(content="hi")
    runtime.list.return_value = pcm_pb2.ListResponse()
    runtime.context.return_value = pcm_pb2.ContextResponse()

    writer = _mk_writer(tmp_path)
    client = TracingPcmClient(runtime, writer=writer)

    client.tree(pcm_pb2.TreeRequest(root="/"))
    client.read(pcm_pb2.ReadRequest(path="AGENTS.md"))
    client.list(pcm_pb2.ListRequest(name="10_entities"))
    client.context(pcm_pb2.ContextRequest())
    writer.close()

    records = [r for r in load_jsonl(writer.path) if isinstance(r, TracePcmOp)]
    assert len(records) == 4
    assert [(r.op, r.path) for r in records] == [
        ("tree", "/"),
        ("read", "AGENTS.md"),
        ("list", "10_entities"),
        ("context", None),
    ]
    assert all(r.ok for r in records)
    assert all(r.error_code is None for r in records)


def test_wrapper_records_failed_op_with_error_code(tmp_path):
    runtime = MagicMock()
    runtime.read.side_effect = TimeoutError("deadline exceeded")

    writer = _mk_writer(tmp_path)
    client = TracingPcmClient(runtime, writer=writer)

    with pytest.raises(TimeoutError):
        client.read(pcm_pb2.ReadRequest(path="missing.md"))
    writer.close()

    records = [r for r in load_jsonl(writer.path) if isinstance(r, TracePcmOp)]
    assert len(records) == 1
    assert records[0].op == "read"
    assert records[0].path == "missing.md"
    assert records[0].ok is False
    assert records[0].error_code == "RPC_DEADLINE"


def test_wrapper_passes_through_unknown_methods_untraced(tmp_path):
    """The runtime may expose methods we haven't wrapped (e.g. health
    checks, future RPCs). Delegation must work; absence of a trace
    record is the expected behavior for unwrapped methods."""
    runtime = MagicMock()
    runtime.some_future_method.return_value = "ok"

    writer = _mk_writer(tmp_path)
    client = TracingPcmClient(runtime, writer=writer)

    assert client.some_future_method("x") == "ok"
    writer.close()

    records = [r for r in load_jsonl(writer.path) if isinstance(r, TracePcmOp)]
    assert len(records) == 0


def test_wrapper_without_writer_still_works(tmp_path):
    """The writer is attached via set_writer after start_trial; calls
    before attachment must not crash."""
    runtime = MagicMock()
    runtime.tree.return_value = pcm_pb2.TreeResponse()

    client = TracingPcmClient(runtime, writer=None)
    client.tree(pcm_pb2.TreeRequest(root="/"))  # must not raise

    # Attach a writer mid-flight; subsequent calls are traced.
    writer = _mk_writer(tmp_path)
    client.set_writer(writer)
    client.tree(pcm_pb2.TreeRequest(root="/50_finance"))
    writer.close()

    records = [r for r in load_jsonl(writer.path) if isinstance(r, TracePcmOp)]
    assert len(records) == 1
    assert records[0].path == "/50_finance"


def test_wrapper_records_response_bytes_from_proto_bytesize(tmp_path):
    """bytes field should reflect the wire-byte size of the response,
    so a trace-vs-dashboard diff lines up on payload sizes too."""
    runtime = MagicMock()
    big = pcm_pb2.ReadResponse(content="x" * 1024)
    runtime.read.return_value = big

    writer = _mk_writer(tmp_path)
    client = TracingPcmClient(runtime, writer=writer)
    client.read(pcm_pb2.ReadRequest(path="big.md"))
    writer.close()

    records = [r for r in load_jsonl(writer.path) if isinstance(r, TracePcmOp)]
    assert len(records) == 1
    assert records[0].bytes == big.ByteSize()
    assert records[0].bytes > 1000


def test_pcm_origin_context_manager_tags_ops(tmp_path):
    """Ops emitted inside `pcm_origin(label)` carry the label as origin.
    Ops emitted outside any block have origin=None."""
    runtime = MagicMock()
    runtime.tree.return_value = pcm_pb2.TreeResponse()
    runtime.read.return_value = pcm_pb2.ReadResponse()

    writer = _mk_writer(tmp_path)
    client = TracingPcmClient(runtime, writer=writer)

    client.tree(pcm_pb2.TreeRequest(root="/"))  # no origin
    with pcm_origin("prepass"):
        client.read(pcm_pb2.ReadRequest(path="AGENTS.md"))
        with pcm_origin("nested"):
            client.read(pcm_pb2.ReadRequest(path="x.md"))
        # After nested block, origin reverts to outer "prepass".
        client.read(pcm_pb2.ReadRequest(path="y.md"))
    client.read(pcm_pb2.ReadRequest(path="after.md"))  # origin=None again
    writer.close()

    records = [r for r in load_jsonl(writer.path) if isinstance(r, TracePcmOp)]
    assert [(r.op, r.path, r.origin) for r in records] == [
        ("tree", "/", None),
        ("read", "AGENTS.md", "prepass"),
        ("read", "x.md", "nested"),
        ("read", "y.md", "prepass"),
        ("read", "after.md", None),
    ]


def test_set_pcm_origin_overwrites_without_reset(tmp_path):
    """`set_pcm_origin` is the agent-loop helper: each call replaces the
    origin; there is no paired reset. Used when a `with` block would
    require re-indenting a huge body (the main loop iteration)."""
    runtime = MagicMock()
    runtime.read.return_value = pcm_pb2.ReadResponse()

    writer = _mk_writer(tmp_path)
    client = TracingPcmClient(runtime, writer=writer)

    set_pcm_origin("step:1")
    client.read(pcm_pb2.ReadRequest(path="a.md"))
    set_pcm_origin("step:2")
    client.read(pcm_pb2.ReadRequest(path="b.md"))
    writer.close()

    records = [r for r in load_jsonl(writer.path) if isinstance(r, TracePcmOp)]
    assert [(r.path, r.origin) for r in records] == [
        ("a.md", "step:1"),
        ("b.md", "step:2"),
    ]


def test_move_records_compose_from_and_to_as_path(tmp_path):
    runtime = MagicMock()
    runtime.move.return_value = pcm_pb2.MoveResponse()

    writer = _mk_writer(tmp_path)
    client = TracingPcmClient(runtime, writer=writer)
    client.move(pcm_pb2.MoveRequest(from_name="a.md", to_name="b.md"))
    writer.close()

    records = [r for r in load_jsonl(writer.path) if isinstance(r, TracePcmOp)]
    assert len(records) == 1
    assert records[0].op == "move"
    assert records[0].path == "a.md → b.md"
