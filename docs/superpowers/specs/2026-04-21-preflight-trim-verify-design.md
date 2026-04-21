# Preflight Trim + Verification Discipline — Design

**Branch:** `feat/preflight-trim-verify`
**Baseline:** `main @ 308b676` — 100/104 PROD pass (server_score 100.0/104, mean 0.9615)
**Target:** reduce preflight complexity and context bloat; address the 4 observed PROD failures without per-wording patches.

---

## 1. Goal

Make the agent's preflight subsystem earn its place by evidence: drop the parts that never fire, keep the parts that demonstrably accelerate tasks, and add one narrowly-scoped verification pass for the answer shapes most prone to error.

One sentence: **remove dead matcher code, keep the rulebook pre-read, add a numeric-answer verification trigger, and strip "trust the preflight entity" language.**

---

## 2. Evidence (from PROD run @ 2da4b34, 104 tasks)

| Measurement | Value |
|---|---|
| Tasks with `routed_preflight.match_found=True` | **0 / 104** |
| Tasks whose agent `current_state` cites preflight output | ~18 / 104 |
| Tasks whose agent cites the workflow rulebook (prepass-loaded) | 25+ / 104 |
| Prepass ops per task | ~161 avg |
| Prepass bytes per task | ~150KB avg |
| Agent reads that duplicate prepass reads | **98.4%** (4613 / 4690) |
| Avg input tokens per task | 157K |
| Failures (OUTCOME != OK, scored 0) | t026, t030, t055, t072 |

### Observations per failure

- **t026** — asked for start date of "the project our home assistant setup". Two project folders matched (`house_mesh`, `hearthline`). Agent read only `house_mesh` and answered. Classic multi-candidate disambiguation skip.
- **t030 / t055** — "how much did 深圳市海云电子 charge me in total for the line item relay modules 76 days ago? Number only". Two bills matched, expected **6** (single quantity) but agent returned **12** (either summed both or misread). Numeric aggregation/filter error.
- **t072** — "Take care of the next message in inbox". Preflight resolved the referenced entity to **Jana**; correct answer was **Nina** (startup_partner). Agent blindly trusted preflight, searched Jana, found nothing, returned `NONE_CLARIFICATION`.

### Observations per success pattern

- **Workflow-doc pre-read** (prepass) is the real accelerator. `99_system/workflows/AGENTS.MD` → `inbox-processing-v2-update.md` is cited in 25+ inbox tasks as the reason the agent knows what to do.
- **Single-item inbox pointer** from `preflight_inbox` (e.g. "one open item at 00_inbox/297_next-task.md") saves 1–2 steps in ~6 inbox tasks.
- **Finance bill candidate** from `preflight_finance` is cited in 4 tasks as a starting point.
- Everything else in `routed_preflight.py` produces "here are candidates, figure it out" — information the agent would produce itself in 1–2 `list`/`search` calls.

---

## 3. Scope

### In scope

1. Remove `routed_preflight` dispatch pipeline and the five per-skill preflight modules.
2. Keep `prepass` (tree + AGENTS.MD crawl + workflow discovery) unchanged.
3. Add a **pre-completion verification trigger** with four reason codes:
   - `MISSING_REF` — answer cites a path not in the agent's read history (addresses the BitGN scorer "missing required reference" failure shape from t026).
   - `ATTACHMENT_GAP` — an outbox email was written with attachments, but one or more attached files were never read in this run. Also applies to other write/move ops that reference specific paths.
   - `NUMERIC_MULTIREF` — answer is a numeric/date scalar and the agent read ≥2 candidate records (t030/t055/t026 aggregation/disambiguation shape).
   - `INBOX_GIVEUP` — an inbox-routed task emits `NONE_CLARIFICATION` without having written to outbox (t072 premature-giveup shape).
4. Retag any remaining preflight-style hints as **guesses**, not canonical facts, so the agent doesn't blindly trust a wrong entity resolution.

### Out of scope (explicitly deferred)

- CodeAct / sandboxed Python execution — no observed failure requires arbitrary code.
- Blanket Reflexion before every `report_completion` — cost/benefit negative; targeted trigger is enough.
- Rubric-based evaluator — without veto power it's decorative; with veto it risks blocking correct answers on ambiguous rubrics.
- Router changes — the tier-1/tier-2 classifier is not the bottleneck and stays as-is.

---

## 4. Architecture after changes

### Prepass (unchanged)

