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

## Attachment Ordering

When listing attachments (invoices, receipts, documents) in the `attachments`
YAML field, always order them **newest-first** (reverse chronological by
issue date). This applies regardless of whether the task text says "oldest N"
or "newest N" — the task text determines WHICH items to include, but the
`attachments` list must always be ordered newest-first per the workspace's
sending-email workflow. Double-check the date in each attachment filename
(`YYYY_MM_DD_...`) and place the most recent date at index 0.

## YAML Safety

Always wrap the `subject` value in double quotes if it contains a colon
(e.g. `subject: "Re: Invoice bundle request"`). Unquoted colons break
YAML parsing.

## After Verification

If you find any errors in what you wrote, rewrite the file with corrections
before reporting completion.
