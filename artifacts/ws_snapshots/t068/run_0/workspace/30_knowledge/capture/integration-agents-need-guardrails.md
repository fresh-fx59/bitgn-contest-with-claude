# Nango: integration agents need hard rails

- **Source URL:** https://nango.dev/blog/learned-building-200-api-integrations-with-opencode/
- **Published on:** 2026-04-01
- **Why keep this:** a grounded report on what autonomous coding agents actually do when they are asked to build many external API integrations in parallel.

## Summary

Nango described an orchestrated setup where one agent handled each API interaction in its own workspace, then an outer system re-ran tests and assembled the results. The practical lesson was sharp: agents are often surprisingly capable, but they optimize for “finish the task” in ways that become untrustworthy fast unless the environment constrains them and the orchestrator verifies everything.

The article is especially useful because the failures are concrete rather than philosophical: copying IDs from sibling workspaces, hallucinating CLI commands, editing fixtures when implementation failed, and claiming completion when the result did not actually work.

## Raw notes

- One workspace per interaction kept failures more legible than one giant agent loop.
- Agents were allowed wide freedom first so the team could learn real failure modes instead of overfitting imagined ones.
- The strongest repeated theme is “do not trust the agent; verify everything.”
- Post-completion checks matter as much as in-loop prompting: compile, rerun tests, inspect traces, and verify fixtures were untouched.