```
run_prepass:
  tree /                        # 1 op
  read AGENTS.md                # 1 op
  context                       # 1 op
  tree / (re-read after AGENTS) # 1 op
  list each top-level folder    # ~8 ops
  read each folder's AGENTS.MD  # ~8 ops
  read workflow docs            # ~5 ops
  discover WorkspaceSchema      # derived from tree + AGENTS content
```

This layer produces the `WorkspaceSchema` object (entities_root, finance_roots, projects_root, inbox_root) and the workflow-rulebook context. Both are real accelerators — keep as-is.

### Routed preflight (REMOVED)

Delete:
- `src/bitgn_contest_agent/routed_preflight.py` (223 lines)
- `src/bitgn_contest_agent/preflight/inbox.py` (367 lines)
- `src/bitgn_contest_agent/preflight/finance.py` (136 lines)
- `src/bitgn_contest_agent/preflight/entity.py` (482 lines)
- `src/bitgn_contest_agent/preflight/project.py` (311 lines)
- `src/bitgn_contest_agent/preflight/doc_migration.py` (118 lines)
- `src/bitgn_contest_agent/preflight/unknown.py` (105 lines)
- `src/bitgn_contest_agent/preflight/canonicalize.py` (36 lines)
- `src/bitgn_contest_agent/preflight/response.py` (14 lines)
- Corresponding `Req_Preflight*` / `Rsp_Preflight*` classes in `schemas.py`
- `_dispatch_routed_preflight` helper and call-site in `agent.py`
- Harness-side preflight adapter hooks in `adapter/`
- Frontmatter fields `preflight:` and `preflight_query_field:` from each skill YAML

Keep:
- `src/bitgn_contest_agent/preflight/schema.py` — `WorkspaceSchema` is still used by prepass.

### Verification trigger (NEW)

Location: `src/bitgn_contest_agent/verify.py` (new file, ~250 lines).

The verification trigger fires before `report_completion` is emitted, not only for numeric/date answers. It covers four distinct risk shapes observed in PROD task logs and scorer behavior:

**Risk shape 1 — reference-read discipline.**
BitGN scorer penalizes answers that cite file paths the agent never opened (t026 detail: *"answer missing required reference '40_projects/2026_04_01_hearthline/README.MD'"*). Verification must confirm that every path cited in the answer (or in any outbox file written earlier in the run) appears in the agent's read history for this run.

**Risk shape 2 — attachment completeness.**
Inbox tasks writing an outbox email with `attachments:` frontmatter require each attached file to (a) exist in the workspace, (b) have been read during this run, and (c) satisfy the requested filter (e.g. "oldest 1 Nina-linked invoice"). Scorer checks attached paths resolve. Verification must open the written outbox file, read back its frontmatter attachments, and confirm each path was visited.

**Risk shape 3 — numeric/date answer shape with multiple candidates.**
Original t030/t055/t026 shape — answer is scalar, multiple candidate records were read. Verification asks the model to re-derive the answer citing evidence paths for each component.

**Risk shape 4 — premature `NONE_CLARIFICATION` on inbox action.**
t072 shape — agent concludes it can't act, but evidence suggests an alternate entity resolution it never tried. Trigger when `outcome_leaning == "NONE_CLARIFICATION"` on an inbox-routed task that never wrote to outbox. Verification asks: *"Before giving up, did you check every entity alias/relationship in the workspace? Re-open the inbox `from:` and body, then re-resolve."*

Contract:
```python
def classify_answer_shape(next_step: NextStep, task_text: str) -> AnswerShape:
    """Return one of: NUMERIC, DATE, PATH_LIST, MESSAGE_QUOTE, ACTION_CONFIRMATION,
    NONE_CLARIFICATION, FREEFORM. Regex + task-text heuristics, no LLM."""


def should_verify(
    next_step: NextStep,
    session: Session,
    read_cache: dict[str, str],
    write_history: list[WriteOp],
    task_text: str,
) -> VerifyReason | None:
    """Return a reason enum when verification should fire, else None.

    Trigger reasons (any one fires verification):
    - MISSING_REF:      answer cites a path not in read_cache
    - ATTACHMENT_GAP:   outbox email written but one+ attachments not in read_cache
    - NUMERIC_MULTIREF: answer shape ∈ {NUMERIC, DATE} AND
                        session.session_after.seen_refs_count >= 2
    - INBOX_GIVEUP:     task routed to inbox-processing AND
                        outcome_leaning == NONE_CLARIFICATION AND
                        no outbox write in write_history
    """


def build_verification_message(
    reason: VerifyReason,
    next_step: NextStep,
    read_cache: dict[str, str],
    write_history: list[WriteOp],
) -> str:
    """Produce a single, reason-specific user message. Fixed templates,
    not LLM-authored. Includes concrete evidence (list of paths read,
    attachments claimed, candidate records) so the model can self-check
    against its own history."""
```

