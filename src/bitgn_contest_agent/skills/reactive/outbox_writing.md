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
Before proceeding, verify the semantic correctness of what you wrote.

## Attachment Verification

Every file path listed in attachments or references in your document MUST be
a file you actually read and verified during this task. Do not reconstruct
paths from memory or partial information.

If you are not 100% certain an attachment path is correct:
- Re-read the source file to confirm its exact path
- Compare the path character-by-character with what you wrote
- Fix any discrepancy before proceeding

## Recipient Verification

The recipient address in your document must match the canonical entity record
you looked up during this task. Do not copy addresses directly from the inbox
message — verify them against the workspace's authoritative entity source.

## Content Fidelity

When forwarding or quoting content from another file, the forwarded text must
match what you read from the source. Do not paraphrase, summarize, or
reconstruct from memory.

## After Verification

If you find any errors in what you wrote, rewrite the file with corrections
before reporting completion.
