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
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator, Optional

from bitgn.vm import pcm_pb2


# Phase attribution for pcm_op records. The agent loop sets this around
# each logical phase (prepass, routed_preflight, step:N) so every op the
# underlying PcmRuntimeClientSync sees inherits the label — including
# ops made by preflight_* tools that call the runtime directly.
_pcm_op_origin: ContextVar[Optional[str]] = ContextVar(
    "pcm_op_origin", default=None,
)


@contextmanager
def pcm_origin(label: str) -> Iterator[None]:
    """Attribute all pcm_op records emitted in this block to `label`.

    Nests cleanly via contextvars — resetting on exit restores whatever
    the outer scope had set. Thread-safe because ContextVar is per-task
    in asyncio and copied into new threads at fork time (not relevant
    here since the agent is synchronous, but stated for the record).
    """
    token = _pcm_op_origin.set(label)
    try:
        yield
    finally:
        _pcm_op_origin.reset(token)


def set_pcm_origin(label: str) -> None:
    """Set the origin label for subsequent pcm_op emissions until the
    next call (or the end of the current Context). Use this when the
    code structure doesn't cleanly fit a `with` block — e.g. inside a
    big agent-loop iteration where re-indenting the body would churn
    300 lines. Each iteration overwrites before any op fires, so
    attribution is still precise per-step. The final value leaks to
    whatever runs after, which is fine as long as no PCM ops fire
    post-loop."""
    _pcm_op_origin.set(label)


def origin_bucket(origin: Optional[str]) -> str:
    """Collapse fine-grained origin labels into summary buckets.

    `step:1`, `step:2`, ..., `step:N` all map to "step" so cross-task
    aggregates compare apples to apples — otherwise a 15-step task has
    15 origin keys and a 3-step task has 3, making
    `tasks[*].pcm_ops_by_origin` awkward to roll up.

    `None` maps to "other" so traces from before attribution landed
    (or off-path code that forgets to set origin) still account for
    their ops rather than vanishing from the bucket breakdown.

    This function is the canonical bucketing rule — both bench_summary
    and failure_report import it so their origin categories always
    agree.
    """
    if origin is None:
        return "other"
    if origin.startswith("step:"):
        return "step"
    return origin


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
                origin=_pcm_op_origin.get(),
            )
        except Exception:
            # Tracing must never mask a real PCM error. Drop silently
            # if the writer is closed or raises.
            pass
