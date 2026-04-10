# BitGN PAC1 Contest Agent — Design Spec

**Date:** 2026-04-10
**Status:** Approved for implementation planning
**Repo:** `bitgn-contest-with-claude`
**Goal:** Build an accurate and fast BitGN PAC1 contest agent — to win the contest, not to build a perfect testing or tooling environment.

---

## 0. Context and Baseline

### 0.1 What we are replacing
The sibling project `~/bitgn-contest` contains a working Codex-backed agent with 1008 historical traces in this repo's `task-t01-t43-logs-produced-by-bitgn-contest-agent/` directory. We replace it because:

- Its tool Union omits `execute_*` RPC verbs — the 0% failure cluster (`t31, t36, t39, t40`) almost certainly needs them.
- 35% of historical runs never emitted `/respond`, indicating crashes or forced termination with no clean failure path.
- The overall pass rate baseline is **44%** across the 1008 runs. This is the number we must beat.

### 0.2 Empirical facts extracted from 1008 existing traces
These calibrate every timeout and budget in this spec:

| Metric | Value |
|---|---|
| Step count: median / p95 / p99 | 9 / 25 / 48 |
| Runs at or near 48-step cap | 146 (14.5%), of which 122 scored 0 |
| Tool result size: median / p95 / p99 / max | 274 B / 1.9 KB / 2.6 KB / 87 KB (single `/fs/search`) |
| Trace size: median / p90 / max | 33 KB / 119 KB / 800 KB |
| Top tools observed | `/fs/read`, `/fs/search`, `/fs/list`, `/fs/context`, `/fs/tree`, `/fs/write`, `/respond` |
| `execute_*` verbs observed | **0 occurrences** |
| Outcome distribution | OK 33%, NONE_CLARIFICATION 22%, ERR_INTERNAL 15%, NONE_UNSUPPORTED 9%, DENIED_SECURITY 7% |
| Runs with no `/respond` at all | 353 (35%) |
| Overall pass rate | 44% |

### 0.3 Success criteria

**Target (contest goal): 100% pass rate on `bitgn/pac1-dev` and `bitgn/pac1-prod`.**
This is what we are aiming for, full stop. Every iteration is judged by how much closer we got to 100%. No "good enough" threshold — the contest goal is winning, not a passing grade.

**Merge gate (day-to-day quality control):**
- **Monotonic ratchet.** Once a benchmark run achieves pass rate `R`, all subsequent runs must achieve at least `R`. No fixed floor. The first committed run establishes the initial bar; every improvement raises it permanently.
- **No per-task regression.** A task that was passing ≥1/3 in the previous best-of cannot drop to 0/3 in the current run.
- **Zero-score cluster** (`t31, t36, t39, t40` in the historical baseline) must score ≥ 1/3 each before the first merge.

**Why a ratchet instead of a 100% hard gate:** if 100% were a hard pre-merge gate, one transient cliproxyapi rate-limit on a 156-run regression would block every subsequent commit until the flake resolved. The ratchet converges monotonically toward 100% while still tolerating the stochasticity inherent to LLM serving.

**Speed targets:**
- Single-task median wall-clock under 90 s, p95 under 240 s.
- Full `bitgn/pac1-dev` regression (52 tasks × 3 runs = 156 runs) under 30 min with `max_parallel=4`.

---

## 1. Architecture — Five hard-bounded layers

```
┌────────────────────────────────────────────────────────┐
│  CLI (run-task, run-benchmark)                         │  <- entrypoints
├────────────────────────────────────────────────────────┤
│  Orchestrator (thread pool, cooperative cancel, tracing)│  <- §3 parallelism
├────────────────────────────────────────────────────────┤
│  Agent Loop (hardened single-session SGR)              │  <- §2 core
│    ├─ Planner backend (provider-agnostic)              │
│    ├─ Session state + loop detector                    │
│    └─ Enforcer (pure-Python, terminal-emission only)   │
├────────────────────────────────────────────────────────┤
│  Adapter (PCM runtime dispatch, Req_* → protobuf RPC)  │  <- §2.6
├────────────────────────────────────────────────────────┤
│  Platform (official BitGN Python SDK, cliproxyapi)     │  <- external
└────────────────────────────────────────────────────────┘
```

**Boundary rules:**
- Each layer depends only on the layer below it. No upward imports.
- The planner loop must NOT import `anthropic` or `openai` directly; it talks to the backend interface only.
- The adapter is the single place that knows PCM protobuf names. No other layer touches `pcm_pb2`.

---

## 2. Components

### 2.1 Provider-agnostic SGR backend
**Default model:** `gpt-5.3-codex` with medium reasoning, routed via the local `cliproxyapi` at `$HOME/cliproxyapi`. Connection settings (base URL, auth) are read from `$HOME/bitgn-contest/`.

**Interface** (`backend/base.py`):
```python
class Backend(Protocol):
    def next_step(
        self,
        messages: list[Message],
        response_schema: type[NextStep],
        timeout_sec: float,
    ) -> NextStep: ...
```

Implementations:
- `backend/openai_compat.py` — uses `openai.Client.beta.chat.completions.parse(response_format=NextStep)`
- `backend/anthropic_compat.py` — uses `anthropic.Client.messages` with tool-use (deferred; add only when needed)

**Critical:** only one implementation ships in v1. The abstraction exists so a second implementation is a file, not a refactor.