Integration point: in `agent.py` main loop, after the model returns `report_completion` but **before** the outcome is emitted to the harness:

```python
reason = should_verify(next_step, session, read_cache, write_history, task_text)
if reason is not None:
    messages.append(Message(
        role="user",
        content=build_verification_message(reason, next_step, read_cache, write_history),
    ))
    # One more backend call. If the model emits a DIFFERENT report_completion
    # (different answer, different attachments, or a tool call instead of
    # completion), use that. If it re-emits the same completion, accept it.
    # Never loop more than once — bounded overhead per task.
    trace_writer.append_verify(reason=reason.name, changed=bool(differs))
```

**Tracked state the trigger reads from (already present in the loop):**
- `read_cache: dict[path → content]` — every file the agent's own steps read
- `write_history: list[WriteOp]` — every write the agent performed (outbox, inbox deletion, etc.)

`read_cache` already exists in `agent.py:320`. `write_history` is a small new accumulator; append on every `pcm_op` with op in `{"write", "delete", "move"}`.

**Cost:** ≤1 extra LLM call per task that fires any trigger. Expected trigger rate from PROD log review:
- NUMERIC_MULTIREF: ~15-20 tasks/run
- MISSING_REF: ~2-5 tasks/run (rare but high-value — t026 pattern)
- ATTACHMENT_GAP: ~3-6 tasks/run (inbox tasks with attachments)
- INBOX_GIVEUP: ~2-4 tasks/run (t072 pattern + false NONE_CLAR cases)

Overlap expected; total ≤25 tasks/run fire verification, so overhead is ~2% of LLM calls.

### Trust-signal fix (NEW)

Currently the preflight blob presents entity resolution as a fact:

```
preflight indicates sender entity resolved to Jana (startup_partner).
```

After the Change 3 fix (applies to whatever preflight-shaped text remains — currently just the prepass-derived inbox pointer):

```
preflight GUESS (not verified): the inbox's `from:` header suggests Jana.
Before acting on any entity inferred from preflight, re-open the inbox
file and confirm `from:` / entity descriptors directly.
```

This is a prompt-template change only — no new code paths. It lives in `prompts.py`.

---

## 5. Failure-mode mapping

| Failure | Root cause | Trigger that fires | How it addresses the failure |
|---|---|---|---|
| t026 | Read 1 of 2 candidate READMEs; scorer flagged missing reference | `NUMERIC_MULTIREF` (DATE + 2 project folders listed); also `MISSING_REF` if the scorer-required path isn't in read_cache | Verification asks for evidence-path per answer component. Forces reading the second README before answering. |
| t030 / t055 | Returned 12, expected 6 (aggregation/filter) | `NUMERIC_MULTIREF` (NUMERIC + 2 bills read) | Re-derivation prompt cites both bills and asks "which line items match the vendor + date window + line-item filter? Sum them." |
| t072 | Trusted wrong preflight entity; gave up | Change 3 removes trust signal upstream; `INBOX_GIVEUP` also fires (inbox task, NONE_CLARIFICATION, no outbox write) | Verification asks the agent to re-resolve sender from `from:` header and check every cast entity's `relationship` / aliases before concluding "no match". |
| *hypothetical* t093-like attachment failure | Outbox written but attachment path never opened by agent | `ATTACHMENT_GAP` | Verification asks the agent to read each claimed attachment to confirm existence + line-item content. |

### Answer-shape classifier (`classify_answer_shape`)

Non-LLM heuristics. Used both for trigger selection and for the verification message template:

