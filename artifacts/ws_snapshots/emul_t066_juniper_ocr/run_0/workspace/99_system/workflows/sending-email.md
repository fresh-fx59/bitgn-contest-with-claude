<!-- AICODE-NOTE: Keep email-send semantics here, not scattered across outbox and finance docs. This file should define the reusable contract for draft-vs-sent state, recipient resolution, timestamped filenames, and attachment paths without leaking task-specific recipes. -->

# Sending email

Use this workflow for outbound email work: sending, drafting, replying, or resending.

The workspace models outbound email as markdown files under `60_outbox/outbox/`.

## Core rules

- Resolve authority, lane, and recipient before writing any outbound email record.
- If the request changes recipient, crosses lanes, touches money, or otherwise creates a new obligation, prefer clarification over guessing.
- A known human name is not enough by itself. Use a visible verified address, preferably the relevant entity's `primary_contact_email`.
- Prefer recipient choices that are already justified by visible canonical evidence.
- Legacy email-channel docs are not the canonical source for recipient email addresses. Use them as context only.
- Keep attachments as exact workspace paths. Do not invent external URLs or filesystem paths outside the visible repo.
- Outbox files represent prepared communication state, not brainstorming.

## File path

Create outbound email records in `60_outbox/outbox/` using this filename format:

```text
eml_YYYY-MM-DDTHH-MM-SSZ.md
```

Timestamp rules:

- derive the timestamp from the runtime-visible current time
- use UTC `Z` form
- replace `:` with `-` in the filename only
- keep the frontmatter timestamp in normal RFC3339 form

Example:

```text
60_outbox/outbox/eml_2026-04-10T09-30-00Z.md
```

## Frontmatter schema

Write the email record as markdown with YAML frontmatter.

```yaml
---
record_type: outbound_email
created_at: 2026-04-10T09:30:00Z
send_state: draft
to:
  - recipient@example.com
subject: Follow-up
attachments:
  - 30_knowledge/notes/example.md
related_entities:
  - person.example
related_projects:
  - project.example
source_channel: 60_outbox/channels/example.md
---
Hello,

Following up with the requested note attached.

Best,
Miles
```

Required fields:

- `record_type`
- `created_at`
- `send_state`
- `to`
- `subject`
- `attachments`

Optional fields:

- `related_entities`
- `related_projects`
- `source_channel`

Field rules:

- `record_type` must be `outbound_email`
- `created_at` must be the runtime-derived RFC3339 timestamp
- `send_state` should be `draft` unless the visible workflow for this lane establishes a later state
- `to` is an array of exact recipient email addresses
- recipient email addresses should come from visible canonical entity email fields, especially `primary_contact_email`, when available
- `subject` should be concrete and appropriate to the request
- `attachments` is an array of exact workspace-relative file paths
- for invoice resends or invoice bundles, order attachments reverse chronologically by the visible invoice issue date unless the request explicitly asks for something else; newest-first is the default because finance review usually starts with the latest invoice
- `related_entities` and `related_projects` should use visible canonical ids when the relevant person or project has been resolved
- `source_channel` should point to the visible channel doc when the email is a reply or lane-specific follow-up

## Body rules

- Put the email body below the frontmatter as normal markdown text.
- Keep the draft narrow and purpose-built for the request.
- Do not claim the email was already sent unless the visible workflow or request establishes sent state.
- Mention only attachments that actually exist in the workspace.

## Recipient resolution

- For reply-shaped requests:
  - prefer the recipient already established by the visible message context
  - if the request comes from a structured inbox email record, use `processing-inbox-email.md` and treat that header as the canonical message metadata
- For a request that names a recipient without a visible verified address:
  - resolve it from canonical visible docs first
  - if the visible docs do not identify one clear address, clarify instead of guessing
- When an entity has a visible `primary_contact_email`, prefer that address over legacy email-channel material.
- Do not silently switch to a new address mentioned in message text unless the workspace explicitly establishes that new address as trusted for that lane
