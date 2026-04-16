# Router-Driven Preflight Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make preflight a deterministic harness side-effect of routing — fire the matching `preflight_*` call right after `router.route()` and inject the result as a user message before the LLM main loop. Remove preflight tools from the LLM function schema. Strip the unused "USE WHEN" wording from skill bodies.

**Architecture:** New `WorkspaceSchema` dataclass parsed once from `preflight_schema` summary. New `BitgnSkill` frontmatter fields `preflight` + `preflight_query_field` declare the harness binding. New `dispatch_routed_preflight(decision, schema, adapter)` helper called from `agent.py` between `_build_initial_messages` and the prepass loop's bootstrap injection. Removed: 6 preflight types from `FunctionUnion`; the `PREFLIGHT_PROTOCOL` block in `prompts.py`; "Step 0: Workspace exploration shortcut" in 5 skill files.

**Tech Stack:** Python 3.12, Pydantic v2 (discriminated Union), pytest, existing `PcmAdapter` dispatch pattern.

**Spec:** [`docs/superpowers/specs/2026-04-16-router-driven-preflight-design.md`](../specs/2026-04-16-router-driven-preflight-design.md)

---

## File Structure

**Create:**
- `src/bitgn_contest_agent/workspace_schema.py` — `WorkspaceSchema` dataclass + `parse_schema_summary()`
- `src/bitgn_contest_agent/routed_preflight.py` — `dispatch_routed_preflight()` + category→tool table sourced from skill frontmatter
- `tests/test_workspace_schema.py`
- `tests/test_routed_preflight.py`

**Modify:**
- `src/bitgn_contest_agent/skills.py` — extend `BitgnSkill` dataclass + frontmatter parser
- `src/bitgn_contest_agent/skills/finance_lookup.md` — frontmatter + body
- `src/bitgn_contest_agent/skills/bill_query.md` — frontmatter + body
- `src/bitgn_contest_agent/skills/entity_message_lookup.md` — frontmatter + body
- `src/bitgn_contest_agent/skills/project_involvement.md` — frontmatter + body
- `src/bitgn_contest_agent/skills/document_migration.md` — frontmatter + body
- `src/bitgn_contest_agent/router.py` — extend classifier system prompt with `extracted.query` requirement; ensure regex named groups already plumb through
- `src/bitgn_contest_agent/adapter/pcm.py` — `run_prepass` returns `(bootstrap_content, schema)` instead of `bootstrap_content`
- `src/bitgn_contest_agent/agent.py` — call `dispatch_routed_preflight` after router decision, inject result; consume tuple from `run_prepass`
- `src/bitgn_contest_agent/schemas.py` — drop 6 preflight types from `FunctionUnion`; keep classes
- `src/bitgn_contest_agent/prompts.py` — delete `PREFLIGHT_PROTOCOL` and stop appending it to `_STATIC_SYSTEM_PROMPT`
- `tests/test_adapter_prepass.py` — update for new return signature
- `tests/test_skills.py` — frontmatter loader tests
- `tests/test_router.py` — classifier prompt asks for query, parser preserves it
- `tests/test_agent_loop.py` — add a routed-preflight injection integration test

---

## Task Breakdown

### Task 1: WorkspaceSchema dataclass + parser

**Files:**
- Create: `src/bitgn_contest_agent/workspace_schema.py`
- Create: `tests/test_workspace_schema.py`

**Background:** `preflight_schema` returns a JSON-ish summary string today (look at `src/bitgn_contest_agent/preflight/schema.py` to confirm shape). We need to parse that once, store the discovered roots typed, and pass it to the routed preflight dispatcher. Roots needed: `inbox_root: str | None`, `entities_root: str | None`, `finance_roots: list[str]`, `projects_root: str | None`. Use `dataclass(frozen=True)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_workspace_schema.py
"""Tests for WorkspaceSchema parsing."""
from __future__ import annotations

from bitgn_contest_agent.workspace_schema import WorkspaceSchema, parse_schema_summary


def test_parse_full_schema():
    summary = (
        '{"inbox_root": "/10_inbox", "entities_root": "/30_entities", '
        '"finance_roots": ["/50_finance/purchases", "/50_finance/invoices"], '
        '"projects_root": "/40_projects"}'
    )
    schema = parse_schema_summary(summary)
    assert schema.inbox_root == "/10_inbox"
    assert schema.entities_root == "/30_entities"
    assert schema.finance_roots == ("/50_finance/purchases", "/50_finance/invoices")
    assert schema.projects_root == "/40_projects"


def test_parse_partial_schema():
    summary = '{"finance_roots": ["/50_finance"]}'
    schema = parse_schema_summary(summary)
    assert schema.inbox_root is None
    assert schema.entities_root is None
    assert schema.finance_roots == ("/50_finance",)
    assert schema.projects_root is None


def test_parse_invalid_returns_empty():
    schema = parse_schema_summary("not json at all")
    assert schema.inbox_root is None
    assert schema.entities_root is None
    assert schema.finance_roots == ()
    assert schema.projects_root is None


def test_parse_none_returns_empty():
    schema = parse_schema_summary(None)
    assert schema == WorkspaceSchema()
```

- [ ] **Step 2: Run test to verify failure**

```
.venv/bin/pytest tests/test_workspace_schema.py -v
```
Expected: 4 FAILs with `ModuleNotFoundError: bitgn_contest_agent.workspace_schema`.

- [ ] **Step 3: Implement `workspace_schema.py`**

