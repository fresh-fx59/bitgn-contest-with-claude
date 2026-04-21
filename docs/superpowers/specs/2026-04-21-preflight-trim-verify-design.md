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
3. Add a **numeric-answer verification trigger**: when the agent is about to call `report_completion` with an all-digits/scalar answer AND ≥2 candidate records were read during the run, inject one extra LLM call asking "re-derive the answer from the evidence you cited."
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

Location: `src/bitgn_contest_agent/verify.py` (new file, ~120 lines).

Contract:
```python
def should_verify(next_step: NextStep, session: Session) -> bool:
    """Return True when the verification trigger should fire.

    Criteria (all must hold):
    - next_step.function.tool == "report_completion"
    - next_step.function.answer matches numeric regex (^-?\d+(\.\d+)?$)
      OR the task text contains 'Answer with a number only' / 'number only'
    - session.session_after.seen_refs_count >= 2
    """


def build_verification_message(next_step: NextStep, messages: list[Message]) -> str:
    """Produce a single user message asking the model to re-derive the answer
    from the evidence it has already read. Fixed-format, not LLM-authored."""
```

Integration point: in `agent.py` main loop, after the model returns `report_completion` but **before** emitting the outcome:

```python
if should_verify(next_step, session):
    messages.append(Message(role="user",
        content=build_verification_message(next_step, messages)))
    # run one more backend call; use its answer if it differs from the
    # original, log both; never loop more than once
```

**Cost:** ≤1 extra LLM call per numeric-answer task with ≥2 refs. From log data, that's ~15-20 tasks/run, so overhead is ~1-2% of total calls.

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

| Failure | Root cause | How this design addresses it |
|---|---|---|
| t026 | Read 1 of 2 candidate READMEs | Verification trigger fires (answer is a date, but see extension below); stronger answer-derivation prompt forces re-checking all candidates |
| t030 / t055 | Returned 12, expected 6 (aggregation) | Verification trigger fires (numeric, ≥2 refs); re-derivation catches the sum/filter error |
| t072 | Trusted wrong preflight entity | Change 3 removes trust signal; agent re-reads inbox `from:` field and resolves correctly |

**t026 extension:** the base trigger is numeric-answer + multi-ref. For date-format answers (`YYYY-MM-DD`, `MM/DD/YYYY`, `DD-MM-YYYY`) we extend the regex. Dates are the other high-risk answer shape (5 of the 104 tasks ask for date-only answers).

---

## 6. Testing strategy

### Unit tests (added alongside implementation)

- `tests/test_verify.py` — `should_verify` matrix over (tool, answer_shape, seen_refs_count)
- `tests/test_verify.py` — `build_verification_message` formats candidate evidence correctly

### Integration tests

- `tests/integration/test_agent_verify_trigger.py` — mock backend returns `report_completion(answer="12")` on step N; assert verification injected; assert second call invoked.
- `tests/integration/test_agent_no_routed_preflight.py` — ensure the agent runs end-to-end without the removed modules; no ImportError, no missing-attribute errors.

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

3. **Phase C — Verification trigger** (one commit)
   - Add `verify.py` + tests.
   - Wire into `agent.py` main loop after `report_completion`.

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
Those 18 tasks explicitly referenced preflight in their `current_state`. Eight of them were the inbox file-pointer (still available post-delete via workflow docs + a single `list` call). The other ~10 cited finance bill narrowing, which is 1–2 `list/search` ops the agent already does anyway. Worst case, +1–2 steps per affected task. Step budget (30) has headroom.

**Risk 2 — verification trigger false positives.**
If the model flips from a correct answer to an incorrect one after re-derivation, we regress. Mitigation: the verification prompt asks the model to *cite evidence paths* for each part of the answer; if the evidence doesn't match the answer, change it. If it does match, keep it. Log both. Initial deployment with n=1 bench watches for exactly this.

**Risk 3 — date-regex too narrow.**
We extend the verification trigger to cover date formats, but task wording for dates varies (`YYYY-MM-DD`, `DD-MM-YYYY`, `MM/DD/YYYY`, `Month DD, YYYY`). The regex will cover common shapes; rare formats silently skip verification. Acceptable — better false negative than false positive blocking.

**Risk 4 — hidden coupling with adapter.**
The adapter may depend on `Req_Preflight*` schemas. Phase A must remove those dependencies in lockstep. A deletion sweep with `grep -r Req_Preflight src/` is required as a dry-run before committing.

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
