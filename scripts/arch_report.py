#!/usr/bin/env python3
"""arch_report — print architecture decision timelines from trace JSONL.

Usage:
    arch_report.py <jsonl>                          one task timeline
    arch_report.py <run-dir>                        all tasks in dir
    arch_report.py <run-dir> --task t100            single task
    arch_report.py <run-dir> --category VALIDATOR_T2
    arch_report.py <run-dir> --category VALIDATOR_T2 --trigger first_transition

Enums come from bitgn_contest_agent.arch_constants — renaming a member
propagates here for free via argparse's `choices=list(Enum)`.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable

# repo root on path so this script runs from the checkout
_here = Path(__file__).resolve()
_repo_root = _here.parent.parent
if str(_repo_root / "src") not in sys.path:
    sys.path.insert(0, str(_repo_root / "src"))

from bitgn_contest_agent.arch_constants import (  # noqa: E402
    ArchCategory,
    ArchResult,
    RouterSource,
    ValidatorT1Rule,
    ValidatorT2Trigger,
)
from bitgn_contest_agent.trace_schema import (  # noqa: E402
    TraceArch,
    TraceMeta,
    load_jsonl,
)


def _iter_trace_files(path: Path) -> Iterable[Path]:
    if path.is_file():
        yield path
    elif path.is_dir():
        yield from sorted(path.rglob("*.jsonl"))
    else:
        raise FileNotFoundError(path)


def _format_row(trace_name: str, rec: TraceArch) -> str:
    step = "-" if rec.at_step is None else str(rec.at_step)
    parts: list[str] = [f"{trace_name:<30}", f"step={step:<4}",
                        f"{rec.category.value:<20}"]
    for key in ("rule", "trigger", "result", "skill", "source"):
        val = getattr(rec, key)
        if val is not None:
            parts.append(f"{key}={val.value if hasattr(val, 'value') else val}")
    if rec.confidence is not None:
        parts.append(f"conf={rec.confidence:.2f}")
    if rec.details:
        parts.append(f"details={rec.details[:80]}")
    return " ".join(parts)


def _matches(rec: TraceArch, args: argparse.Namespace) -> bool:
    if args.category is not None and rec.category != args.category:
        return False
    if args.rule is not None and rec.rule != args.rule:
        return False
    if args.trigger is not None and rec.trigger != args.trigger:
        return False
    if args.result is not None and rec.result != args.result:
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="arch_report",
        description="Print arch observability timeline from trace JSONL(s)",
    )
    parser.add_argument("path", help="JSONL file or run directory")
    parser.add_argument("--task", default=None, help="task_id filter")
    parser.add_argument(
        "--category", type=ArchCategory, choices=list(ArchCategory),
        default=None,
    )
    parser.add_argument(
        "--rule", type=ValidatorT1Rule, choices=list(ValidatorT1Rule),
        default=None,
    )
    parser.add_argument(
        "--trigger", type=ValidatorT2Trigger, choices=list(ValidatorT2Trigger),
        default=None,
    )
    parser.add_argument(
        "--result", type=ArchResult, choices=list(ArchResult),
        default=None,
    )
    args = parser.parse_args(argv)

    for p in _iter_trace_files(Path(args.path)):
        meta: TraceMeta | None = None
        records: list[TraceArch] = []
        try:
            for rec in load_jsonl(p):
                if isinstance(rec, TraceMeta):
                    meta = rec
                elif isinstance(rec, TraceArch):
                    records.append(rec)
        except (ValueError, Exception) as exc:
            print(f"# skip {p.name}: {exc}", file=sys.stderr)
            continue
        if meta is None:
            continue
        if args.task is not None and meta.task_id != args.task:
            continue
        # Header line per trace with intent preview
        if meta.intent_head:
            print(f"# {p.name}  task={meta.task_id}  intent={meta.intent_head[:100]!r}")
        else:
            print(f"# {p.name}  task={meta.task_id}")
        for rec in records:
            if _matches(rec, args):
                print(_format_row(p.name, rec))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
