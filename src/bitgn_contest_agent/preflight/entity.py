"""preflight_entity — disambiguates an entity query against entity
records, searching across all fields (name, alias, relationship,
description) with LLM disambiguation fallback.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from bitgn_contest_agent.adapter.pcm import ToolResult
from bitgn_contest_agent.preflight.canonicalize import normalize_name
from bitgn_contest_agent.preflight.inbox import _load_entities, _parse_aliases_list
from bitgn_contest_agent.preflight.response import build_response
from bitgn_contest_agent.preflight.schema import _parse_frontmatter
from bitgn_contest_agent.schemas import Req_PreflightEntity

_LOG = logging.getLogger(__name__)

# ── body extraction ───────────────────────────────────────────────
_BULLET_LINE = re.compile(r"^-\s+\w+\s*:")
_HEADING_LINE = re.compile(r"^#+\s")


def _extract_body(content: str) -> str:
    """Return the description body text below structured metadata lines."""
    lines = content.splitlines()
    body_start = 0
    in_metadata = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or _HEADING_LINE.match(stripped):
            continue
        if _BULLET_LINE.match(stripped):
            in_metadata = True
            body_start = i + 1
            continue
        if in_metadata and stripped.startswith("-"):
            # continuation bullet under important_dates etc —
            # includes sub-bullets with colons (e.g. `- birthday: 1990-03-29`)
            body_start = i + 1
            continue
        if in_metadata:
            body_start = i
            break
    return "\n".join(lines[body_start:]).strip()


# Relationship synonym classes: query word → additional relationship words
# that should also be considered candidates.
#
# The life-partner class is symmetric: a query rooted in any of
# {partner, wife, husband, spouse, girlfriend, boyfriend} expands to the
# others, so PROD workspaces that represent the user's spouse as "wife"
# OR "husband" OR "spouse" all resolve consistently regardless of how the
# query is phrased ("my partner" / "my spouse" / "my wife").
# "partner" additionally matches the compound "startup_partner" via the
# partial-word tier when the query is qualified ("my design partner");
# bare queries ("my partner") preempt compound matches and resolve to
# the life-partner synonym class deterministically.
_LIFE_PARTNER_CLASS: tuple[str, ...] = (
    "partner", "wife", "husband", "spouse", "girlfriend", "boyfriend",
)
_RELATIONSHIP_SYNONYMS: dict[str, tuple[str, ...]] = {
    word: tuple(w for w in _LIFE_PARTNER_CLASS if w != word)
    for word in _LIFE_PARTNER_CLASS
}


# ── matching phases ───────────────────────────────────────────────

def _match_result(e: dict[str, Any], source: str) -> dict[str, Any]:
    result = {
        "canonical": e["canonical"],
        "aliases": e["aliases"],
        "file": e["file"],
        "frontmatter": e["frontmatter"],
        "match_source": source,
    }
    if "body" in e:
        result["body"] = e["body"]
    return result


def _phase_alias(query_norm: str, entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Phase 1: exact then substring match on name/alias."""
    # exact first
    exact = []
    for e in entities:
        for alias in e["aliases"]:
            if normalize_name(alias) == query_norm:
                exact.append(_match_result(e, "alias_exact"))
                break
    if exact:
        return exact
    # substring fallback
    sub = []
    for e in entities:
        for alias in e["aliases"]:
            a_norm = normalize_name(alias)
            if a_norm and (query_norm in a_norm or a_norm in query_norm):
                sub.append(_match_result(e, "alias_substring"))
                break
    return sub


