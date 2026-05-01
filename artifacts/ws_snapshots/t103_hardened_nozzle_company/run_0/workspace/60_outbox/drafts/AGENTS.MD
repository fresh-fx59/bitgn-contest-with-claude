`60_outbox/drafts/` is for outbound text that is still being prepared.

- Keep drafts narrow and purpose-built.
- Do not treat drafts as sent state.
- If a workflow later introduces explicit send semantics, follow those docs instead of inventing them.
- If outbound email needs to exist as durable communication state, use `99_system/workflows/sending-email.md` and write it to `../outbox/` instead.
