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

## Step 1: Read the inbox item — LITERAL SOURCE OF TRUTH

Read the oldest (or specified) inbox item to understand what action
is requested. **The inbox item is your authoritative task spec.**

**CRITICAL — explicit file lists override everything else:** When the
inbox item lists specific file paths (numbered or bulleted), those
paths are the EXACT and COMPLETE set of files to process. Do NOT
substitute, add, or remove files based on preflight data, entity
relationships, or your own search results. The inbox item's file
list is the ground truth — process exactly those files, no more, no
fewer.

Common inbox actions include:

- **OCR / add frontmatter** — parse unstructured bill text and add
  structured YAML frontmatter
- **Forward / send** — route content to a channel or recipient
- **File / organize** — move or categorize a record

## Step 2: Build the task list

**If the inbox item lists explicit file paths:** your task list IS
that file list. Read each file path exactly as given. Do NOT search
for alternatives or use preflight to narrow/widen the scope.

**If the inbox item references entities instead of files** (e.g.
"process all bills for Hearthline"): use the preflight data to
resolve entity names to file paths. Cross-reference with the
preflight's entity-to-bills graph.

## Step 3: Process ALL items

For each file in your task list:

1. Read the file
2. Perform the requested action (OCR, update frontmatter, etc.)
3. Write the updated file
4. Continue to the NEXT file — do NOT stop early

**Re-read the inbox item** after step 2 if you find yourself
uncertain about which files to process. The inbox item is always
right.

## Step 4: Clean up

After processing ALL files:
- Delete the inbox item to mark it as handled
- Report OUTCOME_OK

## Common Pitfalls

1. Processing only ONE file when multiple are listed. Process every
   listed file.
2. **Substituting different files** based on preflight/search context
   instead of following the inbox item's explicit file list. This is
   the #1 cause of "unexpected write" grading failures.
3. Ignoring invoice files and only processing purchase files (or vice
   versa). The inbox item may list both — process ALL of them.
