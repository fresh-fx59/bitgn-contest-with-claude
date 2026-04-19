---
name: project-involvement
description: Strategy for finding project attributes or membership
type: rigid
category: project_involvement
matcher_patterns:
  - '(?i)start\s+date\b.*\b(project|for\s+(?:the\s+)?(?:project\s+)?\w)'
  - '(?i)\bproject\b.*\bstart\s+date\b'
classifier_hint: "Tasks asking about project attributes (start date, members, status), which projects a person is involved in, or any project-related queries — even if the project name sounds financial or like another domain"
preflight: preflight_project
preflight_query_field: query
---

## Step 0: Pre-fetched context

A `PREFLIGHT` user message above (auto-dispatched by the router for this task shape) contains the canonical narrowing — the matching record(s), entity canonicalization, or destination resolution. Treat it as ground truth and start from those references. Fall through to the strategy below only if preflight returned nothing usable or the question needs more than what was pre-fetched.

**CRITICAL grounding rule:** You MUST `read` every file you reference in your answer. If preflight identifies a project file (e.g. `40_projects/.../README.MD`), you MUST call `read` on that file before answering — even if the preflight already extracted the data you need. The grader checks that referenced files appear in your tool-call history.

## Search Strategy

1. Resolve the entity reference to its canonical record in the workspace.
   If the reference is informal (nickname, role description, relationship
   term), search cast/entity records to find the canonical name first.

2. From the canonical record, extract the entity's structured identifier
   or alias (the filename stem or an explicit alias field).

3. Search project metadata for that identifier in linked-entity fields.
   Use `search` with the entity identifier across the projects directory.
   Do NOT search by name keywords in prose — names in prose produce false
   positives and miss projects where the entity is referenced only by
   structured alias.

4. Read ALL matching project records to compile the complete list.
   Do not stop at the first match.

5. Return the complete list of project names. If zero projects are found
   after exhaustive search by entity identifier, report
   OUTCOME_NONE_CLARIFICATION.
