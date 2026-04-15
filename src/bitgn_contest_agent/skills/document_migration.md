---
name: document-migration
description: Strategy for queuing documents for migration to a target system
type: rigid
category: document_migration
matcher_patterns:
classifier_hint: "Tasks asking to queue, migrate, or prepare documents for transfer to another system"
---

## Step 0: Workspace exploration shortcut

Task shape here = "queue documents for a named target system, where you need the exact destination directory and required metadata schema." That's exactly what `preflight_doc_migration(query=<target system or destination from the task>, source_paths=<list of document paths from the task>, entities_root=<from WORKSPACE SCHEMA>)` solves in one call — it resolves the target system's destination directory and the canonical metadata schema the migration queue expects, so you don't have to guess. The auto-discovered WORKSPACE SCHEMA message lists `entities_root` — copy that value directly.

Use it before the search strategy below. Use the destination and metadata schema preflight returns directly — do NOT invent paths or fields it didn't confirm. If preflight is empty or ambiguous, fall back to reading workspace migration docs.

## Search Strategy

1. Read the workspace documentation for migration instructions BEFORE
   taking any action. Look for process docs, migration guides, or
   system-specific instructions in the docs directory.

2. The target system's requirements, format, and conventions are defined
   in workspace docs — do not assume them. Read the relevant
   documentation to understand:
   - What format the migration queue expects
   - What metadata fields are required
   - What naming conventions to follow

3. Follow the documented migration format exactly. Do not invent fields
   or structure that the documentation does not specify.

4. Verify each referenced document exists before including it in the
   migration queue. Read the document to confirm it is the correct one.

5. If the migration instructions reference a specific directory structure
   or naming convention, follow it precisely. Do not use alternative
   paths or structures.
