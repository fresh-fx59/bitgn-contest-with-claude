# cliproxyapi rate-limit research — Plan B Phase 2

## Hypothesis

cliproxyapi proxies to gpt-5.3-codex and enforces limits at two
granularities: (a) requests-per-minute (RPM) and (b) tokens-per-minute
(TPM). Our trivial-payload burst (~50 tokens per call) will hit the
RPM ceiling first; a secondary ~500-token burst will reveal whether
TPM also matters at our target operating point.

## Methodology

- Primary: escalating concurrent burst at levels [4, 8, 16, 32, 48, 64, 96].
  Each level runs for 15 s steady state after a 60 s cooldown.
- Secondary sanity: a single ~500-token burst at the first level that
  cleared the primary ceiling. If the primary budget divided by
  (trivial/realistic) falls below the realistic level, we are
  TPM-bound and must scale down.

## Stop conditions

- Primary break: N where rate_limit_errors ≥ 3 in the 15 s window.
- Primary cleared through ceiling 96: default operating point = 48.
- Below N=8 break: fail with InsufficientHeadroomError — Plan B cannot
  sustain a useful multi-run baseline at this ceiling.

## Operating point formula

If the first break occurs at N≥8: `max_inflight_llm = floor(0.6 * N)`.
Otherwise abort Phase 2.

## Results (TO BE FILLED BY T2.7)

- First break at: N = ___
- peak_inflight_llm sustained without errors: ___
- Chosen operating point: ___
- Secondary burst verdict: ___
- Recorded artifact: `artifacts/burst/<ts>.json`

## T2.6 execution status — DEFERRED

**Status:** deferred, not executed.

**Reason:** The sandbox where Plan B is being implemented autonomously
cannot reach cliproxyapi:

- DNS lookup for `cliproxyapi.com` fails with `gaierror: Name or
  service not known` (confirmed 2026-04-11; other hosts such as
  `api.openai.com`, `api.anthropic.com`, `api.bitgn.com` all resolve,
  so the network stack is otherwise functional).
- No `CLIPROXY_BASE_URL` or `CLIPROXY_API_KEY` environment variables
  are configured in this sandbox.

The burst script itself (`scripts/burst_test.py`, committed in T2.5)
is fully wired and ready: it imports `OpenAIChatBackend.from_config`,
uses `load_from_env`, walks the `LADDER`, applies the
`pick_operating_point` formula, and writes the artifact. It has been
smoke-imported and syntax-validated; only the live run against the
provider is missing.

**Config defaults left untouched:** `config.py` keeps
`max_parallel_tasks = 4` and `max_inflight_llm = 6`. These are the
pre-Plan-B values, not tuned values. They are conservative enough that
a user rerunning `bitgn-agent run-benchmark` will not trip rate
limits, but they almost certainly leave headroom on the table. A real
burst is needed to push them higher.

**How to resume T2.6:**
1. Export `CLIPROXY_BASE_URL` and `CLIPROXY_API_KEY` (plus
   `BITGN_API_KEY` for any downstream benchmark work).
2. Verify `getent hosts cliproxyapi.com` resolves.
3. Ensure no other process is calling cliproxyapi for the next
   ~10 minutes (the burst needs to be the dominant consumer).
4. Run:
   ```bash
   python scripts/burst_test.py \
     --output artifacts/burst/$(date -u +%Y%m%dT%H%M%SZ).json
   ```
5. Read the chosen `chosen_max_inflight_llm` from the artifact, pick
   `max_parallel_tasks = min(M, 8)`, and update both `config.py`
   fields inside T2.6 step 5. Commit artifact + research note +
   config.py together per step 6.
6. Proceed to T2.7 and T2.8.

T2.7 (tuned `--runs 3` baseline) and T2.8 (v0.1.0 atomic bump) are
also deferred: both depend on the tuned operating point from T2.6,
and T2.7 additionally requires a live bitgn/pac1-dev run that needs
the same provider access.