### 2.2 Schemas (`schemas.py`)
Pydantic models define the full tool Union. Single source of truth for the entire pipeline (writer, analyzer, tests).

```python
class ReportTaskCompletion(BaseModel):
    tool: Literal["report_completion"]
    message: str = Field(..., min_length=1)
    grounding_refs: List[str]
    rulebook_notes: str = Field(..., min_length=1)
    outcome_justification: str = Field(..., min_length=1)
    completed_steps_laconic: List[str]
    finalization_ready: bool  # planner self-assertion consumed by §2.4 R4
    outcome: Literal[
        "OUTCOME_OK",
        "OUTCOME_DENIED_SECURITY",
        "OUTCOME_NONE_CLARIFICATION",
        "OUTCOME_NONE_UNSUPPORTED",
    ]
    # Note: OUTCOME_ERR_INTERNAL is intentionally NOT in this Literal.
    # See §2.4 — internal errors bubble through Python exception handling,
    # not through a self-reported task outcome.

class NextStep(BaseModel):
    current_state: str
    plan_remaining_steps_brief: Annotated[List[str], MinLen(1), MaxLen(5)]
    identity_verified: bool
    function: Union[
        Req_Tree, Req_Find, Req_Search, Req_List, Req_Read,
        Req_Write, Req_Delete, Req_MkDir, Req_Move,
        Req_Context, Req_Outline,
        Req_ExecuteUnary, Req_ExecuteServerStream,
        Req_ExecuteClientStream, Req_ExecuteBidiStream,
        Req_ExecuteOutline, Req_ExecuteClose,
        ReportTaskCompletion,
    ]
```

Notes:
- **`execute_*` verbs are in the Union from day 1.** This is the single most important coverage fix vs. the baseline agent.
- Fields embedded in `NextStep` (`identity_verified`, `plan_remaining_steps_brief`) force the planner to self-check before emitting a terminal — the hardened-single-session pattern.
- `ReportTaskCompletion.finalization_ready` is a self-assertion consumed by §2.4 R4. Modelled on the sibling agent's `workflow_state.finalization_ready` field, which was the single strongest catch signal in the 473-run recent-format research corpus (120 catches @ 77.4% precision).
- **`OUTCOME_ERR_INTERNAL` is deliberately absent from the `Outcome` literal.** The sibling agent's `OUTCOME_ERR_INTERNAL` had 82 cases in the recent corpus and **not one** of them passed the grader. Making that outcome unrepresentable at the schema layer is stronger than catching it at the enforcer — the planner cannot self-surrender through a terminal response. Internal failures propagate through Python exception handling (§4.1 patterns P1–P7) and surface as a synthetic completion record in the trace, not as a valid structured output.
- `ReportTaskCompletion.outcome` is a `Literal`, not a string — Pydantic rejects invalid outcomes at parse time.

### 2.3 Session state (`session.py`)
```python
@dataclass
class Session:
    seen_refs: set[str]            # populated by successful /fs/read (for §2.4 R5 grounding_refs)
    tools_called: set[str]         # every tool name that dispatched successfully (loop detector + logging)
    read_count: int                # successful /fs/read count (for §2.4 R3 content-read gate)
    rulebook_loaded: bool          # /load-respond-instructions succeeded (for §2.4 R2 rulebook gate)
    identity_loaded: bool          # identity/context tool succeeded (for §2.4 R1 identity gate)
    step: int
    recent_calls: deque[tuple]     # sliding window for loop detector, maxlen=6
    nudges_emitted: int            # budget counter for §4.2 invariant 4
```

Responsibilities:
- Track what the agent has actually successfully read (for §2.4 R5 grounding_refs enforcement).
- Increment `read_count` on every successful `/fs/read` (consumed by §2.4 R3).
- Track whether the identity/rulebook pre-pass completed (consumed by §2.4 R1 and R2).
- Maintain `tools_called` for the loop detector and trace logging only. No enforcer rule reads it directly — §2.4 gates all use dedicated counters because the set-based check had negative signal in the recent-format corpus.
- Loop detector: if the same `(tool_name, canonicalized_args)` tuple appears 3× in the last 6 calls, inject a nudge into the next prompt and log an event.
- Count nudges emitted against the §4.2 per-task budget.

### 2.4 Enforcer (`enforcer.py`)
Pure-Python policy check. **Runs only on terminal emission** (when `next_step.function` is `ReportTaskCompletion`). Not a critic, not a correctness oracle — there is no ground-truth reward in production, so the enforcer can only check policy invariants that must hold regardless of the task.

**Rule sources.** Every rule below cites at least one of these provenance tags:
- **[data]** — measured on the 473-run recent-format paired corpus via `scripts/research-logs-from-old-agent/rule_evaluator.py`. Each rule reports `catches` (failures it would have rejected) and `precision` (of all runs it fires on, fraction that actually failed).
- **[AGENTS.md]** — quoted clause from the repo's top-level `AGENTS.md` that requires the behaviour the rule encodes. These are our own operating constraints, not the sibling agent's.
- **[principle]** — cheap, mechanical checks that cannot be calibrated from historical data because the field is new in our schema. They are kept because the cost is near-zero and the failure mode (hallucinated refs, contradicted self-reports) is a well-known LLM pattern.

The older 1008-trace one-shot analysis (`appendix-enforcer-analysis.md`) is preserved for historical reference, but the rules below **supersede** it — they target the recent schema where the planner's own workflow state was accessible for the first time.

