"""preflight_inbox — enumerates open inbox items and the full set of
finance files linked to each referenced entity.

This is the highest-leverage preflight tool. Bench #2 failures t016,
t041, t066, t091 all stem from OCRing one bill when multiple bills for
the same entity exist. The tool pre-computes the entity→bills graph so
the agent sees the full picture before acting.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, List

from bitgn_contest_agent.adapter.pcm import ToolResult
from bitgn_contest_agent.preflight.canonicalize import normalize_name
from bitgn_contest_agent.preflight.response import build_response
from bitgn_contest_agent.preflight.schema import _parse_frontmatter
from bitgn_contest_agent.schemas import Req_PreflightInbox


_ENTITY_MENTION_RE = re.compile(r"\b([A-Z][\w\s\-]{2,40})\b")


def _parse_aliases_list(raw: str) -> List[str]:
    """Very small YAML-list parser: 'aliases: ["a", "b"]' → ['a', 'b']."""
    if not raw:
        return []
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1]
        return [p.strip().strip('"\'') for p in inner.split(",") if p.strip()]
    return [raw.strip('"\'')]


def _load_entities(entities_dir: Path) -> list[dict[str, Any]]:
    """Return a list of {file, canonical, aliases, frontmatter} records."""
    entities = []
    if not entities_dir.exists():
        return entities
    for f in entities_dir.rglob("*.md"):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        fm = _parse_frontmatter(text)
        aliases = _parse_aliases_list(fm.get("aliases", ""))
        canonical = f.stem.replace("_", " ").title()
        entities.append({
            "file": str(f),
            "canonical": canonical,
            "aliases": [canonical] + aliases,
            "frontmatter": fm,
        })
    return entities


def _match_entity(text: str, entities: list[dict[str, Any]]) -> dict[str, Any] | None:
    text_norm = normalize_name(text)
    best = None
    for e in entities:
        for alias in e["aliases"]:
            a_norm = normalize_name(alias)
            if a_norm and a_norm in text_norm:
                # Prefer longer alias matches (more specific).
                if best is None or len(a_norm) > len(normalize_name(best["matched_alias"])):
                    best = {**e, "matched_alias": alias}
    return best


def _bills_for_entity(entity: dict[str, Any], finance_dirs: list[Path]) -> list[str]:
    alias_norms = [normalize_name(a) for a in entity["aliases"] if a]
    hits: set[str] = set()
    for d in finance_dirs:
        if not d.exists():
            continue
        for f in d.rglob("*.md"):
            # Check filename/slug for entity name.
            slug_norm = normalize_name(f.stem)
            if slug_norm and any(a and a in slug_norm for a in alias_norms):
                hits.add(str(f))
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            fm = _parse_frontmatter(text)
            # Check vendor and entity-reference frontmatter fields.
            for key in ("vendor", "related_entity", "buyer", "ordered_by",
                        "entity", "recipient"):
                val = normalize_name(fm.get(key, ""))
                if val and any(a and (a in val or val in a) for a in alias_norms):
                    hits.add(str(f))
                    break
    return sorted(hits)


def enumerate_inbox_from_fs(
    root: Path,
    inbox_root: str,
    entities_root: str,
    finance_roots: list[str],
) -> list[dict[str, Any]]:
    """Local-filesystem implementation — used by tests and shared logic."""
    root = Path(root)
    inbox_dir = root / inbox_root
    entities_dir = root / entities_root
    finance_dirs = [root / fr for fr in finance_roots]

    entities = _load_entities(entities_dir)
    items = []
    if not inbox_dir.exists():
        return items
    for f in sorted(inbox_dir.rglob("*.md")):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        fm = _parse_frontmatter(text)
        body = text.split("---", 2)[-1] if text.count("---") >= 2 else text
        match = _match_entity(body, entities)
        item = {
            "path": str(f),
            "task_type": fm.get("inbox_type") or fm.get("inbox_kind") or "",
            "entity_ref": match["matched_alias"] if match else None,
            "entity_canonical": match["canonical"] if match else None,
            "related_finance_files": _bills_for_entity(match, finance_dirs) if match else [],
            "frontmatter": fm,
        }
        items.append(item)
    return items


def _summarize(items: list[dict[str, Any]]) -> str:
    if not items:
        return "0 open inbox items."
    parts = [f"{len(items)} open inbox item(s)."]
    for i, it in enumerate(items, 1):
        canon = it["entity_canonical"] or "unresolved"
        n = len(it["related_finance_files"])
        parts.append(f"Item #{i} references entity '{canon}' → {n} related finance file(s).")
    return " ".join(parts)


def run_preflight_inbox(client: Any, req: Req_PreflightInbox) -> ToolResult:
    """PCM-backed entry. Uses PCM list+read RPCs to enumerate."""
    from bitgn.vm import pcm_pb2
    items: list[dict[str, Any]] = []
    try:
        # Load entities via PCM
        entities_resp = client.list(pcm_pb2.ListRequest(name=req.entities_root))
        entities = []
        for e in entities_resp.entries:
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

        # Enumerate inbox
        inbox_resp = client.list(pcm_pb2.ListRequest(name=req.inbox_root))
        for e in inbox_resp.entries:
            if not e.name.endswith(".md"):
                continue
            ip = f"{req.inbox_root}/{e.name}"
            ir = client.read(pcm_pb2.ReadRequest(path=ip))
            fm = _parse_frontmatter(ir.content)
            body = ir.content.split("---", 2)[-1] if ir.content.count("---") >= 2 else ir.content
            match = _match_entity(body, entities)
            related: list[str] = []
            if match:
                alias_norms = [normalize_name(a) for a in match["aliases"] if a]
                related_set: set[str] = set()
                for froot in req.finance_roots:
                    try:
                        fresp = client.list(pcm_pb2.ListRequest(name=froot))
                    except Exception:
                        continue
                    for fe in fresp.entries:
                        if not fe.name.endswith(".md"):
                            continue
                        fp = f"{froot}/{fe.name}"
                        # Check filename/slug for entity name.
                        slug_norm = normalize_name(Path(fe.name).stem)
                        if slug_norm and any(a and a in slug_norm for a in alias_norms):
                            related_set.add(fp)
                            continue
                        fr_read = client.read(pcm_pb2.ReadRequest(path=fp))
                        ffm = _parse_frontmatter(fr_read.content)
                        for key in ("vendor", "related_entity", "buyer",
                                    "ordered_by", "entity", "recipient"):
                            val = normalize_name(ffm.get(key, ""))
                            if val and any(a and (a in val or val in a) for a in alias_norms):
                                related_set.add(fp)
                                break
                related = sorted(related_set)
            items.append({
                "path": ip,
                "task_type": fm.get("inbox_type") or fm.get("inbox_kind") or "",
                "entity_ref": match["matched_alias"] if match else None,
                "entity_canonical": match["canonical"] if match else None,
                "related_finance_files": sorted(related),
                "frontmatter": fm,
            })
    except Exception as exc:
        return ToolResult(
            ok=False,
            content="",
            refs=tuple(),
            error=f"preflight_inbox failed: {exc}",
            error_code="INTERNAL",
            wall_ms=0,
        )

    content = build_response(summary=_summarize(items), data={"items": items})
    return ToolResult(
        ok=True,
        content=content,
        refs=tuple(),
        error=None,
        error_code=None,
        wall_ms=0,
    )