```python
# src/bitgn_contest_agent/workspace_schema.py
"""Typed view of the workspace roots discovered by preflight_schema.

The preflight_schema preflight tool returns a JSON-ish summary listing
the canonical roots for inbox / entities / finance / projects. We parse
it once at prepass time so downstream code (routed preflight dispatch,
arch logging) can pass typed root paths without re-reading the summary
each time.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional, Tuple


@dataclass(frozen=True)
class WorkspaceSchema:
    inbox_root: Optional[str] = None
    entities_root: Optional[str] = None
    finance_roots: Tuple[str, ...] = ()
    projects_root: Optional[str] = None


def parse_schema_summary(summary: Optional[str]) -> WorkspaceSchema:
    """Parse the preflight_schema summary string into a WorkspaceSchema.

    Returns an empty WorkspaceSchema on any parse failure. Callers
    should treat that as 'no preflight roots discovered' and skip
    routed preflight dispatch for tasks needing roots.
    """
    if not summary:
        return WorkspaceSchema()
    try:
        data = json.loads(summary)
    except (json.JSONDecodeError, TypeError):
        return WorkspaceSchema()
    if not isinstance(data, dict):
        return WorkspaceSchema()
    finance_raw = data.get("finance_roots") or ()
    if isinstance(finance_raw, str):
        finance_roots: Tuple[str, ...] = (finance_raw,)
    elif isinstance(finance_raw, (list, tuple)):
        finance_roots = tuple(str(x) for x in finance_raw)
    else:
        finance_roots = ()
    return WorkspaceSchema(
        inbox_root=_str_or_none(data.get("inbox_root")),
        entities_root=_str_or_none(data.get("entities_root")),
        finance_roots=finance_roots,
        projects_root=_str_or_none(data.get("projects_root")),
    )


def _str_or_none(v: object) -> Optional[str]:
    if isinstance(v, str) and v:
        return v
    return None
```

**Verify the actual `preflight_schema` summary shape first** by reading `src/bitgn_contest_agent/preflight/schema.py` and any test that exercises it. If the real summary uses different keys or wrapping (e.g. `{"summary": "...", "data": {"roots": {...}}}`), adjust `parse_schema_summary` to extract from the right path. Add a test fixture using the actual real summary string.

- [ ] **Step 4: Run tests to verify pass**

```
.venv/bin/pytest tests/test_workspace_schema.py -v
```
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/bitgn_contest_agent/workspace_schema.py tests/test_workspace_schema.py
git commit -m "feat(preflight): add WorkspaceSchema dataclass + parser"
```

---

### Task 2: BitgnSkill frontmatter — `preflight` + `preflight_query_field`

**Files:**
- Modify: `src/bitgn_contest_agent/skills.py`
- Modify: `tests/test_skills.py`

**Background:** Each routed skill needs to declare which preflight tool the harness should auto-call (or none) and which `extracted` field carries the query. The frontmatter parser today (`load_skill`) reads `name`, `description`, `category`, `matcher_patterns`, `classifier_hint`. Extend with two optional fields: `preflight: str | None`, `preflight_query_field: str | None` (defaults to `"query"`).

- [ ] **Step 1: Read current skill loader**

```bash
.venv/bin/python -c "from bitgn_contest_agent.skills import BitgnSkill, load_skill; help(BitgnSkill); help(load_skill)"
```

Confirm `BitgnSkill` is a dataclass and `load_skill` parses YAML-ish frontmatter. Locate exact line numbers.

- [ ] **Step 2: Write the failing test**

Add to `tests/test_skills.py`:

```python
def test_load_skill_with_preflight_frontmatter(tmp_path):
    md = tmp_path / "demo.md"
    md.write_text(
        "---\n"
        "name: demo\n"
        "description: d\n"
        "category: DEMO\n"
        "preflight: preflight_finance\n"
        "preflight_query_field: vendor\n"
        "---\n"
        "Body.\n"
    )
    from bitgn_contest_agent.skills import load_skill
    s = load_skill(md)
    assert s.preflight == "preflight_finance"
    assert s.preflight_query_field == "vendor"


def test_load_skill_without_preflight_defaults_none(tmp_path):
    md = tmp_path / "demo.md"
    md.write_text(
        "---\n"
        "name: demo\n"
        "description: d\n"
        "category: DEMO\n"
        "---\n"
        "Body.\n"
    )
    from bitgn_contest_agent.skills import load_skill
    s = load_skill(md)
    assert s.preflight is None
    assert s.preflight_query_field == "query"
