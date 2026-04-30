<!-- AICODE-NOTE: Batch queue markers need one stable batch timestamp plus a deterministic in-batch order so repeated migration passes can reason about exactly which note belonged where in the operator's batch. -->

# Bulk processing and queueing frontmatter

Use this schema when a task asks you to mark an existing note for later bulk processing or queueing.

This file is the exact schema for the queueing marker. Workflow docs may tell you when to apply it, but the field contract lives here.

Add YAML frontmatter like this:

```yaml
---
bulk_processing_workflow: <workflow name>
queue_batch_timestamp: <batch timestamp>
queue_order_id: <order id>
queue_state: <state>
queue_target: <target>
---
```

Batch fields:

- `queue_batch_timestamp` is the batch creation timestamp taken from current time when the batch is prepared
- every note in the same migration batch must carry the same `queue_batch_timestamp`
- `queue_order_id` is a sortable integer position within that batch
- compute `queue_order_id` after sorting the batch's file paths alphanumerically
- within one batch, `queue_order_id` must form a contiguous sequence from `1` to `N`

Queue state machine:

- `pending` means the note has been queued for later processing and no processor has claimed it yet
- `exporting` means a worker has claimed the note and is preparing or sending the source version into the destination system
- `imported` means the destination system now has a candidate copy, but parity has not been checked yet
- `verifying` means both sides exist and the migration process is checking structure, metadata, links, or attachments before calling it done
- `migrated` means the destination copy is accepted as canonical and no divergence is currently known
- `merge_conflict` means both sides were edited in incompatible ways during migration and a human or higher-level merge workflow must reconcile the content
- `split_brain` means both systems now carry plausible but diverging active versions, and the process can no longer assume which side is authoritative
- later workflows or tools may advance the state, but initial queueing starts at `pending` unless another schema says otherwise

Common transitions:

- `pending -> exporting` when a batch worker picks up the note
- `exporting -> imported` when the target system successfully receives the first candidate copy
- `imported -> verifying` when migration checks begin
- `verifying -> migrated` when parity checks pass and the destination becomes the accepted copy
- `verifying -> merge_conflict` when both copies changed and an automatic merge is not trustworthy
- `verifying -> split_brain` when both systems continue accepting edits and authority is unclear
- `merge_conflict -> verifying` after a reconciled version is written back and re-checked
- `split_brain -> verifying` after one side is declared authoritative and the other side is realigned

Required fields:

- `bulk_processing_workflow` must be filled with the workflow identifier supplied by the relevant workflow doc
- `queue_batch_timestamp` must be the current timestamp captured once for the whole batch when the note set is queued
- `queue_order_id` must be the note's integer position after sorting the batch's file paths alphanumerically
- `queue_state` must be `pending` when a note is first placed into the queue
- `queue_target` must be filled with the target supplied by the relevant workflow doc

Rules:

- Preserve unrelated existing frontmatter fields.
- Do not add extra migration fields unless the task or another schema explicitly requires them.
- Field order is not semantically important, but keep the diff small.

