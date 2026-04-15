---
name: project-involvement
description: Strategy for finding all projects an entity participates in
type: rigid
category: project_involvement
matcher_patterns:
classifier_hint: "Tasks asking which projects a person or entity is involved in, or project participation queries"
---

## Step 0: Workspace exploration shortcut

Task shape here = "list projects involving a specific person, where the person may be referenced informally and projects may link to them via structured alias rather than prose." That's exactly what `preflight_project(query=<entity name or reference from the task>, projects_root=<from WORKSPACE SCHEMA>, entities_root=<from WORKSPACE SCHEMA>)` solves in one call — it resolves the entity to its canonical identifier and returns matching project records indexed by linked-entity fields (not by prose keywords). The auto-discovered WORKSPACE SCHEMA message lists `projects_root` and `entities_root` — copy those values directly.

Use it before Step 1. If preflight returns a non-empty list, use it as the answer set (after reading each matched project record to confirm) instead of doing a fresh `search`. If it's empty or ambiguous, fall back to the search strategy below.

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
