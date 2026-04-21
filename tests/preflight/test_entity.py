from pathlib import Path

from bitgn_contest_agent.preflight.entity import (
    _extract_body,
    _load_entities,
    _phase_relationship,
    normalize_name,
    run_entity_from_fs,
)
from bitgn_contest_agent.preflight.canonicalize import normalize_name as _norm


FIXTURE = Path(__file__).parent / "fixtures" / "tiny_ws"


def _load_cast(tmp_path: Path, files: dict[str, str]) -> list[dict]:
    cast = tmp_path / "cast"
    cast.mkdir(parents=True, exist_ok=True)
    for name, body in files.items():
        (cast / name).write_text(body)
    entities = _load_entities(cast)
    for e in entities:
        p = tmp_path / e["file"]
        if p.exists():
            e["body"] = _extract_body(p.read_text())
    return entities


def test_entity_direct_match():
    out = run_entity_from_fs(
        root=FIXTURE,
        entities_root="20_entities",
        query="Juniper",
    )
    assert len(out["matches"]) >= 1
    assert out["matches"][0]["canonical"] == "Juniper"


def test_entity_alias_match():
    out = run_entity_from_fs(
        root=FIXTURE,
        entities_root="20_entities",
        query="House Mesh",
    )
    assert len(out["matches"]) >= 1
    assert "House Mesh" in out["matches"][0]["aliases"]


def test_entity_no_match():
    out = run_entity_from_fs(
        root=FIXTURE,
        entities_root="20_entities",
        query="Unknown Name ZZZ",
    )
    assert out["matches"] == []


_PETRA_MD = (
    "# Petra\n\n- alias: `petra`\n- kind: `person`\n- relationship: `wife`\n\n"
    "Architect, practical.\n"
)
_NINA_MD = (
    "# Nina\n\n- alias: `nina`\n- kind: `person`\n"
    "- relationship: `startup_partner`\n\nPushes the product forward.\n"
)
_BIX_MD = (
    "# Bix\n\n- alias: `bix`\n- kind: `pet`\n- relationship: `dog`\n\nGood dog.\n"
)


def test_partner_query_returns_both_candidates_for_llm(tmp_path):
    """'my partner' should surface the wife AND the startup_partner so
    the LLM disambiguation step can pick the right one by context."""
    cast = _load_cast(tmp_path, {
        "petra.md": _PETRA_MD,
        "nina.md": _NINA_MD,
    })
    hits = _phase_relationship(normalize_name("my partner"), cast)
    names = {h["canonical"] for h in hits}
    assert names == {"Petra", "Nina"}, hits


def test_wife_query_is_unambiguous(tmp_path):
    """'wife' has no synonyms pointing out — Petra is the sole match."""
    cast = _load_cast(tmp_path, {
        "petra.md": _PETRA_MD,
        "nina.md": _NINA_MD,
    })
    hits = _phase_relationship(normalize_name("wife"), cast)
    names = [h["canonical"] for h in hits]
    assert names == ["Petra"], hits


def test_direct_substring_preempts_synonym_candidates(tmp_path):
    """When a direct substring match exists, synonym/word candidates
    should be suppressed — keeps 'our dog' from pulling in Petra/Nina."""
    cast = _load_cast(tmp_path, {
        "petra.md": _PETRA_MD,
        "bix.md": _BIX_MD,
    })
    hits = _phase_relationship(normalize_name("our dog"), cast)
    names = [h["canonical"] for h in hits]
    assert names == ["Bix"], hits
