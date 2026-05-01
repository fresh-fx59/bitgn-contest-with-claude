`60_outbox/` is the communication execution lane.

- `channels/` documents trust and channel semantics.
- `drafts/` is for outbound material that is not yet final.
- `outbox/` is for durable outbound state when the workspace models it explicitly.
- Use the relevant entity's `primary_contact_email` as the canonical email identity for recipient resolution and reply work.
- Legacy email-channel docs are context only; they are no longer the canonical source for email identity or outbound email execution.
- Read `99_system/workflows/sending-email.md` before creating outbound email records.
- Always resolve authority and lane before acting from this folder.

