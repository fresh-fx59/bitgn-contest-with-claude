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
preflight: preflight_finance
preflight_query_field: query
---

# Finance Lookup Strategy

You are answering a question about a past financial transaction — a charge, invoice, receipt, or bill from a specific vendor or for a specific item.

## Step 0: Pre-fetched context

A `PREFLIGHT` user message above (auto-dispatched by the router for this task shape) contains the canonical narrowing — the matching record(s), entity canonicalization, or destination resolution. Treat it as ground truth and start from those references. Fall through to the strategy below only if preflight returned nothing usable or the question needs more than what was pre-fetched.

**CRITICAL grounding rule:** You MUST `read` every file you reference in your answer or use for calculation. Preflight helps you *find* files faster, but the grader requires each referenced file to appear in your tool-call history. Never answer based solely on preflight summaries without reading the actual files.

## Step 1: Anchor the Date

Calculate the reference date from the task's time expression (e.g., "51 days ago") using the current date from context. This is your approximate target — the actual filing date of records may differ significantly.

## Step 2: Progressive Search

Start with the most specific artifact mentioned in the task and progressively broaden:

1. **Search by the most specific term first** — use the vendor name, item description, or amount mentioned in the task. Search across the entire workspace, not just one directory. **When preflight returned no entity match (match_found=false):** use `search` with the vendor name or item name — do NOT just read random files.
2. **If no results:** try partial matches — shorter vendor name, alternate spellings, abbreviations, or just the distinctive part of the name. For non-ASCII vendor names (Chinese, Arabic, etc.), try the exact Unicode characters from the task.
3. **If still no results:** search by a different artifact from the task — if you searched by vendor, now search by the item description, or vice versa.
4. **If still no results:** use broader workspace exploration — list financial directories, scan filenames for any recognizable fragment from the task.

Do NOT constrain your search to a narrow date range. Filing dates in filenames often differ from the transaction date the task references.

## Step 3: Cross-Validate and Select

When you find candidate files through any search path:

- Read each candidate fully
- **Primary match criteria: vendor name + item/line-item description.** These are the definitive identifiers.
- **Vendor mismatch is disqualifying.** If none of the candidate records' vendor fields match the vendor named in the task, do NOT answer with a number from any of them. Widen the search (Step 2.2 partial match, Step 2.3 different artifact, Step 2.4 broader listing) before falling back to `OUTCOME_NONE_CLARIFICATION`. A numeric answer pulled from a different vendor's invoice is worse than asking for clarification.
- **Date is contextual, NOT a strict filter.** The "N days ago" in the task is an approximate hint. The actual record's filing date or transaction date may differ significantly from the computed anchor date. Do NOT reject a record just because the date doesn't align — if vendor and item match, it IS the right record.
- **"Since" queries have NO upper bound.** When the task says "since January 2026" or "from date X", include ALL matching records from that date onward — even records dated after the context date. The workspace contains the full historical record; do NOT use today's date as an end filter. Read and sum ALL search results that match the query.
- **Multiple matches for the same vendor + item — use date as tiebreaker:** When two or more records match on vendor and item description, compute the target date (today minus N days) and select the record whose date is **closest** to that target. The "N days ago" phrasing points to a specific transaction in time; when all other fields match, temporal proximity is the tiebreaker.
- **Single match:** Accept it regardless of date distance — the vendor + item match is sufficient.

## Step 4: Extract and Answer

- **Read every matching file** — if your search returned N results, read ALL N of them. Do not stop after reading 2 when your search showed more matches.
- Extract the exact numeric total for the requested line item from the selected record(s)
- For "total" or "since" queries, sum across ALL matching records — not just the first few
- Return the number only as your answer
- **Use OUTCOME_OK whenever you find a record matching vendor + item**, regardless of date alignment
- Do NOT use OUTCOME_NONE_CLARIFICATION when you have a matching record — a date mismatch is not grounds for clarification

Only use OUTCOME_NONE_CLARIFICATION if you have exhausted all progressive search strategies and genuinely found no matching vendor + item anywhere in the workspace.
