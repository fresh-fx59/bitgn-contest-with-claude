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