```

- [ ] **Step 3: Run tests to verify failure**

```
.venv/bin/pytest tests/test_skills.py::test_load_skill_with_preflight_frontmatter tests/test_skills.py::test_load_skill_without_preflight_defaults_none -v
```
Expected: FAIL — `BitgnSkill` has no `preflight` attribute.

- [ ] **Step 4: Extend `BitgnSkill` + parser**

In `src/bitgn_contest_agent/skills.py`, add to the dataclass (preserving field order; new fields with defaults go last):

```python
preflight: Optional[str] = None
preflight_query_field: str = "query"
```

In `load_skill` (or its frontmatter parsing helper), pull these two keys with `data.get("preflight")` and `data.get("preflight_query_field", "query")`. Pass into the `BitgnSkill(...)` constructor.

- [ ] **Step 5: Run tests to verify pass**

```
.venv/bin/pytest tests/test_skills.py -v
```
Expected: ALL PASS (existing skill tests + 2 new).

- [ ] **Step 6: Commit**

```bash
git add src/bitgn_contest_agent/skills.py tests/test_skills.py
git commit -m "feat(preflight): add preflight + preflight_query_field to BitgnSkill frontmatter"
```

---

### Task 3: Update 5 skill .md files — frontmatter + Step 0 rewrite

**Files:**
- Modify: `src/bitgn_contest_agent/skills/finance_lookup.md`
- Modify: `src/bitgn_contest_agent/skills/bill_query.md`
- Modify: `src/bitgn_contest_agent/skills/entity_message_lookup.md`
- Modify: `src/bitgn_contest_agent/skills/project_involvement.md`
- Modify: `src/bitgn_contest_agent/skills/document_migration.md`

**Per-skill changes** — for each file:

1. Add to frontmatter (between existing keys):
   - `finance_lookup.md`: `preflight: preflight_finance` and `preflight_query_field: query`
   - `bill_query.md`: `preflight: preflight_finance` and `preflight_query_field: query`
   - `entity_message_lookup.md`: `preflight: preflight_entity` and `preflight_query_field: query`
   - `project_involvement.md`: `preflight: preflight_project` and `preflight_query_field: query`
   - `document_migration.md`: `preflight: preflight_doc_migration` and `preflight_query_field: query`

2. Replace the existing "Step 0: Workspace exploration shortcut" section with this exact text:

```markdown
## Step 0: Pre-fetched context

A `PREFLIGHT` user message above (auto-dispatched by the router for this task shape) contains the canonical narrowing — the matching record(s), entity canonicalization, or destination resolution. Treat it as ground truth and start from those references. Fall through to the strategy below only if preflight returned nothing usable or the question needs more than what was pre-fetched.
```

- [ ] **Step 1: Apply edits to all 5 files**

Use Edit to find the existing `## Step 0:` heading + body in each and replace per the rule above. Frontmatter additions go in the same Edit (combine old_string to include the closing `---` marker for safety).

- [ ] **Step 2: Sanity check**

```bash
.venv/bin/python -c "
from bitgn_contest_agent.router import load_router
from pathlib import Path
r = load_router(Path('src/bitgn_contest_agent/skills'))
for c in r._compiled:
    print(c.skill.name, '->', c.skill.preflight)
"
```
Expected output:
```
bill-query -> preflight_finance
document-migration -> preflight_doc_migration
entity-message-lookup -> preflight_entity
finance-lookup -> preflight_finance
project-involvement -> preflight_project
```

- [ ] **Step 3: Commit**

```bash
git add src/bitgn_contest_agent/skills/
git commit -m "refactor(skills): bind each routed skill to its preflight + simplify Step 0"
```

---

### Task 4: Router classifier asks for query

**Files:**
- Modify: `src/bitgn_contest_agent/router.py`
- Modify: `tests/test_router.py`

**Background:** Tier2 classifier today returns `{"category", "confidence", "extracted"}`. The classifier system prompt in `_classifier_system_prompt` (router.py:163) needs to instruct the model to populate `extracted.query` with a short string capturing the most specific identifier in the task — vendor name, person reference, project hint, etc. — when one exists. `parse_response` already preserves arbitrary `extracted` fields, so no change needed there.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_router.py`:

```python
def test_classifier_system_prompt_requests_query_field():
    from bitgn_contest_agent.router import _classifier_system_prompt
    sys_prompt = _classifier_system_prompt([("FINANCE_LOOKUP", "finance task")])
    # Must request a query field with examples
    assert "query" in sys_prompt.lower()
    assert "extracted" in sys_prompt.lower()
```

- [ ] **Step 2: Run test to verify failure**

```
.venv/bin/pytest tests/test_router.py::test_classifier_system_prompt_requests_query_field -v
```
Expected: FAIL — current prompt mentions only `target_name` example.

- [ ] **Step 3: Update `_classifier_system_prompt`**

In `router.py:163`, replace the JSON example block. New body:

```python
def _classifier_system_prompt(skill_meta: list[tuple[str, str]]) -> str:
    lines = [f"  - {cat}: {hint}" for cat, hint in skill_meta]
    lines.append("  - UNKNOWN: task does not match any known category")
    category_block = "\n".join(lines)
    return (
        "You classify bitgn benchmark tasks into one of these categories:\n"
        f"{category_block}\n"
        "\n"
        "Return ONLY a JSON object of the form:\n"
        '  {"category": "<one of above>", "confidence": <0.0-1.0>, '
        '"extracted": {"query": "<short canonical identifier from the task>"}}\n'
        "\n"
        'The "query" field should be a short string with the most specific '
        'identifier the task hinges on — a vendor name, item description, '
        'person reference, project hint, or destination system. Omit "query" '
        'only if the task has no such identifier (e.g. inbox tasks like '
        '"take the next inbox item").\n'
        "\n"
        "No prose. No markdown fences."
    )
```

- [ ] **Step 4: Run tests to verify pass**

```
.venv/bin/pytest tests/test_router.py -v
```
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add src/bitgn_contest_agent/router.py tests/test_router.py
git commit -m "feat(router): classifier prompt requests extracted.query for routed preflight"
```

---

### Task 5: `dispatch_routed_preflight` helper

**Files:**
- Create: `src/bitgn_contest_agent/routed_preflight.py`
- Create: `tests/test_routed_preflight.py`

**Background:** Pure function called by the agent loop. Input: `RoutingDecision`, `WorkspaceSchema`, `PcmAdapter`. Output: `Optional[ToolResult]` plus a record of what was attempted (for trace/arch logging). The dispatcher reads the `BitgnSkill.preflight` + `BitgnSkill.preflight_query_field` for the matched skill, plucks the query from `decision.extracted`, fills root args from the schema, constructs the right `Req_Preflight*` Pydantic object, calls `adapter.dispatch(req)`, returns the `ToolResult`. Returns `(None, "skipped:<reason>")` when:

