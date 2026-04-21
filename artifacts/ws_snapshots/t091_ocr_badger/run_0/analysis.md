# t091 failure — deep dive

**Source:** `logs/fa86094_prod/20260421_144552/t091__run0.jsonl`, commit `fa86094`.
**Outcome:** `OUTCOME_NONE_CLARIFICATION`, score 0.0, grader expected `OUTCOME_OK`.
**One failure out of 104 tasks (103/104 = 99.0%).**

## Task

> **Inbox item:** OCR all bills related to Badger
> *(router picked `inbox-processing` skill via tier1_regex on "Work … oldest … message")*

`10_entities/cast/badger.md` (read at step 14):
> # Badger · alias: `badger` · kind: `system` · relationship: `printer` · 3D printer that keeps pulling family usefulness and tinkering into the same lane.

Expected grader behavior: read each `50_finance/purchases/*.md`, identify the ones with `| related_entity | Badger |`, and rewrite each with YAML frontmatter per `99_system/schemas/finance-record-frontmatter.md`. 5 bills actually have `related_entity: Badger` — toy_forge_pla_bundle, studio_parts_petg_batch, studio_parts_nozzle_and_inserts, black_library_terrain_spool, studio_parts_magnet_and_felt.

## What the agent did — 18 steps

| # | tool | target | result |
|---|---|---|---|
| 1 | tree | (root) | workspace map |
| 2 | read | `AGENTS.MD` | root rulebook |
| 3 | context | — | identity bootstrap |
| 4 | tree | (root) | workspace map again |
| 5 | read | `99_system/AGENTS.MD` | |
| 6 | read | `99_system/workflows/AGENTS.MD` | |
| 7 | read | `99_system/workflows/inbox-processing-v2-update.md` | |
| 8 | read | `99_system/workflows/process-next-inbox-item.md` | |
| 9 | read | `00_inbox/AGENTS.MD` | |
| 10 | read | `00_inbox/000_next-task.md` | reveals the OCR request |
| 11 | read | `99_system/workflows/ocr-records.md` | OCR workflow |
| 12 | read | `99_system/workflows/migrate-records-to-frontmatter.md` | migration workflow |
| 13 | read | `99_system/schemas/finance-record-frontmatter.md` | target schema |
| 14 | read | `10_entities/cast/badger.md` | entity confirmed |
| **15** | **search** | **pattern=`badger`, root=`50_finance`** | **0 matches** |
| **16** | **search** | **pattern=`printer`, root=`50_finance`** | **0 matches** |
| **17** | **search** | **pattern=`3D`, root=`50_finance`** | **0 matches** |
| 18 | report_completion | OUTCOME_NONE_CLARIFICATION | grader: expected OUTCOME_OK |

## Root cause — case-sensitive `search` + no fallback to `list`+`read`

**Correcting an earlier analysis:** the bills were *not* in the agent's evidence window. The `pcm_transcript.txt` shows 19 bill `cat`s, but those were **prepass** pcm ops (backend-side identity bootstrap — 122 reads total), not LLM tool calls. The LLM's read_cache at step 18 contained **12 files, zero of them bills.**

Breakdown from the trace's `pcm_op` records:
- `prepass` reads: 122 (incl. all 19 `50_finance/purchases/*.md`, all 11 `50_finance/invoices/*.md`)
- `step:N` reads: 12 (none in `50_finance/`)

So the prepass *knew* the bills existed — but the LLM never asked to read any of them. Prepass output is not in the LLM's evidence stream.

### The specific failure

The agent's plan at step 14 was correct:

> `'Locate related bill files in finance roots', 'Read each target bill', 'Write frontmatter-preserving updates for all targets'`

But at step 15 it chose `search` for the "locate" step:

> **Step 15** · `current_state`: "Canonical entity read; identifier alias is 'badger'. Need find all bill records related to this entity across finance roots using canonical identifier."

PCM `search` is **case-sensitive substring match**. The bill files contain `related_entity | Badger |` (title-cased) — searching for lowercase `badger` returns 0. The agent tried `printer` (only appears in `badger.md`, not bills) and `3D` (only in body text of entity, not bills) — both also 0.

