# Phase 0 lifecycle findings — 2026-04-26

Partial run against PROD `bitgn/pac1-prod`. Four sub-spikes were resolved by user-confirmed facts (no measurement); three were measured here.

## User-confirmed (no measurement needed)

- **rotation:** `StartPlayground` rotates the `instruction` field per call for the same `task_id`. Local clone must serve N variants per task.
- **url_lifetime:** `harness_url` remains reachable effectively forever after `EndTrial`. No URL-expiration handling required.
- **auto_termination:** Unended trials are NOT GC'd by the harness. No stale-trial cleanup behavior to model.
- **rate_limit:** No throttling observed on `StartPlayground` burst calls. No backoff strategy required.

## Measured

### state_isolation
A `Write` to `/_scraper_probe.txt` in trial N is **not** visible from a fresh trial N+1 (same `task_id`). `second_trial_saw_write=False`. Trials are isolated — the local clone must replicate this and serve a fresh workspace per trial.

### answer_replay
The first `pcm.Answer` call succeeds; the **second** `pcm.Answer` call on the same trial raises `ConnectError("Answer was already provided")`. The harness enforces a hard "one answer per trial" wire-level rule. Consequence: `graded_against` is structurally `first` — there's no real "replay" question to ask. The local clone's PCM mock must reject the second answer with the same error code/message rather than silently accepting it.

Score detail returned for the (only-accepted) `alpha` answer on `t001`: `["answer is incorrect. Expected: 'March 26, 2026'"]` — confirms the canonical score-detail prefix `"answer is incorrect. Expected: '<X>'"` that the seed-rules extractor already keys on.

### size_sanity
5-task sample (`t001, t010, t020, t030, t050`). Workspace byte totals: `[130432, 130603, 130774, 130432, 130432]`. Max = **130 774 bytes (~128 KiB)**. The tight 342-byte spread suggests the workspace shell is nearly identical across tasks with only small per-task content differences. Storage cost for the local clone is trivial: even a full 104-task scrape would land at <15 MiB total.

## Implications for Plan 1B (Phase 1 + 2 + 3)

- **Phase 1 (workspace scrape):** budget ~130 KiB × 104 tasks × N rotation variants. With N≈5 variants, we're at ~70 MiB — comfortable as flat files. SQLite `workspace_files` index stays small.
- **Phase 2 (probe matrix):** the answer-once rule means the P5 "alternate-answer" probe must use a **fresh trial per probe**. Cannot piggyback multiple Answer calls on one trial.
- **Local PCM mock:** must enforce the same "one answer per trial" rejection on the second `Answer` call.

## Sub-spike code drift

The canonical `_spike_answer_replay` in `src/bitgn_scraper/phase0.py` assumes both `Answer` calls succeed and inspects `score_detail` to determine which one was graded. PROD raises `ConnectError` on the second call, which propagates out of the spike. `scripts/phase0_partial.py` works around this by catching the error and recording it as the finding. The canonical spike should be updated in a follow-up to handle this case before any future full run.
