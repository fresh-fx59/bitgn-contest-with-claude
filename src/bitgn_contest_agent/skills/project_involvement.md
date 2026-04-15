---
name: project-involvement
description: Strategy for finding all projects an entity participates in
type: rigid
category: project_involvement
matcher_patterns:
classifier_hint: "Tasks asking which projects a person or entity is involved in, or project participation queries"
---

## Step 0: Preflight

Start by calling `preflight_project(query=<entity name or reference from the task>, projects_root=<from WORKSPACE SCHEMA>, entities_root=<from WORKSPACE SCHEMA>)`. The auto-discovered workspace schema message lists both `projects_root` and `entities_root` — copy those values directly. The preflight result resolves the entity to its canonical identifier and returns the matching project records indexed by linked-entity fields. If preflight returns a non-empty list, use it as the answer set (after reading the matched project records to confirm) instead of doing a fresh `search`.

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
