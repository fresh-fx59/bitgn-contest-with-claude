"""Semantic-index preflight — compact digest of cast + project records.

Emitted once per task in the prepass, right after `preflight_schema`,
so the agent sees descriptor-to-id mappings ("the founder I talk product
with" → `entity.nina`) from the first LLM reply.

Parsing reuses `parse_record_metadata` from `preflight.schema`. The digest
is a one-line-per-record, side-by-side view that makes semantic contrast
visible in a single message.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from bitgn_contest_agent.preflight.schema import parse_record_metadata


_SUMMARY_MAX = 160


@dataclass(frozen=True)
class CastEntry:
    id: str
    alias: str
    relationship: str
    kind: str
    summary: str


def _first_prose_line(text: str) -> str:
    """Return the first non-blank line after any frontmatter / bullet
    block. Trimmed and capped at _SUMMARY_MAX chars.
    """
    in_yaml = False
    seen_bullets = False
    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            if seen_bullets:
                seen_bullets = False  # blank line ends bullet block
            continue
        if stripped == "---":
            in_yaml = not in_yaml
            continue
        if in_yaml:
            continue
        if stripped.startswith("#"):
            continue
        if stripped.startswith("- ") and ":" in stripped:
            seen_bullets = True
            continue
        if seen_bullets:
            continue
        # First real prose line.
        return stripped[:_SUMMARY_MAX]
    return ""


def _file_id_from_path(path: Path, kind: str) -> str:
    """`entity.nina` from `10_entities/cast/nina.md`; `project.harbor_body`
    from `40_projects/2026_04_03_harbor_body/README.MD`.
    """
    if kind == "project":
        # Project id == directory name with date prefix stripped if present.
        name = path.parent.name
        # Strip a leading YYYY_MM_DD_ prefix if it matches.
        parts = name.split("_", 3)
        if len(parts) == 4 and all(p.isdigit() for p in parts[:3]):
            name = parts[3]
        return f"project.{name}"
    return f"entity.{path.stem.lower()}"


def extract_cast_entries(cast_dir: Path) -> List[CastEntry]:
    """Walk `cast_dir` for .md/.MD files; return one CastEntry per
    parseable record. Records whose metadata parser returns {} are
    skipped silently.
    """
    entries: list[CastEntry] = []
    if not cast_dir.exists() or not cast_dir.is_dir():
        return entries
    for f in sorted(cast_dir.iterdir()):
        if not f.is_file():
            continue
        if not f.name.lower().endswith(".md"):
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        md = parse_record_metadata(text)
        if not md:
            continue
        alias = md.get("alias") or f.stem.lower()
        entries.append(CastEntry(
            id=_file_id_from_path(f, kind="entity"),
            alias=alias,
            relationship=md.get("relationship", ""),
            kind=md.get("kind", ""),
            summary=_first_prose_line(text),
        ))
    return entries


@dataclass(frozen=True)
class ProjectEntry:
    id: str
    alias: str
    lane: str
    status: str
    goal: str


def extract_project_entries(projects_dir: Path) -> List[ProjectEntry]:
    """Walk `projects_dir` for subdirectories containing a README.md or
    README.MD; return one ProjectEntry per parseable record.

    `goal` prefers the `goal:` metadata field; falls back to the first
    prose line after the bullet block.
    """
    entries: list[ProjectEntry] = []
    if not projects_dir.exists() or not projects_dir.is_dir():
        return entries
    for sub in sorted(projects_dir.iterdir()):
        if not sub.is_dir():
            continue
        readme: Optional[Path] = None
        for name in ("README.md", "README.MD", "readme.md"):
            candidate = sub / name
            if candidate.is_file():
                readme = candidate
                break
        if readme is None:
            continue
        try:
            text = readme.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        md = parse_record_metadata(text)
        if not md:
            continue
        goal_field = md.get("goal", "").strip()
        goal = goal_field[:_SUMMARY_MAX] if goal_field else _first_prose_line(text)
        alias = md.get("alias") or sub.name
        entries.append(ProjectEntry(
            id=_file_id_from_path(readme, kind="project"),
            alias=alias,
            lane=md.get("lane", ""),
            status=md.get("status", ""),
            goal=goal,
        ))
    return entries


_HEADER = (
    "WORKSPACE SEMANTIC INDEX (cast + projects digest, use to map "
    "informal descriptors like \"the founder I talk product with\" or "
    "\"the do-not-degrade lane\" to canonical ids before running any "
    "lookup):"
)


def _fmt_kv(key: str, value: str) -> str:
    """Render `key=value` only when value is non-empty."""
    return f"{key}={value}" if value else ""


def _fmt_cast_line(e: CastEntry) -> str:
    parts = [f"- {e.id}", _fmt_kv("alias", e.alias), _fmt_kv("relationship", e.relationship)]
    if e.kind:
        parts.append(_fmt_kv("kind", e.kind))
    head = "  ".join(p for p in parts if p)
    summary = f'  "{e.summary}"' if e.summary else ""
    return head + summary


def _fmt_project_line(e: ProjectEntry) -> str:
    parts = [
        f"- {e.id}",
        _fmt_kv("alias", e.alias),
        _fmt_kv("lane", e.lane),
        _fmt_kv("status", e.status),
    ]
    head = "  ".join(p for p in parts if p)
    goal = f'  "{e.goal}"' if e.goal else ""
    return head + goal


def format_digest(
    *,
    cast: List[CastEntry],
    projects: List[ProjectEntry],
    cast_cap: int = 100,
    project_cap: int = 100,
) -> str:
    """Return the bootstrap string the adapter appends to prepass output.
    Empty inputs (both blocks empty) → empty string so the caller can
    suppress the message entirely.
    """
    if not cast and not projects:
        return ""
    blocks: list[str] = [_HEADER]
    if cast:
        lines = [_fmt_cast_line(e) for e in cast[:cast_cap]]
        if len(cast) > cast_cap:
            lines.append(f"  …(+{len(cast) - cast_cap} more)")
        blocks.append("CAST:\n" + "\n".join(lines))
    if projects:
        lines = [_fmt_project_line(e) for e in projects[:project_cap]]
        if len(projects) > project_cap:
            lines.append(f"  …(+{len(projects) - project_cap} more)")
        blocks.append("PROJECTS:\n" + "\n".join(lines))
    return "\n\n".join(blocks)


def build_digest_from_fs(
    *,
    root: Path,
    entities_root: Optional[str],
    projects_root: Optional[str],
) -> str:
    """Filesystem-backed composer — used by tests and by the PCM
    wrapper's fs fallback. Returns an empty string when neither root
    is present so the adapter can suppress the bootstrap message.

    `entities_root` is the top-level 10_entities path; this function
    looks for a `cast/` subdirectory inside it (PROD convention). If no
    `cast/` subdir exists, it falls back to the entities root itself.
    """
    root = Path(root)
    cast_entries: list[CastEntry] = []
    project_entries: list[ProjectEntry] = []
    if entities_root:
        ent_path = root / entities_root
        cast_dir = ent_path / "cast"
        if cast_dir.is_dir():
            cast_entries = extract_cast_entries(cast_dir)
        else:
            cast_entries = extract_cast_entries(ent_path)
    if projects_root:
        proj_path = root / projects_root
        project_entries = extract_project_entries(proj_path)
    return format_digest(cast=cast_entries, projects=project_entries)


from bitgn_contest_agent.adapter.pcm import ToolResult
from bitgn_contest_agent.preflight.schema import WorkspaceSchema


def _list_md_names_via_pcm(client, dir_path: str) -> list[str]:
    """Return the .md/.MD filenames in `dir_path` via the PCM list RPC."""
    from bitgn.vm import pcm_pb2
    try:
        resp = client.list(pcm_pb2.ListRequest(name=dir_path))
    except Exception:
        return []
    return [
        e.name for e in resp.entries
        if not e.is_dir and e.name.lower().endswith(".md")
    ]


def _list_subdirs_via_pcm(client, dir_path: str) -> list[str]:
    from bitgn.vm import pcm_pb2
    try:
        resp = client.list(pcm_pb2.ListRequest(name=dir_path))
    except Exception:
        return []
    return [e.name for e in resp.entries if e.is_dir]


def _read_text_via_pcm(client, path: str) -> str:
    from bitgn.vm import pcm_pb2
    try:
        resp = client.read(pcm_pb2.ReadRequest(path=path))
    except Exception:
        return ""
    return resp.content or ""


def _extract_cast_via_pcm(client, cast_dir: str) -> list[CastEntry]:
    entries: list[CastEntry] = []
    md_names = _list_md_names_via_pcm(client, cast_dir)
    for name in sorted(md_names):
        full = f"{cast_dir}/{name}"
        text = _read_text_via_pcm(client, full)
        if not text:
            continue
        md = parse_record_metadata(text)
        if not md:
            continue
        stem = name.rsplit(".", 1)[0].lower()
        alias = md.get("alias") or stem
        entries.append(CastEntry(
            id=f"entity.{stem}",
            alias=alias,
            relationship=md.get("relationship", ""),
            kind=md.get("kind", ""),
            summary=_first_prose_line(text),
        ))
    return entries


def _strip_date_prefix(name: str) -> str:
    parts = name.split("_", 3)
    if len(parts) == 4 and all(p.isdigit() for p in parts[:3]):
        return parts[3]
    return name


def _extract_projects_via_pcm(client, projects_dir: str) -> list[ProjectEntry]:
    entries: list[ProjectEntry] = []
    subdirs = _list_subdirs_via_pcm(client, projects_dir)
    for sub in sorted(subdirs):
        sub_path = f"{projects_dir}/{sub}"
        md_names = _list_md_names_via_pcm(client, sub_path)
        readme_name = None
        for candidate in ("README.md", "README.MD", "readme.md"):
            if candidate in md_names:
                readme_name = candidate
                break
        if readme_name is None:
            continue
        text = _read_text_via_pcm(client, f"{sub_path}/{readme_name}")
        if not text:
            continue
        md = parse_record_metadata(text)
        if not md:
            continue
        goal_field = md.get("goal", "").strip()
        goal = goal_field[:_SUMMARY_MAX] if goal_field else _first_prose_line(text)
        alias = md.get("alias") or sub
        entries.append(ProjectEntry(
            id=f"project.{_strip_date_prefix(sub)}",
            alias=alias,
            lane=md.get("lane", ""),
            status=md.get("status", ""),
            goal=goal,
        ))
    return entries


def run_preflight_semantic_index(client, schema: WorkspaceSchema) -> ToolResult:
    """PCM-backed entry point. Consumes a schema produced by
    `run_preflight_schema` and returns a ToolResult whose `content` is
    the bootstrap digest (or empty string when no roots are available).
    """
    cast: list[CastEntry] = []
    projects: list[ProjectEntry] = []
    try:
        if schema.entities_root:
            cast_dir = f"{schema.entities_root}/cast"
            cast = _extract_cast_via_pcm(client, cast_dir)
            if not cast:
                # Fallback: walk entities_root directly (non-PROD shape).
                cast = _extract_cast_via_pcm(client, schema.entities_root)
        if schema.projects_root:
            projects = _extract_projects_via_pcm(client, schema.projects_root)
    except Exception as exc:
        return ToolResult(
            ok=False, content="", refs=tuple(), error=str(exc),
            error_code="INTERNAL", wall_ms=0,
        )
    digest = format_digest(cast=cast, projects=projects)
    return ToolResult(
        ok=True, content=digest, refs=tuple(),
        error=None, error_code=None, wall_ms=0,
    )
