"""preflight_project — locates a project record and returns its
metadata + entities involved (members).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from bitgn_contest_agent.adapter.pcm import ToolResult
from bitgn_contest_agent.preflight.canonicalize import normalize_name
from bitgn_contest_agent.preflight.response import build_response
from bitgn_contest_agent.preflight.schema import _parse_frontmatter
from bitgn_contest_agent.schemas import Req_PreflightProject


def _find_project(projects_dir: Path, query: str) -> dict[str, Any] | None:
    if not projects_dir.exists():
        return None
    q_norm = normalize_name(query)
    for f in projects_dir.rglob("*.md"):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        fm = _parse_frontmatter(text)
        pname = fm.get("project", "")
        if pname and (normalize_name(pname) == q_norm or q_norm in normalize_name(pname) or normalize_name(pname) in q_norm):
            return {
                "name": pname,
                "start_date": fm.get("start_date", ""),
                "members": fm.get("members", ""),
                "file": str(f),
                "frontmatter": fm,
            }
    return None


def run_project_from_fs(
    root: Path, projects_root: str, entities_root: str, query: str,
) -> dict[str, Any]:
    root = Path(root)
    proj = _find_project(root / projects_root, query)
    return {"project": proj, "involved_entities": []}


def run_preflight_project(client: Any, req: Req_PreflightProject) -> ToolResult:
    from bitgn.vm import pcm_pb2
    try:
        q_norm = normalize_name(req.query)
        found = None
        lresp = client.List(pcm_pb2.ListRequest(path=req.projects_root))
        for e in lresp.entries:
            if not e.name.endswith(".md"):
                continue
            fp = f"{req.projects_root}/{e.name}"
            rr = client.Read(pcm_pb2.ReadRequest(path=fp))
            fm = _parse_frontmatter(rr.content)
            pname = fm.get("project", "")
            if pname and (normalize_name(pname) == q_norm
                          or q_norm in normalize_name(pname)
                          or normalize_name(pname) in q_norm):
                found = {
                    "name": pname,
                    "start_date": fm.get("start_date", ""),
                    "members": fm.get("members", ""),
                    "file": fp,
                    "frontmatter": fm,
                }
                break
        data = {"project": found, "involved_entities": []}
    except Exception as exc:
        return ToolResult(
            ok=False, content="", refs=tuple(),
            error=f"preflight_project failed: {exc}",
            error_code="INTERNAL", wall_ms=0,
        )
    if found:
        summary = f"Project '{found['name']}' found. Start date: {found['start_date']}."
    else:
        summary = f"Query '{req.query}' → no project match."
    return ToolResult(
        ok=True, content=build_response(summary=summary, data=data),
        refs=tuple(), error=None, error_code=None, wall_ms=0,
    )