```python
# Refusal outcomes are exempt from content-read and identity gates because a
# task can legitimately be refused from its description alone. See AGENTS.md:
# "use OUTCOME_NONE_CLARIFICATION when the benchmark expects a resolution
# outcome" and the ERC3-like identity/policy-pass clause.
REFUSAL_OUTCOMES = {
    "OUTCOME_NONE_UNSUPPORTED",
    "OUTCOME_DENIED_SECURITY",
    "OUTCOME_NONE_CLARIFICATION",  # refinement: AGENTS.md explicitly allows this as a resolution outcome
}

def check_terminal(session: Session, step: NextStep) -> Verdict:
    fn = step.function
    if not isinstance(fn, ReportTaskCompletion):
        return Verdict(ok=True)
    reasons = []
    non_refusal = fn.outcome not in REFUSAL_OUTCOMES

    # R1 — Identity-context gate.
    # [data] catches 4 failures @ 100% precision (recent corpus).
    # [AGENTS.md] "perform a pre-execution identity and policy pass first:
    # resolve actor context (whoami equivalent), select applicable rule set
    # (public/authenticated or role-scoped), and only then execute side-
    # effectful steps."
    if non_refusal and not session.identity_loaded:
        reasons.append("identity gate: no identity/context tool called before terminal")

    # R2 — Rulebook-loaded gate (replaces the old "nontrivial-work" set check).
    # [data] catches 88 failures @ 84.6% precision. The single strongest
    # hard-gate signal in the recent corpus after OUTCOME_ERR_INTERNAL.
    # [AGENTS.md] "Treat every in-scope AGENTS.md as authoritative. If an
    # AGENTS.md points to other project, vault, or repository instructions,
    # treat that referenced guidance as part of the governing instruction
    # chain." The Planner cannot satisfy this without first loading the
    # rulebook for the active subtree.
    if non_refusal and not session.rulebook_loaded:
        reasons.append("rulebook gate: respond-instructions / AGENTS.md not loaded before terminal")

    # R3 — Content-read gate.
    # [data] catches 19 failures @ 86.4% precision. This replaces the
    # READ_LIKE_TOOLS set-intersection rule, which had negative signal in
    # the recent corpus (the set included /fs/tree and /fs/list, which fire
    # during discovery without producing content evidence). The planner's
    # own "did we actually read content?" counter is the right signal.
    # [AGENTS.md] "treat tool calls as primary evidence and natural language
    # as secondary: gather data from tools first, then answer with explicit
    # constraint and permission checks."
    if non_refusal and session.read_count == 0:
        reasons.append("content-read gate: zero successful /fs/read calls before terminal")

    # R4 — Planner self-assertion (new NextStep field).
    # [data] catches 120 failures @ 77.4% precision via the planner's own
    # finalization_ready flag on the sibling agent. Precision is below
    # hard-gate threshold, but the retry policy below bounds the cost:
    # a false reject costs one extra LLM call, while a true reject catches
    # half of all failures. Worth the cost.
    # [AGENTS.md] "Do not advance to the next implementation step until the
    # active regression or validation target is confirmed fixed by the
    # required verification for that step."
    if non_refusal and step.finalization_ready is False:
        reasons.append("planner self-assertion: finalization_ready=False at non-refusal terminal")

    # R5 — Grounding-refs reachability.
    # [principle] cannot be calibrated — the sibling agent's planner always
    # emitted grounding_refs on OUTCOME_OK (0 catches / 0 false positives on
    # the empty-refs check). Our schema requires refs for OK and the check
    # that every ref was actually read is a cheap mechanical guard against
    # the classic "cite a file I never opened" hallucination.
    for ref in fn.grounding_refs:
        if ref not in session.seen_refs:
            reasons.append(f"grounding_ref {ref!r} never successfully read")

    return Verdict(ok=not reasons, reasons=reasons)
```

**Rules the data killed** (recent-format corpus):

| Rule | fire@pass | fire@fail | verdict |
|---|---:|---:|---|
| `READ_LIKE_TOOLS` set intersection ("nontrivial-work gate") | 4/234 | 2/239 | **negative delta** — worse than random; dropped in favour of `read_count` |
| `grounding_refs_empty_on_ok` | 0 | 0 | no signal — planner always emits refs on OK |
| `post_mutation_unverified` | 0 | 0 | field not populated in traces |
| `loop_forced_fallback` | 0 | 0 | field not populated at terminal |
| `OUTCOME_OK` minimum message length | pass median 160 vs fail median 168 | — | distributions overlap perfectly |
| `NONE_CLARIFICATION` keyword check | 40% vs 37% | — | no discriminative power |

**Rules the data could have supported, but are intentionally handled upstream of the enforcer:**

- `OUTCOME_ERR_INTERNAL` as a reject rule had 100% precision / 82 catches in the recent corpus — the single cleanest signal. Instead of enforcing it at terminal, we **remove this outcome from the `Outcome` enum entirely**. The planner cannot report an error as a task outcome; if it cannot proceed, that is an internal error bubbled up through the Python error-handling layer (§4.1 patterns P1–P7), not a self-reported successful termination. This is a stronger move than an enforcer rule — it is unrepresentable rather than unenforceable.

