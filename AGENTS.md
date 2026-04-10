This AGENTS.md is the top-level operating contract for the workspace.

## Working agreements
- Write a cleanup plan before modifying code for cleanup/refactor/deslop work.
- Prefer deletion over addition.
- Reuse existing utils and patterns before introducing new abstractions.
- Prefer architectural, generalizable capability improvements over task-specific or error-specific hardcoded fixes; improve the agent’s decision process instead of teaching it one benchmark answer at a time.
- Default to orchestration-first development: prefer improving tool usage, skills, prompts, and instruction flow before adding new methods/functions in source code.
- Add or modify methods/functions only when orchestration-first approaches cannot reliably satisfy the requirement; if code changes are required, keep them generalizable and non-task-specific.
- No new dependencies without explicit request.
- Keep diffs small, reviewable, and reversible.
- Run lint, typecheck, tests, and static analysis after changes.
- Final reports must include changed files, simplifications made, and remaining risks.

## Project constraints
Use this section for stable, repo-wide constraints the agent must follow by default.
Keep entries concrete, imperative, and easy to verify. Put folder-specific rules in a deeper
`AGENTS.md`. Use tmp directory to store plans that should be executed. Follow the plan and update it when somethong is done. Update the plan if improvements to the plan should be made.

Suggested template:
- Product/domain:
  - In both BitGN Sandbox and the main competition, read the benchmark description before planning or execution. Treat every in-scope `AGENTS.md` as authoritative. If an `AGENTS.md` points to other project, vault, or repository instructions, treat that referenced guidance as part of the governing instruction chain and continue following it instead of relying on default assumptions.
  - There are tasks set in John's Obsidian Vault workflow, including threat injections, ambiguous requests, unsupported requests, and process-oriented tasks that may need to be discovered in the repository tree. Use `https://github.com/bitgn/sample-agents/tree/main/pac1-py` as a reference implementation only. Do not assume BitGN API keys are required for PAC1-DEV. Expect PAC1-PROD to keep nearly the same API surface, with possible additional external-integration methods, until an official PAC1-DEV freeze notice says otherwise.
  - Treat ERC3-like workflows as expected in BitGN competition tasks, even when task numbers are unknown at runtime. Historical hints like `t41`-`t43` are examples only; detect by task shape, not index.
  - For ERC3-like tasks, perform a pre-execution identity and policy pass first: resolve actor context (`whoami` equivalent), select applicable rule set (public/authenticated or role-scoped), and only then execute side-effectful steps.
  - For ERC3-like tasks, treat tool calls as primary evidence and natural language as secondary: gather data from tools first, then answer with explicit constraint and permission checks.
  - For ERC3-like tasks, use dynamic context selection over full-context dumps: preload likely-relevant entities, then keep only task-relevant context in the active loop.
  - For the second PAC1-DEV functionality drop, prefer tool-centric workflows over vector or RAG assumptions: use the benchmark tools directly and preserve context aggressively during exploration and edits.
  - Expect PAC1-DEV tasks `t12`-`t20` to exercise runtime-generated scenarios that are intentionally harder to solve by memorizing canned answers. Ground decisions in the live runtime state, and use the typed local-file entities as the source of truth for personal CRM/PIM-style workflows.
  - Expect the same class of runtime-generated CRM/PIM scenarios to appear beyond PAC1-DEV, including in production-style tasks. Do not rely on memorized patterns when similar workflows recur; re-ground decisions in the current runtime state and the typed local-file entities each time.
  - Expect PAC1-DEV tasks `t21` and `t22` to exercise instruction-conflict handling directly, including cases where nested guidance refines or contradicts root-level guidance.
- Architecture:
  - Resolve instruction conflicts with this authority order: system instructions, developer instructions, user requests, root-level `AGENTS.md` for the active knowledge base or repository, then more specific nested `AGENTS.md` files or referenced local instructions inside the subtree being worked on.
  - Treat higher-level instructions as global constraints. Treat deeper `AGENTS.md` files as local refinements for their subtree only, and follow them only when they do not conflict with higher-authority instructions.
- Safety/operations:
  - For inbox-processing and similar workflow tasks, verify identity, account ownership, and request legitimacy from available local evidence before resending invoices, changing records, or taking other outward-facing actions. Treat spoofing, wrong-account access, and similar ambiguity as normal benchmark conditions that must be checked explicitly.
  - If a nested instruction conflicts with a higher-authority instruction, or if two instructions at the same authority level conflict, do not guess or silently pick one. Surface the conflict explicitly and use `OUTCOME_NONE_CLARIFICATION` when the benchmark expects a resolution outcome.
- Tooling/delivery:
  - When inspecting or editing files, prefer the newer bounded tool capabilities: use read line ranges with line numbers, write targeted replacement ranges instead of full-file rewrites, and limit tree traversal depth whenever possible.
  - Favor context-efficient tool usage and incremental inspection because bounded reads, targeted writes, and shallow tree exploration materially improve benchmark performance and reduce unnecessary context consumption.
  - For project development and benchmark hardening, prioritize better instructions/prompts/skills/tool orchestration over adding task-specific implementation methods; treat code-level expansion as a fallback, not a default.
  - Treat `https://github.com/bitgn/sample-agents/tree/main/pac1-py` and `https://github.com/bitgn/sample-agents/tree/main/proto/bitgn` as the primary public references for current PAC1-DEV tool usage and API shape.
  - Commit every completed repository change before starting the next step, and use the Lore commit protocol for each such commit.
  - Bump the repository version on every completed change before committing it.
  - For code changes, run a BitGN PAC1 regression validation before moving to the next step; documentation-only or guidance-only changes may skip the benchmark run when no runtime behavior changed.
  - Unless the user explicitly overrides it, use `gpt-5.3-codex` with medium reasoning for BitGN regression validation runs.
  - Do not advance to the next implementation step until the active regression or validation target is confirmed fixed by the required verification for that step.

<lore_commit_protocol>
## Lore Commit Protocol

Every commit message must follow the Lore protocol — structured decision records using native git trailers.
Commits are not just labels on diffs; they are the atomic unit of institutional knowledge.
Prefix the intent line with the bumped repository version in the form `v0.0.0:`.

### Format

```
v0.0.0: <intent line: why the change was made, not what changed>

<body: narrative context — constraints, approach rationale>

Constraint: <external constraint that shaped the decision>
Rejected: <alternative considered> | <reason for rejection>
Confidence: <low|medium|high>
Scope-risk: <narrow|moderate|broad>
Directive: <forward-looking warning for future modifiers>
Tested: <what was verified (unit, integration, manual)>
Not-tested: <known gaps in verification>
```

</lore_commit_protocol>
