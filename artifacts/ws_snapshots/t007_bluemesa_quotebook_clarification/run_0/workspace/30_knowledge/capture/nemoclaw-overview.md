# NVIDIA NemoClaw: reference stack for always-on assistants

- **Source URL:** https://docs.nvidia.com/nemoclaw/latest/about/overview.html
- **Captured on:** 2026-04-08
- **Why keep this:** a compact overview of an “agent runtime as reference stack” design that bundles sandboxing, inference routing, and lifecycle management.

## Summary

The NemoClaw overview described an open source reference stack for always-on assistants built around OpenClaw and OpenShell. The emphasis was operational: safe onboarding, lifecycle control, routed inference, declarative egress policy, and a hardened default sandbox rather than open-ended agent freedom.

This is useful as another data point that agent platforms are converging on a common bundle: policy, sandbox, routing, and operator control all live close to the runtime instead of being left as optional app glue.

## Raw notes

- The `nemoclaw` CLI is positioned as the single entrypoint for the whole stack.
- Credentials stay on the host while the sandbox talks to `inference.local`.
- Channel messaging is treated as supervised runtime infrastructure, not as a casual add-on.
- The system is explicitly designed for always-on assistants, which makes lifecycle and hot-reloadable policy central.


