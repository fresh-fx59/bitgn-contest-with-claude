"""Walk a live PCM workspace and produce FileRecord rows.

Used by Phase 1 (initial scrape) and Phase 3 (integrity check).
A file that fails to read is recorded with byte_size=0, sha256='READ_ERROR'
so the scrape doesn't abort on a single bad file.
"""
from __future__ import annotations

import hashlib
from typing import Any

from bitgn_scraper.fingerprint import FileRecord


def walk_workspace(pcm: Any) -> list[FileRecord]:
    """Return a FileRecord per file in the workspace rooted at /."""
    from bitgn.vm.pcm_pb2 import ReadRequest, TreeRequest
    from connectrpc.errors import ConnectError

    tree_resp = pcm.tree(TreeRequest(root="/"))

    records: list[FileRecord] = []
    _collect(pcm, tree_resp.root, "", records, ConnectError)
    return records


def _collect(pcm: Any, entry: Any, prefix: str, out: list[FileRecord], rpc_error: type) -> None:
    """Recursive helper. Mutates `out`."""
    name = entry.name or ""
    path = prefix + ("/" + name if name and name != "/" else "")
    if entry.is_dir:
        for child in entry.children:
            _collect(pcm, child, path, out, rpc_error)
        return

    from bitgn.vm.pcm_pb2 import ReadRequest

    file_path = path or "/"
    try:
        resp = pcm.read(ReadRequest(path=file_path))
        content_bytes = resp.content.encode("utf-8")
        out.append(FileRecord(
            path=file_path,
            sha256=hashlib.sha256(content_bytes).hexdigest(),
            byte_size=len(content_bytes),
        ))
    except (rpc_error, KeyError, OSError):
        out.append(FileRecord(
            path=file_path,
            sha256="READ_ERROR",
            byte_size=0,
        ))
