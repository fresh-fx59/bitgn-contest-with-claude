"""preflight_project — locates a project record and returns its
metadata + entities involved (members).

Handles both layouts:
  DEV: flat <projects_root>/*.md files
  PROD: nested <projects_root>/<slug>/README.MD files
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from bitgn_contest_agent.adapter.pcm import ToolResult
from bitgn_contest_agent.preflight.canonicalize import normalize_name
from bitgn_contest_agent.preflight.response import build_response
from bitgn_contest_agent.preflight.schema import parse_record_metadata
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
        md = parse_record_metadata(text)
        pname = md.get("project", "")
        if pname and (
            normalize_name(pname) == q_norm
            or q_norm in normalize_name(pname)
            or normalize_name(pname) in q_norm
        ):
            return {
                "name": pname,
                "start_date": md.get("start_date", ""),
                "members": md.get("members", ""),
                "file": str(f),
                "frontmatter": md,
            }
    return None


def run_project_from_fs(
    root: Path, projects_root: str, entities_root: str, query: str,
) -> dict[str, Any]:
    root = Path(root)
    proj = _find_project(root / projects_root, query)
    return {"project": proj, "involved_entities": []}


def _candidate_paths(projects_root: str, entries: Iterable[Any]) -> list[str]:
    """Build ordered candidate paths to read.

    PROD: `<projects_root>/<slug>/README.MD` (uppercase) then README.md.
    DEV: flat `<projects_root>/<name>.md`.

    Returns the list; caller reads each, first successful parse with a
    matching `project` field wins.
    """
    out: list[str] = []
    for e in entries:
        if getattr(e, "is_dir", False):
            slug = e.name
            out.append(f"{projects_root}/{slug}/README.MD")
            out.append(f"{projects_root}/{slug}/README.md")
        else:
            if e.name.endswith(".md") or e.name.endswith(".MD"):
                out.append(f"{projects_root}/{e.name}")
    return out


def run_preflight_project(client: Any, req: Req_PreflightProject) -> ToolResult:
    from bitgn.vm import pcm_pb2
    try:
        q_norm = normalize_name(req.query)
        found = None
        lresp = client.list(pcm_pb2.ListRequest(name=req.projects_root))
        for fp in _candidate_paths(req.projects_root, lresp.entries):
            try:
                rr = client.read(pcm_pb2.ReadRequest(path=fp))
            except Exception:
                # Missing README.md after README.MD tried, etc.
                continue
            md = parse_record_metadata(rr.content)
            pname = md.get("project", "")
            if pname and (
                normalize_name(pname) == q_norm
                or q_norm in normalize_name(pname)
                or normalize_name(pname) in q_norm
            ):
                found = {
                    "name": pname,
                    "start_date": md.get("start_date", ""),
                    "members": md.get("members", ""),
                    "file": fp,
                    "frontmatter": md,
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
        # Non-leaky summary — cite the file instead of the value so the
        # agent is pressured to read it (grader enforces attribution).
        summary = f"Project '{found['name']}' found at {found['file']}."
        refs: tuple[str, ...] = (found["file"],)
    else:
        summary = f"Query '{req.query}' → no project match."
        refs = ()
    return ToolResult(
        ok=True, content=build_response(summary=summary, data=data),
        refs=refs, error=None, error_code=None, wall_ms=0,
    )
