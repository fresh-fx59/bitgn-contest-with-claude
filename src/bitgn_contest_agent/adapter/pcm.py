"""Single-class adapter between Pydantic Req_* models and the official
bitgn PcmRuntimeClientSync. Every other layer is adapter-agnostic.

The adapter is the ONLY place in the project that imports bitgn.vm.pcm_pb2
or bitgn.vm.pcm_connect. Anywhere else that references bitgn is a smell
to be fixed.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Sequence, Tuple

from bitgn.vm import pcm_pb2
from bitgn.vm.pcm_connect import PcmRuntimeClientSync

from bitgn_contest_agent.schemas import (
    NextStep,  # noqa: F401 — used by T10 type hints
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

_LOG = logging.getLogger(__name__)


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


def _response_to_text(resp: Any) -> str:
    """Extract a printable representation of any pcm_pb2 response.

    Generated proto messages are not JSON-serializable out of the box, so
    we use the protobuf MessageToJson helper + a plain string fallback.

    Special case: `SearchResponse` gets a `total_matches` field stamped
    at the very top of the JSON body — ahead of the `matches` array —
    so counting tasks survive response truncation. `_finish` may still
    cut the tail of the matches list, but the count is written in the
    first ~30 bytes and cannot be lost.
    """
    try:
        if isinstance(resp, pcm_pb2.SearchResponse):
            return _search_response_to_text(resp)
        from google.protobuf.json_format import MessageToJson

        return MessageToJson(resp, preserving_proto_field_name=True, indent=None)
    except Exception:
        return str(resp)


def _search_response_to_text(resp: "pcm_pb2.SearchResponse") -> str:
    """Serialize a SearchResponse with a truncation-proof total_matches header.

    The canonical `MessageToJson` shape is `{"matches": [...]}` which
    buries the count behind an arbitrarily long array. We invert it:
    `{"total_matches": N, "matches": [...]}`. The count is an exact
    lower-bound (equal to `len(resp.matches)` at the moment the adapter
    received the response) — it is exact when the caller's `limit` was
    not reached and a lower bound when it was. Client code should treat
    `total_matches == limit` as "possibly more; raise limit or subdivide".
    """
    import json as _json

    matches_obj = [
        {"path": m.path, "line": m.line, "line_text": m.line_text}
        for m in resp.matches
    ]
    payload = {"total_matches": len(matches_obj), "matches": matches_obj}
    return _json.dumps(payload, separators=(", ", ": "))


_FIND_TYPE_MAP: Dict[str, int] = {
    "TYPE_ALL": pcm_pb2.FindRequest.TYPE_ALL,
    "TYPE_FILES": pcm_pb2.FindRequest.TYPE_FILES,
    "TYPE_DIRS": pcm_pb2.FindRequest.TYPE_DIRS,
}


_OUTCOME_MAP: Dict[str, int] = {
    "OUTCOME_OK": pcm_pb2.OUTCOME_OK,
    "OUTCOME_DENIED_SECURITY": pcm_pb2.OUTCOME_DENIED_SECURITY,
    "OUTCOME_NONE_CLARIFICATION": pcm_pb2.OUTCOME_NONE_CLARIFICATION,
    "OUTCOME_NONE_UNSUPPORTED": pcm_pb2.OUTCOME_NONE_UNSUPPORTED,
    "OUTCOME_ERR_INTERNAL": pcm_pb2.OUTCOME_ERR_INTERNAL,
}


class PcmAdapter:
    def __init__(
        self,
        *,
        runtime: PcmRuntimeClientSync,
        max_tool_result_bytes: int,
    ) -> None:
        self._runtime = runtime
        self._max_bytes = max_tool_result_bytes

    # -- dispatch ---------------------------------------------------------

    def dispatch(self, req: Any) -> ToolResult:
        start = time.monotonic()
        try:
            if isinstance(req, Req_Read):
                resp = self._runtime.read(pcm_pb2.ReadRequest(path=req.path))
                return self._finish(start, resp, refs=(req.path,))
            if isinstance(req, Req_Write):
                resp = self._runtime.write(
                    pcm_pb2.WriteRequest(path=req.path, content=req.content)
                )
                return self._finish(start, resp, refs=())
            if isinstance(req, Req_Delete):
                resp = self._runtime.delete(pcm_pb2.DeleteRequest(path=req.path))
                return self._finish(start, resp, refs=())
            if isinstance(req, Req_MkDir):
                resp = self._runtime.mk_dir(pcm_pb2.MkDirRequest(path=req.path))
                return self._finish(start, resp, refs=())
            if isinstance(req, Req_Move):
                resp = self._runtime.move(
                    pcm_pb2.MoveRequest(from_name=req.from_name, to_name=req.to_name)
                )
                return self._finish(start, resp, refs=())
            if isinstance(req, Req_List):
                resp = self._runtime.list(pcm_pb2.ListRequest(name=req.name))
                return self._finish(start, resp, refs=())
            if isinstance(req, Req_Tree):
                resp = self._runtime.tree(pcm_pb2.TreeRequest(root=req.root))
                return self._finish(start, resp, refs=())
            if isinstance(req, Req_Find):
                resp = self._runtime.find(
                    pcm_pb2.FindRequest(
                        root=req.root,
                        name=req.name,
                        type=_FIND_TYPE_MAP[req.type],
                        limit=req.limit,
                    )
                )
                return self._finish(start, resp, refs=())
            if isinstance(req, Req_Search):
                resp = self._runtime.search(
                    pcm_pb2.SearchRequest(
                        root=req.root, pattern=req.pattern, limit=req.limit
                    )
                )
                return self._finish(start, resp, refs=())
            if isinstance(req, Req_Context):
                resp = self._runtime.context(pcm_pb2.ContextRequest())
                return self._finish(start, resp, refs=())
            raise TypeError(f"unsupported request type: {type(req).__name__}")
        except Exception as exc:
            wall_ms = int((time.monotonic() - start) * 1000)
            return ToolResult(
                ok=False,
                content="",
                refs=(),
                error=str(exc),
                error_code=self._classify_exception(exc),
                wall_ms=wall_ms,
            )

    def submit_terminal(self, completion: ReportTaskCompletion) -> ToolResult:
        start = time.monotonic()
        try:
            resp = self._runtime.answer(
                pcm_pb2.AnswerRequest(
                    message=completion.message,
                    outcome=_OUTCOME_MAP[completion.outcome],
                    refs=list(completion.grounding_refs),
                )
            )
            return self._finish(start, resp, refs=tuple(completion.grounding_refs))
        except Exception as exc:
            wall_ms = int((time.monotonic() - start) * 1000)
            return ToolResult(
                ok=False,
                content="",
                refs=(),
                error=str(exc),
                error_code=self._classify_exception(exc),
                wall_ms=wall_ms,
            )

    def run_prepass(self, *, session: Any, trace_writer: Any) -> None:
        """Best-effort identity bootstrap.

        Attempts tree(/), read(AGENTS.md), context(). Each failure is
        recorded and proceeds to the next call — identity_loaded flips
        true on ANY success. Per §1 the session is task-local, and the
        trace writer captures every attempt for the analyzer.
        """
        pre_cmds = [
            ("tree", Req_Tree(tool="tree", root="/")),
            ("read_agents_md", Req_Read(tool="read", path="AGENTS.md")),
            ("context", Req_Context(tool="context")),
        ]
        for label, req in pre_cmds:
            result = self.dispatch(req)
            if result.ok:
                session.identity_loaded = True
                if label == "read_agents_md":
                    session.rulebook_loaded = True
                for ref in result.refs:
                    session.seen_refs.add(ref)
            trace_writer.append_prepass(
                cmd=label,
                ok=result.ok,
                bytes=result.bytes,
                wall_ms=result.wall_ms,
                error=result.error,
                error_code=result.error_code,
            )

    # -- helpers ----------------------------------------------------------

    def _finish(
        self,
        start: float,
        resp: Any,
        *,
        refs: Tuple[str, ...],
    ) -> ToolResult:
        text = _response_to_text(resp)
        encoded = text.encode("utf-8", errors="replace")
        original_bytes = len(encoded)
        truncated = False
        if original_bytes > self._max_bytes:
            encoded = encoded[: self._max_bytes]
            text = encoded.decode("utf-8", errors="replace")
            truncated = True
        wall_ms = int((time.monotonic() - start) * 1000)
        return ToolResult(
            ok=True,
            content=text,
            refs=refs,
            error=None,
            error_code=None,
            wall_ms=wall_ms,
            truncated=truncated,
            original_bytes=original_bytes if truncated else 0,
        )

    def _classify_exception(self, exc: Exception) -> str:
        name = type(exc).__name__
        if "Deadline" in name or "Timeout" in name:
            return "RPC_DEADLINE"
        if "Unavailable" in name or "Connection" in name:
            return "RPC_UNAVAILABLE"
        if "InvalidArgument" in name or isinstance(exc, (TypeError, ValueError)):
            return "INVALID_ARG"
        if "PcmError" in name:
            return "PCM_ERROR"
        return "UNKNOWN"
