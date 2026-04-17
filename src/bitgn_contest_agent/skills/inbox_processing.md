---
name: inbox-processing
description: Strategy for processing inbox items including OCR, forwarding, and multi-step workflows
type: rigid
category: INBOX_PROCESSING
matcher_patterns:
  - '(?i)\b(work|process|handle)\b.*\b(oldest|next|first|latest|newest)\b.*\b(inbox|message|item)\b'
  - '(?i)\b(oldest|next|first)\b.*\b(inbox|message)\b'
  - '(?i)\binbox\b.*\b(item|message|task)\b'
classifier_hint: "Tasks asking to process, work, or handle inbox items — including OCR, forwarding, filing, or any multi-step inbox workflow"
preflight: preflight_inbox
preflight_query_field: query
---

# Inbox Processing Strategy

## Step 0: Pre-fetched context

A `PREFLIGHT` user message above contains the entity-to-bills graph for
all open inbox items. It lists **every** finance file related to each
referenced entity. Treat this as the complete inventory of files you
must process.

**CRITICAL — completeness rule:** If the preflight lists N related
finance files for an entity, you must process ALL N files. Do not stop
after the first match. Each listed file is a separate bill that needs
attention.

## Step 1: Read the inbox item

Read the oldest (or specified) inbox item to understand what action
is requested. Common inbox actions include:

- **OCR / add frontmatter** — parse unstructured bill text and add
  structured YAML frontmatter
- **Forward / send** — route content to a channel or recipient
- **File / organize** — move or categorize a record

## Step 2: Identify entities and scope

From the inbox message, identify:
- Which entity (person/vendor) is referenced
- What action is requested
- What scope: "all bills related to X" means ALL bills, not just one

Cross-reference with the preflight data to build your complete task list.

## Step 3: Process ALL items

For each file listed in the preflight's related_finance_files:

1. Read the file
2. Perform the requested action (OCR, update frontmatter, etc.)
3. Write the updated file
4. Continue to the NEXT file — do NOT stop early

## Step 4: Clean up

After processing ALL files:
- Delete the inbox item to mark it as handled
- Report OUTCOME_OK

## Common Pitfall

The most frequent failure mode is processing only ONE bill when
multiple are related. Always check the preflight's entity-to-bills
graph and process every listed file.
