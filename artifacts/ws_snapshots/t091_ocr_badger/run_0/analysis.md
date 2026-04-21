# t091 failure analysis — "OCR all bills related to Badger"

**Source:** `artifacts/bench/fa86094_verify_full_p3i6_prod_runs1.json`, commit `fa86094`.
**Outcome:** `OUTCOME_NONE_CLARIFICATION`, grader rejected (expected `OUTCOME_OK`). Score 0.0. The only failure in 103/104.

## What the agent saw

`00_inbox/000_next-task.md`:
> Please handle this request: OCR all bills related to Badger

`10_entities/cast/badger.md`: Badger is the family 3D printer (`kind: system`, `relationship: printer`).

During steps 2–13 the agent cat'd all 19 bills under `50_finance/purchases/`. At least 5 bills have `| related_entity | Badger |` in their body-table (the in-workspace canonical entity attribution):

| bill file | date | total | line-item hint |
|---|---|---|---|
| `bill.toy_forge_pla_bundle` | 2025-11-12 | €72 | PLA spool mixed colors |
| `bill.studio_parts_petg_batch` | 2026-01-04 | €80 | black/clear PETG spool |
| `bill.studio_parts_nozzle_and_inserts` | 2026-02-04 | €33 | nozzle + inserts |
| `bill.black_library_terrain_spool` | 2026-03-03 | €89 | terrain filament |
| `bill.studio_parts_magnet_and_felt` | 2026-03-13 | €20 | magnet + felt pads |

The evidence to satisfy the task was already in the read_cache.

## Why it failed — "case-sensitive grep → catastrophic forgetting"

Late in the trace the agent ran three searches against `50_finance/`:

- `rg --max-count 1000 badger 50_finance` → 0 hits (the files say `Badger`, not `badger`)
- `rg --max-count 1000 printer 50_finance` → 0 hits
- `rg --max-count 1000 3D 50_finance` → 0 hits

Finding no matches via search, the agent contradicted the evidence it had already cat'd and emitted:

> "I cannot safely complete the inbox request yet. The oldest inbox item asks to OCR all bills related to Badger, but no bill files can be canonically resolved from available evidence."

This is the classic **search-tool > read-cache** fallacy — the agent trusted a negative `rg` hit over the positive content it had already read.

## Verify framework behavior

`verify.should_verify` **correctly** detected INBOX_GIVEUP (inbox skill + NONE_CLARIFICATION + no outbox write) and injected the nudge. But `changed=False`: the agent re-emitted the identical clarification without re-scanning the bills sitting in its own read_cache.

**The verify trigger fired the right reason — the re-derivation logic didn't use the right signal.**

## Root-cause summary

Two independent defects stack:

1. **Case-sensitive search in finance lookups.** `rg` without `-i` is brittle for entity-name-scoped queries. The workspace has title-cased entity names in canonical tables.
2. **INBOX_GIVEUP nudge lacks read_cache re-entry instruction.** `_section_inbox_giveup()` (verify.py:220-239) tells the agent to re-check aliases and relationship fields, but does not tell it: *"before concluding no evidence exists, re-scan every file already in your read_cache for the entity by name, alias, or relationship."* A case-insensitive substring search over read_cache would have found all 5 Badger bills.

## Candidate fixes (not in scope for this PR)

- **Agent-side:** Default `rg` invocations against the workspace to `-i` when the pattern is entity-name-like (single word, mixed-case), or prefer `grep -rni` when searching for canonical names.
- **Verify-side:** Extend INBOX_GIVEUP section with: *"Re-scan every file already in read_cache for the entity's alias, display name, and relationship tokens before concluding no evidence exists."* This closes the gap where verify fires but the agent doesn't look at its own evidence.
- **Workspace-side:** Enforce `related_entity` lower-case alias as the canonical field so naive searches hit. (Out of our control — benchmark-side convention.)

## Relationship to verify framework PR

The failure is **not** a verify-framework regression. Baseline (no verify) would have failed the same task for the same reason. Verify contributed: a correct detection and one unused retry. Net impact on this task: 0 — but also 0 false positives.

For the PR merge decision: this is a content-layer issue orthogonal to the verify trim+trigger work. 103/104 = +26 tasks vs. baseline 77/104 is a clean win; this single miss is worth a follow-up ticket but does not block.
