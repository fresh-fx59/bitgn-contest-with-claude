"""Harness-level preflight gate — proves that non-whitelisted tool
calls are rejected until a preflight_* tool has been observed.
"""
from bitgn_contest_agent.harness_gate import (
    PREFLIGHT_WHITELIST,
    is_preflight_tool,
    should_reject,
)


def test_whitelist_contains_schema_list_context():
    assert "preflight_schema" in PREFLIGHT_WHITELIST
    assert "list" in PREFLIGHT_WHITELIST
    assert "context" in PREFLIGHT_WHITELIST
    assert "report_completion" in PREFLIGHT_WHITELIST


def test_is_preflight_tool_true_for_all_six():
    for name in [
        "preflight_schema", "preflight_inbox", "preflight_finance",
        "preflight_entity", "preflight_project", "preflight_doc_migration",
    ]:
        assert is_preflight_tool(name)


def test_should_reject_when_read_before_preflight():
    # No preflight seen yet, first non-whitelisted call is 'read'
    assert should_reject(tool_name="read", preflight_seen=False) is True


def test_should_reject_false_when_preflight_seen():
    assert should_reject(tool_name="read", preflight_seen=True) is False


def test_should_reject_false_for_whitelist_even_without_preflight():
    assert should_reject(tool_name="list", preflight_seen=False) is False
    assert should_reject(tool_name="preflight_schema", preflight_seen=False) is False


def test_should_reject_false_for_preflight_itself():
    assert should_reject(tool_name="preflight_inbox", preflight_seen=False) is False
