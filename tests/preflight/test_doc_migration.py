from pathlib import Path

from bitgn_contest_agent.preflight.doc_migration import run_doc_migration_from_fs


FIXTURE = Path(__file__).parent / "fixtures" / "tiny_ws"


def test_doc_migration_resolves_alias_to_entity_dir():
    out = run_doc_migration_from_fs(
        root=FIXTURE,
        source_paths=["some/source/a.md", "some/source/b.md"],
        entities_root="20_entities",
        query="NORA",
    )
    assert out["target_canonical"] == "Nora Rees"
    assert out["destination_root"].startswith("20_entities")


def test_doc_migration_preserves_source_filenames():
    out = run_doc_migration_from_fs(
        root=FIXTURE,
        source_paths=["some/source/a.md"],
        entities_root="20_entities",
        query="NORA",
    )
    m = out["migrations"][0]
    assert m["destination"].endswith("a.md")
    assert m["source"] == "some/source/a.md"
