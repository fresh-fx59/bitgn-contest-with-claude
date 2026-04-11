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
