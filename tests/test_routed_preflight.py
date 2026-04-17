"""Tests for routed preflight dispatch.

The dispatcher reads each routed skill's `preflight` frontmatter binding,
constructs the matching `Req_Preflight*` Pydantic object, and runs it
through the harness adapter — never relies on the LLM to opt in.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from bitgn_contest_agent.adapter.pcm import ToolResult
from bitgn_contest_agent.preflight.schema import WorkspaceSchema
from bitgn_contest_agent.router import RoutingDecision
from bitgn_contest_agent.routed_preflight import (
    RoutedPreflightOutcome,
    dispatch_routed_preflight,
)
from bitgn_contest_agent.skill_loader import BitgnSkill


def _skill(category: str, preflight: str | None = None, query_field: str = "query") -> BitgnSkill:
    return BitgnSkill(
        name=f"{category.lower()}-skill",
        description="d",
        type="rigid",
        category=category,
        matcher_patterns=[],
        body="b",
        classifier_hint="hint",
        preflight=preflight,
        preflight_query_field=query_field,
    )


def _ok_result(content: str = '{"summary": "ok", "data": {}}') -> ToolResult:
    return ToolResult(
        ok=True, content=content, refs=(),
        error=None, error_code=None, wall_ms=12,
    )


def test_skipped_when_no_skill_decided() -> None:
    decision = RoutingDecision(
        category="UNKNOWN", source="classifier", confidence=0.0,
        extracted={}, skill_name=None,
    )
    schema = WorkspaceSchema(finance_roots=["/50_finance"], entities_root="/30_e")
    adapter = MagicMock()
    out = dispatch_routed_preflight(
        decision=decision, schema=schema, adapter=adapter, skills_by_name={},
    )
    assert isinstance(out, RoutedPreflightOutcome)
    assert out.tool is None
    assert out.skipped_reason == "no_skill"
    adapter.dispatch.assert_not_called()


def test_skipped_when_skill_has_no_preflight() -> None:
    skill = _skill("OTHER", preflight=None)
    decision = RoutingDecision(
        category="OTHER", source="regex", confidence=1.0,
        extracted={"query": "foo"}, skill_name=skill.name,
    )
    schema = WorkspaceSchema()
    adapter = MagicMock()
    out = dispatch_routed_preflight(
        decision=decision, schema=schema, adapter=adapter,
        skills_by_name={skill.name: skill},
    )
    assert out.tool is None
    assert out.skipped_reason == "no_preflight_for_skill"
    adapter.dispatch.assert_not_called()


def test_skipped_when_query_and_task_text_both_empty() -> None:
    """When extracted has no query AND task_text is empty, skip."""
    skill = _skill("FINANCE_LOOKUP", preflight="preflight_finance")
    decision = RoutingDecision(
        category="FINANCE_LOOKUP", source="classifier", confidence=0.9,
        extracted={}, skill_name=skill.name,
        task_text="",
    )
    schema = WorkspaceSchema(finance_roots=["/50_finance"], entities_root="/30_e")
    adapter = MagicMock()
    out = dispatch_routed_preflight(
        decision=decision, schema=schema, adapter=adapter,
        skills_by_name={skill.name: skill},
    )
    assert out.tool == "preflight_finance"
    assert out.skipped_reason == "missing_query"
    adapter.dispatch.assert_not_called()


def test_regex_match_without_named_group_falls_back_to_task_text() -> None:
    """Tier 1 regex match with no named capture groups should use full
    task_text as query, not skip with missing_query."""
    skill = _skill("FINANCE_LOOKUP", preflight="preflight_finance")
    task = "How much did Acme charge me in total for widgets 51 days ago?"
    decision = RoutingDecision(
        category="FINANCE_LOOKUP", source="regex", confidence=1.0,
        extracted={},  # no named groups extracted
        skill_name=skill.name,
        task_text=task,
    )
    schema = WorkspaceSchema(
        finance_roots=["/50_finance/purchases"],
        entities_root="/30_entities",
    )
    adapter = MagicMock()
    adapter.dispatch.return_value = _ok_result()
    out = dispatch_routed_preflight(
        decision=decision, schema=schema, adapter=adapter,
        skills_by_name={skill.name: skill},
    )
    assert out.tool == "preflight_finance"
    assert out.skipped_reason is None
    assert out.result is not None and out.result.ok
    req = adapter.dispatch.call_args[0][0]
    assert req.query == task


def test_skipped_when_finance_roots_missing() -> None:
    skill = _skill("FINANCE_LOOKUP", preflight="preflight_finance")
    decision = RoutingDecision(
        category="FINANCE_LOOKUP", source="regex", confidence=1.0,
        extracted={"query": "datenspeicher"}, skill_name=skill.name,
    )
    schema = WorkspaceSchema()  # no finance_roots
    adapter = MagicMock()
    out = dispatch_routed_preflight(
        decision=decision, schema=schema, adapter=adapter,
        skills_by_name={skill.name: skill},
    )
    assert out.tool == "preflight_finance"
    assert out.skipped_reason == "missing_roots"
    adapter.dispatch.assert_not_called()


def test_dispatch_finance_with_full_inputs() -> None:
    skill = _skill("FINANCE_LOOKUP", preflight="preflight_finance")
    decision = RoutingDecision(
        category="FINANCE_LOOKUP", source="regex", confidence=1.0,
        extracted={"query": "datenspeicher"}, skill_name=skill.name,
    )
    schema = WorkspaceSchema(
        finance_roots=["/50_finance/purchases"],
        entities_root="/30_entities",
    )
    adapter = MagicMock()
    adapter.dispatch.return_value = _ok_result('{"summary": "1 candidate", "data": {}}')
    out = dispatch_routed_preflight(
        decision=decision, schema=schema, adapter=adapter,
        skills_by_name={skill.name: skill},
    )
    assert out.tool == "preflight_finance"
    assert out.skipped_reason is None
    assert out.result is not None and out.result.ok
    args, _ = adapter.dispatch.call_args
    req = args[0]
    assert req.tool == "preflight_finance"
    assert req.query == "datenspeicher"
    assert req.finance_roots == ["/50_finance/purchases"]
    assert req.entities_root == "/30_entities"


def test_dispatch_entity_query_only() -> None:
    skill = _skill("entity_message_lookup", preflight="preflight_entity")
    decision = RoutingDecision(
        category="entity_message_lookup", source="classifier", confidence=0.9,
        extracted={"query": "the founder"}, skill_name=skill.name,
    )
    schema = WorkspaceSchema(entities_root="/30_entities")
    adapter = MagicMock()
    adapter.dispatch.return_value = _ok_result('{"summary": "matched alex", "data": {}}')
    out = dispatch_routed_preflight(
        decision=decision, schema=schema, adapter=adapter,
        skills_by_name={skill.name: skill},
    )
    assert out.tool == "preflight_entity"
    assert out.skipped_reason is None
    assert out.result is not None and out.result.ok
    args, _ = adapter.dispatch.call_args
    req = args[0]
    assert req.tool == "preflight_entity"
    assert req.query == "the founder"
    assert req.entities_root == "/30_entities"


def test_dispatch_swallows_exception_and_returns_skip() -> None:
    skill = _skill("FINANCE_LOOKUP", preflight="preflight_finance")
    decision = RoutingDecision(
        category="FINANCE_LOOKUP", source="regex", confidence=1.0,
        extracted={"query": "datenspeicher"}, skill_name=skill.name,
    )
    schema = WorkspaceSchema(
        finance_roots=["/50_finance"], entities_root="/30_e",
    )
    adapter = MagicMock()
    adapter.dispatch.side_effect = RuntimeError("boom")
    out = dispatch_routed_preflight(
        decision=decision, schema=schema, adapter=adapter,
        skills_by_name={skill.name: skill},
    )
    assert out.tool == "preflight_finance"
    assert out.skipped_reason == "dispatch_exception"
    assert out.error == "boom"


def test_dispatch_routes_unknown_to_preflight_unknown():
    """When decision.skill_name is None (router returned UNKNOWN), the
    dispatcher runs preflight_unknown rather than skipping with
    reason='no_skill' — provided a backend is available."""
    from bitgn_contest_agent.adapter.pcm import ToolResult as TR
    from unittest.mock import patch

    fake_backend = MagicMock()
    schema = WorkspaceSchema(
        entities_root="10_entities/cast",
        projects_root="40_projects",
        finance_roots=["50_finance/invoices"],
        inbox_root="00_inbox",
    )
    decision = RoutingDecision(
        category="UNKNOWN",
        source="unknown",
        confidence=0.0,
        extracted={},
        skill_name=None,
        task_text="when was my ambient buddy born",
    )
    fake_result = TR(
        ok=True,
        content="scaffold content",
        refs=(),
        error=None,
        error_code=None,
        wall_ms=5,
    )
    with patch(
        "bitgn_contest_agent.preflight.unknown.run_preflight_unknown",
        return_value=fake_result,
    ) as mock_run:
        out = dispatch_routed_preflight(
            decision=decision,
            schema=schema,
            adapter=MagicMock(),
            skills_by_name={},
            backend=fake_backend,
        )

    assert out.tool == "preflight_unknown"
    assert out.result is not None and out.result.ok is True
    mock_run.assert_called_once()
    # verify the allowed_roots contains schema roots (hallucination guard input)
    call_kwargs = mock_run.call_args.kwargs
    assert "entities_root" in str(call_kwargs["req"].workspace_schema_summary) \
        or "10_entities/cast" in call_kwargs["req"].allowed_roots
