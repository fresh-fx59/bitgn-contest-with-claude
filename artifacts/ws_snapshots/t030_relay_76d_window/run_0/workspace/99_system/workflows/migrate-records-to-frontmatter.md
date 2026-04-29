# Migrate records to frontmatter

Use this workflow when a task asks you to OCR, normalize, or add structured metadata to an existing markdown note.

- Keep the canonical file path unless the task explicitly asks for a rename or sidecar extract.
- Add structured metadata as YAML frontmatter at the top of the existing note.
- Preserve the existing note body below the frontmatter as the source OCR or human-readable content.
- Discover the exact field shape by inspecting the relevant schema doc under `99_system/schemas/`; do not invent fields just because a nearby note uses them.
- Keep the diff focused. Do not rewrite body text that is already correct just to make formatting prettier.
- If the visible note does not support one required schema field, stop and ask for clarification instead of guessing.

