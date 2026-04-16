"""TracingPcmClient — a proxy around PcmRuntimeClientSync that writes
one `pcm_op` trace record per runtime call.

Motivation: the BitGN dashboard's "steps" metric counts PCM runtime
ops (list/read/tree/find/search/context/write/...), not LLM iterations
or high-level tool calls. Until we logged this layer, reconciling the
dashboard against a local trace required shuttling screenshots or
pastebins. With this wrapper, the local JSONL trace contains the same
ops in the same order, so `jq 'select(.kind=="pcm_op")' trace.jsonl`
gives you the dashboard view verbatim.

Wrapping the runtime (not the adapter) is load-bearing: preflight_*
tools receive the runtime directly and make raw `client.list()` /
`client.read()` calls that bypass PcmAdapter.dispatch. Tracing at the
adapter would miss those.
"""
from __future__ import annotations

import time
from typing import Any, Optional

from bitgn.vm import pcm_pb2


def _response_bytes(resp: Any) -> int:
    """Wire-byte size of a proto response. Matches how the dashboard
    would measure payload size. Returns 0 on non-proto objects."""
    try:
        return int(resp.ByteSize())
    except Exception:
        return 0


def _classify_exception(exc: BaseException) -> str:
    """Same buckets as PcmAdapter._classify_exception — kept local so
    the wrapper has no circular import on the adapter."""
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


# Map request proto type → (op label, attribute to extract as `path`).
# For Move, we compose "from → to" at call time.
_REQUEST_PATH_ATTR: dict[type, tuple[str, Optional[str]]] = {
    pcm_pb2.ReadRequest: ("read", "path"),
    pcm_pb2.WriteRequest: ("write", "path"),
    pcm_pb2.DeleteRequest: ("delete", "path"),
    pcm_pb2.MkDirRequest: ("mk_dir", "path"),
    pcm_pb2.ListRequest: ("list", "name"),
    pcm_pb2.TreeRequest: ("tree", "root"),
    pcm_pb2.FindRequest: ("find", "root"),
    pcm_pb2.SearchRequest: ("search", "root"),
    pcm_pb2.ContextRequest: ("context", None),
    pcm_pb2.AnswerRequest: ("answer", None),
}


class TracingPcmClient:
    """Drop-in replacement for `PcmRuntimeClientSync` that records
    every call to a `TraceWriter`. Methods mirror the underlying
    client; unknown attributes are delegated verbatim so future PCM
    methods work without a wrapper update (they just won't be traced).
    """

    def __init__(self, runtime: Any, *, writer: Any = None) -> None:
        self._runtime = runtime
        self._writer = writer

    def set_writer(self, writer: Any) -> None:
        """Attach a writer after construction. Ops dispatched before
        a writer is attached are silently not traced — the caller is
        responsible for wiring early enough. Used when the writer
        depends on task_id which is only known after start_trial."""
        self._writer = writer

    # -- traced proxies --------------------------------------------------

    def read(self, req: "pcm_pb2.ReadRequest") -> Any:
        return self._traced(req, self._runtime.read)

    def write(self, req: "pcm_pb2.WriteRequest") -> Any:
        return self._traced(req, self._runtime.write)

    def delete(self, req: "pcm_pb2.DeleteRequest") -> Any:
        return self._traced(req, self._runtime.delete)

    def mk_dir(self, req: "pcm_pb2.MkDirRequest") -> Any:
        return self._traced(req, self._runtime.mk_dir)

    def move(self, req: "pcm_pb2.MoveRequest") -> Any:
        path = f"{getattr(req, 'from_name', '')} → {getattr(req, 'to_name', '')}"
        return self._traced(req, self._runtime.move, op="move", path=path)

    def list(self, req: "pcm_pb2.ListRequest") -> Any:
        return self._traced(req, self._runtime.list)

    def tree(self, req: "pcm_pb2.TreeRequest") -> Any:
        return self._traced(req, self._runtime.tree)

    def find(self, req: "pcm_pb2.FindRequest") -> Any:
        return self._traced(req, self._runtime.find)

    def search(self, req: "pcm_pb2.SearchRequest") -> Any:
        return self._traced(req, self._runtime.search)

    def context(self, req: "pcm_pb2.ContextRequest") -> Any:
        return self._traced(req, self._runtime.context)

    def answer(self, req: "pcm_pb2.AnswerRequest") -> Any:
        return self._traced(req, self._runtime.answer)

    # -- unknown method passthrough --------------------------------------

    def __getattr__(self, name: str) -> Any:
        """Delegate any attribute we don't explicitly wrap. Do NOT use
        for `_runtime`/`_writer` — those are set in __init__ and hit
        __getattribute__ first."""
        return getattr(self._runtime, name)

    # -- internals -------------------------------------------------------

    def _traced(
        self,
        req: Any,
        method: Any,
        *,
        op: Optional[str] = None,
        path: Optional[str] = None,
    ) -> Any:
        resolved_op, resolved_path = self._resolve(req, op, path)
        start = time.monotonic()
        try:
            resp = method(req)
        except BaseException as exc:
            wall_ms = int((time.monotonic() - start) * 1000)
            self._emit(
                op=resolved_op,
                path=resolved_path,
                bytes_=0,
                wall_ms=wall_ms,
                ok=False,
                error_code=_classify_exception(exc),
            )
            raise
        wall_ms = int((time.monotonic() - start) * 1000)
        self._emit(
            op=resolved_op,
            path=resolved_path,
            bytes_=_response_bytes(resp),
            wall_ms=wall_ms,
            ok=True,
            error_code=None,
        )
        return resp

    def _resolve(
        self, req: Any, op: Optional[str], path: Optional[str],
    ) -> tuple[str, Optional[str]]:
        if op is not None:
            return op, path
        entry = _REQUEST_PATH_ATTR.get(type(req))
        if entry is None:
            return type(req).__name__, path
        op_label, path_attr = entry
        if path_attr is None:
            return op_label, path
        return op_label, getattr(req, path_attr, None) or None

    def _emit(
        self,
        *,
        op: str,
        path: Optional[str],
        bytes_: int,
        wall_ms: int,
        ok: bool,
        error_code: Optional[str],
    ) -> None:
        w = self._writer
        if w is None:
            return
        try:
            w.append_pcm_op(
                op=op,
                path=path,
                bytes=bytes_,
                wall_ms=wall_ms,
                ok=ok,
                error_code=error_code,
            )
        except Exception:
            # Tracing must never mask a real PCM error. Drop silently
            # if the writer is closed or raises.
            pass
