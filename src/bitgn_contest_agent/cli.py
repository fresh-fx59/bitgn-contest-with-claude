"""bitgn-agent CLI — run-task + run-benchmark.

Fail-fast pattern P6: config validation happens before the thread pool
is created. All runtime wiring lives here; agent.py / orchestrator.py
stay pure.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import os
import sys
import time
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from bitgn_contest_agent import __version__
from bitgn_contest_agent.adapter.pcm import PcmAdapter
from bitgn_contest_agent.agent import AgentLoop, AgentLoopResult
from bitgn_contest_agent.backend.openai_compat import OpenAIChatBackend
from bitgn_contest_agent.config import AgentConfig, ConfigError, load_from_env
from bitgn_contest_agent.harness import BitgnHarness, StartedTask
from bitgn_contest_agent.orchestrator import (
    Orchestrator,
    TaskExecutionResult,
    TaskSpec,
)
from bitgn_contest_agent.trace_schema import TRACE_SCHEMA_VERSION, TraceMeta
from bitgn_contest_agent.trace_writer import TraceWriter


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bitgn-agent", description="BitGN PAC1 contest agent")
    parser.add_argument("--version", action="version", version=f"bitgn-agent {__version__}")
    subs = parser.add_subparsers(dest="command", required=True)

    run_task = subs.add_parser("run-task", help="run a single benchmark task")
    run_task.add_argument("--task-id", required=True)
    run_task.add_argument("--benchmark", default=None)
    run_task.add_argument("--log-dir", default=None)

    run_bench = subs.add_parser("run-benchmark", help="run every task in a benchmark")
    run_bench.add_argument("--benchmark", default=None)
    run_bench.add_argument("--runs", type=int, default=1, help="repeat each task N times")
    run_bench.add_argument("--max-parallel", type=int, default=None)
    run_bench.add_argument("--output", default=None, help="bench_summary.json path")
    run_bench.add_argument("--log-dir", default=None)

    return parser


def _resolve_config(args: argparse.Namespace) -> AgentConfig:
    # PLAN DEVIATION: plan uses cfg.__dict__ but AgentConfig is
    # frozen=True, slots=True — slotted dataclasses have no __dict__.
    # dataclasses.replace() is the idiomatic way to override fields.
    cfg = load_from_env()
    overrides: dict = {}
    if getattr(args, "benchmark", None):
        overrides["benchmark"] = args.benchmark
    if getattr(args, "log_dir", None):
        overrides["log_dir"] = args.log_dir
    if getattr(args, "max_parallel", None) is not None:
        overrides["max_parallel_tasks"] = args.max_parallel
    return dataclasses.replace(cfg, **overrides) if overrides else cfg


def _make_harness(cfg: AgentConfig) -> BitgnHarness:
    base_url = os.environ.get("BITGN_BASE_URL") or "https://api.bitgn.com"
    return BitgnHarness.from_env(
        benchmark=cfg.benchmark,
        bitgn_base_url=base_url,
        bitgn_api_key=cfg.bitgn_api_key,
    )


def _make_backend(cfg: AgentConfig) -> OpenAIChatBackend:
    return OpenAIChatBackend.from_config(
        base_url=cfg.cliproxy_base_url,
        api_key=cfg.cliproxy_api_key,
        model=cfg.model,
        reasoning_effort=cfg.reasoning_effort,
    )


def _trace_path(cfg: AgentConfig, run_id: str, task_id: str, run_index: int) -> Path:
    return Path(cfg.log_dir) / run_id / f"{task_id}__run{run_index}.jsonl"


def _git_commit_short() -> str:
    import subprocess

    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        return "unknown"


def _run_single_task(
    *,
    cfg: AgentConfig,
    harness: BitgnHarness,
    backend: OpenAIChatBackend,
    task: TaskSpec,
    run_id: str,
    run_index: int,
    cancel_event: threading.Event,
) -> TaskExecutionResult:
    started: StartedTask | None = None
    try:
        started = harness.start_task(task.task_id)
        adapter = PcmAdapter(
            runtime=started.runtime_client,
            max_tool_result_bytes=cfg.max_tool_result_bytes,
        )

        trace_path = _trace_path(cfg, run_id, task.task_id, run_index)
        writer = TraceWriter(path=trace_path)
        writer.write_meta(
            TraceMeta(
                agent_version=__version__,
                agent_commit=_git_commit_short(),
                model=cfg.model,
                backend="openai_compat",
                reasoning_effort=cfg.reasoning_effort,
                benchmark=cfg.benchmark,
                task_id=task.task_id,
                task_index=task.task_index,
                started_at=datetime.now(timezone.utc).isoformat(),
                trace_schema_version=TRACE_SCHEMA_VERSION,
                harness_url=started.harness_url,
            )
        )

        loop = AgentLoop(
            backend=backend,
            adapter=adapter,
            writer=writer,
            max_steps=cfg.max_steps,
            llm_http_timeout_sec=float(cfg.llm_http_timeout_sec),
            cancel_event=cancel_event,
            backend_backoff_ms=cfg.rate_limit_backoff_ms,
        )
        result: AgentLoopResult = loop.run(
            task_id=task.task_id,
            task_text=started.instruction,
        )
        writer.close()

        score, _detail = harness.end_task(started)
        # Back-fill the grader score into the trace so bench_summary
        # sees the authoritative verdict instead of the agent's
        # self-reported OUTCOME_OK. Best-effort — a failure here must
        # not lose the task result.
        try:
            writer.patch_outcome_score(float(score))
        except Exception:
            pass
        return TaskExecutionResult(
            task_id=task.task_id,
            score=float(score),
            terminated_by=result.terminated_by,
            error_kind=result.error_kind,
            error_msg=result.error_msg,
        )
    except Exception as exc:
        import traceback as tb

        msg = f"{type(exc).__name__}: {exc}"
        if started is not None:
            try:
                harness.end_task(started)
            except Exception:
                pass
        return TaskExecutionResult(
            task_id=task.task_id,
            score=0.0,
            terminated_by="error",
            error_kind="INTERNAL_CRASH",
            error_msg=msg,
        )


def _cmd_run_task(args: argparse.Namespace) -> int:
    cfg = _resolve_config(args)
    harness = _make_harness(cfg)
    backend = _make_backend(cfg)
    all_ids = harness.list_task_ids()
    try:
        idx = all_ids.index(args.task_id)
    except ValueError:
        print(f"error: task {args.task_id} not found in {cfg.benchmark}", file=sys.stderr)
        return 2

    # Use the harness instruction as the task text (§harness wrapper).
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    task = TaskSpec(task_id=args.task_id, task_index=idx, task_text="")
    result = _run_single_task(
        cfg=cfg,
        harness=harness,
        backend=backend,
        task=task,
        run_id=run_id,
        run_index=0,
        cancel_event=threading.Event(),
    )
    print(json.dumps(dataclasses.asdict(result), indent=2))
    return 0 if result.terminated_by == "report_completion" else 1


def _cmd_run_benchmark(args: argparse.Namespace) -> int:
    cfg = _resolve_config(args)
    harness = _make_harness(cfg)
    backend = _make_backend(cfg)

    task_ids = harness.list_task_ids()
    tasks: List[TaskSpec] = [
        TaskSpec(task_id=tid, task_index=i, task_text="")
        for i, tid in enumerate(task_ids)
    ]

    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    all_results: list[TaskExecutionResult] = []
    for run_index in range(args.runs):
        def runner(task: TaskSpec, cancel_event: threading.Event, _ri=run_index):
            return _run_single_task(
                cfg=cfg,
                harness=harness,
                backend=backend,
                task=task,
                run_id=run_id,
                run_index=_ri,
                cancel_event=cancel_event,
            )

        orch = Orchestrator(
            runner=runner,
            max_parallel_tasks=cfg.max_parallel_tasks,
            task_timeout_sec=cfg.task_timeout_sec,
            task_timeout_grace_sec=cfg.task_timeout_grace_sec,
        )
        all_results.extend(orch.run(tasks))

    if args.output:
        # scripts/ is a sibling of src/, not part of the installed package
        # (pyproject.toml only packages src/). Pytest finds it via its
        # implicit rootdir sys.path injection; at runtime we need to do
        # the same here so the CLI works from both the editable install
        # and a built wheel invoked from the repo checkout.
        _repo_root = Path(__file__).resolve().parents[2]
        if str(_repo_root) not in sys.path:
            sys.path.insert(0, str(_repo_root))
        from scripts.bench_summary import summarize  # type: ignore[attr-defined]

        summary = summarize(logs_dir=Path(cfg.log_dir) / run_id)
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"bench summary → {args.output}")

    total = len(all_results)
    passed = sum(1 for r in all_results if r.score >= 1.0)
    print(f"pass rate: {passed}/{total} ({passed / max(1, total) * 100:.1f}%)")
    return 0 if passed == total else 1


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "run-task":
            return _cmd_run_task(args)
        if args.command == "run-benchmark":
            return _cmd_run_benchmark(args)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
