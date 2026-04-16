"""Workspace role discovery — identifies which directories hold inbox,
entities, finance, projects, outbox, rulebook, workflows, schemas by
inspecting frontmatter signatures of the files inside.

Path-agnostic: no directory name is hardcoded. Discovery is by content
signature only.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional

from bitgn_contest_agent.adapter.pcm import ToolResult
from bitgn_contest_agent.preflight.response import build_response


_LOG = logging.getLogger(__name__)

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

# Minimum fraction of files in a directory that must match the signature
# for the directory to be tagged with that role.
_MATCH_THRESHOLD = 0.3


@dataclass
class WorkspaceSchema:
    inbox_root: Optional[str] = None
    entities_root: Optional[str] = None
    finance_roots: List[str] = field(default_factory=list)
    projects_root: Optional[str] = None
    outbox_root: Optional[str] = None
    rulebook_root: Optional[str] = None
    workflows_root: Optional[str] = None
    schemas_root: Optional[str] = None
    errors: List[str] = field(default_factory=list)

    def summary(self) -> str:
        parts = []
        if self.inbox_root:
            parts.append(f"inbox at {self.inbox_root}")
        if self.entities_root:
            parts.append(f"entities at {self.entities_root}")
        if self.finance_roots:
            parts.append(f"{len(self.finance_roots)} finance root(s)")
        if self.projects_root:
            parts.append(f"projects at {self.projects_root}")
        if self.outbox_root:
            parts.append(f"outbox at {self.outbox_root}")
        extras = [r for r in (self.rulebook_root, self.workflows_root, self.schemas_root) if r]
        if extras:
            parts.append(f"{len(extras)} doc root(s)")
        return "Workspace schema: " + ", ".join(parts) + "."

    def as_data(self) -> dict[str, Any]:
        return {
            "inbox_root": self.inbox_root,
            "entities_root": self.entities_root,
            "finance_roots": self.finance_roots,
            "projects_root": self.projects_root,
            "outbox_root": self.outbox_root,
            "rulebook_root": self.rulebook_root,
            "workflows_root": self.workflows_root,
            "schemas_root": self.schemas_root,
            "errors": self.errors,
        }


def _parse_frontmatter(text: str) -> dict[str, str]:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}
    body = m.group(1)
    out: dict[str, str] = {}
    for line in body.splitlines():
        if ":" in line and not line.startswith(" "):
            k, _, v = line.partition(":")
            out[k.strip().lower()] = v.strip()
    return out


def _classify_dir(frontmatters: list[dict[str, str]]) -> list[str]:
    """Return a list of role labels this directory's contents match.

    A directory can have multiple roles only if more than one signature
    trips the threshold — in practice each dir gets one dominant role.
    """
    if not frontmatters:
        return []
    n = len(frontmatters)

    def frac(pred) -> float:
        return sum(1 for fm in frontmatters if pred(fm)) / n

    roles = []
    if frac(lambda fm: "inbox_type" in fm or "inbox_kind" in fm) >= _MATCH_THRESHOLD:
        roles.append("inbox")
    if frac(lambda fm: "aliases" in fm or ("role" in fm and "relationship" not in fm) or "relationship" in fm) >= _MATCH_THRESHOLD:
        roles.append("entities")
    if frac(lambda fm: "vendor" in fm or "eur_total" in fm or "line_items" in fm) >= _MATCH_THRESHOLD:
        roles.append("finance")
    if frac(lambda fm: "project" in fm and ("start_date" in fm or "members" in fm)) >= _MATCH_THRESHOLD:
        roles.append("projects")
    if frac(lambda fm: "to" in fm and "subject" in fm) >= _MATCH_THRESHOLD:
        roles.append("outbox")
    return roles


def _classify_dir_by_content(contents: list[str]) -> list[str]:
    """Fallback classifier for PAC1 PROD-style workspaces where records
    use markdown bullet lists or ASCII `| record_type | ... |` tables
    instead of YAML frontmatter.

    Runs on the raw file content and looks for canonical field markers
    that appear verbatim in the dataset. Returns the same role labels
    `_classify_dir` produces.
    """
    if not contents:
        return []
    n = len(contents)

    def frac(pred) -> float:
        return sum(1 for c in contents if pred(c)) / n

    roles = []
    if frac(lambda c: "record_type" in c and "inbox" in c) >= _MATCH_THRESHOLD:
        roles.append("inbox")
    if frac(lambda c: "- alias:" in c or "- relationship:" in c or "- aliases:" in c) >= _MATCH_THRESHOLD:
        roles.append("entities")
    if frac(
        lambda c: (
            ("record_type" in c and "invoice" in c)
            or ("record_type" in c and "bill" in c)
            or "eur_total" in c
            or "| vendor" in c
        )
    ) >= _MATCH_THRESHOLD:
        roles.append("finance")
    if frac(
        lambda c: (
            ("record_type" in c and "project" in c)
            or ("project" in c and ("- members:" in c or "- start_date:" in c))
        )
    ) >= _MATCH_THRESHOLD:
        roles.append("projects")
    if frac(
        lambda c: (
            ("record_type" in c and ("outbox" in c or "message" in c))
            or ("- to:" in c and "- subject:" in c)
        )
    ) >= _MATCH_THRESHOLD:
        roles.append("outbox")
    return roles


def discover_schema_from_fs(root: Path) -> WorkspaceSchema:
    """Filesystem-based discovery — used for local tests and as the
    core implementation that the PCM-backed version wraps.
    """
    schema = WorkspaceSchema()
    root = Path(root)
    if not root.exists():
        schema.errors.append(f"root does not exist: {root}")
        return schema

    for dirpath in sorted(p for p in root.rglob("*") if p.is_dir()):
        md_files = [f for f in dirpath.iterdir() if f.is_file() and f.suffix == ".md"]
        if not md_files:
            continue
        frontmatters = []
        for f in md_files[:50]:  # cap per dir for speed
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
                frontmatters.append(_parse_frontmatter(text))
            except OSError as exc:
                schema.errors.append(f"read failed {f}: {exc}")

        roles = _classify_dir(frontmatters)
        rel = str(dirpath.relative_to(root))
        for role in roles:
            if role == "inbox" and schema.inbox_root is None:
                schema.inbox_root = rel
            elif role == "entities" and schema.entities_root is None:
                schema.entities_root = rel
            elif role == "finance":
                if rel not in schema.finance_roots:
                    schema.finance_roots.append(rel)
            elif role == "projects" and schema.projects_root is None:
                schema.projects_root = rel
            elif role == "outbox" and schema.outbox_root is None:
                schema.outbox_root = rel

    return schema


def run_preflight_schema(client: Any, workspace_ctx: Any) -> ToolResult:
    """PCM-backed entry point. Walks the workspace via the PCM list/tree
    RPC, parses frontmatters via read RPC, returns a ToolResult.

    `workspace_ctx` carries the root path or handle the adapter uses to
    talk to PCM. For the PCM client the adapter will pass `client`'s own
    workspace root.
    """
    from bitgn.vm import pcm_pb2  # local import to keep schema module light

    schema = WorkspaceSchema()
    try:
        # Tree walk from root. TreeResponse.root is a recursive TreeEntry
        # with (name, is_dir, children). Walk it to collect directories
        # that contain .md files, then list+read each to classify.
        tree_resp = client.tree(pcm_pb2.TreeRequest(root="/"))
        dirs: list[str] = []

        def _walk(entry, prefix: str) -> None:
            path = (
                f"{prefix}/{entry.name}".lstrip("/")
                if entry.name
                else prefix.lstrip("/")
            )
            if entry.is_dir:
                has_md = any(
                    c.name.endswith(".md") and not c.is_dir
                    for c in entry.children
                )
                if has_md and path:
                    dirs.append(path)
                for c in entry.children:
                    _walk(c, path)

        _walk(tree_resp.root, "")
        dirs.sort()
        for d in dirs:
            list_resp = client.list(pcm_pb2.ListRequest(name=d))
            md_names = [
                e.name for e in list_resp.entries
                if e.name.endswith(".md") and not e.is_dir
            ][:50]
            frontmatters = []
            raw_contents: list[str] = []
            for name in md_names:
                read_resp = client.read(
                    pcm_pb2.ReadRequest(path=f"{d}/{name}")
                )
                frontmatters.append(_parse_frontmatter(read_resp.content))
                raw_contents.append(read_resp.content)
            roles = _classify_dir(frontmatters)
            if not roles:
                # Fall back to content-based classification for PAC1 PROD.
                roles = _classify_dir_by_content(raw_contents)
            for role in roles:
                if role == "inbox" and schema.inbox_root is None:
                    schema.inbox_root = d
                elif role == "entities" and schema.entities_root is None:
                    schema.entities_root = d
                elif role == "finance":
                    if d not in schema.finance_roots:
                        schema.finance_roots.append(d)
                elif role == "projects" and schema.projects_root is None:
                    schema.projects_root = d
                elif role == "outbox" and schema.outbox_root is None:
                    schema.outbox_root = d
    except Exception as exc:
        schema.errors.append(f"pcm walk failed: {exc}")

    content = build_response(summary=schema.summary(), data=schema.as_data())
    return ToolResult(
        ok=True,
        content=content,
        refs=tuple(),
        error=None,
        error_code=None,
        wall_ms=0,
    )


def parse_schema_content(content: Optional[str]) -> WorkspaceSchema:
    """Reverse of build_response — parse a preflight_schema content
    string back into a typed WorkspaceSchema. Returns an empty
    WorkspaceSchema on any parse failure (treat as 'no roots discovered').
    """
    if not content:
        return WorkspaceSchema()
    try:
        envelope = json.loads(content)
    except (ValueError, TypeError):
        return WorkspaceSchema()
    if not isinstance(envelope, dict):
        return WorkspaceSchema()
    data = envelope.get("data")
    if not isinstance(data, dict):
        return WorkspaceSchema()

    def _s(v):
        return v if isinstance(v, str) and v else None

    finance_raw = data.get("finance_roots") or []
    if isinstance(finance_raw, str):
        finance_roots = [finance_raw]
    elif isinstance(finance_raw, list):
        finance_roots = [str(x) for x in finance_raw if isinstance(x, str) and x]
    else:
        finance_roots = []

    errors_raw = data.get("errors") or []
    errors = [str(e) for e in errors_raw if isinstance(e, str) and e] if isinstance(errors_raw, list) else []

    return WorkspaceSchema(
        inbox_root=_s(data.get("inbox_root")),
        entities_root=_s(data.get("entities_root")),
        finance_roots=finance_roots,
        projects_root=_s(data.get("projects_root")),
        outbox_root=_s(data.get("outbox_root")),
        rulebook_root=_s(data.get("rulebook_root")),
        workflows_root=_s(data.get("workflows_root")),
        schemas_root=_s(data.get("schemas_root")),
        errors=errors,
    )
