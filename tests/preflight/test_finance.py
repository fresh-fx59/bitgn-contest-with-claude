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
    assert "path" in f
    assert "frontmatter" in f
    assert f["frontmatter"].get("vendor")


def test_finance_file_record_includes_full_frontmatter():
    """Every invoice record surfaces the full parsed frontmatter dict,
    not a cherry-picked subset. Regression guard for t008 service_line."""
    out = run_finance_from_fs(
        root=FIXTURE,
        finance_roots=["50_finance/purchases"],
        entities_root="20_entities",
        query="Juniper Systems",
    )
    f = out["finance_files"][0]
    assert "frontmatter" in f
    assert isinstance(f["frontmatter"], dict)
    assert "vendor" in f["frontmatter"]


def test_finance_no_entity_match_returns_all_invoices():
    """When the query doesn't match any entity alias, the preflight
    returns all invoices so the agent can filter (e.g., by service_line)
    in-prompt rather than doing cold-start tree/search."""
    out = run_finance_from_fs(
        root=FIXTURE,
        finance_roots=["50_finance/purchases"],
        entities_root="20_entities",
        query="staff follow-up support",
    )
    assert out["canonical_entity"] is None
    assert len(out["finance_files"]) > 0
    for f in out["finance_files"]:
        assert "frontmatter" in f and isinstance(f["frontmatter"], dict)
