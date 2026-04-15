from pathlib import Path

from bitgn_contest_agent.preflight.finance import run_finance_from_fs


FIXTURE = Path(__file__).parent / "fixtures" / "tiny_ws"


def test_finance_canonicalizes_via_alias():
    out = run_finance_from_fs(
        root=FIXTURE,
        finance_roots=["50_finance/purchases"],
        entities_root="20_entities",
        query="House Mesh",
    )
    assert out["canonical_entity"] == "Juniper"
    assert len(out["finance_files"]) >= 1


def test_finance_returns_file_metadata():
    out = run_finance_from_fs(
        root=FIXTURE,
        finance_roots=["50_finance/purchases"],
        entities_root="20_entities",
        query="Juniper Systems",
    )
    f = out["finance_files"][0]
    assert "vendor" in f
    assert "path" in f


def test_finance_empty_on_unknown_query():
    out = run_finance_from_fs(
        root=FIXTURE,
        finance_roots=["50_finance/purchases"],
        entities_root="20_entities",
        query="NonExistentVendor XYZ",
    )
    assert out["canonical_entity"] is None
    assert out["finance_files"] == []
