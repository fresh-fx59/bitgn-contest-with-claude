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
    run_bench.add_argument("--smoke", action="store_true",
                           help="run the fixed smoke subset with hardcoded parallelism (180s budget)")
    run_bench.add_argument("--max-inflight-llm", type=int, default=None,
                           help="max concurrent LLM calls across all parallel tasks")

    tri = subs.add_parser("triage", help="classify bench failures")
    tri.add_argument("summary", nargs="?", default=None,
                     help="path to a v1.1 bench_summary JSON (single-mode)")
    tri.add_argument("--before", help="baseline summary for diff mode")
    tri.add_argument("--after", help="candidate summary for diff mode")

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
    inflight_semaphore: threading.Semaphore | None = None,
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
            inflight_semaphore=inflight_semaphore,
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


def _run_tasks_and_summarize(
    cfg: AgentConfig,
    tasks: List[TaskSpec],
    *,
    harness: BitgnHarness,
    backend: OpenAIChatBackend,
    run_id: str,
    runs: int,
    output: str | None,
    inflight_semaphore: threading.Semaphore | None = None,
) -> list[TaskExecutionResult]:
    """Execute `tasks` across `runs` repetitions and optionally write a
    bench_summary JSON. Returns the flat list of TaskExecutionResult."""
    all_results: list[TaskExecutionResult] = []
    for run_index in range(runs):
        def runner(task: TaskSpec, cancel_event: threading.Event, _ri=run_index):
            return _run_single_task(
                cfg=cfg,
                harness=harness,
                backend=backend,
                task=task,
                run_id=run_id,
                run_index=_ri,
                cancel_event=cancel_event,
                inflight_semaphore=inflight_semaphore,
            )

        orch = Orchestrator(
            runner=runner,
            max_parallel_tasks=cfg.max_parallel_tasks,
            task_timeout_sec=cfg.task_timeout_sec,
            task_timeout_grace_sec=cfg.task_timeout_grace_sec,
        )
        all_results.extend(orch.run(tasks))

    if output:
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
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"bench summary → {output}")

    return all_results


def _cmd_run_benchmark(args: argparse.Namespace) -> int:
    cfg = _resolve_config(args)

    # --smoke overrides task list and parallelism BEFORE harness/backend creation.
    # dataclasses.replace hits max_parallel_tasks a SECOND time (after _resolve_config
    # already set it from --max-parallel) — intentional: smoke beats user args.
    if args.smoke:
        from bitgn_contest_agent.bench.smoke import (
            SMOKE_TASKS,
            SMOKE_MAX_PARALLEL,
            SMOKE_MAX_INFLIGHT_LLM,
        )
        cfg = dataclasses.replace(
            cfg,
            max_parallel_tasks=SMOKE_MAX_PARALLEL,
            max_inflight_llm=SMOKE_MAX_INFLIGHT_LLM,
        )
        tasks: List[TaskSpec] = [
            TaskSpec(task_id=tid, task_index=i, task_text="")
            for i, tid in enumerate(SMOKE_TASKS)
        ]
    else:
        if args.max_inflight_llm is not None:
            cfg = dataclasses.replace(cfg, max_inflight_llm=args.max_inflight_llm)

    harness = _make_harness(cfg)
    backend = _make_backend(cfg)

    if not args.smoke:
        task_ids = harness.list_task_ids()
        tasks = [
            TaskSpec(task_id=tid, task_index=i, task_text="")
            for i, tid in enumerate(task_ids)
        ]

    # One semaphore shared across all parallel agents in this run
    inflight_semaphore = threading.Semaphore(cfg.max_inflight_llm)

    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    all_results = _run_tasks_and_summarize(
        cfg,
        tasks,
        harness=harness,
        backend=backend,
        run_id=run_id,
        runs=args.runs,
        output=args.output,
        inflight_semaphore=inflight_semaphore,
    )

    total = len(all_results)
    passed = sum(1 for r in all_results if r.score >= 1.0)
    print(f"pass rate: {passed}/{total} ({passed / max(1, total) * 100:.1f}%)")
    return 0 if passed == total else 1


def _cmd_triage(args: argparse.Namespace) -> int:
    # sys.path injection for scripts.bench_summary (same pattern as run-benchmark)
    _repo_root = Path(__file__).resolve().parents[2]
    if str(_repo_root) not in sys.path:
        sys.path.insert(0, str(_repo_root))
    from scripts.bench_summary import load_summary  # type: ignore[attr-defined]
    from bitgn_contest_agent.bench.triage import classify_failure, TRIAGE_ORDER

    def cluster(path: Path) -> dict[str, list[str]]:
        raw = json.loads(path.read_text(encoding="utf-8"))
        summary = load_summary(raw)
        buckets: dict[str, list[str]] = {c: [] for c in TRIAGE_ORDER}
        for tid, t in summary.get("tasks", {}).items():
            if t.get("passes", 0) >= t.get("runs", 1):
                continue  # all runs passed — not a failure
            evidence = {
                "task_id": tid,
                "outcome": t.get("last_outcome", "OUTCOME_OK"),
                "grader_failed": True,
                "step_texts": t.get("step_texts", []),
                "latency_ms": t.get("last_latency_ms", 0),
                "timed_out": t.get("timed_out", False),
                "task_category": t.get("category", "other"),
            }
            buckets[classify_failure(evidence)].append(tid)
        return buckets

    if args.before and args.after:
        b = cluster(Path(args.before))
        a = cluster(Path(args.after))
        for c in TRIAGE_ORDER:
            cleared = sorted(set(b[c]) - set(a[c]))
            added = sorted(set(a[c]) - set(b[c]))
            if cleared or added:
                parts = [f"-{t}" for t in cleared] + [f"+{t}" for t in added]
                print(f"{c}: {' '.join(parts)}")
    else:
        if not args.summary:
            print("error: triage requires a summary path or --before/--after", file=sys.stderr)
            return 2
        b = cluster(Path(args.summary))
        for c in TRIAGE_ORDER:
            if b[c]:
                print(f"{c}: {' '.join(sorted(b[c]))}")
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "run-task":
            return _cmd_run_task(args)
        if args.command == "run-benchmark":
            return _cmd_run_benchmark(args)
        if args.command == "triage":
            return _cmd_triage(args)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