- `decision.skill_name is None` or category UNKNOWN
- skill has no `preflight` frontmatter
- query is required but missing/empty
- needed roots are missing from schema (e.g. `preflight_finance` needs `finance_roots`)

- [ ] **Step 1: Write failing tests**

```python
# tests/test_routed_preflight.py
"""Tests for routed preflight dispatch."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from bitgn_contest_agent.router import RoutingDecision
from bitgn_contest_agent.routed_preflight import (
    RoutedPreflightOutcome,
    dispatch_routed_preflight,
)
from bitgn_contest_agent.skills import BitgnSkill
from bitgn_contest_agent.workspace_schema import WorkspaceSchema


def _skill(category, preflight=None, query_field="query"):
    return BitgnSkill(
        name=f"{category.lower()}-skill",
        description="d",
        category=category,
        body="b",
        matcher_patterns=[],
        classifier_hint=None,
        preflight=preflight,
        preflight_query_field=query_field,
    )


def test_skipped_when_no_skill_decided():
    decision = RoutingDecision(
        category="UNKNOWN", source="classifier", confidence=0.0,
        extracted={}, skill_name=None,
    )
    schema = WorkspaceSchema(finance_roots=("/50_finance",), entities_root="/30_e")
    adapter = MagicMock()
    out = dispatch_routed_preflight(
        decision=decision, schema=schema, adapter=adapter, skills_by_name={},
    )
    assert out.tool is None
    assert out.skipped_reason == "no_skill"
    adapter.dispatch.assert_not_called()


def test_skipped_when_skill_has_no_preflight():
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


def test_skipped_when_query_missing_for_finance():
    skill = _skill("FINANCE_LOOKUP", preflight="preflight_finance")
    decision = RoutingDecision(
        category="FINANCE_LOOKUP", source="classifier", confidence=0.9,
        extracted={}, skill_name=skill.name,
    )
    schema = WorkspaceSchema(finance_roots=("/50_finance",), entities_root="/30_e")
    adapter = MagicMock()
    out = dispatch_routed_preflight(
        decision=decision, schema=schema, adapter=adapter,
        skills_by_name={skill.name: skill},
    )
    assert out.tool is None
    assert out.skipped_reason == "missing_query"


def test_skipped_when_finance_roots_missing():
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
    assert out.tool is None
    assert out.skipped_reason == "missing_roots"


def test_dispatch_finance_with_full_inputs():
    from bitgn_contest_agent.adapter.pcm import ToolResult
    skill = _skill("FINANCE_LOOKUP", preflight="preflight_finance")
    decision = RoutingDecision(
        category="FINANCE_LOOKUP", source="regex", confidence=1.0,
        extracted={"query": "datenspeicher"}, skill_name=skill.name,
    )
    schema = WorkspaceSchema(
        finance_roots=("/50_finance/purchases",),
        entities_root="/30_entities",
    )
    adapter = MagicMock()
    adapter.dispatch.return_value = ToolResult(
        ok=True, content='{"summary": "1 candidate", "data": {}}',
        refs=(), error=None, error_code=None, wall_ms=12, bytes=42,
    )
    out = dispatch_routed_preflight(
        decision=decision, schema=schema, adapter=adapter,
        skills_by_name={skill.name: skill},
    )
    assert out.tool == "preflight_finance"
    assert out.skipped_reason is None
    assert out.result is not None and out.result.ok
    # confirm the constructed Req_PreflightFinance had the right args
    args, kwargs = adapter.dispatch.call_args
    req = args[0]
    assert req.tool == "preflight_finance"
    assert req.query == "datenspeicher"
    assert req.finance_roots == ["/50_finance/purchases"]
    assert req.entities_root == "/30_entities"


def test_dispatch_entity_query_only():
    from bitgn_contest_agent.adapter.pcm import ToolResult
    skill = _skill("entity_message_lookup", preflight="preflight_entity")
    decision = RoutingDecision(
        category="entity_message_lookup", source="classifier", confidence=0.9,
        extracted={"query": "the founder"}, skill_name=skill.name,
    )
    schema = WorkspaceSchema(entities_root="/30_entities")
    adapter = MagicMock()
    adapter.dispatch.return_value = ToolResult(
        ok=True, content='{"summary": "matched alex", "data": {}}',
        refs=(), error=None, error_code=None, wall_ms=8, bytes=30,
    )
    out = dispatch_routed_preflight(
        decision=decision, schema=schema, adapter=adapter,
        skills_by_name={skill.name: skill},
    )
    assert out.tool == "preflight_entity"
    assert out.result is not None and out.result.ok
    args, kwargs = adapter.dispatch.call_args
    req = args[0]
    assert req.tool == "preflight_entity"
    assert req.query == "the founder"
    assert req.entities_root == "/30_entities"


def test_dispatch_swallows_exception_and_returns_skip():
    skill = _skill("FINANCE_LOOKUP", preflight="preflight_finance")
    decision = RoutingDecision(
        category="FINANCE_LOOKUP", source="regex", confidence=1.0,
        extracted={"query": "datenspeicher"}, skill_name=skill.name,
    )
    schema = WorkspaceSchema(
        finance_roots=("/50_finance",), entities_root="/30_e",
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
```

- [ ] **Step 2: Run tests to verify failure**

```
.venv/bin/pytest tests/test_routed_preflight.py -v
```
Expected: 7 FAIL — module + helper not yet implemented.