Three zero results convinced the agent that no Badger-linked bills exist, so it gave up. It never tried:
- `list 50_finance/purchases/` — would have shown 19 candidate files
- `read 50_finance/purchases/*.md` — would have revealed `related_entity: Badger`
- `search` with capitalized `Badger` — would have hit 5 files

### Why verify didn't save it

`verify.should_verify` correctly fired `INBOX_GIVEUP` at step 18 (inbox skill + NONE_CLARIFICATION + no outbox write). The nudge from `verify.py:220-239`:

```
## INBOX_GIVEUP
You routed as an inbox task, marked outcome NONE_CLARIFICATION, and did
not write any outbox reply. This usually indicates premature giveup —
reconsider before finalizing:
  - Re-read the inbox `from:` header and resolve the sender via the
    entity cast directly (aliases, relationship, primary_contact_email).
  - If the task mentions a descriptor (e.g. 'design partner', 'my spouse'),
    re-check every entity's relationship field — the descriptor may map
    semantically to startup_partner, wife, etc.
  - If after that check no entity matches, re-emit report_completion with
    outcome OUTCOME_NONE_UNSUPPORTED (task really has no answer) or
    OUTCOME_NONE_CLARIFICATION with a specific clarifying question …
```

The nudge is **entity-centric** (designed for "find sender" inbox tasks). It doesn't tell the agent:
- "OCR/migration tasks require reading files, not searching"
- "Before concluding no evidence, list the relevant lane (`50_finance/purchases/`) and read its entries"
- "Try `search` again with a capitalized/case-swapped pattern"

Verify's `changed=False` outcome reflects this — the agent re-emitted the same clarification without re-considering file-enumeration strategy.

## Concrete fixes (not in this PR — follow-up)

### 1. Expand `inbox-processing` skill's instructions (biggest lever)

Current inbox skill has no explicit rule for OCR-over-collection tasks. Add to `src/bitgn_contest_agent/skills/inbox_processing.md` (or equivalent):

> When the inbox request names a collection action over an entity ("OCR all bills related to X", "summarize all notes about Y"), DO NOT rely on `search` to find candidates. Instead: `list` the relevant lane (`50_finance/purchases/` for bills, `30_knowledge/notes/` for notes, etc.), then `read` each entry and filter on the entity name match (alias, display name, or relationship token) in file content.

### 2. Extend INBOX_GIVEUP verify nudge to cover collection-over-entity

`verify.py:220-239` — add a branch when the inbox text contains "all" + an entity name:

```python
def _section_inbox_giveup(task_text: str) -> str:
    base = (...existing...)
    if re.search(r"\ball\b", task_text, re.IGNORECASE):
        base += (
            "\n  - The request names a collection (e.g. 'all bills', "
            "'all notes'). Do not conclude no evidence exists based on "
            "`search` alone — lists with case-sensitive match miss "
            "title-cased entity names. List the relevant lane, read each "
            "entry, and filter by entity name in file content."
        )
    return base
```

### 3. Harness-level: default `search` to case-insensitive

Out of scope for the agent — it's a PCM behavior. But the skill docs should flag the quirk so the LLM stops treating empty `search` as authoritative.

## Scoring the miss against the verify framework

| Question | Answer |
|---|---|
| Did verify fire for the right reason? | ✅ Yes — INBOX_GIVEUP is exactly the correct reason code. |
| Did the nudge cause a correction? | ❌ No — `changed=False`. |
| Would the baseline (no verify) have failed the same? | ✅ Yes — same exact outcome. |
| Is this a verify-framework regression? | ❌ No — the framework detected correctly; the prescriptive content in the nudge is tuned for "find sender" and doesn't cover collection-over-entity. |
| Would we block the PR on this? | ❌ No — 103/104 = +26 tasks vs. baseline. The single miss is a known orthogonal issue (skill content + search case-sensitivity). |

## Raw transcripts

- `pcm_transcript.txt` — full PCM op stream (prepass + step ops) captured by the harness
- `../../../logs/fa86094_prod/20260421_144552/t091__run0.jsonl` — structured trace
- `../../../logs/fa86094_prod/20260421_144552/t091__run0.log` — arch events + HTTP timing
