"""preflight_entity — disambiguates an entity query against entity
records and aliases. Pure lookup, no cross-referencing.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from bitgn_contest_agent.adapter.pcm import ToolResult
from bitgn_contest_agent.preflight.canonicalize import normalize_name
from bitgn_contest_agent.preflight.inbox import _load_entities, _parse_aliases_list
from bitgn_contest_agent.preflight.response import build_response
from bitgn_contest_agent.preflight.schema import _parse_frontmatter
from bitgn_contest_agent.schemas import Req_PreflightEntity


def _find_matches(query: str, entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    q_norm = normalize_name(query)
    if not q_norm:
        return []
    matches = []
    for e in entities:
        for alias in e["aliases"]:
            if normalize_name(alias) == q_norm:
                matches.append({
                    "canonical": e["canonical"],
                    "aliases": e["aliases"],
                    "file": e["file"],
                    "frontmatter": e["frontmatter"],
                })
                break
        else:
            # substring fallback
            for alias in e["aliases"]:
                a_norm = normalize_name(alias)
                if a_norm and (q_norm in a_norm or a_norm in q_norm):
                    matches.append({
                        "canonical": e["canonical"],
                        "aliases": e["aliases"],
                        "file": e["file"],
                        "frontmatter": e["frontmatter"],
                    })
                    break
    return matches


def run_entity_from_fs(root: Path, entities_root: str, query: str) -> dict[str, Any]:
    root = Path(root)
    entities = _load_entities(root / entities_root)
    return {"matches": _find_matches(query, entities)}


def run_preflight_entity(client: Any, req: Req_PreflightEntity) -> ToolResult:
    from bitgn.vm import pcm_pb2
    try:
        entities = []
        eresp = client.list(pcm_pb2.ListRequest(name=req.entities_root))
        for e in eresp.entries:
            if not e.name.endswith(".md"):
                continue
            rp = f"{req.entities_root}/{e.name}"
            rr = client.read(pcm_pb2.ReadRequest(path=rp))
            fm = _parse_frontmatter(rr.content)
            aliases = _parse_aliases_list(fm.get("aliases", ""))
            canonical = Path(e.name).stem.replace("_", " ").title()
            entities.append({
                "file": rp,
                "canonical": canonical,
                "aliases": [canonical] + aliases,
                "frontmatter": fm,
            })
        matches = _find_matches(req.query, entities)
        data = {"matches": matches}
    except Exception as exc:
        return ToolResult(
            ok=False, content="", refs=tuple(),
            error=f"preflight_entity failed: {exc}",
            error_code="INTERNAL", wall_ms=0,
        )
    summary = (
        f"Query '{req.query}' → {len(matches)} entity match(es)."
        if matches else
        f"Query '{req.query}' → no entity match."
    )
    return ToolResult(
        ok=True, content=build_response(summary=summary, data=data),
        refs=tuple(), error=None, error_code=None, wall_ms=0,
    )