- [ ] **Step 3: Implement `routed_preflight.py`**

```python
# src/bitgn_contest_agent/routed_preflight.py
"""Harness-side preflight dispatch driven by router category.

After the router decides a category, this module looks up the matching
preflight tool from the skill's frontmatter and dispatches it through
the same adapter the LLM would use. The result is injected as a user
message before the main loop, so the model never has to opt in.

The five mappings (skill category -> preflight tool) and required
arguments live on each skill's frontmatter (`preflight:` and
`preflight_query_field:`). This module reads those mappings and
constructs the correct `Req_Preflight*` Pydantic object.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from bitgn_contest_agent.router import RoutingDecision
from bitgn_contest_agent.schemas import (
    Req_PreflightDocMigration,
    Req_PreflightEntity,
    Req_PreflightFinance,
    Req_PreflightInbox,
    Req_PreflightProject,
)
from bitgn_contest_agent.skills import BitgnSkill
from bitgn_contest_agent.workspace_schema import WorkspaceSchema

_LOG = logging.getLogger(__name__)


@dataclass
class RoutedPreflightOutcome:
    """Result of attempting a routed preflight dispatch.

    `tool` is the preflight tool name attempted (or None if skipped
    before construction). `result` is the ToolResult if dispatched.
    `skipped_reason` is set when no dispatch happened. `error` carries
    the exception message if dispatch raised.
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
) -> RoutedPreflightOutcome:
    """Dispatch the preflight tool bound to the decided skill, if any.

    Returns RoutedPreflightOutcome describing what happened. Callers
    inject the result content as a user message when `tool` is set
    AND `result.ok` is True.
    """
    if decision.skill_name is None:
        return RoutedPreflightOutcome(skipped_reason="no_skill")

    skill = skills_by_name.get(decision.skill_name)
    if skill is None or not skill.preflight:
        return RoutedPreflightOutcome(skipped_reason="no_preflight_for_skill")

    tool = skill.preflight
    query_field = skill.preflight_query_field or "query"
    query = (decision.extracted or {}).get(query_field) or ""
    query = query.strip() if isinstance(query, str) else ""

    builder = _BUILDERS.get(tool)
    if builder is None:
        return RoutedPreflightOutcome(
            tool=tool, skipped_reason="unknown_preflight_tool",
        )

    try:
        req, missing = builder(query=query, schema=schema)
    except _MissingArg as exc:
        return RoutedPreflightOutcome(
            tool=tool, skipped_reason=str(exc),
        )

    if missing:
        return RoutedPreflightOutcome(
            tool=tool, skipped_reason=missing,
        )

    try:
        result = adapter.dispatch(req)
    except Exception as exc:  # noqa: BLE001 — never crash the task
        _LOG.warning("routed_preflight %s dispatch raised: %s", tool, exc)
        return RoutedPreflightOutcome(
            tool=tool, skipped_reason="dispatch_exception", error=str(exc),
        )

    return RoutedPreflightOutcome(tool=tool, result=result)


# ---------------------------------------------------------------------
# Per-tool builders. Each returns (Req_*, missing_reason_or_None).
# ---------------------------------------------------------------------


class _MissingArg(Exception):
    pass


def _build_finance(*, query: str, schema: WorkspaceSchema):
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


def _build_entity(*, query: str, schema: WorkspaceSchema):
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


def _build_project(*, query: str, schema: WorkspaceSchema):
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


def _build_doc_migration(*, query: str, schema: WorkspaceSchema):
    if not query:
        return None, "missing_query"
    if not schema.entities_root:
        return None, "missing_roots"
    req = Req_PreflightDocMigration(
        tool="preflight_doc_migration",
        query=query,
        source_paths=[],  # router has no per-task source paths today
        entities_root=schema.entities_root,
    )
    return req, None


def _build_inbox(*, query: str, schema: WorkspaceSchema):
    # query is unused for inbox preflight
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


_BUILDERS = {
    "preflight_finance": _build_finance,
    "preflight_entity": _build_entity,
    "preflight_project": _build_project,
    "preflight_doc_migration": _build_doc_migration,
    "preflight_inbox": _build_inbox,
}
```

**Critical constructor-arg note:** The tests construct `Req_Preflight*` classes — verify each constructor signature matches the actual `schemas.py` definitions (field names: e.g. `finance_roots: List[str]` vs `finance_roots: list[str]`, `tool` discriminator literal). Read `schemas.py` lines 73-115 first; if a constructor uses different field names than this plan assumes, fix the builder accordingly.

- [ ] **Step 4: Run tests to verify pass**

```
.venv/bin/pytest tests/test_routed_preflight.py -v
```
Expected: 7 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/bitgn_contest_agent/routed_preflight.py tests/test_routed_preflight.py
git commit -m "feat(preflight): add dispatch_routed_preflight harness helper"
```

---

### Task 6: `run_prepass` returns `(content, schema)`

**Files:**
- Modify: `src/bitgn_contest_agent/adapter/pcm.py`
- Modify: `tests/test_adapter_prepass.py`

**Background:** `run_prepass` today returns `list[str]` of bootstrap contents. Change return type to a small `PrepassResult` dataclass: `bootstrap_content: list[str]`, `schema: WorkspaceSchema`. Parse the schema from the `preflight_schema` result content using the new parser. Keep all existing prepass behavior (4 calls, identity_loaded flips, trace appends).

- [ ] **Step 1: Update existing test**

In `tests/test_adapter_prepass.py`, the test currently asserts the return is a `list[str]`. Update it to assert the new shape:

```python
def test_run_prepass_returns_content_and_schema(...):  # adjust existing test
    ...
    out = adapter.run_prepass(session=session, trace_writer=writer)
    assert isinstance(out.bootstrap_content, list)
    assert any("WORKSPACE SCHEMA" in c for c in out.bootstrap_content)
    # schema typed view
    assert out.schema.entities_root is not None  # or test's chosen value
