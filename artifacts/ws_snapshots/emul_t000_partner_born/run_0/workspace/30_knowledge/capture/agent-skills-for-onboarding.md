# Antithesis: agent skills for painful onboarding

- **Source URL:** https://antithesis.com/blog/2026/agent_skills/
- **Published on:** 2026-03-25
- **Why keep this:** a strong example of packaging tacit operational knowledge into reusable skills instead of expecting users to rediscover it by trial and error.

## Summary

The Antithesis post framed “skills” as a way to compress the ugly parts of onboarding into reusable instructions and artifacts. The author's point was not just that agents can automate setup, but that they can carry specialized reasoning about system properties, container topology, and testability that would otherwise live in forward-deployed engineer heads.

That makes the piece useful as evidence that the real value of agent scaffolding often sits in captured operational judgment, not in generic prompt cleverness.

## Raw notes

- The workflow is split into research, setup, and workload generation.
- Research produces architecture notes, a property catalog, and a minimal deployment topology.
- Setup handles packaging and deployment glue so the system becomes runnable inside Antithesis without handholding.
- Workload generation turns the earlier property catalog into concrete assertions and test-driving clients.

