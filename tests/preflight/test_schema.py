import json
from pathlib import Path

from bitgn_contest_agent.preflight.schema import (
    WorkspaceSchema,
    discover_schema_from_fs,
)


FIXTURE = Path(__file__).parent / "fixtures" / "tiny_ws"


def test_discover_schema_identifies_all_roots():
    schema = discover_schema_from_fs(FIXTURE)
    assert schema.inbox_root == "00_inbox"
    assert schema.entities_root == "20_entities"
    assert "50_finance/purchases" in schema.finance_roots
    assert schema.projects_root == "30_projects"
    assert schema.outbox_root == "60_outbox/outbox"


def test_schema_summary_mentions_each_role():
    schema = discover_schema_from_fs(FIXTURE)
    s = schema.summary()
    assert "inbox" in s.lower()
    assert "finance" in s.lower()
    assert "entit" in s.lower()
    assert "project" in s.lower()
    assert "outbox" in s.lower()


def test_schema_as_data_dict_roundtrips_json():
    schema = discover_schema_from_fs(FIXTURE)
    data = schema.as_data()
    # Must be JSON serializable
    json.dumps(data)
    assert data["inbox_root"] == "00_inbox"
