Be pragmatic. This is one Obsidian-style personal workspace for Miles's household, work, startup, and project life.

Key locations:

- `00_inbox/`: unprocessed drops and requests
- `10_entities/cast/`: canonical people, pets, and named systems
- `20_work/`: reminders and active tasks
- `30_knowledge/`: capture, notes, and threads
- `40_projects/`: concrete project folders and artifacts; folder names start with the project creation date as `YYYY_MM_DD_`, and the canonical project record is `README.MD` inside each folder
- `50_finance/`: invoices and purchases
- `60_outbox/`: channel trust docs, drafts, and outbound state
- `90_memory/`: assistant memory and story/history surfaces
- `99_system/`: workflows and schemas

Rules:

- Read nested `AGENTS.MD` files when you enter a folder.
- Before starting task work, inspect `99_system/` with `tree` and then read the relevant workflow or schema docs there.
- Records are gradually migrating toward YAML frontmatter so they stay easy to browse in Obsidian while carrying structured fields for automation.
- The migration period can be a little messy in the short term because older notes and newer structured notes may coexist, but the long-term goal is to streamline the workspace and clean up record handling.
- If a task asks you to add or repair structured metadata on an existing note, first look in `99_system/workflows/` for the current migration guidance, then discover the matching shape doc under `99_system/schemas/`.
- Entity files in `10_entities/cast/` are authoritative for identity, `primary_contact_email` when present, and birthdays when present.
- If the relevant canonical file does not show the needed fact, ask for clarification instead of guessing.
- Keep changes focused and preserve lane boundaries across household, day job, client, startup, and hobby contexts.