**Biggest findings the enforcer cannot fix** (noted here so we don't pretend it can):
- `OUTCOME_NONE_CLARIFICATION` has a **36% pass rate** in the recent corpus — the agent hallucinates ambiguity ~64% of the time it claims clarification is needed. This is a prompt/planning issue. It belongs in §2.5 prompt design, not here. Required field `outcome_justification` is the lever.
- `OUTCOME_OK` has **~33% false positives** in the recent corpus (52 failing OKs out of 160). When the agent says "done," the grader disagrees a third of the time. Same root cause category: planner confidence is miscalibrated. Mitigation lives in prompts + the `completed_steps_laconic` and `outcome_justification` required fields, not in enforcer rules.

**Session state requirements (added to §2.3):**
- `rulebook_loaded: bool` — set True by the adapter when the Planner calls `/load-respond-instructions` or its successor and the call succeeds. Consumed by R2.
- `read_count: int` — incremented by the adapter on every successful `/fs/read`. Consumed by R3. Note: `tools_called: set[str]` is still tracked for logging and the loop detector, but no enforcer rule reads it directly.

**NextStep schema requirement (added to §2.2):**
- `ReportTaskCompletion.finalization_ready: bool` — the Planner's self-reported assertion that all obligations for the task have been completed. Consumed by R4. Modelled on the sibling agent's `workflow_state.finalization_ready` field which provided the strongest catch signal in the corpus.

**Retry policy:** 1 retry with the verdict's reasons injected into the next prompt as critique. If the retry also fails enforcement → **submit anyway**. The agent's best attempt is better than no submission at all. The enforcer verdict and the `submit_anyway` decision are both logged to the trace for post-hoc analysis.

**How to reproduce the rule-by-rule numbers:**
```
python3 scripts/research-logs-from-old-agent/rule_evaluator.py --all
```
The registry in `rule_evaluator.py` is the canonical source for the catch and precision figures cited above. Anyone proposing a new rule should add it to that registry first and only promote it to this section if the data supports it.

### 2.5 Prompts (`prompts.py`)
Separate module, owned by the design — not buried in the loop. The system prompt is the #1 reliability lever.

Responsibilities:
- Static system prompt (for provider-side prompt caching).
- `HINT` env var interpolated into the system prompt only on debugging runs.
- A critique-injection helper for validation/enforcer retries.
- A loop-nudge helper for the loop detector.

The system prompt covers: identity pass discipline, rulebook/AGENTS.md loading order, outcome enum semantics (with concrete examples of OK/CLARIFICATION/UNSUPPORTED/DENIED distinctions), grounding_refs rule, tool-centric workflow, never-fabricate rule.

### 2.6 Adapter (`adapter/pcm.py`)
Single file, single class. Translates `Req_*` Pydantic models to `PcmRuntimeClientSync` calls via `pcm_pb2`. Every other layer is adapter-agnostic.

Pre-pass (best-effort):
```python
def run_prepass(adapter, session, trace):
    for cmd in [Req_Tree(level=2, root="/"), Req_Read(path="AGENTS.md"), Req_Context()]:
        try:
            result = adapter.dispatch(cmd)
            if result.ok:
                session.identity_loaded = True  # set on ANY success
                session.seen_refs.update(result.refs)
        except Exception as e:
            trace.append_prepass(cmd, error=str(e))
```

The pre-pass must be best-effort per step. One failing step must not abort the others — we proceed even if only one of three succeeded.

### 2.7 Agent loop (`agent.py`)
The core planning loop. ~80 LoC. Responsibilities:

1. Build initial messages (system prompt + task description).
2. Run pre-pass via adapter.
3. Step loop up to `max_steps`:
   - Check cooperative-cancel event at top of each iteration.
   - Call `backend.next_step(...)`.
   - If `ValidationError` → one retry with critique-injection (P3); if retry also fails → fail task per P5.
   - If loop detector fires → inject nudge on next turn, continue.
   - Dispatch tool via adapter. On failure, feed the error back to the model (P1 pattern).
   - If terminal → run enforcer. On retry-exhausted failure → submit anyway.
   - Append everything to the trace.
4. Submit final outcome via the adapter's `/respond` equivalent.
5. Flush trace.

---

## 3. Parallelism, Cancellation, Tracing

### 3.1 Parallelism — Par-A (threads)
- `concurrent.futures.ThreadPoolExecutor(max_workers=max_parallel_tasks)` for task-level parallelism.
- Separate `threading.Semaphore(max_inflight_llm)` cap to protect cliproxyapi throughput.
- Default `max_parallel_tasks = 4`, `max_inflight_llm = 6`.
- LLM calls are blocking (the backend interface is synchronous). Threads give us the speedup without the asyncio color-function tax.

### 3.2 Cooperative cancellation
Each task worker receives a `threading.Event` (`cancel_event`) and a wall-clock deadline.

- The orchestrator sets `cancel_event` when the deadline fires OR when a SIGTERM arrives.
- The worker checks `cancel_event` at the top of every step-loop iteration.
- On cancel, the worker writes a synthetic `{"kind":"outcome","terminated_by":"cancel_timeout","error_kind":"task_timeout", ...}` trace event, flushes, and returns. It does **not** fabricate a `ReportTaskCompletion` — that outcome is reserved for the planner's own successful termination, and `OUTCOME_ERR_INTERNAL` no longer exists in the schema (see §2.2). The benchmark driver sees the synthetic outcome and records the task as failed, which is the correct semantic.
- No thread is abandoned. No partial traces are lost.

Grace period after cancel_event fires: `task_timeout_grace_sec = 20` (enough to flush trace + one submit call).

### 3.3 Transient backend retry
On `TransientBackendError` (rate limits, 5xx, network timeouts — the backend adapter maps provider-specific exceptions to this common type): exponential backoff `[500, 1500, 4000, 10000]` ms, max 4 attempts. **The LLM semaphore is released before sleeping and reacquired before retrying** — otherwise workers waste a slot during backoff and stall the pool.

### 3.4 Prompt caching
Only the static system prompt (turn 0) is reliably cacheable across tasks. The pre-pass output (turns 1-3) varies with filesystem state and cannot be cached. We keep the system prompt bit-identical across runs to maximize provider-side cache hits.

### 3.5 Trace format — JSON Lines, append-friendly
**Format:** JSONL (one event per line). Written incrementally during the run. Survives crashes; trivially `tail -f`-able by the operator tooling (§6).

```jsonl
{"kind":"meta","agent_version":"0.1.0","agent_commit":"abc","model":"gpt-5.3-codex","backend":"openai_compat","reasoning_effort":"medium","benchmark":"bitgn/pac1-dev","task_id":"t14","task_index":13,"started_at":"2026-04-10T14:05:12Z","trace_schema_version":"1.0.0"}
{"kind":"task","task_id":"t14","task_text":"..."}
{"kind":"prepass","cmd":"Req_Tree","ok":true,"bytes":1902,"wall_ms":118}
{"kind":"step","step":1,"wall_ms":4203,"llm":{"latency_ms":4100,"prompt_tokens":12300,"completion_tokens":480,"cached_tokens":11200,"retry_count":0},"next_step":{...},"tool_result":{"ok":true,"bytes":274,"wall_ms":51,"truncated":false},"session_after":{"seen_refs_count":3,"identity_loaded":true,"rulebook_loaded":true}}
{"kind":"event","at_step":2,"event_kind":"rate_limit_backoff","wait_ms":1500,"attempt":1}
{"kind":"step","step":2,...}
{"kind":"outcome","terminated_by":"report_completion","reported":"OUTCOME_OK","enforcer_bypassed":false,"error_kind":null,"total_steps":9,"total_llm_calls":9,"total_prompt_tokens":89120,"total_completion_tokens":2840,"total_cached_tokens":72000}
```

**Closed enums:**
- `error_kind`: `null | BACKEND_ERROR | SUBMISSION_FAILED | CONTEXT_OVERFLOW | INTERNAL_CRASH | MAX_STEPS | CANCELLED`
- `terminated_by`: `report_completion | cancel_timeout | error | cancel | exhausted`
- `event.event_kind`: `validation_retry | loop_nudge | rate_limit_backoff | timeout_cancel | enforcer_reject`
- `tool_result.error_code`: `null | RPC_DEADLINE | RPC_UNAVAILABLE | PCM_ERROR | INVALID_ARG | UNKNOWN`

**Crash fallback:** unhandled worker exceptions write `<trace>_CRASHED.json` containing the exception + traceback + reference to the partial trace.

**Schema evolution rule:** additive-only within a major version. Fields are `Optional` with defaults. Renaming, retyping, or removing a field requires a major version bump. See §6.6.

---

## 4. Error Handling — seven response patterns

Every failure mode in the agent maps to one of these. Each pattern defines both the recovery action AND what gets logged.

| Pattern | Trigger | Action | Logged as |
|---|---|---|---|
| **P1** Tool-feedback | PCM tool call fails (RPC error, invalid arg) | Feed error text back to model as tool result; continue loop | `step.tool_result.ok=false`, `error_code`, `error` |
| **P2** Retry + backoff | `TransientBackendError` (rate limit, 5xx, timeout — mapped by backend adapter from provider-specific types) | Release semaphore, sleep per §3.3 backoff, retry up to 4 attempts | `step.llm.retry_count++`, `event.kind=rate_limit_backoff` |
| **P3** One-shot retry + critique | Pydantic `ValidationError` on model output | Inject critique into next turn, retry exactly once; if retry also fails → P5 | `event.kind=validation_retry`, `event.details` |
| **P4** Trace + continue | Loop detector fires | Inject nudge on next turn, continue | `event.kind=loop_nudge`, `event.repeated_tuple` |
| **P5** Fail task, continue benchmark | Unrecoverable task error (backend exhausted, submission failed) | Mark task as failed with `error_kind`, flush trace, worker returns; orchestrator continues remaining tasks | `outcome.terminated_by=error`, `error_kind`, `error_msg` |
| **P6** Fail-fast at startup | Invalid config, missing creds, missing SDK | Raise before thread pool starts; non-zero exit; no traces written | CLI stderr + exit code |
| **P7** Cooperative cancel | Task wall-clock deadline OR SIGTERM | Set `cancel_event`; worker detects at step-loop top; emits synthetic terminal; flushes trace | `meta.cancelled=true`, `outcome.terminated_by=cancel` |

**Enforcer retry exhaustion is handled separately** (not a P-pattern). Per §2.4: on first enforcer veto, one retry with critique injection. If that retry also fails, the agent **submits anyway** — the best attempt is better than no submission. Both the verdict and the `submit_anyway` decision are logged as `step.enforcer_verdict` and `step.enforcer_action`.

**All errors are captured in the trace**, by design. Specifically:
- `outcome.error_kind` (closed enum) for task-level failures
- `outcome.terminated_by` for how the task ended
- `events[]` array for in-flight recoveries (backoffs, retries, nudges, enforcer vetoes)
- `steps[i].tool_result.error_code` + `error` for per-step tool failures
- `steps[i].llm.retry_count` for P2 retries
- `meta.cancelled` for P7
- Sibling `<trace>_CRASHED.json` for unhandled exceptions

This makes the failure histogram buildable from pure JSON via the §6 tooling — no LLM needed to diagnose what went wrong across a benchmark run.

### 4.1 Calibrated defaults (from §0.2 empirical analysis)

| Setting | Default | Source |
|---|---:|---|
| `max_steps` | **40** | Old agent cap was 48, p99 = 48; 40 recovers most p95-p99 without inviting infinite loops |
| `task_timeout_sec` | **300** | 40 steps × ~6 s/step + 60 s slack |
| `task_timeout_grace_sec` | **20** | Enough to flush trace + one submit call |
| `llm_http_timeout_sec` | **30** | Single-call ceiling; matches cliproxyapi upstream defaults. Verify on first 50 runs and adjust. |
| `max_tool_result_bytes` | **16384** | p99 = 2.6 KB, but `/fs/search` outlier = 87 KB; cap at 16 KB with `truncated=true` flag |
| `max_parallel_tasks` | **4** | Throughput bound is cliproxyapi, not local CPU |
| `max_inflight_llm` | **6** | 1.5× parallel tasks for retry burst, under the release-during-backoff rule |
| `rate_limit_backoff_ms` | **[500, 1500, 4000, 10000]** | 4 attempts, drops the 16 s tail that exceeded cancel grace |

**`task_timeout_sec=0`** disables the wall-clock cancel entirely (dev-loop convenience).

**Recalibration policy:** every value in the table above was extracted from the *old agent's* historical traces (§0.2). The new agent's execution profile will differ — different tool verbs, different prompt, different model latency. **After the first 50 real new-agent runs**, re-run the §0.2 analysis against the fresh traces and adjust these defaults. Record the recalibration as a separate commit with the empirical justification in the commit body. Do not treat these initial numbers as final.

### 4.2 Error-handling invariants

1. Worker boundary uses `except Exception`, never `except BaseException` (must not catch `KeyboardInterrupt` / `SystemExit`).
2. Per-step `llm.retry_count` is incremented across retries, never overwritten.
3. Startup config validation runs **before** thread pool creation (P6 fail-fast).
4. Loop-detection nudge budget: a maximum of 2 `loop_nudge` events per task. If the detector would fire a third time, the worker instead emits a synthetic error terminal with `error_kind=INTERNAL_CRASH`. This prevents infinite nudge-ignore cycles.
5. Tool result truncation emits `tool_result.truncated=true` AND `tool_result.original_bytes`, so the planner can decide to paginate.
6. The submit-anyway path logs `enforcer_action=submit_anyway` + the full rejected verdict reasons.
7. Crash file is written even if the partial trace flush itself fails (separate I/O path).

---

## 5. Testing — the minimum that stays valuable

### 5.1 Philosophy
Write tests that **cannot** be invalidated by prompt tuning, enforcer tuning, or loop-detector threshold changes. If a test asserts "given input X, agent outputs Y", it will be rewritten every iteration and become dead weight. The only tests we keep are **mechanical contracts** — things that must hold regardless of how the agent behaves.

The real quality gate is the regression harness (§5.4), which measures pass rate and is behavior-agnostic.

### 5.2 Unit tests (the entire suite, ~120 LoC total)

**Test 1 — Tool coverage** (`tests/test_tool_coverage.py`, ~10 LoC)
Asserts that every verb in `KNOWN_PCM_RUNTIME_TOOLS` appears in the `NextStep.function` Union. Protects against the #1 historical failure mode (the baseline agent was missing `execute_*`).

**Test 2 — Schema round-trip** (`tests/test_schemas.py`, ~15 LoC)
For each Union variant, synthesize an instance, dump to JSON, reparse, assert equality. Catches Pydantic / structured-output drift on the next dependency bump.

**Test 3 — Adapter dispatch** (`tests/test_adapter_dispatch.py`, ~30 LoC)
For each `Req_*` model, assert `adapter.dispatch(req)` invokes the correct `PcmRuntimeClientSync` method with the expected proto field mapping. Uses a `MagicMock` runtime client.

**Test 4 — Analyzer completeness** (`tests/test_analyzer_completeness.py`, ~40 LoC)
Property test. Uses introspection to build an exhaustive synthetic trace covering every tool variant, every event kind, every error kind. Asserts that `trace_stats` surfaces every variant in its output and that arithmetic invariants hold (token totals, step counts). Self-updating via introspection — adding a new variant picks up automatically.

**Test 5 — Version compatibility** (`tests/test_version_compat.py`, ~25 LoC, grows ~5 LoC per major bump)
Parametrized over every committed `tests/fixtures/trace_v*.jsonl`. Asserts the current analyzer can extract core metrics (score, outcome, step count, token totals) from every historical fixture. Enforces the additive-only rule from §3.5.

### 5.3 What we explicitly do NOT test
- Enforcer rule truth tables (we tune these; they're not contracts).
- Session internals (regression harness catches the consequences).
- Loop detector threshold (that threshold IS the thing we tune).
- Backend retry math (simple, flaky around `time.sleep`).
- Single live integration task (regression harness subsumes it).
- Trace schema structural assertions (single source of truth + analyzer-completeness test covers it).

### 5.4 Regression harness (the real quality gate)
```bash
python -m bitgn_contest_agent.cli run-benchmark \
  --benchmark bitgn/pac1-dev \
  --runs 3 \
  --max-parallel 4 \
  --output artifacts/regression_<commit>.json
```

**Pass criteria (hard gate before merge):**
- Overall pass rate ≥ 55% (starting floor). The floor ratchets upward: once a run achieves rate R, subsequent runs must hit at least R — regressions below the current floor block merge.
- 0% failure cluster (`t31, t36, t39, t40`) scores ≥ 1/3 each
- No individual task regresses from ≥1/3 to 0/3

**Rule going forward:** write a new unit test only when a bug slipped past the regression harness AND is expensive to reproduce end-to-end. React, don't preempt.

---

## 6. Log analysis and operator tooling

### 6.1 Principle
> Anything deterministic goes into a CLI. LLM cost is paid only for judgment, not for counting.

Six CLIs + one skill. Total code budget: ~600 LoC, pure stdlib, no new dependencies.

### 6.2 CLIs (`scripts/`)

**`trace_stats.py`** — one trace → metrics JSON
Flags: `--terse`, `--errors-only`, `--show-step=N`, `--show-prompt=N`
Output schema:
```json
{
  "meta": {"agent_version","agent_commit","model","backend","benchmark","task_id","started_at","wall_clock_sec"},
  "score": 1.0,
  "outcome": {"reported","terminated_by","error_kind"},
  "steps": {"count","tool_breakdown","truncated_results","failed_tool_calls"},
  "llm": {"calls","prompt_tokens","completion_tokens","cached_tokens","latency_ms":{"p50","p95","max"},"retries"},
  "enforcer": {"verdicts","retries","submit_anyway"},
  "events": [...],
  "session_final": {"identity_loaded","rulebook_loaded","seen_refs_count"}
}
```

**`bench_summary.py`** — directory of traces → aggregate JSON
Output is a **frozen, never-changing schema** (see §6.6). Committed to `artifacts/bench/<version>_<timestamp>.json` as permanent historical record.

**`failure_clusters.py`** — group failures by `(error_kind, outcome, last_tool_name, final_message_hash)`; show top N clusters. Point of this tool: find "5 tasks fail the same way" without reading 30 traces.

**`grep_traces.py`** — structured filter: `--benchmark --task --outcome --min-steps --has-event --tool-used --error-kind`. Returns matching trace paths.

**`trace_diff.py`** — two traces of the same task → step-by-step diff of NextStep fields and tool calls. For "why did t14 pass once and fail twice".

**`bench_diff.py`** — two `bench_summary` JSONs → regression report (which tasks improved/regressed, step count deltas, token spend delta).

**`agent_ctl.py`** — sub-commands: `run` (background launch with PID file), `status` (in-flight progress), `tail <run_id>` (stream current task's trace events), `stop <run_id>` (SIGTERM + cooperative-cancel wait).

### 6.3 Skill (`.claude/skills/bitgn-agent-ops/SKILL.md`)
Short markdown decision tree mapping questions to commands:

| Question | Command |
|---|---|
| How did this run go? | `trace_stats --terse <path>` |
| Why did it fail? | `trace_stats --errors-only <path>` |
| Compare two runs of same task | `trace_diff <a> <b>` |
| Which tasks regressed? | `bench_diff <old> <new>` |
| Top failure patterns? | `failure_clusters <dir>` |
| Runs that hit step cap | `grep_traces --error-kind MAX_STEPS` |
| Specific step's prompt | `trace_stats --show-prompt=N <path>` |
| Benchmark still running? | `agent_ctl status` |
| Watch current task | `agent_ctl tail <run_id>` |
| Stop run cleanly | `agent_ctl stop <run_id>` |

**Rule at top of skill:**
> Before reading any trace JSON directly: check if one of these commands answers your question. Read files only when you need context the CLIs don't expose.

### 6.4 Explicit non-goals
- No LLM-powered log analysis (CLIs suffice).
- No replay/recording framework (speculative value).
- No custom query language.
- No dashboard in this repo (the sibling has one; copy later if needed).
- No `prompt_dump` as a separate tool (it's a `trace_stats` flag).
- No `diff_configs` tool (`git diff` covers this).

### 6.5 Analyzer-completeness contract (folds to §5 test 4)
Both the writer and the reader import `TraceRecord`, `ToolName`, `EventKind`, `ErrorKind` from a **single source of truth** (`trace_schema.py`). The Pydantic model uses `model_config = ConfigDict(extra="ignore")` so unknown future fields are safe to discard.

Test 4 from §5.2 uses introspection to generate an exhaustive synthetic trace and asserts the analyzer surfaces every variant. Known limitation: catches coverage drift, not statistical-aggregation correctness (the regression harness is the backstop for the latter).

### 6.6 Schema evolution — two assets, two policies

**Asset A: Pass-rate summary history (iteration decisions).**
`bench_summary` output has a **frozen, minimal schema**: `task_id → {runs, passes, median_steps, median_tokens, failure_cluster}`. Never changes. Committed to `artifacts/bench/`. Cross-version comparisons (v0.5 vs. v0.1) work forever without any migration code because both files have identical shape. This eliminates ~90% of the "can we read old logs" problem by making the question irrelevant for the use case that actually matters.

**Asset B: Full trace detail (debugging forensics).**
Rules:
1. **Additive-only within a major version.** New fields are `Optional[...] = None`. Existing fields are never renamed, retyped, or removed.
2. **Pydantic `extra="ignore"`** so old traces with fewer fields and future traces with more fields both parse.
3. **One golden fixture committed per major version** (`tests/fixtures/trace_v1.jsonl`, `trace_v2.jsonl`, ...). Frozen, never edited.
4. **Test 5 from §5.2** is parametrized over every committed fixture. Asserts core metric extractability (score, outcome, step count, token totals). This is the **enforcement mechanism** — Rule 1 is discipline; this test is the check that keeps the discipline honest.

**Major version bump = deliberate rare event.** Happens only when additive-only genuinely cannot accommodate the change. Then we commit a new fixture, keep all older fixtures with their tests, and either write a small adapter for the previous version or explicitly refuse it with a clear error message.

**Known limitation:** metric-definition drift (e.g., v2 starts counting `cached_tokens` in `prompt_tokens` but v1 didn't) is not auto-detected. Mitigation: record such changes in project memory; there is no elegant automatic fix, and freezing metric definitions forever is worse than the drift.

**Existing 1008 sibling-agent traces:** treated as foreign data. If we need them in our tooling, write a one-shot `scripts/import_legacy_traces.py` that converts once to v1 format, commit the converted artifacts, never run again. Otherwise the empirical numbers already extracted in §0.2 are sufficient and the originals can be ignored.

---

## 7. Directory layout

```
bitgn-contest-with-claude/
├── AGENTS.md                         # existing, governs project rules
├── src/bitgn_contest_agent/
│   ├── __init__.py
│   ├── cli.py                        # run-task, run-benchmark entrypoints
│   ├── agent.py                      # planning loop (~80 LoC)
│   ├── orchestrator.py               # thread pool, cancel event, dispatch
│   ├── schemas.py                    # NextStep, Req_*, ReportTaskCompletion
│   ├── trace_schema.py               # SINGLE SOURCE OF TRUTH for trace format
│   ├── session.py                    # Session dataclass, loop detector
│   ├── enforcer.py                   # check_terminal
│   ├── prompts.py                    # static system prompt, critique helpers
│   ├── backend/
│   │   ├── base.py                   # Backend protocol
│   │   └── openai_compat.py          # default implementation
│   ├── adapter/
│   │   └── pcm.py                    # Req_* → PcmRuntimeClientSync dispatch
│   └── config.py                     # AgentConfig dataclass
├── scripts/
│   ├── trace_stats.py
│   ├── bench_summary.py
│   ├── failure_clusters.py
│   ├── grep_traces.py
│   ├── trace_diff.py
│   ├── bench_diff.py
│   └── agent_ctl.py
├── tests/
│   ├── fixtures/
│   │   └── trace_v1.jsonl            # golden fixture for schema v1
│   ├── test_tool_coverage.py
│   ├── test_schemas.py
│   ├── test_adapter_dispatch.py
│   ├── test_analyzer_completeness.py
│   └── test_version_compat.py
├── .claude/skills/bitgn-agent-ops/
│   └── SKILL.md                      # decision tree for operator questions
├── artifacts/
│   └── bench/                        # frozen-schema bench summaries (committed)
├── docs/
│   └── superpowers/specs/
│       └── 2026-04-10-bitgn-agent-design.md  # this document
├── logs/                             # runtime trace output (JSONL)
└── pyproject.toml
```

---

## 8. Explicit non-goals

- No multi-agent Planner/Executor/Critic split. There is no ground-truth reward in production, so a Critic can only check policy invariants — which are baked into the Enforcer and NextStep schema fields.
- No asyncio. Threads (Par-A) are simpler and the throughput bottleneck is cliproxyapi, not local concurrency.
- No RAG, no vector store, no embedding cache. PAC1 tools are the primary evidence source per AGENTS.md.
- No custom benchmark adapters beyond `bitgn/pac1-*`. Out of scope.
- No replay/recording infrastructure. Speculative.
- No backwards compatibility with the sibling project's trace format. One-shot import or ignore.
- No new dependencies beyond what the official BitGN SDK, `pydantic`, and the chosen backend SDK require.

---

## 9. Open questions (to resolve during implementation planning)

1. **Exact `execute_*` verb signatures.** Need to read the PCM protobuf definitions to lock the `Req_Execute*` Pydantic shapes. Blocked on reading `bitgn.vm.pcm_pb2` contents.
2. **`llm_http_timeout_sec=30` validation.** Calibrated against assumption, not measurement. Must measure on first 50 new-agent runs and adjust.
3. **Whether the BitGN SDK supports sync context managers for the runtime client.** Affects `adapter/pcm.py` resource cleanup shape.
4. **Whether cliproxyapi's OpenAI-compatible endpoint supports `response_format` structured outputs for gpt-5.3-codex.** If not, the backend falls back to manual JSON parsing with critique-injection retry — the loop already handles this via P3.

These are resolved during the writing-plans phase, not deferred forever.

---

## 10. Approval trail

- §1 Architecture — approved
- §2 Components — approved with A-E folded, F deferred
- §3 Parallelism / cancel / trace — approved with 7 fixes + JSONL format + trace-schema redesign
- §4 Error handling — approved with all 11 critique items folded + empirical timeout calibration
- §5 Testing — approved after scope cut (4 → 5 tests, all mechanical)
- §6 Tooling — approved with version-compat test added as §6.6
