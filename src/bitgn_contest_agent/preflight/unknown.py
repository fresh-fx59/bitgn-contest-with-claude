"""preflight_unknown — generic scaffold for tasks the router couldn't
bind to a skill. Emits a structured investigation plan so the agent
starts with food for thought rather than cold-start tree/search.

Unlike other preflights this does NOT call PCM — it operates on the
already-captured workspace schema + a single LLM classification call.
Failures degrade gracefully: the agent falls through to manual
investigation as it would without this preflight.
"""
from __future__ import annotations

from typing import Any

from bitgn_contest_agent.adapter.pcm import ToolResult
from bitgn_contest_agent.preflight.response import build_response
from bitgn_contest_agent.schemas import (
    Req_PreflightUnknown,
    Rsp_PreflightUnknown,
)


_PROMPT_TEMPLATE = """You help an agent bootstrap investigation of a task
that could not be routed to a specialised skill. Analyse the task and
emit a structured scaffold. Be honest when the task is ambiguous.

TASK:
{task}

WORKSPACE SCHEMA (these are the roots that actually exist):
{schema}

ALLOWED ROOTS (you MUST only name paths from this list in
recommended_roots; do not invent new paths):
{allowed_roots}

Classify the task and emit the Rsp_PreflightUnknown object.
Guidelines:
- likely_class: pick the best fit from the enum; "other" is fine
- clarification_risk_flagged: true when the task references an entity
  by descriptor (e.g. "the new hire", "my AI buddy") rather than a
  unique name, OR when multiple candidates could reasonably match
- recommended_roots: 1-4 top roots the agent should investigate,
  drawn ONLY from ALLOWED ROOTS; each with a short "why"
- investigation_plan: 2-5 concrete steps (not abstract advice)
- known_pitfalls: 0-3 gotchas specific to this task class
"""


def _render_content(rsp: Rsp_PreflightUnknown, allowed: set[str]) -> str:
    """Render the structured response as a concise block the agent
    sees. Filters out hallucinated roots not in `allowed`."""
    filtered_roots = [r for r in rsp.recommended_roots if r.path in allowed]
    lines = [
        f"likely_class: {rsp.likely_class}",
    ]
    if rsp.clarification_risk_flagged:
        lines.append(
            f"clarification_risk: FLAGGED — {rsp.clarification_risk_why}"
        )
    if filtered_roots:
        lines.append("recommended_roots:")
        for r in filtered_roots:
            lines.append(f"  - {r.path} — {r.why}")
    if rsp.investigation_plan:
        lines.append("investigation_plan:")
        for i, step in enumerate(rsp.investigation_plan, 1):
            lines.append(f"  {i}. {step}")
    if rsp.known_pitfalls:
        lines.append("known_pitfalls:")
        for p in rsp.known_pitfalls:
            lines.append(f"  - {p}")
    return "\n".join(lines)


def run_preflight_unknown(*, backend: Any, req: Req_PreflightUnknown) -> ToolResult:
    """Dispatch the preflight. `backend` must expose a `call_structured`
    method that takes (prompt: str, response_schema: type[BaseModel])
    and returns an instance of response_schema. See Task B3 for the
    backend-side plumbing of call_structured.
    """
    try:
        prompt = _PROMPT_TEMPLATE.format(
            task=req.task_text,
            schema=req.workspace_schema_summary,
            allowed_roots="\n".join(f"  - {r}" for r in req.allowed_roots),
        )
        rsp: Rsp_PreflightUnknown = backend.call_structured(
            prompt, Rsp_PreflightUnknown,
        )
    except Exception as exc:  # noqa: BLE001 — never crash the agent
        return ToolResult(
            ok=False, content="", refs=tuple(),
            error=f"preflight_unknown failed: {exc}",
            error_code="INTERNAL", wall_ms=0,
        )
    content_body = _render_content(rsp, set(req.allowed_roots))
    summary = (
        f"Task classified as '{rsp.likely_class}'. "
        f"Clarification risk: {'FLAGGED' if rsp.clarification_risk_flagged else 'no'}."
    )
    return ToolResult(
        ok=True,
        content=build_response(summary=summary, data={"scaffold": content_body}),
        refs=tuple(), error=None, error_code=None, wall_ms=0,
    )
