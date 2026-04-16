"""preflight_finance — canonicalizes a finance query against entity
aliases and returns matching purchase/invoice files with extracted
metadata (vendor, date, total, line_items).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from bitgn_contest_agent.adapter.pcm import ToolResult
from bitgn_contest_agent.preflight.canonicalize import normalize_name
from bitgn_contest_agent.preflight.inbox import (
    _bills_for_entity,
    _load_entities,
    _match_entity,
)
from bitgn_contest_agent.preflight.response import build_response
from bitgn_contest_agent.preflight.schema import _parse_frontmatter
from bitgn_contest_agent.schemas import Req_PreflightFinance


def run_finance_from_fs(
    root: Path,
    finance_roots: list[str],
    entities_root: str,
    query: str,
) -> dict[str, Any]:
    root = Path(root)
    entities = _load_entities(root / entities_root)
    match = _match_entity(query, entities)
    finance_dirs = [root / fr for fr in finance_roots]
    if match:
        bill_paths = _bills_for_entity(match, finance_dirs)
    else:
        # Fallback: match by query directly against vendor field
        q_norm = normalize_name(query)
        bill_paths = []
        for d in finance_dirs:
            if not d.exists():
                continue
            for f in d.rglob("*.md"):
                try:
                    text = f.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                fm = _parse_frontmatter(text)
                if q_norm and q_norm in normalize_name(fm.get("vendor", "")):
                    bill_paths.append(str(f))
    files_meta = []
    for bp in bill_paths:
        try:
            text = Path(bp).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        fm = _parse_frontmatter(text)
        files_meta.append({
            "path": bp,
            "vendor": fm.get("vendor", ""),
            "date": fm.get("date", ""),
            "total": fm.get("eur_total", ""),
            "line_items": fm.get("line_items", ""),
        })
    return {
        "canonical_entity": match["canonical"] if match else None,
        "aliases_matched": [match["matched_alias"]] if match else [],
        "finance_files": files_meta,
    }


def run_preflight_finance(client: Any, req: Req_PreflightFinance) -> ToolResult:
    from bitgn.vm import pcm_pb2
    try:
        # Load entities
        entities = []
        eresp = client.list(pcm_pb2.ListRequest(name=req.entities_root))
        for e in eresp.entries:
            if not e.name.endswith(".md"):
                continue
            rp = f"{req.entities_root}/{e.name}"
            rr = client.read(pcm_pb2.ReadRequest(path=rp))
            fm = _parse_frontmatter(rr.content)
            from bitgn_contest_agent.preflight.inbox import _parse_aliases_list
            aliases = _parse_aliases_list(fm.get("aliases", ""))
            canonical = Path(e.name).stem.replace("_", " ").title()
            entities.append({
                "file": rp,
                "canonical": canonical,
                "aliases": [canonical] + aliases,
                "frontmatter": fm,
            })
        match = _match_entity(req.query, entities)
        alias_norms = [normalize_name(a) for a in (match["aliases"] if match else [req.query]) if a]

        files_meta = []
        for froot in req.finance_roots:
            try:
                fresp = client.list(pcm_pb2.ListRequest(name=froot))
            except Exception:
                continue
            for fe in fresp.entries:
                if not fe.name.endswith(".md"):
                    continue
                fp = f"{froot}/{fe.name}"
                fr = client.read(pcm_pb2.ReadRequest(path=fp))
                ffm = _parse_frontmatter(fr.content)
                vendor = normalize_name(ffm.get("vendor", ""))
                if vendor and any(a in vendor or vendor in a for a in alias_norms if a):
                    files_meta.append({
                        "path": fp,
                        "vendor": ffm.get("vendor", ""),
                        "date": ffm.get("date", ""),
                        "total": ffm.get("eur_total", ""),
                        "line_items": ffm.get("line_items", ""),
                    })
        data = {
            "canonical_entity": match["canonical"] if match else None,
            "aliases_matched": [match["matched_alias"]] if match else [],
            "finance_files": files_meta,
        }
    except Exception as exc:
        return ToolResult(
            ok=False, content="", refs=tuple(),
            error=f"preflight_finance failed: {exc}",
            error_code="INTERNAL", wall_ms=0,
        )

    summary = (
        f"Query '{req.query}' → entity '{data['canonical_entity']}' "
        f"({len(data['finance_files'])} finance file(s))."
        if data["canonical_entity"] else
        f"Query '{req.query}' → no entity match. {len(data['finance_files'])} direct vendor match(es)."
    )
    return ToolResult(
        ok=True,
        content=build_response(summary=summary, data=data),
        refs=tuple(), error=None, error_code=None, wall_ms=0,
    )
