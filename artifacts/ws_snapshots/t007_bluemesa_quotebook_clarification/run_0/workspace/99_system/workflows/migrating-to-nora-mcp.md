<!-- AICODE-NOTE: Nora queueing is batch-oriented. Keep all files in one requested migration batch on the same timestamp and derive order strictly from alphanumeric path sorting so reruns stay explainable. -->

# Migrating to NORA MCP

Use this workflow when a task asks you to mark existing notes for later migration into the NORA MCP vault.

- Discover the exact migration marker shape under `../schemas/` before editing.
- Read `../schemas/bulk-processing-and-queueing-frontmatter.md` for the exact required fields.
- For this workflow, set:
  - `bulk_processing_workflow: nora_mcp`
  - `queue_target: vault2`
- Treat the requested file set as one migration batch, even if it contains only one file:
  - capture the current UTC timestamp once for the batch and write that same RFC3339 `queue_batch_timestamp` to every touched file, using the `Z` form like `2026-04-10T14:37:12Z`
  - sort the requested file paths alphanumerically and assign `queue_order_id` from `1` through `N` in that order
- Treat this as a header-only migration step unless the task explicitly asks for body cleanup too.
- Inspect only enough of each requested file to determine whether YAML frontmatter already exists and whether the NORA MCP marker is already present and correct.
- If a requested file already carries the correct marker, leave it unchanged.
- If a requested file has frontmatter, merge the migration marker into the existing frontmatter instead of replacing unrelated fields.
- If a requested file has no frontmatter, add the migration marker as new YAML frontmatter at the top of the existing file.
- Preserve the note body below the frontmatter byte-for-byte. Do not rewrap paragraphs, normalize headings, or "clean up" large files just because you opened them.
- Keep the touched-file set exact. Do not broaden the migration to nearby notes that were not named in the task.
- If one requested file is missing or ambiguous, stop and ask for clarification instead of inventing partial migration state.

