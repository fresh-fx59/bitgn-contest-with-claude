---
name: finance-lookup
description: Progressive search strategy for financial queries about past charges, invoices, or receipts
type: flexible
category: FINANCE_LOOKUP
matcher_patterns:
  - '(?i)charge.*total.*line.?item'
  - '(?i)how much.*\d+\s*days?\s*ago'
  - '(?i)total.*(invoice|receipt|bill).*ago'
  - '(?i)(invoice|receipt|bill).*charge.*total'
  - '(?i)(what was the total|total from).*\d+\s*days?\s*ago'
---

# Finance Lookup Strategy

You are answering a question about a past financial transaction — a charge, invoice, receipt, or bill from a specific vendor or for a specific item.

## Step 1: Anchor the Date

Calculate the reference date from the task's time expression (e.g., "51 days ago") using the current date from context. This is your approximate target — the actual filing date of records may differ significantly.

## Step 2: Progressive Search

Start with the most specific artifact mentioned in the task and progressively broaden:

1. **Search by the most specific term first** — use the vendor name, item description, or amount mentioned in the task. Search across the entire workspace, not just one directory.
2. **If no results:** try partial matches — shorter vendor name, alternate spellings, abbreviations, or just the distinctive part of the name.
3. **If still no results:** search by a different artifact from the task — if you searched by vendor, now search by the item description, or vice versa.
4. **If still no results:** use broader workspace exploration — list financial directories, scan filenames for any recognizable fragment from the task.

Do NOT constrain your search to a narrow date range. Filing dates in filenames often differ from the transaction date the task references.

## Step 3: Cross-Validate and Select

When you find candidate files through any search path:

- Read each candidate fully
- **Primary match criteria: vendor name + item/line-item description.** These are the definitive identifiers.
- **Date is contextual, NOT a strict filter.** The "N days ago" in the task is an approximate hint. The actual record's filing date or transaction date may differ significantly from the computed anchor date. Do NOT reject a record just because the date doesn't align — if vendor and item match, it IS the right record.
- **Multiple matches for the same vendor + item:** When two or more records match on vendor and item description, select the **most recent** record (latest date). The task is asking about the most recent transaction.

## Step 4: Extract and Answer

- Extract the exact numeric total for the requested line item from the selected record
- Return the number only as your answer
- **Use OUTCOME_OK whenever you find a record matching vendor + item**, regardless of date alignment
- Do NOT use OUTCOME_NONE_CLARIFICATION when you have a matching record — a date mismatch is not grounds for clarification

Only use OUTCOME_NONE_CLARIFICATION if you have exhausted all progressive search strategies and genuinely found no matching vendor + item anywhere in the workspace.