```

Also add a test that schema is empty when preflight_schema fails:

```python
def test_run_prepass_returns_empty_schema_on_preflight_failure(monkeypatch, ...):
    # make preflight_schema return ok=False
    ...
    out = adapter.run_prepass(session=session, trace_writer=writer)
    from bitgn_contest_agent.workspace_schema import WorkspaceSchema
    assert out.schema == WorkspaceSchema()
```

Read the existing test file first to understand the fixture setup; reuse it.

- [ ] **Step 2: Run tests to verify failure**

```
.venv/bin/pytest tests/test_adapter_prepass.py -v
```
Expected: FAIL — return is currently a list.

- [ ] **Step 3: Implement the change in `pcm.py`**

Add at the top of pcm.py:

```python
from dataclasses import dataclass, field as _dc_field
from bitgn_contest_agent.workspace_schema import WorkspaceSchema, parse_schema_summary


@dataclass
class PrepassResult:
    bootstrap_content: list[str]
    schema: WorkspaceSchema
```

Change `run_prepass` return signature to `-> PrepassResult` and the body's final `return bootstrap_content` block:

```python
def run_prepass(self, *, session: Any, trace_writer: Any) -> PrepassResult:
    bootstrap_content: list[str] = []
    schema_summary: str | None = None
    pre_cmds = [
        ("tree", Req_Tree(tool="tree", root="/")),
        ("read_agents_md", Req_Read(tool="read", path="AGENTS.md")),
        ("context", Req_Context(tool="context")),
        ("preflight_schema", Req_PreflightSchema(tool="preflight_schema")),
    ]
    for label, req in pre_cmds:
        result = self.dispatch(req)
        if result.ok:
            session.identity_loaded = True
            if label == "read_agents_md":
                session.rulebook_loaded = True
            for ref in result.refs:
                session.seen_refs.add(ref)
            if label == "preflight_schema" and result.content:
                bootstrap_content.append(
                    "WORKSPACE SCHEMA (auto-discovered, use these roots "
                    "when a preflight tool asks for inbox_root / "
                    "entities_root / finance_roots / projects_root):\n"
                    f"{result.content}"
                )
                schema_summary = result.content
        trace_writer.append_prepass(
            cmd=label, ok=result.ok, bytes=result.bytes,
            wall_ms=result.wall_ms, error=result.error,
            error_code=result.error_code,
        )
    return PrepassResult(
        bootstrap_content=bootstrap_content,
        schema=parse_schema_summary(schema_summary),
    )
```

**If the `preflight_schema` ToolResult `content` is the full `{"summary": ..., "data": ...}` blob,** parse `summary` from there. Read the actual content shape by examining `src/bitgn_contest_agent/preflight/schema.py` first and adjusting `parse_schema_summary` accordingly (Task 1 may need a follow-up edit).

- [ ] **Step 4: Run tests to verify pass**

```
.venv/bin/pytest tests/test_adapter_prepass.py -v
```
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add src/bitgn_contest_agent/adapter/pcm.py tests/test_adapter_prepass.py
git commit -m "refactor(prepass): return PrepassResult with parsed WorkspaceSchema"
```

---

### Task 7: Wire `dispatch_routed_preflight` into `agent.py`

**Files:**
- Modify: `src/bitgn_contest_agent/agent.py`
- Modify: `tests/test_agent_loop.py`

**Background:** Two changes to `AgentLoop.run`:

1. Consume new `PrepassResult` from `run_prepass` (was `list[str]`).
2. After router decision is made (in `_build_initial_messages` today, or relocated), call `dispatch_routed_preflight(...)` and append the result content as another user message.

**Wiring decision:** keep router call inside `_build_initial_messages`, but expose the `RoutingDecision` so `run` can use it. Easiest path: change `_build_initial_messages` to return `(messages, decision)` tuple. Then `run` calls dispatch_routed_preflight after prepass (so schema is available), and appends the preflight content to `messages`.

Order matters:
- system prompt
- task text
- skill body (router-injected)
- task hint (if any)
- WORKSPACE SCHEMA (from prepass bootstrap_content)
- **NEW: PREFLIGHT message (from routed dispatch)**
- → first LLM step

- [ ] **Step 1: Write failing integration test**

Add to `tests/test_agent_loop.py`:

```python
def test_routed_preflight_injects_message_before_first_llm_step(
    tmp_path, monkeypatch
):
    """When router picks FINANCE_LOOKUP and schema has finance_roots,
    the harness must dispatch preflight_finance and inject a PREFLIGHT
    user message before the first LLM step.
    """
    # Build a workspace with one finance bill so adapter dispatches successfully.
    # Use existing test fixture infrastructure (see other tests in this file
    # for the standard adapter + workspace setup).
    ...
    # Capture messages the backend sees on its FIRST call.
    captured_first_call_messages = []
    def fake_complete(*, messages, **_):
        if not captured_first_call_messages:
            captured_first_call_messages.extend(messages)
        # return a ReportTaskCompletion to end the loop in 1 step
        ...
    backend = FakeBackend(fake_complete)
    ...
    loop.run(task_id="t-test", task_text="What was the total for Datenspeicher?")
    # Assert PREFLIGHT message is in initial messages
    assert any(
        "PREFLIGHT" in (m.content if hasattr(m, "content") else m["content"])
        for m in captured_first_call_messages
    )
```

