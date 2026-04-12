---
name: outbox-writing
description: Verify semantic correctness of outbound documents before finalizing
type: rigid
category: OUTBOX_WRITING
reactive_tool: write
reactive_path: '(?i)(outbox|outbound|ausgang|sortie|送信|发件)'
---

# Outbox Writing Verification

You just wrote an outbound document (email, message, or communication record).
Verify what you wrote is correct. **Do NOT rewrite the file** — the sandbox
forbids overwriting outbox files. If you find an error, note it in your
`current_state` and proceed to report_completion; the write is final.

## Verification Checklist

Mentally confirm each of these. Do NOT call write again on this file.

1. **Attachment paths** — every path in `attachments` must be a file you
   actually read during this task. No reconstructed or guessed paths.
2. **Attachment ordering** — `attachments` must be newest-first (reverse
   chronological by issue date). The most recent date at index 0.
3. **Recipient** — the `to` address matches the canonical entity record,
   not just the inbox message.
4. **Content fidelity** — forwarded or quoted text matches the source
   exactly. No paraphrasing.
5. **YAML safety** — `subject` values containing a colon are wrapped in
   double quotes.
