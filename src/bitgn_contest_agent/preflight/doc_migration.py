"""preflight_doc_migration — resolves a migration destination root
from a query (entity alias or area name), computes per-source
destination paths, flags collisions.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from bitgn_contest_agent.adapter.pcm import ToolResult
from bitgn_contest_agent.preflight.entity import _find_matches
from bitgn_contest_agent.preflight.inbox import _load_entities, _parse_aliases_list
from bitgn_contest_agent.preflight.response import build_response
from bitgn_contest_agent.preflight.schema import _parse_frontmatter
from bitgn_contest_agent.schemas import Req_PreflightDocMigration


def _slugify(name: str) -> str:
    return "_".join(name.lower().split())


def run_doc_migration_from_fs(
    root: Path,
    source_paths: list[str],
    entities_root: str,
    query: str,
) -> dict[str, Any]:
    root = Path(root)
    entities = _load_entities(root / entities_root)
    matches = _find_matches(query, entities)
    if not matches:
        return {
            "target_canonical": None,
            "destination_root": None,
            "migrations": [],
        }
    m = matches[0]
    dest_root = f"{entities_root}/{_slugify(m['canonical'])}"
    dest_path = root / dest_root
    existing = set()
    if dest_path.exists():
        existing = {f.name for f in dest_path.iterdir() if f.is_file()}
    migrations = []
    for sp in source_paths:
        fname = os.path.basename(sp)
        migrations.append({
            "source": sp,
            "destination": f"{dest_root}/{fname}",
            "collision": fname in existing,
        })
    return {
        "target_canonical": m["canonical"],
        "destination_root": dest_root,
        "migrations": migrations,
    }


def run_preflight_doc_migration(client: Any, req: Req_PreflightDocMigration) -> ToolResult:
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
                "file": rp, "canonical": canonical,
                "aliases": [canonical] + aliases, "frontmatter": fm,
            })
        matches = _find_matches(req.query, entities)
        if not matches:
            data = {"target_canonical": None, "destination_root": None, "migrations": []}
        else:
            m = matches[0]
            dest_root = f"{req.entities_root}/{_slugify(m['canonical'])}"
            existing = set()
            try:
                lresp = client.list(pcm_pb2.ListRequest(name=dest_root))
                existing = {e.name for e in lresp.entries}
            except Exception:
                pass
            migrations = []
            for sp in req.source_paths:
                fname = sp.rsplit("/", 1)[-1]
                migrations.append({
                    "source": sp,
                    "destination": f"{dest_root}/{fname}",
                    "collision": fname in existing,
                })
            data = {
                "target_canonical": m["canonical"],
                "destination_root": dest_root,
                "migrations": migrations,
            }
    except Exception as exc:
        return ToolResult(
            ok=False, content="", refs=tuple(),
            error=f"preflight_doc_migration failed: {exc}",
            error_code="INTERNAL", wall_ms=0,
        )
    if data["target_canonical"]:
        summary = (
            f"Target '{req.query}' → '{data['target_canonical']}'. "
            f"Destination: {data['destination_root']}. "
            f"{len(data['migrations'])} source file(s)."
        )
    else:
        summary = f"Target '{req.query}' → no entity match."
    return ToolResult(
        ok=True, content=build_response(summary=summary, data=data),
        refs=tuple(), error=None, error_code=None, wall_ms=0,
    )
