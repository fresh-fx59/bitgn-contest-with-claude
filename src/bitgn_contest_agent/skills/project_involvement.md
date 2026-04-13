---
name: project-involvement
description: Strategy for finding all projects an entity participates in
type: rigid
category: project_involvement
matcher_patterns:
classifier_hint: "Tasks asking which projects a person or entity is involved in, or project participation queries"
---

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
