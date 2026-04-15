"""Harness-level preflight gate.

Policy: before any non-whitelisted tool call, at least one preflight_*
tool must have been successfully dispatched in the current task trace.
Rejected calls do not consume a step; the agent is told to preflight
first and retries.

Whitelist covers:
 - preflight tools themselves (so the agent can call them)
 - light discovery (list, context) — safe probes that don't read content
 - report_completion — agents that fail to do any work still get to
   terminate rather than spin forever.
"""
from __future__ import annotations


PREFLIGHT_TOOLS = frozenset({
    "preflight_schema",
    "preflight_inbox",
    "preflight_finance",
    "preflight_entity",
    "preflight_project",
    "preflight_doc_migration",
})

PREFLIGHT_WHITELIST = PREFLIGHT_TOOLS | frozenset({
    "list",
    "context",
    "report_completion",
})


REJECTION_MESSAGE = (
    "Preflight required. Before reading, searching, or writing anything, "
    "call preflight_schema to learn the workspace layout, then call the "
    "preflight_* tool(s) that match your task: preflight_inbox for inbox/OCR, "
    "preflight_finance for finance lookups, preflight_entity for entity "
    "questions, preflight_project for project questions, "
    "preflight_doc_migration for document migration. You may call any of "
    "these again later in the task."
)


def is_preflight_tool(tool_name: str) -> bool:
    return tool_name in PREFLIGHT_TOOLS


def should_reject(tool_name: str, preflight_seen: bool) -> bool:
    if tool_name in PREFLIGHT_WHITELIST:
        return False
    return not preflight_seen
