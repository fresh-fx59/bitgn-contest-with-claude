"""Compute bench summary artifacts for a benchmark run directory.

Schema v1.1 (additive over v1.0): extends overall and per-task records with
multi-run aggregates, token usage, harness_url, and divergence counts.
v1.0 consumers reading v1.1 output must tolerate unknown keys (Pydantic
ConfigDict(extra="ignore")); v1.1 consumers reading v1.0 input fill missing
fields with defaults.
"""
from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable

from bitgn_contest_agent.bench.aggregate import aggregate_runs
from bitgn_contest_agent.trace_schema import (
    TraceMeta,
    TraceOutcome,
    load_jsonl,
)


FROZEN_SCHEMA_KEYS = ("schema_version", "overall", "tasks")
BENCH_SUMMARY_SCHEMA_VERSION = "1.1.0"


def _iter_jsonl_files(logs_dir: Path) -> Iterable[Path]:
    return sorted(Path(logs_dir).rglob("*.jsonl"))


def _extract_run(path: Path) -> tuple[str, float, int, TraceMeta, TraceOutcome] | None:
    meta: TraceMeta | None = None
    outcome: TraceOutcome | None = None
    try:
        for rec in load_jsonl(path):
            if isinstance(rec, TraceMeta):
                meta = rec
            elif isinstance(rec, TraceOutcome):
                outcome = rec
    except (ValueError, json.JSONDecodeError):
        return None
    if meta is None or outcome is None:
        return None
    score = float(outcome.score) if outcome.score is not None else (
        1.0 if (outcome.reported == "OUTCOME_OK" and outcome.terminated_by == "report_completion") else 0.0
    )
    return meta.task_id, score, outcome.total_steps, meta, outcome


def summarize(*, logs_dir: Path) -> Dict[str, Any]:
    # by_task maps task_id -> list of (score, steps, meta, outcome) per run
    by_task: dict[str, list[tuple[float, int, TraceMeta, TraceOutcome]]] = defaultdict(list)
    total_runs = 0
    total_passes = 0

    for path in _iter_jsonl_files(logs_dir):
        run = _extract_run(path)
        if run is None:
            continue
        task_id, score, steps, meta, outcome = run
        by_task[task_id].append((score, steps, meta, outcome))
        total_runs += 1
        if score >= 1.0:
            total_passes += 1

    tasks_out: dict[str, dict[str, Any]] = {}
    total_input_tokens = 0
    total_output_tokens = 0
    total_reasoning_tokens = 0

    for task_id, entries in sorted(by_task.items()):
        runs = len(entries)
        passes = sum(1 for s, _, __, ___ in entries if s >= 1.0)
        med_steps = int(statistics.median(s for _, s, __, ___ in entries)) if entries else 0
        passes_per_run = [1 if s >= 1.0 else 0 for s, _, __, ___ in entries]

        # Token sums from TraceOutcome
        task_input = sum(oc.total_prompt_tokens for _, __, ___, oc in entries)
        task_output = sum(oc.total_completion_tokens for _, __, ___, oc in entries)
        task_reasoning = sum(oc.total_reasoning_tokens for _, __, ___, oc in entries)

        total_input_tokens += task_input
        total_output_tokens += task_output
        total_reasoning_tokens += task_reasoning

        harness_url = (entries[0][2].harness_url or "") if entries else ""

        tasks_out[task_id] = {
            "runs": runs,
            "passes": passes,
            "median_steps": med_steps,
            # v1.1 additive fields
            "passes_per_run": passes_per_run,
            "input_tokens": task_input,
            "output_tokens": task_output,
            "reasoning_tokens": task_reasoning,
            "harness_url": harness_url,
            "divergence_steps": [],  # T1.10 will populate
        }

    # aggregate_runs expects a list of per-run summary dicts. In Phase 1 every
    # directory is single-run-per-task, so we synthesize one summary per task —
    # the bootstrap becomes "variance across tasks at this single run" and
    # degenerates to identity for a single-task directory. Phase 2's real
    # multi-run scoring will rework this call site with per-run summaries.
    task_summaries = []
    for task_id, entries in by_task.items():
        runs = len(entries)
        passes = sum(1 for s, _, __, ___ in entries if s >= 1.0)
        task_summaries.append({"overall": {"pass_rate": passes / runs if runs else 0.0}})

    agg = aggregate_runs(task_summaries, seed=12345)
    runs_per_task = max((len(e) for e in by_task.values()), default=0)

    overall_pass_rate = (total_passes / total_runs) if total_runs else 0.0

    return {
        "schema_version": BENCH_SUMMARY_SCHEMA_VERSION,
        "overall": {
            "total_runs": total_runs,
            "total_passes": total_passes,
            "pass_rate": overall_pass_rate,
            # v1.1 additive fields
            "runs_per_task": runs_per_task,
            "pass_rate_median": agg["pass_rate_median"],
            "pass_rate_min": agg["pass_rate_min"],
            "pass_rate_ci_lower": agg["pass_rate_ci_lower"],
            "pass_rate_ci_upper": agg["pass_rate_ci_upper"],
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "total_reasoning_tokens": total_reasoning_tokens,
            "trace_dir": str(Path(logs_dir).resolve()),
            "divergence_count": 0,  # T1.8 will populate
        },
        "tasks": tasks_out,
    }


def load_summary(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Upcast a v1.0 or v1.1 bench_summary dict to the v1.1 shape.

    v1.0 files are missing the additive fields; this fills them with
    sensible defaults so callers can always assume v1.1 structure.
    """
    overall = dict(raw.get("overall", {}))
    pass_rate = overall.get("pass_rate", 0.0)

    # Fill v1.1 overall fields with defaults when absent
    overall.setdefault("runs_per_task", 0)
    overall.setdefault("pass_rate_median", pass_rate)
    overall.setdefault("pass_rate_min", pass_rate)
    overall.setdefault("pass_rate_ci_lower", pass_rate)
    overall.setdefault("pass_rate_ci_upper", pass_rate)
    overall.setdefault("total_input_tokens", 0)
    overall.setdefault("total_output_tokens", 0)
    overall.setdefault("total_reasoning_tokens", 0)
    overall.setdefault("trace_dir", "")
    overall.setdefault("divergence_count", 0)

    tasks = {}
    for task_id, task_data in raw.get("tasks", {}).items():
        t = dict(task_data)
        t.setdefault("passes_per_run", [])
        t.setdefault("input_tokens", 0)
        t.setdefault("output_tokens", 0)
        t.setdefault("reasoning_tokens", 0)
        t.setdefault("harness_url", "")
        t.setdefault("divergence_steps", [])
        tasks[task_id] = t

    return {
        "schema_version": raw.get("schema_version", "1.0.0"),
        "overall": overall,
        "tasks": tasks,
    }


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Aggregate JSONL traces into a frozen bench_summary")
    parser.add_argument("logs_dir", type=Path)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)
    summary = summarize(logs_dir=args.logs_dir)
    out_text = json.dumps(summary, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(out_text, encoding="utf-8")
    else:
        print(out_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
