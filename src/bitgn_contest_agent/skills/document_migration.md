---
name: document-migration
description: Strategy for queuing documents for migration to a target system
type: rigid
category: document_migration
matcher_patterns:
classifier_hint: "Tasks asking to queue, migrate, or prepare documents for transfer to another system"
---

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