def _phase_relationship(query_norm: str, entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Phase 2: match on the relationship frontmatter field.

    The relationship value uses underscores (home_server) while the
    query uses spaces (home server). We normalize both.

    Match tiers (stronger tiers preempt weaker ones):
      1. Direct — query ↔ rel substring match.
      2. word_full — rel_words ⊆ q_words (e.g. "startup partner" covers
         startup_partner exactly).
      3. synonym_full — rel_words ⊆ match_targets, no direct q_words
         overlap (e.g. query "partner"/"spouse"/"wife" → rel wife).
      4. word_partial — q_words overlap rel_words but do not cover
         them (e.g. "design partner" shares only "partner" with
         startup_partner).
      5. synonym_partial — match_targets overlap rel_words via synonyms
         but do not cover them (e.g. query "spouse" touches startup_
         partner only through the expanded "partner" sibling).

    Return rules:
      - Any tier-1 → return only those.
      - Else any tier-2 (word_full) → return only those.
      - Else if BARE query (exactly one ≥3-char word that is a synonym
        key) AND synonym_full hits exist → return only synonym_full.
        This resolves "my partner"/"my spouse" → wife deterministically
        without surfacing the compound startup_partner.
      - Else → word_partial + synonym_full + synonym_partial (LLM
        disambiguates among the remaining candidates).
    """
    q_words = {w for w in query_norm.split() if len(w) >= 3}
    match_targets = set(q_words)
    for w in q_words:
        match_targets.update(_RELATIONSHIP_SYNONYMS.get(w, ()))
    bare_query = (len(q_words) == 1
                  and next(iter(q_words), None) in _RELATIONSHIP_SYNONYMS)

    direct: list[dict[str, Any]] = []
    word_full: list[dict[str, Any]] = []
    word_partial: list[dict[str, Any]] = []
    synonym_full: list[dict[str, Any]] = []
    synonym_partial: list[dict[str, Any]] = []
    for e in entities:
        rel = e["frontmatter"].get("relationship", "")
        if not rel:
            continue
        rel_norm = normalize_name(rel.replace("_", " "))
        if not rel_norm:
            continue
        if (query_norm == rel_norm
                or query_norm in rel_norm
                or rel_norm in query_norm):
            direct.append(_match_result(e, "relationship"))
            continue
        rel_words = set(rel_norm.split())
        if not (match_targets & rel_words):
            continue
        if q_words & rel_words:
            if rel_words <= q_words:
                word_full.append(_match_result(e, "relationship_word"))
            else:
                word_partial.append(
                    _match_result(e, "relationship_word_partial"))
        else:
            # No direct q_word overlap — hit is via synonym expansion.
            if rel_words <= match_targets:
                synonym_full.append(_match_result(e, "relationship_synonym"))
            else:
                synonym_partial.append(
                    _match_result(e, "relationship_synonym_partial"))

    if direct:
        return direct
    if word_full:
        return word_full
    if bare_query and synonym_full:
        return synonym_full
    return word_partial + synonym_full + synonym_partial


def _phase_compound(query_norm: str, entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Phase 2b: compound descriptor split.

    For "design partner", try each word as a relationship-type match.
    If multiple entities match the relationship word (e.g. "partner"),
    rank by whether the qualifier word appears in the entity description
    or frontmatter values.
    """
    # Filter stopwords and very short tokens — they produce noise
    # when substring-matched against relationship names.
    _STOP = {"the", "a", "an", "i", "my", "at", "to", "in", "on", "of", "is",
             "it", "me", "we", "he", "do", "if", "or", "so", "no", "up",
             "by", "as", "be", "am", "with", "for", "and", "but", "not",
             "this", "that", "from", "was", "are", "has", "had", "who",
             "how", "what", "when", "where", "which", "talk", "find"}
    words = [w for w in query_norm.split() if len(w) >= 3 and w not in _STOP]
    if len(words) < 2:
        return []
    # try each word as a potential relationship type
    best: list[dict[str, Any]] = []
    for i, rel_word in enumerate(words):
        qualifiers = [w for j, w in enumerate(words) if j != i]
        rel_matches = []
        for e in entities:
            rel = e["frontmatter"].get("relationship", "")
            if not rel:
                continue
            rel_norm = normalize_name(rel.replace("_", " "))
            # Require whole-word match in the relationship name.
            rel_words = rel_norm.split()
            if rel_word not in rel_words:
                continue
            rel_matches.append(e)
        if not rel_matches:
            continue
        # score each match by qualifier presence in description/frontmatter
        scored = []
        for e in rel_matches:
            score = 0
            body_norm = normalize_name(e.get("body", ""))
            fm_values = " ".join(str(v) for v in e["frontmatter"].values())
            fm_norm = normalize_name(fm_values)
            for q in qualifiers:
                if q in body_norm or q in fm_norm:
                    score += 1
            scored.append((score, e))
        scored.sort(key=lambda x: x[0], reverse=True)
        if scored[0][0] > 0:
            # return only entities that matched a qualifier
            best = [_match_result(e, "compound") for s, e in scored if s > 0]
        elif not best:
            # All scored 0 — relationship word matched but no qualifier
            # confirmed. These are weak matches; pass them to later phases
            # (LLM) rather than returning them as definitive.
            pass
    return best


def _phase_description(query_norm: str, entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Phase 3: check if query words appear in the entity description body."""
    q_words = set(query_norm.split())
    if not q_words:
        return []
    matches = []
    for e in entities:
        body = e.get("body", "")
        if not body:
            continue
        body_norm = normalize_name(body)
        # require all query words present in the body
        if all(w in body_norm for w in q_words):
            matches.append(_match_result(e, "description"))
    return matches


# Stopwords for keyword scoring — same set as compound phase.
_SCORE_STOP = {"the", "a", "an", "i", "my", "at", "to", "in", "on", "of",
               "is", "it", "me", "we", "he", "do", "if", "or", "so", "no",
               "up", "by", "as", "be", "am", "with", "for", "and", "but",
               "not", "this", "that", "from", "was", "are", "has", "had",
               "who", "how", "what", "when", "where", "which"}


def _phase_keyword_score(
    query_norm: str, entities: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Phase 3b: flexible keyword scoring across all entity fields.

    Scores each entity by how many content words from the query appear
    in its relationship, description, or email domain. Returns only the
    top scorer(s) if they have a clear lead over the runner-up.
    """
    content_words = [w for w in query_norm.split()
                     if len(w) >= 3 and w not in _SCORE_STOP]
    if not content_words:
        return []

    scored: list[tuple[int, dict[str, Any]]] = []
    for e in entities:
        fm = e.get("frontmatter", {})
        haystack_parts = []
        rel = fm.get("relationship", "")
        if rel:
            haystack_parts.append(normalize_name(rel.replace("_", " ")))
        body = e.get("body", "")
        if body:
            haystack_parts.append(normalize_name(body))
        email = fm.get("primary_contact_email", "")
        if email:
            haystack_parts.append(normalize_name(email.replace(".", " ").replace("@", " ")))
        haystack = " ".join(haystack_parts)
        score = sum(1 for w in content_words if w in haystack)
        if score > 0:
            scored.append((score, e))

    if not scored:
        return []
    scored.sort(key=lambda x: x[0], reverse=True)
    top_score = scored[0][0]
    # Require the top scorer to beat the runner-up by at least 1 point,
    # or be the only scorer, to avoid ambiguity.
    if len(scored) == 1 or top_score > scored[1][0]:
        return [_match_result(scored[0][1], "keyword_score")]
    # Tie — return all tied entities for LLM disambiguation.
    return [_match_result(e, "keyword_score") for s, e in scored if s == top_score]


def _disambiguate_via_llm(
    query: str, candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Ask classifier LLM to pick the best entity match from candidates."""
    if not candidates:
        return []
    def _entity_line(i: int, c: dict[str, Any]) -> str:
        fm = c["frontmatter"]
        parts = [
            f"  {i+1}. {c['canonical']}",
            f"alias={fm.get('alias', '?')}",
            f"kind={fm.get('kind', '?')}",
            f"relationship={fm.get('relationship', '?')}",
        ]
        email = fm.get("primary_contact_email", "")
        if email:
            parts.append(f"email={email}")
        desc = c.get("body", "").strip()
        if desc:
            # First sentence of description — keeps prompt concise.
            short = desc.split(".")[0].strip()
            if short:
                parts.append(f'desc="{short}"')
        return " — ".join(parts[:2]) + ", " + ", ".join(parts[2:])

    numbered = "\n".join(_entity_line(i, c) for i, c in enumerate(candidates))
    system = (
        "You match an informal entity reference to one of the entities "
        "listed below. The query is from the perspective of the workspace "
        "owner (Miles). Match the ENTIRE descriptor, not just the role "
        "word — e.g. 'the founder I talk product with' requires BOTH a "
        "founder-like role AND product-related interaction in the "
        "description. Return ONLY a JSON object:\n"
        '  {"match": "<exact canonical name from the list>", '
        '"confidence": <0.0-1.0>}\n'
        "If none of the entities is a plausible match, return "
        '{"match": null, "confidence": 0.0}.\n'
        "No prose. No markdown fences."
    )
    user = f"Query: {query}\n\nEntities:\n{numbered}"
    try:
        from bitgn_contest_agent import classifier
        raw = classifier.classify(system=system, user=user)
        if not isinstance(raw, dict):
            return candidates
        match_name = raw.get("match")
        conf = float(raw.get("confidence", 0))
        if match_name and conf >= 0.5:
            for c in candidates:
                if c["canonical"] == match_name:
                    return [c]
    except Exception:
        _LOG.debug("LLM entity disambiguation failed for query=%r", query, exc_info=True)
    return []


# ── main entry points ─────────────────────────────────────────────

def _find_matches(query: str, entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    q_norm = normalize_name(query)
    if not q_norm:
        return []

    # Phase 1 — alias (exact then substring)
    hits = _phase_alias(q_norm, entities)
    if len(hits) == 1:
        return hits

    # Phase 2a — relationship field (full query)
    rel_hits = _phase_relationship(q_norm, entities)
    if rel_hits:
        if len(rel_hits) == 1:
            return rel_hits
        # merge with alias hits for disambiguation
        hits = _dedupe(hits + rel_hits)

    # Phase 2b — compound descriptor split (e.g. "design partner")
    if not hits:
        comp_hits = _phase_compound(q_norm, entities)
        if comp_hits:
            if len(comp_hits) == 1:
                return comp_hits
            hits = comp_hits

    # Phase 3 — description body
    if not hits:
        desc_hits = _phase_description(q_norm, entities)
        if desc_hits:
            hits = desc_hits

    # Phase 3b — keyword scoring across all fields
    if not hits:
        kw_hits = _phase_keyword_score(q_norm, entities)
        if kw_hits:
            if len(kw_hits) == 1:
                return kw_hits
            hits = kw_hits

    # Phase 4 — LLM disambiguation for ambiguous or zero matches
    if len(hits) > 1:
        hits = _disambiguate_via_llm(query, hits)
    elif not hits:
        # no match from any phase — try LLM against all entities
        hits = _disambiguate_via_llm(query, [
            _match_result(e, "llm_fallback") for e in entities
        ])

    return hits


def _dedupe(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove duplicate matches by file path."""
    seen: set[str] = set()
    out = []
    for m in matches:
        if m["file"] not in seen:
            seen.add(m["file"])
            out.append(m)
    return out


def run_entity_from_fs(root: Path, entities_root: str, query: str) -> dict[str, Any]:
    root = Path(root)
    entities = _load_entities(root / entities_root)
    # enrich with body text
    for e in entities:
        body_path = root / e["file"]
        if body_path.exists():
            e["body"] = _extract_body(body_path.read_text(encoding="utf-8", errors="replace"))
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
                "body": _extract_body(rr.content),
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
