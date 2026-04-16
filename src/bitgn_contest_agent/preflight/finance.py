"""preflight_finance — canonicalizes a finance query against entity
aliases and returns matching purchase/invoice files with full parsed
frontmatter.
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
        # No entity match — emit ALL invoices so service-line-style
        # queries (e.g. "staff follow-up support") have data to filter.
        bill_paths = []
        for d in finance_dirs:
            if not d.exists():
                continue
            for f in sorted(d.rglob("*.md")):
                bill_paths.append(str(f))
    files_meta = []
    for bp in bill_paths:
        try:
            text = Path(bp).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        fm = _parse_frontmatter(text)
        files_meta.append({"path": bp, "frontmatter": fm})
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

        files_meta = []
        if match:
            # Filter by vendor-alias match (existing behaviour).
            alias_norms = [normalize_name(a) for a in match["aliases"] if a]
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
                        files_meta.append({"path": fp, "frontmatter": ffm})
        else:
            # No entity match — emit every invoice so service-line-style
            # queries have data.
            for froot in req.finance_roots:
                try:
                    fresp = client.list(pcm_pb2.ListRequest(name=froot))
                except Exception:
                    continue
                for fe in sorted(fresp.entries, key=lambda x: x.name):
                    if not fe.name.endswith(".md"):
                        continue
                    fp = f"{froot}/{fe.name}"
                    fr = client.read(pcm_pb2.ReadRequest(path=fp))
                    ffm = _parse_frontmatter(fr.content)
                    files_meta.append({"path": fp, "frontmatter": ffm})
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
        f"Query '{req.query}' → no entity match. {len(data['finance_files'])} invoice(s) returned (all invoices fallback)."
    )
    return ToolResult(
        ok=True,
        content=build_response(summary=summary, data=data),
        refs=tuple(), error=None, error_code=None, wall_ms=0,
    )