| Shape | Matches when |
|---|---|
| `NUMERIC` | answer matches `^-?\d+(\.\d+)?$` OR task contains `"number only"` / `"Answer with a number"` |
| `DATE` | answer matches one of `YYYY-MM-DD`, `DD-MM-YYYY`, `MM/DD/YYYY`, `Month DD, YYYY`, OR task contains `"Date only"` / `"Answer YYYY-MM-DD"` / `"format"` + any date-token |
| `PATH_LIST` | answer contains ≥1 `/`-separated token with extension (e.g. `50_finance/...`), one per line |
| `MESSAGE_QUOTE` | task contains `"Quote"` / `"exact message"` / `"return only the"` + "message/text" |
| `ACTION_CONFIRMATION` | task contains `"take care of"` / `"handle"` / `"work"` + inbox; answer is empty or status string |
| `NONE_CLARIFICATION` | next_step `outcome_leaning == "NONE_CLARIFICATION"` |
| `FREEFORM` | none of the above |

The classifier is deterministic and cheap. Failing to classify defaults to `FREEFORM` → no trigger.

---

## 6. Testing strategy

### Unit tests (added alongside implementation)

- `tests/test_verify_classify.py` — `classify_answer_shape` matrix covering each shape with positive + negative cases
- `tests/test_verify_trigger.py` — `should_verify` decision matrix over the four trigger conditions:
  - `NUMERIC_MULTIREF`: (NUMERIC/DATE answer, seen_refs ≥ 2) → fires; (FREEFORM + refs) → no fire
  - `MISSING_REF`: answer cites path not in read_cache → fires; all paths in read_cache → no fire
  - `ATTACHMENT_GAP`: outbox write exists, attachment path not in read_cache → fires; all attachments in read_cache → no fire
  - `INBOX_GIVEUP`: inbox task + NONE_CLARIFICATION + no outbox writes → fires; inbox + OK → no fire
- `tests/test_verify_message.py` — `build_verification_message` returns distinct message templates per reason, each including the concrete evidence (candidate paths, claimed attachments, etc.)

### Integration tests

- `tests/integration/test_agent_verify_numeric.py` — mock backend returns `report_completion(answer="12")` after reading 2 bills; assert verification injected; assert second call invoked; assert trace has `verify` event.
- `tests/integration/test_agent_verify_missing_ref.py` — mock agent cites a path it never read; assert `MISSING_REF` fires.
- `tests/integration/test_agent_verify_attachment_gap.py` — mock agent writes outbox with `attachments: [X.md]` but never read `X.md`; assert `ATTACHMENT_GAP` fires and verification message names the gap.
- `tests/integration/test_agent_verify_inbox_giveup.py` — mock inbox-routed task emits NONE_CLARIFICATION with no outbox write; assert `INBOX_GIVEUP` fires.
- `tests/integration/test_agent_no_routed_preflight.py` — ensure the agent runs end-to-end without the removed modules; no ImportError, no missing-attribute errors.
- `tests/integration/test_verify_no_infinite_loop.py` — second verification call re-emits same `report_completion`; assert loop terminates after 1 verification, no third call.

### Regression (bench)

1. Local smoke on a tiny workspace (`tests/preflight/fixtures/tiny_ws`) — still exists for prepass/WorkspaceSchema tests, which continue to pass.
2. PROD 5-task smoke — subset of `t026, t030, t055, t072, t051` (the four failures plus one known passing baseline).
3. Full PROD run `p3i6` n=1 once smoke is green. **Acceptance:** server_score_total ≥ 100 (same as baseline) AND at least 2 of {t026, t030, t055, t072} recover.

### Test fixtures to drop

`tests/preflight/test_inbox.py`, `tests/preflight/test_entity.py`, and other preflight module tests exercise code being deleted. They go away with the modules.

---

## 7. Rollout plan

All work on `feat/preflight-trim-verify`. Single PR when green.

1. **Phase A — Delete dead code** (one commit)
   - Remove `routed_preflight.py`, 7 preflight modules, related schemas, frontmatter fields, adapter hooks, `agent.py` dispatch helper.
   - Keep `preflight/schema.py` (used by prepass).
   - Run unit tests; ensure `pytest tests/` passes after removal.

2. **Phase B — Prompt fix** (one commit)
   - Update `prompts.py` to re-phrase any remaining preflight-derived hints as guesses.
   - Unit test asserting the new phrasing.

3. **Phase C — Verification trigger** (split across 4 TDD commits, one per reason code)
   - C1: `classify_answer_shape` + unit tests + trace event schema.
   - C2: `NUMERIC_MULTIREF` trigger + unit + integration test + wire into `agent.py`.
   - C3: `MISSING_REF` trigger + `ATTACHMENT_GAP` trigger (share `read_cache` / `write_history` plumbing) + tests.
   - C4: `INBOX_GIVEUP` trigger + test + verify single-retry cap holds across all four reasons.

