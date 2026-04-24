# bitgn-contest-agent

A hardened, single-session agentic system for the [BitGN PAC1](https://github.com/bitgn/sample-agents/tree/main/pac1-py) competition. The agent autonomously solves tasks in John's Obsidian Vault — reading files, writing records, navigating inboxes, handling finances, and resolving security-aware workflows — by driving a ReAct-style tool loop against the BitGN PCM runtime.

**Contest score:** 76 OK / 104 tasks  - gpt-5.4

**Current scores:** 

- 104/104 - gpt-5.4
- 50/104 - gpt-oss-20b
- 68/104 - gpt-oss-120b
- 70.8/104 - qwen3.5-35b-a3b

---

## How it works

The agent runs a structured loop per task:

1. **Pre-pass** — reads `AGENTS.md` and calls `context()` to ground itself in the runtime environment
2. **Step loop** (up to 40 steps) — LLM emits a `NextStep` JSON with a reasoning scratchpad, a short plan, and a single tool call; the result feeds back as the next user message
3. **Terminal** — `report_completion` emits an outcome with mandatory `grounding_refs` (every cited file must have been successfully read)

Reliability layers: exponential-backoff retry (P2), validation-error critique injection (P3), loop detection with nudges (P4), and an enforcer that hard-gates fabricated refs and surrender outcomes.

---

## Quick start

### 1. Install

```bash
# Python 3.12+ required
uv pip install -e ".[dev]"
```

### 2. Set credentials

```bash
export BITGN_API_KEY=<your-bitgn-key>
export CLIPROXY_BASE_URL=<cliproxy-endpoint>
export CLIPROXY_API_KEY=<cliproxy-key>
```

### 3. Run a single task

```bash
bitgn-agent run-task --task-id t01
```

Logs are written to `logs/` as JSONL traces.

### 4. Run the full benchmark

```bash
bitgn-agent run-benchmark
```

Optional flags:

| Flag | Default | Purpose |
|------|---------|---------|
| `--benchmark` | `bitgn/pac1-dev` | Override benchmark slug |
| `--runs N` | `1` | Repeat each task N times |
| `--max-parallel N` | `8` | Parallel task workers |
| `--smoke` | off | Run fixed smoke subset (180s budget) |
| `--output path` | none | Write `bench_summary.json` |

### 5. Triage failures

```bash
# Single run
bitgn-agent triage artifacts/bench/my_run.json

# Diff two runs
bitgn-agent triage --before artifacts/bench/baseline.json --after artifacts/bench/candidate.json
```

---

## Configuration

All tunables are set via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENT_MODEL` | `gpt-5.3-codex` | LLM model ID |
| `AGENT_REASONING_EFFORT` | `medium` | Reasoning effort (`low`/`medium`/`high`) |
| `MAX_STEPS` | `40` | Max tool steps per task |
| `TASK_TIMEOUT_SEC` | `300` | Per-task wall-clock budget |
| `MAX_PARALLEL_TASKS` | `8` | Concurrent task workers |
| `MAX_INFLIGHT_LLM` | `48` | Concurrent LLM calls across all workers |
| `LOG_DIR` | `logs` | Trace output directory |

---

## Project layout

```
src/bitgn_contest_agent/
  cli.py           # Entry point — run-task, run-benchmark, triage
  agent.py         # AgentLoop: step iteration, LLM calls, P2/P3/P4 patterns
  orchestrator.py  # ThreadPoolExecutor task dispatch with deadline/cancel
  adapter/pcm.py   # Bridge to BitGN PCM runtime (read, write, search, …)
  backend/         # Provider-agnostic LLM interface (OpenAI-compat + cliproxyapi)
  schemas.py       # Pydantic tool schemas (NextStep discriminated union)
  enforcer.py      # Terminal policy: grounding-refs reachability, no-surrender gate
  session.py       # Per-task state + loop detector
  prompts.py       # Static system prompt (~55 clauses, bit-identical for caching)
  task_hints.py    # Narrow per-failure-cluster hint injections
  trace_writer.py  # Thread-safe incremental JSONL tracing

artifacts/bench/   # Saved benchmark run summaries
docs/              # Design specs and enforcer analysis
tests/             # Unit + coverage tests
```

---

## Development

```bash
# Run tests
pytest

# Run smoke benchmark (fast subset, ~3 min)
bitgn-agent run-benchmark --smoke --output artifacts/bench/smoke.json
```

Benchmark results in `artifacts/bench/` follow the naming convention:
`<git-sha>_<label>_<model>_<timestamp>_<env>_runs<n>.json`
