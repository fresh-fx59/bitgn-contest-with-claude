"""preflight_project — locates a project record and returns its
metadata + entities involved (members).

Handles both layouts:
  DEV: flat <projects_root>/*.md files with `project:` frontmatter
  PROD: nested <projects_root>/<YYYY_MM_DD_slug>/README.MD files whose
        project name is conveyed by the `# Heading`, `alias:` field,
        and/or the slug itself (no `project:` key, no `start_date:`
        key — start date comes from the slug prefix).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from bitgn_contest_agent.adapter.pcm import ToolResult
from bitgn_contest_agent.preflight.canonicalize import normalize_name
from bitgn_contest_agent.preflight.response import build_response
from bitgn_contest_agent.preflight.schema import parse_record_metadata
from bitgn_contest_agent.schemas import Req_PreflightProject


def _extract_heading(text: str) -> str:
    """Return the first `# H1` heading text (without the `#`), or ''."""
    for raw in text.splitlines():
        stripped = raw.strip()
        if stripped.startswith("# ") and not stripped.startswith("## "):
            return stripped[2:].strip()
        if stripped and not stripped.startswith("#"):
            break
    return ""


def _slug_parts(slug: str) -> tuple[str, str]:
    """Split `YYYY_MM_DD_<rest>` slug into (date_str, rest).

    Returns ('2026-04-21', 'studio parts library') for
    `2026_04_21_studio_parts_library`. Returns ('', slug_as_title) if
    no date prefix is present.
    """
    parts = slug.split("_")
    if (
        len(parts) >= 4
        and parts[0].isdigit() and len(parts[0]) == 4
        and parts[1].isdigit() and len(parts[1]) == 2
        and parts[2].isdigit() and len(parts[2]) == 2
    ):
        date = f"{parts[0]}-{parts[1]}-{parts[2]}"
        rest = " ".join(parts[3:])
        return date, rest
    return "", slug.replace("_", " ")


def _match(query_norm: str, candidate: str) -> bool:
    if not candidate:
        return False
    c = normalize_name(candidate)
    return c == query_norm or query_norm in c or c in query_norm


def _find_project(projects_dir: Path, query: str) -> dict[str, Any] | None:
    """Filesystem lookup — used only by offline tests."""
    if not projects_dir.exists():
        return None
    q_norm = normalize_name(query)
    # First: flat .md records with `project:` field (DEV shape).
    for f in projects_dir.glob("*.md"):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        md = parse_record_metadata(text)
        pname = md.get("project", "")
        if _match(q_norm, pname):
            return {
                "name": pname,
                "start_date": md.get("start_date", ""),
                "members": md.get("members", ""),
                "file": str(f),
                "frontmatter": md,
            }
    # Second: nested `<slug>/README.(MD|md)` records (PROD shape).
    for subdir in sorted(p for p in projects_dir.iterdir() if p.is_dir()):
        for ext in ("README.MD", "README.md"):
            readme = subdir / ext
            if not readme.exists():
                continue
            try:
                text = readme.read_text(encoding="utf-8", errors="replace")
            except OSError:
                break
            md = parse_record_metadata(text)
            heading = _extract_heading(text)
            slug_date, slug_title = _slug_parts(subdir.name)
            candidates = [md.get("project", ""), heading, slug_title, md.get("alias", "")]
            matched = next((c for c in candidates if _match(q_norm, c)), "")
            if matched:
                return {
                    "name": matched or heading or slug_title,
                    "start_date": md.get("start_date") or slug_date,
                    "members": md.get("members") or md.get("linked_entities", ""),
                    "file": str(readme),
                    "frontmatter": md,
                }
            break  # only one README per subdir
    return None


def run_project_from_fs(
    root: Path, projects_root: str, entities_root: str, query: str,
) -> dict[str, Any]:
    root = Path(root)
    proj = _find_project(root / projects_root, query)
    return {"project": proj, "involved_entities": []}


def _match_in_file(
    client: Any, projects_root: str, slug: str, file_path: str, content: str, q_norm: str,
) -> dict[str, Any] | None:
    md = parse_record_metadata(content)
    heading = _extract_heading(content)
    slug_date, slug_title = _slug_parts(slug)
    candidates = [md.get("project", ""), heading, slug_title, md.get("alias", "")]
    matched = next((c for c in candidates if _match(q_norm, c)), "")
    if not matched:
        return None
    return {
        "name": matched or heading or slug_title,
        "start_date": md.get("start_date") or slug_date,
        "members": md.get("members") or md.get("linked_entities", ""),
        "file": file_path,
        "frontmatter": md,
    }


def run_preflight_project(client: Any, req: Req_PreflightProject) -> ToolResult:
    from bitgn.vm import pcm_pb2
    try:
        q_norm = normalize_name(req.query)
        found: dict[str, Any] | None = None
        lresp = client.list(pcm_pb2.ListRequest(name=req.projects_root))
        # Phase 1: flat `.md` files directly under projects_root (DEV).
        for e in lresp.entries:
            if getattr(e, "is_dir", False):
                continue
            name_lower = e.name.lower()
            if not name_lower.endswith(".md"):
                continue
            fp = f"{req.projects_root}/{e.name}"
            try:
                rr = client.read(pcm_pb2.ReadRequest(path=fp))
            except Exception:
                continue
            m = _match_in_file(
                client, req.projects_root, e.name.rsplit(".", 1)[0], fp, rr.content, q_norm,
            )
            if m:
                found = m
                break
        # Phase 2: nested `<slug>/README.(MD|md)` (PROD).
        if found is None:
            for e in lresp.entries:
                if not getattr(e, "is_dir", False):
                    continue
                slug = e.name
                for ext in ("README.MD", "README.md"):
                    fp = f"{req.projects_root}/{slug}/{ext}"
                    try:
                        rr = client.read(pcm_pb2.ReadRequest(path=fp))
                    except Exception:
                        continue
                    m = _match_in_file(
                        client, req.projects_root, slug, fp, rr.content, q_norm,
                    )
                    if m:
                        found = m
                        break
                    # Found a readable README but didn't match — skip this subdir.
                    break
                if found is not None:
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