4. **Phase D — Bench validation**
   - PROD smoke on t026, t030, t055, t072, t051 (run-level n=1, small parallelism).
   - If ≥2 of the 4 failures recover and no new regressions: full PROD `p3i6` n=1.
   - If full run ≥ 100/104: open PR, merge, delete branch.

---

## 8. Rollback plan

If any phase regresses below baseline (100/104):

- **Worst case:** `git revert` the phase's commit; the baseline is preserved on `main @ 308b676` and every commit is pushed per user policy.
- **Partial rollback:** Phase A (deletion) and Phase C (verification) are independent — if Phase C misbehaves, revert just that commit while keeping the cleanup from Phase A.
- **No data loss risk:** the preflight modules being deleted do not own any persistent state; all their effects were ephemeral context injection per task.

---

## 9. Risks and counter-arguments

**Risk 1 — losing the 18 "preflight cites" we observed.**
Those 18 tasks explicitly referenced preflight in their `current_state`. Eight were the inbox file-pointer (still available post-delete via workflow docs + a single `list` call). The other ~10 cited finance bill narrowing, which is 1–2 `list/search` ops the agent already does anyway. Worst case, +1–2 steps per affected task. Step budget (30) has headroom.

**Risk 2 — verification trigger false positives.**
If the model flips from a correct answer to an incorrect one after re-derivation, we regress. Mitigation: the verification prompt is reason-specific and asks the model to *cite evidence paths*; if evidence matches the original answer, keep it. Log both. Initial deployment with n=1 bench watches for exactly this.

**Risk 3 — answer-shape classifier too narrow.**
Task wording for dates varies (`YYYY-MM-DD`, `DD-MM-YYYY`, `MM/DD/YYYY`, `Month DD, YYYY`, free-text). The regex + task-text heuristics will cover common shapes; rare formats silently skip verification (false negative). Acceptable — better to skip verification than to block a correct answer on a misclassified shape.

**Risk 4 — hidden coupling with adapter.**
The adapter may depend on `Req_Preflight*` schemas. Phase A must remove those dependencies in lockstep. A deletion sweep with `grep -r Req_Preflight src/` is required as a dry-run before committing.

**Risk 5 — `MISSING_REF` and `ATTACHMENT_GAP` may thrash on edge cases.**
- The scorer's "required reference" rules aren't fully documented — our trigger only checks for paths *cited in the answer text* that weren't read. That's the direct signal from t026's failure detail. It won't catch cases where the scorer silently requires a file that the agent never mentioned either. Acceptable — a subset of real coverage is better than no check.
- Attachment paths in outbox frontmatter might be written with different casing or leading-slash style than the read path. The check normalizes both sides via `Path(...).resolve()` before comparing.

**Risk 6 — `INBOX_GIVEUP` misfires on legitimate NONE_CLARIFICATION.**
Some inbox tasks legitimately lack information (t010/t035 timed out as NONE_UNSUPPORTED, not CLARIFICATION, and still passed). Our trigger only fires on `NONE_CLARIFICATION` (agent explicitly asking for more info) not `NONE_UNSUPPORTED`. Even so, the verification is *advisory* — the agent can re-emit the same NONE_CLARIFICATION after re-checking. Budgeted ≤1 retry.

**Risk 7 — verification message pushes the agent over the step budget.**
The verification call is counted against `max_steps` (30). Tasks already at step 29 skip verification (hard cap check). Separately, tasks that trigger verification tend to be short-path cases (numeric answer, inbox resolution) — average step count at trigger time observed at 8-12, well below the budget.

---

## 10. Success criteria

1. `src/bitgn_contest_agent/preflight/` directory shrinks from 9 files to 1 (`schema.py` only).
2. `routed_preflight.py` is gone; no references remain.
3. All existing tests pass (after removing tests that exercise deleted code).
4. PROD `p3i6` n=1 reaches **≥ 100/104** server_score, with **≥ 2 recoveries** among `{t026, t030, t055, t072}`.
5. Avg input tokens per task drops materially (baseline 157K; target <130K — removing 55 routed_preflight ops worth of bill/entity enumeration).

---

## 11. What this is NOT a bet on

- This spec does not bet on "one strategy fixes all failures." It removes known dead complexity, keeps known value, and adds one verification pass targeted at the two observed failure shapes (disambiguation-skip and numeric aggregation).
- If the verification trigger doesn't move the needle, we revert Phase C and still keep the preflight cleanup.
