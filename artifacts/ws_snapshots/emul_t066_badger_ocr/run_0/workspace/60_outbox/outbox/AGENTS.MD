`60_outbox/outbox/` is for durable outbound communication state.

- Use this folder only when outbound communication is being recorded as durable workspace state.
- Use `99_system/workflows/sending-email.md` for outbound email filename, frontmatter, and attachment rules.
- Keep identifiers stable and exact.
- Outbox records should reflect action, not brainstorming.
