"""Trace writer — append-per-event JSONL with crash fallback."""
from __future__ import annotations

import json
from pathlib import Path

from bitgn_contest_agent.trace_schema import (
    TRACE_SCHEMA_VERSION,
    TraceMeta,
    load_jsonl,
)
from bitgn_contest_agent.trace_writer import TraceWriter


def _mk_meta(task_id: str = "t1") -> TraceMeta:
    return TraceMeta(
        agent_version="0.0.7",
        agent_commit="dev",
        model="gpt-5.3-codex",
        backend="openai_compat",
        reasoning_effort="medium",
        benchmark="bitgn/pac1-dev",
        task_id=task_id,
        task_index=0,
        started_at="2026-04-10T00:00:00Z",
        trace_schema_version=TRACE_SCHEMA_VERSION,
    )


def test_writer_appends_meta_and_flushes_each_record(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    w = TraceWriter(path=path)
    w.write_meta(_mk_meta())
    w.append_task(task_id="t1", task_text="do stuff")
    w.append_prepass(
        cmd="tree", ok=True, bytes=10, wall_ms=5, error=None, error_code=None
    )
    w.close()

    records = list(load_jsonl(path))
    assert len(records) == 3
    assert records[0].kind == "meta"
    assert records[1].kind == "task"
    assert records[2].kind == "prepass"


def test_writer_survives_crash_and_writes_crashed_sidecar(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    w = TraceWriter(path=path)
    w.write_meta(_mk_meta())
    w.write_crash_sidecar("synthetic boom", traceback_text="tb here")
    # Sidecar path is next to the trace.
    sidecar = path.with_name(path.name.replace(".jsonl", "_CRASHED.json"))
    assert sidecar.exists()
    blob = json.loads(sidecar.read_text(encoding="utf-8"))
    assert blob["error"] == "synthetic boom"
    assert blob["traceback"] == "tb here"
    assert blob["partial_trace"] == str(path)


def test_writer_is_thread_safe_per_instance(tmp_path: Path) -> None:
    import threading

    path = tmp_path / "trace.jsonl"
    w = TraceWriter(path=path)
    w.write_meta(_mk_meta())

    def worker(i: int) -> None:
        for _ in range(20):
            w.append_event(
                at_step=i, event_kind="rate_limit_backoff", wait_ms=10, attempt=1
            )

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    w.close()

    records = list(load_jsonl(path))
    # 1 meta + 100 events
    assert len(records) == 101
