# bench_summary history

Committed artifacts in this directory form the ratchet floor for merges
per the regression harness gate in §5.4 of the design spec.

## Rule

Every PR must produce a `bench_summary` whose `overall.pass_rate` is
greater than or equal to the maximum `pass_rate` previously recorded in
this directory. PRs that regress the floor are blocked.

## Current floor

See the most recent `*.json` file. As of 2026-04-10 the floor is
`1623b40_20260410T181832Z.json` — **22/43 passes (51.2%)** against
`bitgn/pac1-dev`, produced by the `v0.0.33` agent using
`gpt-5.3-codex` at `reasoning_effort=medium` via `cliproxyapi`.

## How to produce a new summary

```bash
BITGN_API_KEY=... \
CLIPROXY_BASE_URL=http://127.0.0.1:8317/v1 \
CLIPROXY_API_KEY=... \
LLM_HTTP_TIMEOUT_SEC=120 \
bitgn-agent run-benchmark \
  --benchmark bitgn/pac1-dev \
  --runs 1 --max-parallel 4 \
  --output "artifacts/bench/$(git rev-parse --short HEAD)_$(date -u +%Y%m%dT%H%M%SZ).json"
```

The CLI's final `pass rate: N/M (P%)` line matches the JSON's
`overall.pass_rate` field — both are grader-scored, not agent-
self-reported. If they diverge, the per-task
`TraceWriter.patch_outcome_score()` back-fill path is broken.

## Known variance

The first benchmark run at the same commit scored 26/43 (60.5%); this
run scored 22/43 (51.2%). Run-to-run variance of this size is expected
because gpt-5.3-codex is non-deterministic and the grader evaluates
free-form output for several tasks. To bring the ratchet floor up
reliably, run the bench multiple times and commit the artifact with the
lowest pass rate (conservative floor) — or use `--runs N` once the
multi-run code path is exercised.
