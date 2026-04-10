"""Single-class adapter between Pydantic Req_* models and the official
bitgn PcmRuntimeClientSync. Every other layer is adapter-agnostic.

The adapter is the ONLY place in the project that imports bitgn.vm.pcm_pb2
or bitgn.vm.pcm_connect. Anywhere else that references bitgn is a smell
to be fixed.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Sequence, Tuple

from bitgn.vm import pcm_pb2
from bitgn.vm.pcm_connect import PcmRuntimeClientSync

from bitgn_contest_agent.schemas import (
    ReportTaskCompletion,
    Req_Context,
    Req_Delete,
    Req_Find,
    Req_List,
    Req_MkDir,
    Req_Move,
    Req_Read,
    Req_Search,
    Req_Tree,
    Req_Write,
)


@dataclass(frozen=True, slots=True)
class ToolResult:
    ok: bool
    content: str
    refs: Tuple[str, ...]
    error: str | None
    error_code: str | None
    wall_ms: int
    truncated: bool = False
    original_bytes: int = 0

    @property
    def bytes(self) -> int:
        return len(self.content.encode("utf-8", errors="replace"))


class PcmAdapter:
    def __init__(
        self,
        *,
        runtime: PcmRuntimeClientSync,
        max_tool_result_bytes: int,
    ) -> None:
        self._runtime = runtime
        self._max_bytes = max_tool_result_bytes

    # Task 9 implements these. Task 10 implements run_prepass.
    def dispatch(self, req: Any) -> ToolResult:  # noqa: ARG002 — filled in T9
        raise NotImplementedError

    def run_prepass(self, *, session: Any, trace_writer: Any) -> None:  # noqa: ARG002 — filled in T10
        raise NotImplementedError

    def submit_terminal(self, completion: ReportTaskCompletion) -> ToolResult:  # filled in T9
        raise NotImplementedError
