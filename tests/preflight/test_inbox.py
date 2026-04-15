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
    # Juniper has aliases Juniper Systems + House Mesh → 2 bills expected.
    assert len(item["related_finance_files"]) == 2
