`00_inbox/` is the intake lane.

- Treat inbox files as unprocessed requests or source drops, not canonical truth.
- If an inbox file is an email-shaped markdown record with YAML frontmatter, use `99_system/workflows/processing-inbox-email.md` and treat the header as canonical email metadata for that file.
- For email identity checks, prefer the entity's canonical `primary_contact_email` over legacy email-channel notes.
- Start with the lowest visible inbox filename in normal sort unless the task explicitly says otherwise.
- After fully completing one inbox request, delete that inbox file. If the request is blocked on clarification, trust, or missing canonical support, stop without mutating the workspace.
- Cross-check identity, dates, and authority against canonical records before acting.
- Move durable knowledge into `30_knowledge/` or `40_projects/`; do not turn inbox into long-term storage.
