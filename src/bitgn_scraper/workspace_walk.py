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
    from bitgn.vm.pcm_pb2 import TreeRequest

    tree_resp = pcm.tree(TreeRequest(root="/"))

    records: list[FileRecord] = []
    _collect(pcm, tree_resp.root, "", records)
    return records


def _collect(pcm: Any, entry: Any, prefix: str, out: list[FileRecord]) -> None:
    """Recursive helper. Mutates `out`."""
    from bitgn.vm.pcm_pb2 import ReadRequest
    from connectrpc.errors import ConnectError

    name = entry.name or ""
    path = prefix + ("/" + name if name and name != "/" else "")
    if entry.is_dir:
        for child in entry.children:
            _collect(pcm, child, path, out)
        return

    file_path = path or "/"
    try:
        resp = pcm.read(ReadRequest(path=file_path))
        content_bytes = resp.content.encode("utf-8")
        out.append(FileRecord(
            path=file_path,
            sha256=hashlib.sha256(content_bytes).hexdigest(),
            byte_size=len(content_bytes),
        ))
    except ConnectError:
        out.append(FileRecord(
            path=file_path,
            sha256="READ_ERROR",
            byte_size=0,
        ))
