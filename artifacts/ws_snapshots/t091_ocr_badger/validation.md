# t091 Fix Validation — Local Harness

## Summary

Three 5× local runs on `local_t091_ocr_badger` (workspace snapshot of PROD
failure): **baseline 5/5 PASS, Fix A 5/5 PASS, Fix A+B 5/5 PASS**. Local
harness did not reproduce the PROD failure in any configuration.

## Experimental setup

- Model: `gpt-5.3-codex` via cliproxyapi (same as PROD bench)
- Workspace: `artifacts/ws_snapshots/t091_ocr_badger/run_0/workspace/`
  (replayed from PROD fail `20260421_t091_fa86094_verify_full_p3i6_prod_runs1`)
- Context date: `2026-04-21T15:59:55Z` (matches PROD timestamp)
- Adapter path: `LocalPcmAdapter` → `TracingPcmClient` → `LocalPcmClient`
  (wired in `scripts/local_bench.py` for this experiment — previously
  bypassed, which invalidated earlier runs)
- `LocalPcmClient.search` made case-sensitive to match PROD PCM semantics
  (gated behind `PCM_LOCAL_CASE_INSENSITIVE` env var; default off)

## Results

| Phase | PASS | FAIL | median steps | notes |
|-------|------|------|--------------|-------|
| baseline (no Fix A, no Fix B) | 5 | 0 | 30 | Fix A+B removed |
| Fix A only (search retry)     | 5 | 0 | 29 | Fix B removed |
| Fix A+B                       | 5 | 0 | 29 | both active |

## Why the fixes never fired

Per-run pcm_op trace analysis:

- `search` calls in any of the 15 runs: **0**
- `context` calls per run: 2 (normal bootstrap)
- pcm_ops per run: 30–34

The local agent went directly to `list`/`read` on
`00_inbox/*` and `50_finance/purchases/*`. It never used `search`, so
**Fix A (search case-fold retry) never had an opportunity to fire**.
Similarly, no run produced `OUTCOME_NONE_CLARIFICATION`, so **Fix B
(INBOX_GIVEUP collection nudge) never fired** either. Both fixes are
latent in these runs.

## What this tells us

1. **No regression**: Fix A+B does not break the success path when the
   fixes aren't needed. The agent's non-search strategy on this task
   yields the same outcome.
2. **Local harness ≠ PROD**: The PROD failure path was
   `search("badger") → 0 hits → OUTCOME_NONE_CLARIFICATION`. Local
   agent chose a different strategy and avoided the trap. This is
   expected variance between runs — `search` usage is
   non-deterministic at the LLM level.
3. **Validation is inconclusive for the fix mechanism**. The fixes
   *must* be validated on PROD, where the exact failure reproduced.

## Unit tests

Fix A: 7 new tests in `tests/test_pcm_tracing.py` covering:
- empty lowercase-token → retry with Title case
- first-pass hit → no retry
- regex metacharacters → no retry
- multi-word pattern → no retry
- mixed-case pattern → no retry
- retry is observable (both probes appear as `pcm_op` records)
- retry-empty falls back to first response

Fix B: 3 new tests in `tests/test_verify_message.py` covering:
- collection quantifier (`all`/`every`/`each`) → nudge appended
- no quantifier → no nudge
- case-insensitive quantifier match (`ALL`)

Full suite: **508/508 PASS**.

## Extra fixes discovered during validation

1. **`scripts/local_bench.py`**: Wired `TracingPcmClient` around
   `LocalPcmClient`. Previously bypassed, so every "Fix A experiment"
   before 2026-04-21 22:53 CEST was actually baseline — any delta was
   LLM variance.
2. **`scripts/local_pcm.py`**: Gated `re.IGNORECASE` in
   `LocalPcmClient.search()` behind the `PCM_LOCAL_CASE_INSENSITIVE`
   env var. Default is case-sensitive — matches PROD PCM behavior.
3. **`src/bitgn_contest_agent/adapter/pcm_tracing.py`**: Made
   `TracingPcmClient.context()` tolerate no-arg calls
   (`context()` without a request object) because `LocalPcmAdapter`
   invokes it that way while `PcmAdapter` passes
   `pcm_pb2.ContextRequest()`. Without this, every local replay hit an
   `INVALID_ARG` error twice on bootstrap.
4. **`src/bitgn_contest_agent/adapter/pcm_tracing.py`**: Added pydantic
   `model_copy` branch to Fix A's retry-request construction so
   `Req_Search` (agent-facing BaseModel) works — `type(req)()` fails on
   pydantic models with required fields.

## PROD full bench (p3i6, SHA 3770ad1, 2026-04-21 22:58 → 01:21 CEST)

Artifact: `artifacts/bench/3770ad1_t091_fix_p3i6_prod_runs1.json`
Log dir: `logs/20260421_215807/`

### Target task (Badger OCR)

PROD reshuffles task IDs per run — the "OCR all bills related to
Badger" task landed at slot **t066** in this run. Trace evidence:

- `pcm_op search(root=50_finance, pattern=badger)` → 0 bytes (no matches).
- **Fix A retry fired**: a second `pcm_op search` at the same
  `origin=step:14` returned 557 bytes.
- Agent observation at step 15: *"Search in 50_finance for 'badger'
  returned exactly 4 matches, all in 50_finance/purchases with
  related_entity Badger."*
- `[ARCH:TERMINAL_R4] result=CONSISTENT confidence=0.92` →
  `[ARCH:TERMINAL] result=ACCEPT outcome=OUTCOME_OK`.

**Verdict: FIX A WORKED AS DESIGNED on the real PROD failure path.**

### Aggregate outcome

ARCH:TERMINAL ACCEPT count: **101/104**. Three non-accepts:

| Task | Failure | Related to fixes? |
|------|---------|-------------------|
| t043 | R4 MISMATCH — agent's 4 claimed writes didn't match actual mutation filenames (2 invoices + 2 bills) | No — mutation-integrity issue, not search/INBOX_GIVEUP |
| t052 | R4 REJECT — `grounding_ref '60_outbox/channels/work_calendar.md' never successfully read` | No — outbox grounding, unrelated |
| t061 | R4 REJECT — 3 grounding_refs never successfully read | No — general grounding issue |

Recent baseline 104-task ACCEPT history (from `logs/*/` scan):
101–103. This run's 101 sits at the low end of that noise band with
n=1 — not a statistically meaningful regression.

### Bench JSON caveat

`artifacts/bench/3770ad1_*.json` contains only 63 task entries (all
100% pass). This is normal — the bench aggregator includes only tasks
for which server-score fetch succeeded (`run_metrics.rate_limit_errors
= 7`). The full 104-task outcome was reconstructed from ARCH:TERMINAL
log lines.

## Conclusion

- Fix A (search case-fold retry) fires correctly on PROD. The Badger
  task flipped from FAIL → PASS.
- Fix B (INBOX_GIVEUP collection nudge) did not fire in this run —
  the agent with Fix A already succeeded before reaching
  OUTCOME_NONE_CLARIFICATION. Latent.
- No regression attributable to either fix.
