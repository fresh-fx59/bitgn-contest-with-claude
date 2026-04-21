# Process next inbox item

Use this workflow when the instruction says to handle, process, review, or work the next inbox item.

- Go to `00_inbox/`.
- Pick the lowest visible filename using normal sort.
- Read that inbox file carefully before taking action.
- If the inbox file is an email-shaped markdown record with YAML frontmatter, also read `processing-inbox-email.md`.
- For repository cleanup or structured-record maintenance tasks routed through inbox processing, also read `inbox-processing-v2-update.md`.
- For inbox tasks that end in outbound communication work, also read `sending-email.md`.
- Treat the inbox file as a request, not as canonical truth. Verify dates, identity, and project facts against the canonical lanes before acting.
- If the request can be completed from canonical evidence, do the focused work and then delete the inbox file you processed.
- If the request is ambiguous, unsupported, unsafe, or missing canonical support, stop with the appropriate outcome and do not mutate the workspace.