Use existing fixtures in `test_agent_loop.py` for adapter + backend; add a new test that constructs a minimal workspace where `preflight_schema` succeeds and `preflight_finance` returns one match.

- [ ] **Step 2: Run test to verify failure**

```
.venv/bin/pytest tests/test_agent_loop.py::test_routed_preflight_injects_message_before_first_llm_step -v
```
Expected: FAIL.

- [ ] **Step 3: Update `_build_initial_messages` signature**

Change return type from `List[Message]` to `tuple[List[Message], RoutingDecision]`. Move the router call to produce a decision that gets returned. Existing callers that don't care can ignore the second element. Update callers in `run` and any test.

- [ ] **Step 4: Update `AgentLoop.run`**

```python
def run(self, *, task_id: str, task_text: str) -> AgentLoopResult:
    session = Session()
    messages, decision = _build_initial_messages(
        task_text=task_text,
        router=self._router,
        task_id=task_id,
    )

    prepass = self._adapter.run_prepass(
        session=session, trace_writer=self._writer
    )
    for content in prepass.bootstrap_content:
        messages.append(Message(role="user", content=content))

    # Routed preflight — harness-side dispatch based on category.
    if self._router is not None and decision is not None:
        from bitgn_contest_agent.routed_preflight import dispatch_routed_preflight
        from bitgn_contest_agent.arch_log import emit_arch, ArchCategory

        outcome = dispatch_routed_preflight(
            decision=decision,
            schema=prepass.schema,
            adapter=self._adapter,
            skills_by_name={
                c.skill.name: c.skill for c in self._router._compiled
            },
        )
        # Trace + arch log
        if outcome.tool is not None:
            self._writer.append_prepass(
                cmd=f"routed_{outcome.tool}",
                ok=outcome.result.ok if outcome.result else False,
                bytes=outcome.result.bytes if outcome.result else 0,
                wall_ms=outcome.result.wall_ms if outcome.result else 0,
                error=outcome.error,
                error_code=None,
            )
        # Inject the PREFLIGHT message if the dispatch produced content.
        if outcome.result is not None and outcome.result.ok and outcome.result.content:
            messages.append(Message(
                role="user",
                content=(
                    f"PREFLIGHT (auto-dispatched by router for "
                    f"category={decision.category}, query="
                    f"{(decision.extracted or {}).get('query','')!r}):\n"
                    f"{outcome.result.content}\n\n"
                    f"This is the canonical narrowing for this task. "
                    f"Use these references first; widen the search only "
                    f"if the answer is not derivable from them."
                ),
            ))

    self._writer.append_task(task_id=task_id, task_text=task_text)
    ...  # rest of run() unchanged
```

Also expose `Router._compiled` access cleanly — add a `Router.skills_by_name(self) -> dict[str, BitgnSkill]` method so we don't reach into `_compiled` from agent.py.

- [ ] **Step 5: Run all tests to verify pass**

```
.venv/bin/pytest tests/test_agent_loop.py tests/test_routed_preflight.py -v
```
Expected: ALL PASS.

- [ ] **Step 6: Commit**

```bash
git add src/bitgn_contest_agent/agent.py src/bitgn_contest_agent/router.py tests/test_agent_loop.py
git commit -m "feat(agent): wire dispatch_routed_preflight after router + prepass"
```

---

### Task 8: Remove preflight tools from LLM function schema + delete PREFLIGHT_PROTOCOL

**Files:**
- Modify: `src/bitgn_contest_agent/schemas.py`
- Modify: `src/bitgn_contest_agent/prompts.py`

