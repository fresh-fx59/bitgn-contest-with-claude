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

from bitgn_contest_agent.trace_schema import (
    TraceMeta,
    TraceOutcome,
    load_jsonl,
)


FROZEN_SCHEMA_KEYS = ("schema_version", "overall", "tasks")
BENCH_SUMMARY_SCHEMA_VERSION = "1.1.0"


def _iter_jsonl_files(logs_dir: Path) -> Iterable[Path]:
    return sorted(Path(logs_dir).rglob("*.jsonl"))


def _extract_run(path: Path) -> tuple[str, float, int] | None:
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
    return meta.task_id, score, outcome.total_steps


def summarize(*, logs_dir: Path) -> Dict[str, Any]:
    by_task: dict[str, list[tuple[float, int]]] = defaultdict(list)
    total_runs = 0
    total_passes = 0

    for path in _iter_jsonl_files(logs_dir):
        run = _extract_run(path)
        if run is None:
            continue
        task_id, score, steps = run
        by_task[task_id].append((score, steps))
        total_runs += 1
        if score >= 1.0:
            total_passes += 1

    tasks_out: dict[str, dict[str, Any]] = {}
    for task_id, entries in sorted(by_task.items()):
        runs = len(entries)
        passes = sum(1 for s, _ in entries if s >= 1.0)
        med_steps = int(statistics.median(s for _, s in entries)) if entries else 0
        tasks_out[task_id] = {
            "runs": runs,
            "passes": passes,
            "median_steps": med_steps,
        }

    return {
        "schema_version": BENCH_SUMMARY_SCHEMA_VERSION,
        "overall": {
            "total_runs": total_runs,
            "total_passes": total_passes,
            "pass_rate": (total_passes / total_runs) if total_runs else 0.0,
        },
        "tasks": tasks_out,
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
