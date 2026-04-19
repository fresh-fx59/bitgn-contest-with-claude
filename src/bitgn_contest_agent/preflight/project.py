"""preflight_project — locates a project record and returns its
metadata + entities involved (members).

Handles both layouts:
  DEV: flat <projects_root>/*.md files with `project:` frontmatter
  PROD: nested <projects_root>/<YYYY_MM_DD_slug>/README.MD files whose
        project name is conveyed by the `# Heading`, `alias:` field,
        and/or the slug itself (no `project:` key, no `start_date:`
        key — start date comes from the slug prefix).

When no exact or substring match is found, falls back to a lightweight
LLM call (via the shared classifier module) to disambiguate the query
against the list of known project names.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from bitgn_contest_agent.adapter.pcm import ToolResult
from bitgn_contest_agent.preflight.canonicalize import normalize_name
from bitgn_contest_agent.preflight.response import build_response
from bitgn_contest_agent.preflight.schema import parse_record_metadata
from bitgn_contest_agent.schemas import Req_PreflightProject

_LOG = logging.getLogger(__name__)


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


_HIGH_CONFIDENCE = 0.85


def _disambiguate_via_llm(
    query: str, candidates: list[str],
) -> tuple[str | None, list[str]]:
    """Ask the classifier LLM to pick the best project name from
    ``candidates`` given a possibly-informal ``query``.

    Returns ``(chosen, runner_ups)`` where *chosen* is the top pick
    (or None) and *runner_ups* are additional plausible matches the
    agent should also read when confidence is below ``_HIGH_CONFIDENCE``.
    """
    if not candidates:
        return None, []
    numbered = "\n".join(f"  {i+1}. {c}" for i, c in enumerate(candidates))
    system = (
        "You match an informal project name to one of the canonical "
        "project names listed below.  Return ONLY a JSON object:\n"
        '  {"match": "<exact canonical name from the list>", '
        '"confidence": <0.0-1.0>, '
        '"runner_ups": ["<other plausible names>"]}\n'
        "runner_ups should include any project whose name partially "
        "overlaps with the query or could be confused with the match.\n"
        "If none of the projects is a plausible match, return "
        '{"match": null, "confidence": 0.0, "runner_ups": []}.\n'
        "No prose. No markdown fences."
    )
    user = f"Query: {query}\n\nProjects:\n{numbered}"
    try:
        from bitgn_contest_agent import classifier
        raw = classifier.classify(system=system, user=user)
        if not isinstance(raw, dict):
            return None, []
        match = raw.get("match")
        conf = float(raw.get("confidence", 0))
        runner_ups_raw = raw.get("runner_ups") or []
        runner_ups = [r for r in runner_ups_raw if r in candidates and r != match]
        if match and conf >= 0.5 and match in candidates:
            return match, runner_ups
    except Exception:  # noqa: BLE001 — never crash the preflight
        _LOG.debug("LLM disambiguation failed for query=%r", query, exc_info=True)
    return None, []


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


def _record_to_result(
    content: str, slug: str, file_path: str, md: dict[str, str],
) -> dict[str, Any]:
    """Build the result dict for a matched project record."""
    heading = _extract_heading(content)
    slug_date, slug_title = _slug_parts(slug)
    name = md.get("project") or heading or slug_title
    return {
        "name": name,
        "start_date": md.get("start_date") or slug_date,
        "members": md.get("members") or md.get("linked_entities", ""),
        "file": file_path,
        "frontmatter": md,
    }


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
        # all_candidates: list of (display_name, content, slug, file_path, md)
        # populated during scanning for Phase 3 LLM fallback.
        all_candidates: list[tuple[str, str, str, str, dict[str, str]]] = []

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
            slug = e.name.rsplit(".", 1)[0]
            m = _match_in_file(
                client, req.projects_root, slug, fp, rr.content, q_norm,
            )
            if m:
                found = m
                break
            # Collect as candidate for Phase 3.
            md = parse_record_metadata(rr.content)
            heading = _extract_heading(rr.content)
            display = md.get("project") or heading or slug.replace("_", " ")
            all_candidates.append((display, rr.content, slug, fp, md))

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
                    # Collect as candidate for Phase 3.
                    md = parse_record_metadata(rr.content)
                    heading = _extract_heading(rr.content)
                    display = md.get("project") or heading or slug.replace("_", " ")
                    all_candidates.append((display, rr.content, slug, fp, md))
                    break  # only one README per subdir
                if found is not None:
                    break

        # Phase 3: LLM disambiguation when exact/substring match missed.
        also_read: list[dict[str, Any]] = []
        if found is None and all_candidates:
            names = [c[0] for c in all_candidates]
            chosen, runner_ups = _disambiguate_via_llm(req.query, names)
            if chosen:
                for display, content, slug, fp, md in all_candidates:
                    if display == chosen:
                        found = _record_to_result(content, slug, fp, md)
                    elif display in runner_ups:
                        also_read.append(_record_to_result(content, slug, fp, md))

        data: dict[str, Any] = {
            "project": found,
            "involved_entities": [],
        }
        if also_read:
            data["also_read"] = also_read
    except Exception as exc:
        return ToolResult(
            ok=False, content="", refs=tuple(),
            error=f"preflight_project failed: {exc}",
            error_code="INTERNAL", wall_ms=0,
        )
    if found:
        # Non-leaky summary — cite the file instead of the value so the
        # agent is pressured to read it (grader enforces attribution).
        ref_list: list[str] = [found["file"]]
        if also_read:
            extra = ", ".join(a["file"] for a in also_read)
            summary = (
                f"Project '{found['name']}' found at {found['file']}. "
                f"Disambiguation was ambiguous — also read these "
                f"before answering: {extra}"
            )
            ref_list.extend(a["file"] for a in also_read)
        else:
            summary = f"Project '{found['name']}' found at {found['file']}."
        refs: tuple[str, ...] = tuple(ref_list)
    else:
        summary = f"Query '{req.query}' → no project match."
        refs = ()
    return ToolResult(
        ok=True, content=build_response(summary=summary, data=data),
        refs=refs, error=None, error_code=None, wall_ms=0,
    )
