"""Harness-side preflight dispatch driven by router category.

After the router decides a category, this module looks up the matching
preflight tool from the skill's frontmatter and dispatches it through
the same adapter the LLM would use. The result is injected as a user
message before the main loop, so the model never has to opt in.

The five mappings (skill category -> preflight tool) live on each
skill's frontmatter (`preflight:` and `preflight_query_field:`). This
module reads those mappings and constructs the right `Req_Preflight*`
Pydantic object.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple

from bitgn_contest_agent.preflight.schema import WorkspaceSchema
from bitgn_contest_agent.router import RoutingDecision
from bitgn_contest_agent.schemas import (
    Req_PreflightDocMigration,
    Req_PreflightEntity,
    Req_PreflightFinance,
    Req_PreflightInbox,
    Req_PreflightProject,
)
from bitgn_contest_agent.skill_loader import BitgnSkill

_LOG = logging.getLogger(__name__)


@dataclass
class RoutedPreflightOutcome:
    """Result of attempting a routed preflight dispatch.

    `tool` is the preflight tool name attempted (None if skipped before
    we even chose a tool). `result` is the adapter's `ToolResult` if
    dispatch ran. `skipped_reason` is set when no dispatch happened.
    `error` carries the exception message if dispatch raised.
    """
    tool: Optional[str] = None
    result: Optional[Any] = None
    skipped_reason: Optional[str] = None
    error: Optional[str] = None


def dispatch_routed_preflight(
    *,
    decision: RoutingDecision,
    schema: WorkspaceSchema,
    adapter: Any,
    skills_by_name: Dict[str, BitgnSkill],
    backend: Any = None,
) -> RoutedPreflightOutcome:
    """Dispatch the preflight tool bound to the decided skill, if any.

    Returns RoutedPreflightOutcome describing what happened. Callers
    should inject `result.content` as a user message when `tool` is set
    AND `result.ok` is True.
    """
    if decision.skill_name is None:
        if backend is None:
            return RoutedPreflightOutcome(skipped_reason="no_skill")
        return _dispatch_unknown(
            decision=decision, schema=schema, backend=backend,
        )

    skill = skills_by_name.get(decision.skill_name)
    if skill is None or not skill.preflight:
        return RoutedPreflightOutcome(skipped_reason="no_preflight_for_skill")

    tool = skill.preflight
    query_field = skill.preflight_query_field or "query"
    raw_query = (decision.extracted or {}).get(query_field)
    query = raw_query.strip() if isinstance(raw_query, str) else ""
    # Fall back to full task text when regex match didn't extract a query.
    if not query and decision.task_text:
        query = decision.task_text

    builder = _BUILDERS.get(tool)
    if builder is None:
        return RoutedPreflightOutcome(
            tool=tool, skipped_reason="unknown_preflight_tool",
        )

    req, missing = builder(query=query, schema=schema)
    if missing:
        return RoutedPreflightOutcome(tool=tool, skipped_reason=missing)

    try:
        result = adapter.dispatch(req)
    except Exception as exc:  # noqa: BLE001 — never crash the task
        _LOG.warning("routed_preflight %s dispatch raised: %s", tool, exc)
        return RoutedPreflightOutcome(
            tool=tool, skipped_reason="dispatch_exception", error=str(exc),
        )

    return RoutedPreflightOutcome(tool=tool, result=result)


# ---------------------------------------------------------------------
# Per-tool builders. Each returns (Req_* | None, missing_reason | None).
# ---------------------------------------------------------------------


_BuilderResult = Tuple[Optional[Any], Optional[str]]


def _build_finance(*, query: str, schema: WorkspaceSchema) -> _BuilderResult:
    if not query:
        return None, "missing_query"
    if not schema.finance_roots or not schema.entities_root:
        return None, "missing_roots"
    req = Req_PreflightFinance(
        tool="preflight_finance",
        query=query,
        finance_roots=list(schema.finance_roots),
        entities_root=schema.entities_root,
    )
    return req, None


def _build_entity(*, query: str, schema: WorkspaceSchema) -> _BuilderResult:
    if not query:
        return None, "missing_query"
    if not schema.entities_root:
        return None, "missing_roots"
    req = Req_PreflightEntity(
        tool="preflight_entity",
        query=query,
        entities_root=schema.entities_root,
    )
    return req, None


def _build_project(*, query: str, schema: WorkspaceSchema) -> _BuilderResult:
    if not query:
        return None, "missing_query"
    if not schema.entities_root or not schema.projects_root:
        return None, "missing_roots"
    req = Req_PreflightProject(
        tool="preflight_project",
        query=query,
        projects_root=schema.projects_root,
        entities_root=schema.entities_root,
    )
    return req, None


def _build_doc_migration(*, query: str, schema: WorkspaceSchema) -> _BuilderResult:
    # source_paths has min_length=1 in the Pydantic schema. The router
    # has no per-task source paths today, so until the classifier
    # extracts them we cannot dispatch this preflight from the harness.
    # Skip cleanly so the skill body's fall-through search runs.
    if not query:
        return None, "missing_query"
    return None, "missing_source_paths"


def _build_inbox(*, query: str, schema: WorkspaceSchema) -> _BuilderResult:
    # query is unused for inbox preflight (root-driven enumeration).
    if (not schema.inbox_root or not schema.entities_root
            or not schema.finance_roots):
        return None, "missing_roots"
    req = Req_PreflightInbox(
        tool="preflight_inbox",
        inbox_root=schema.inbox_root,
        entities_root=schema.entities_root,
        finance_roots=list(schema.finance_roots),
    )
    return req, None


_BUILDERS: Dict[str, Callable[..., _BuilderResult]] = {
    "preflight_finance": _build_finance,
    "preflight_entity": _build_entity,
    "preflight_project": _build_project,
    "preflight_doc_migration": _build_doc_migration,
    "preflight_inbox": _build_inbox,
}


def _dispatch_unknown(
    *,
    decision: RoutingDecision,
    schema: WorkspaceSchema,
    backend: Any,
) -> RoutedPreflightOutcome:
    from bitgn_contest_agent.preflight.unknown import run_preflight_unknown
    from bitgn_contest_agent.schemas import Req_PreflightUnknown

    allowed = [r for r in [
        schema.entities_root, schema.projects_root, schema.inbox_root,
        *schema.finance_roots,
    ] if r]

    # Compact summary — one line per root.
    summary_lines: list[str] = []
    if schema.entities_root:
        summary_lines.append(f"entities_root={schema.entities_root}")
    if schema.projects_root:
        summary_lines.append(f"projects_root={schema.projects_root}")
    if schema.inbox_root:
        summary_lines.append(f"inbox_root={schema.inbox_root}")
    if schema.finance_roots:
        summary_lines.append(f"finance_roots={','.join(schema.finance_roots)}")

    req = Req_PreflightUnknown(
        task_text=decision.task_text,
        workspace_schema_summary="; ".join(summary_lines),
        allowed_roots=allowed,
    )
    try:
        result = run_preflight_unknown(backend=backend, req=req)
    except Exception as exc:  # noqa: BLE001 — never crash the agent
        _LOG.warning("preflight_unknown raised: %s", exc)
        return RoutedPreflightOutcome(
            tool="preflight_unknown",
            skipped_reason="dispatch_exception",
            error=str(exc),
        )
    return RoutedPreflightOutcome(tool="preflight_unknown", result=result)
