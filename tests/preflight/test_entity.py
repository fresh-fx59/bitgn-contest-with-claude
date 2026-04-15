from pathlib import Path

from bitgn_contest_agent.preflight.entity import run_entity_from_fs


FIXTURE = Path(__file__).parent / "fixtures" / "tiny_ws"


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
