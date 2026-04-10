"""Task-level parallelism + cooperative cancel.

Uses ThreadPoolExecutor because the backend interface is synchronous and
the throughput bottleneck is cliproxyapi, not local CPU.

§3.1, §3.2, §4.2 invariant 1 (worker boundary uses except Exception).
"""
from __future__ import annotations

import concurrent.futures as cf
import logging
import threading
import time
import traceback
from dataclasses import dataclass
from typing import Callable, List, Optional, Sequence


_LOG = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TaskSpec:
    task_id: str
    task_index: int
    task_text: str


@dataclass(frozen=True, slots=True)
class TaskExecutionResult:
    task_id: str
    score: float
    terminated_by: str
    error_kind: Optional[str]
    error_msg: Optional[str]


TaskRunner = Callable[[TaskSpec, threading.Event], TaskExecutionResult]


class Orchestrator:
    def __init__(
        self,
        *,
        runner: TaskRunner,
        max_parallel_tasks: int,
        task_timeout_sec: int,
        task_timeout_grace_sec: int = 20,
    ) -> None:
        self._runner = runner
        self._max_parallel_tasks = max_parallel_tasks
        self._task_timeout_sec = task_timeout_sec
        self._grace_sec = task_timeout_grace_sec

    def run(self, tasks: Sequence[TaskSpec]) -> List[TaskExecutionResult]:
        results: List[TaskExecutionResult] = [None] * len(tasks)  # type: ignore[list-item]
        cancel_events: dict[int, threading.Event] = {i: threading.Event() for i in range(len(tasks))}

        with cf.ThreadPoolExecutor(max_workers=self._max_parallel_tasks) as pool:
            futures = {
                pool.submit(self._wrap_runner, tasks[i], cancel_events[i]): i
                for i in range(len(tasks))
            }
            start_times = {futures[f]: time.monotonic() for f in futures}
            deadlines = {
                i: (start_times[i] + self._task_timeout_sec) if self._task_timeout_sec > 0 else None
                for i in range(len(tasks))
            }

            pending = set(futures.keys())
            while pending:
                done, pending = cf.wait(
                    pending, timeout=0.25, return_when=cf.FIRST_COMPLETED
                )
                # Fire deadlines.
                now = time.monotonic()
                for fut, idx in list(futures.items()):
                    dl = deadlines[idx]
                    if dl is not None and now >= dl and not fut.done():
                        cancel_events[idx].set()
                        # Extend the future's effective deadline by grace
                        # so the worker can flush its trace.
                        deadlines[idx] = dl + self._grace_sec
                for fut in done:
                    idx = futures[fut]
                    try:
                        results[idx] = fut.result()
                    except Exception as exc:
                        results[idx] = TaskExecutionResult(
                            task_id=tasks[idx].task_id,
                            score=0.0,
                            terminated_by="error",
                            error_kind="INTERNAL_CRASH",
                            error_msg=f"{type(exc).__name__}: {exc}",
                        )
        return [r for r in results if r is not None]

    def _wrap_runner(self, task: TaskSpec, cancel_event: threading.Event) -> TaskExecutionResult:
        try:
            return self._runner(task, cancel_event)
        except Exception as exc:
            _LOG.exception("worker crashed on task %s", task.task_id)
            return TaskExecutionResult(
                task_id=task.task_id,
                score=0.0,
                terminated_by="error",
                error_kind="INTERNAL_CRASH",
                error_msg=f"{type(exc).__name__}: {exc}",
            )