**Background:** With harness-side dispatch in place, the LLM should no longer be offered preflight tools (they'd be unused/confusing). Remove the 6 preflight types from `FunctionUnion` (lines 133-154 area). Keep the class definitions importable. Delete the entire `PREFLIGHT_PROTOCOL` block in `prompts.py` (lines 232-256) and the line `_STATIC_SYSTEM_PROMPT = _STATIC_SYSTEM_PROMPT + PREFLIGHT_PROTOCOL` (line 258).

- [ ] **Step 1: Edit `schemas.py`**

In `FunctionUnion`, delete these 6 lines:

```python
        Req_PreflightSchema,
        Req_PreflightInbox,
        Req_PreflightFinance,
        Req_PreflightEntity,
        Req_PreflightProject,
        Req_PreflightDocMigration,
```

The classes themselves (lines 73-115) stay untouched — they're imported by `pcm.py` and `routed_preflight.py`.

- [ ] **Step 2: Edit `prompts.py`**

Delete the assignment block:

```python
PREFLIGHT_PROTOCOL = """
## Preflight Shortcuts
...
"""

_STATIC_SYSTEM_PROMPT = _STATIC_SYSTEM_PROMPT + PREFLIGHT_PROTOCOL
```

- [ ] **Step 3: Run full test suite**

```
.venv/bin/pytest tests/ -q
```
Expected: ALL PASS. Watch for tests that asserted the preflight tools were in the schema or that the system prompt contained "Preflight" — update them to reflect the new harness-side reality.

- [ ] **Step 4: Spot-check JSON schema generation**

```bash
.venv/bin/python -c "
from bitgn_contest_agent.schemas import NextStep
import json
schema = NextStep.model_json_schema()
tools = schema['properties']['function']['discriminator']['mapping']
print('LLM-callable tools:', sorted(tools.keys()))
"
```
Expected: no `preflight_*` keys. Should see `read`, `write`, `delete`, `mkdir`, `move`, `list`, `tree`, `find`, `search`, `context`, `report_task_completion`.

- [ ] **Step 5: Commit**

```bash
git add src/bitgn_contest_agent/schemas.py src/bitgn_contest_agent/prompts.py
git commit -m "refactor(schemas): drop preflight tools from LLM function schema; delete PREFLIGHT_PROTOCOL"
```

---

### Task 9: Bench validation

**Files:** none — measurement only.

- [ ] **Step 1: Confirm full test suite green**

```
.venv/bin/pytest tests/ -q
```
Expected: 0 failures.

- [ ] **Step 2: Smoke test t005**

```
set -a && source .worktrees/plan-b/.env && set +a
.venv/bin/python scripts/rerun_failing_tasks.py --tasks t005 --runs 1 \
    --max-parallel 1 --max-inflight-llm 4 --output /tmp/t005_routed.json
```
Expected: PASS. Then check the trace file for the new `routed_preflight_finance` prepass event:

```
.venv/bin/python -c "
import json, glob, os
trace = sorted(glob.glob('logs/*/t005__run0.jsonl'))[-1]
for line in open(trace):
    r = json.loads(line)
    if r.get('kind') == 'prepass':
        print(r['cmd'], 'ok=', r.get('ok'))
"
```
Expected: see `routed_preflight_finance ok= True`.

- [ ] **Step 3: Push to feature branch + run full PROD bench**

```
git push
SHA=$(git rev-parse --short HEAD)
OUT=artifacts/bench/${SHA}_routed_preflight_p3i6_gpt54_prod_runs1.json
LOG=artifacts/bench/${SHA}_routed_preflight_p3i6_gpt54_prod_runs1.stdout.log
set -a && source .worktrees/plan-b/.env && set +a
nohup .venv/bin/python -m bitgn_contest_agent.cli run-benchmark \
    --benchmark bitgn/pac1-prod \
    --max-parallel 3 --max-inflight-llm 6 --runs 1 \
    --output "$OUT" > "$LOG" 2>&1 &
echo "pid=$!"
```

- [ ] **Step 4: After bench completes, ingest server scores**

```
RUN_ID=$(grep -oE "run_id=run-[A-Za-z0-9]+" "$LOG" | sort -u | sed 's/run_id=//')
.venv/bin/python scripts/ingest_bitgn_scores.py --run-id "$RUN_ID" --bench "$OUT"
```

- [ ] **Step 5: Compare to 1af9bd7 baseline (100/104)**

```
.venv/bin/python -c "
import json
runs=[
    ('routed', '$OUT'),
    ('1af9bd7_usewhen', 'artifacts/bench/1af9bd7_usewhen_p3i6_gpt54_prod_runs1.json'),
]
for label, p in runs:
    d=json.load(open(p))
    o=d['overall']
    fails=sorted(tid for tid,t in d['tasks'].items() if t.get('passes',0)==0)
    print(f'{label}: {o[\"total_passes\"]}/{o[\"total_runs\"]} fails={fails}')
"
```

Specific predictions to validate:
- t001 should pass (preflight_project resolves "house AI thing")
- t081 should pass (preflight_finance canonicalizes "0.6 mm hardened nozzle")
- t022 unchanged (no INBOX skill yet — preflight_inbox only fires when INBOX category exists)
- t009 unrelated (TCP reset infra)

Pass condition for this implementation: **net pass rate ≥ 100/104** AND **at least 1 of {t001, t081} flips to pass**. If both predictions hold, write a follow-up note to add an INBOX skill for t022.

---

## Self-Review

Performed against the design spec:

**Spec coverage check:**
- WorkspaceSchema dataclass + parser → Task 1 ✓
- Skill frontmatter `preflight` + `preflight_query_field` → Task 2 ✓
- Per-skill `.md` updates → Task 3 ✓
- Classifier `extracted.query` → Task 4 ✓
- `dispatch_routed_preflight` helper → Task 5 ✓
- `run_prepass` returns schema → Task 6 ✓
- Agent loop wiring → Task 7 ✓
- Function schema + PREFLIGHT_PROTOCOL removal → Task 8 ✓
- Bench validation → Task 9 ✓

**Type consistency check:**
- `BitgnSkill.preflight: Optional[str]` and `BitgnSkill.preflight_query_field: str` defined consistently across Task 2 (definition), Task 3 (frontmatter usage), Task 5 (read access).
- `WorkspaceSchema.finance_roots: Tuple[str, ...]` consistently typed; converted to `list[str]` only when constructing `Req_PreflightFinance` (which expects a list per `schemas.py`).
- `RoutedPreflightOutcome.result: Optional[ToolResult]` — caller treats as `result.ok`/`result.content`/`result.bytes`/`result.wall_ms`; matches existing `ToolResult` shape.

**Placeholder scan:**
- All steps have concrete code or commands.
- One deliberate "..." in Task 7 step 1 referencing existing fixture setup — implementer must read the existing `test_agent_loop.py` to understand the fixture pattern. Acceptable because the fixture IS the unknown to be matched, not an unwritten requirement.
- Two deliberate notes flagging "verify before assuming" in Tasks 1 and 5 — implementer must read `preflight/schema.py` and `schemas.py` to confirm summary shape and Req_* constructor signatures match the plan's assumptions, fixing the plan code if not. This is necessary diligence, not deferred work.

---

## Execution Handoff

After plan saved, proceeding with **Subagent-Driven Execution** per memory `feedback_plan_execution_mode.md`.
