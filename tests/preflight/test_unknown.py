"""Tests for preflight_unknown — the generic UNKNOWN-route preflight.

Mocks the LLM backend; asserts the tool passes the right prompt and
wraps the response as a ToolResult the agent can consume.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from bitgn_contest_agent.preflight.unknown import run_preflight_unknown
from bitgn_contest_agent.schemas import (
    Req_PreflightUnknown,
    Rsp_PreflightUnknown,
    UnknownRecommendedRoot,
)


def test_preflight_unknown_returns_structured_scaffold():
    fake_rsp = Rsp_PreflightUnknown(
        likely_class="ambiguous_referent",
        clarification_risk_flagged=True,
        clarification_risk_why="descriptor 'ambient AI buddy' is not a unique name",
        recommended_roots=[
            UnknownRecommendedRoot(path="10_entities/cast/", why="task mentions a person"),
        ],
        investigation_plan=["enumerate candidates", "if >1 match → OUTCOME_NONE_CLARIFICATION"],
        known_pitfalls=["descriptor matching != unique-name match"],
    )
    fake_backend = MagicMock()
    fake_backend.call_structured.return_value = fake_rsp

    req = Req_PreflightUnknown(
        task_text="When was my ambient AI buddy born?",
        workspace_schema_summary="entities_root=10_entities/cast/, projects_root=40_projects/",
        allowed_roots=["10_entities/cast/", "40_projects/"],
    )
    out = run_preflight_unknown(backend=fake_backend, req=req)
    assert out.ok is True
    assert "ambiguous_referent" in out.content
    assert "clarification" in out.content.lower()
    fake_backend.call_structured.assert_called_once()


def test_preflight_unknown_rejects_hallucinated_root():
    """If the LLM recommends a root not in allowed_roots, it gets
    filtered out of the emitted content."""
    fake_rsp = Rsp_PreflightUnknown(
        likely_class="other",
        clarification_risk_flagged=False,
        recommended_roots=[
            UnknownRecommendedRoot(path="99_made_up_root/", why="hallucination"),
            UnknownRecommendedRoot(path="10_entities/cast/", why="legit"),
        ],
    )
    fake_backend = MagicMock()
    fake_backend.call_structured.return_value = fake_rsp

    req = Req_PreflightUnknown(
        task_text="whatever",
        workspace_schema_summary="...",
        allowed_roots=["10_entities/cast/"],
    )
    out = run_preflight_unknown(backend=fake_backend, req=req)
    assert "99_made_up_root" not in out.content
    assert "10_entities/cast/" in out.content


def test_preflight_unknown_backend_error_returns_skipped_not_crash():
    """Backend exception must not crash the agent — return ok=False
    and let the agent fall through to normal exploration."""
    fake_backend = MagicMock()
    fake_backend.call_structured.side_effect = RuntimeError("llm died")

    req = Req_PreflightUnknown(
        task_text="x",
        workspace_schema_summary="...",
        allowed_roots=[],
    )
    out = run_preflight_unknown(backend=fake_backend, req=req)
    assert out.ok is False
    assert out.error_code == "INTERNAL"
