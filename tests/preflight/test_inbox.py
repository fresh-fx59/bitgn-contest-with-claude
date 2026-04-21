from pathlib import Path
from unittest.mock import patch

from bitgn_contest_agent.preflight.inbox import (
    _load_entities,
    _match_entity,
    _match_sender,
    enumerate_inbox_from_fs,
)
from bitgn_contest_agent.preflight.entity import _extract_body


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


# ── sender-exclusion (t022/t097 regression) ───────────────────────────

_MILES_MD = (
    "# Miles Novak\n\n- alias: `miles`\n- kind: `person`\n"
    "- relationship: `self`\n- primary_contact_email: "
    "`miles@novak.example`\n\nOverloaded systems builder.\n"
)
_NINA_MD = (
    "# Nina Schreiber\n\n- alias: `nina`\n- kind: `person`\n"
    "- relationship: `startup_partner`\n- primary_contact_email: "
    "`nina@finance-workflow.example`\n\nPushes Miles on product.\n"
)
_PETRA_MD = (
    "# Petra Novak\n\n- alias: `petra`\n- kind: `person`\n"
    "- relationship: `wife`\n- primary_contact_email: "
    "`petra@novak.example`\n\nArchitect.\n"
)


def _load_inbox_cast(tmp_path: Path, files: dict[str, str]) -> list[dict]:
    cast = tmp_path / "cast"
    cast.mkdir(parents=True, exist_ok=True)
    for name, body in files.items():
        (cast / name).write_text(body)
    entities = _load_entities(cast)
    for e in entities:
        p = Path(e["file"])
        if p.exists():
            e["body"] = _extract_body(p.read_text())
    return entities


def test_match_sender_resolves_from_email(tmp_path):
    """`from: miles@novak.example` in inbox frontmatter resolves to the
    entity whose primary_contact_email matches."""
    entities = _load_inbox_cast(tmp_path, {
        "miles.md": _MILES_MD,
        "nina.md": _NINA_MD,
    })
    sender = _match_sender({"from": "miles@novak.example"}, entities)
    assert sender is not None
    assert sender["canonical"] == "Miles"


def test_match_sender_returns_none_when_no_match(tmp_path):
    """An unknown sender email yields None (no false match)."""
    entities = _load_inbox_cast(tmp_path, {"nina.md": _NINA_MD})
    assert _match_sender({"from": "stranger@elsewhere.example"}, entities) is None


def test_match_entity_excludes_sender_from_alias_substring(tmp_path):
    """When a body mentions an explicit alias (e.g. 'Nina'), the sender
    (Miles, in signature 'Thanks, Miles') must not steal the match."""
    entities = _load_inbox_cast(tmp_path, {
        "miles.md": _MILES_MD,
        "nina.md": _NINA_MD,
    })
    body = "\nHi,\n\nPlease file Nina's latest receipt.\n\nThanks,\nMiles\n"
    fm = {"from": "miles@novak.example"}
    match = _match_entity(body, entities, fm)
    assert match is not None
    assert match["canonical"] == "Nina"


def test_match_entity_falls_back_to_sender_when_no_subject(tmp_path):
    """If the body doesn't reference any other entity and relationship
    matching returns nothing, return the sender — better than None."""
    entities = _load_inbox_cast(tmp_path, {
        "miles.md": _MILES_MD,
        "nina.md": _NINA_MD,
    })
    body = "\nHi,\n\nPlease file my monthly records.\n\nThanks,\nMiles\n"
    fm = {"from": "miles@novak.example"}
    with patch("bitgn_contest_agent.classifier.classify", return_value={
        "match": None, "confidence": 0.0,
    }):
        match = _match_entity(body, entities, fm)
    assert match is not None
    assert match["canonical"] == "Miles"


def test_match_entity_resolves_design_partner_to_startup_partner(tmp_path):
    """t022/t097 regression: body 'my design partner' sent by Miles must
    resolve to Nina (startup_partner) via LLM disambiguation, not Miles.
    The LLM is mocked to return Nina — in PROD the proxy picks Nina
    because the descriptor 'design partner' semantically matches her
    `startup_partner` relationship."""
    entities = _load_inbox_cast(tmp_path, {
        "miles.md": _MILES_MD,
        "nina.md": _NINA_MD,
        "petra.md": _PETRA_MD,
    })
    body = (
        "\nHi,\n\nReply back with the oldest 1 invoices linked to my "
        "design partner.\n\nThanks,\nMiles\n"
    )
    fm = {"from": "miles@novak.example"}
    with patch("bitgn_contest_agent.classifier.classify", return_value={
        "match": "Nina", "confidence": 0.9,
    }):
        match = _match_entity(body, entities, fm)
    assert match is not None
    assert match["canonical"] == "Nina", match


def test_match_entity_backcompat_without_frontmatter(tmp_path):
    """When no frontmatter is passed (finance.py caller), the legacy
    alias-substring + LLM-fallback behavior is preserved — the sender
    is NOT excluded since there's no way to identify them."""
    entities = _load_inbox_cast(tmp_path, {
        "miles.md": _MILES_MD,
        "nina.md": _NINA_MD,
    })
    # Query mentions "miles" — legacy matcher returns Miles.
    match = _match_entity("records for miles", entities)
    assert match is not None
    assert match["canonical"] == "Miles"
