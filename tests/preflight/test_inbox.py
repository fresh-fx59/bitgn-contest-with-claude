from pathlib import Path

from bitgn_contest_agent.preflight.inbox import enumerate_inbox_from_fs


FIXTURE = Path(__file__).parent / "fixtures" / "tiny_ws"


def test_enumerate_finds_open_inbox_item():
    items = enumerate_inbox_from_fs(
        root=FIXTURE,
        inbox_root="00_inbox",
        entities_root="20_entities",
        finance_roots=["50_finance/purchases"],
    )
    assert len(items) == 1
    item = items[0]
    assert item["path"].endswith("task_a.md")


def test_item_resolves_entity_via_alias():
    items = enumerate_inbox_from_fs(
        root=FIXTURE,
        inbox_root="00_inbox",
        entities_root="20_entities",
        finance_roots=["50_finance/purchases"],
    )
    item = items[0]
    # "Juniper" in task body should canonicalize to the juniper.md entity.
    assert item["entity_canonical"] is not None


def test_item_lists_all_bills_for_entity():
    items = enumerate_inbox_from_fs(
        root=FIXTURE,
        inbox_root="00_inbox",
        entities_root="20_entities",
        finance_roots=["50_finance/purchases"],
    )
    item = items[0]
    # Juniper has aliases Juniper Systems + House Mesh → 2 vendor-matched
    # bills + 1 filename-matched bill (bill_003_juniper_filter.md) = 3.
    assert len(item["related_finance_files"]) == 3


def test_filename_match_finds_bill_without_vendor_match():
    """Bill whose filename contains entity name but whose vendor field
    does NOT match should still be found via slug matching."""
    items = enumerate_inbox_from_fs(
        root=FIXTURE,
        inbox_root="00_inbox",
        entities_root="20_entities",
        finance_roots=["50_finance/purchases"],
    )
    item = items[0]
    paths = [p for p in item["related_finance_files"] if "juniper_filter" in p]
    assert len(paths) == 1, f"Expected filename-matched bill, got: {item['related_finance_files']}"


def test_inbox_item_includes_full_frontmatter():
    """Every inbox item surfaces the full parsed frontmatter dict so
    fields beyond inbox_type (priority, sender, due, status, ...) are
    visible without re-reading the file."""
    items = enumerate_inbox_from_fs(
        root=FIXTURE,
        inbox_root="00_inbox",
        entities_root="20_entities",
        finance_roots=["50_finance/purchases"],
    )
    assert len(items) >= 1
    for it in items:
        assert "frontmatter" in it
        assert isinstance(it["frontmatter"], dict)
