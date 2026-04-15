"""Workspace role discovery — identifies which directories hold inbox,
entities, finance, projects, outbox, rulebook, workflows, schemas by
inspecting frontmatter signatures of the files inside.

Path-agnostic: no directory name is hardcoded. Discovery is by content
signature only.
"""
from __future__ import annotations

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
        # Tree walk from root. Depth cap prevents runaway on big workspaces.
        req = pcm_pb2.TreeRequest(path="", max_depth=4)
        tree_resp = client.Tree(req)
        dirs = sorted({entry.path.rsplit("/", 1)[0] for entry in tree_resp.entries if entry.path.endswith(".md")})
        for d in dirs:
            if not d:
                continue
            list_resp = client.List(pcm_pb2.ListRequest(path=d))
            md_names = [e.name for e in list_resp.entries if e.name.endswith(".md")][:50]
            frontmatters = []
            for name in md_names:
                read_resp = client.Read(pcm_pb2.ReadRequest(path=f"{d}/{name}"))
                frontmatters.append(_parse_frontmatter(read_resp.content))
            roles = _classify_dir(frontmatters)
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
