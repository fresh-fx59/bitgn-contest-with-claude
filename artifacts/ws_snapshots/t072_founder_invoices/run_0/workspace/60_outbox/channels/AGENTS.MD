`60_outbox/channels/` is where trust semantics live close to communication actions.

- Use channel docs here to decide whether a sender is household-trusted, work-trusted, client-trusted, socially trusted, or unknown.
- Legacy email channels remain useful as trust and conversation history context, but they are no longer the canonical place to model outbound email work.
- For new email preparation or resend work, use `99_system/workflows/sending-email.md` and record the email in `60_outbox/outbox/`.
- Familiarity is not the same thing as authority.
- If channel and domain do not line up cleanly, slow down and clarify.
