# Agent control planes and runtime shape

- **Source mix:** recent captures on managed agents, virtual filesystems, integration runners, and MCP packaging
- **Why keep this:** a cross-cutting note that ties several recent captures into one recurring pattern.

## Summary

A lot of recent agent writing converges on the same architecture even when the branding changes. The winning stack usually includes a constrained runtime, a file-shaped or tool-shaped working surface, explicit trust or permission boundaries, durable traces, and a small amount of reusable operational doctrine packaged as docs, skills, or workflows.

What varies is which piece gets sold as the headline feature. One article leads with managed sessions. Another leads with filesystems over embeddings. Another leads with skills. Another leads with deployment and policy. But the recurring shape underneath is a control plane wrapped around a model, not a naked model doing heroic improvisation.

## Raw notes

- Runtime design is becoming the durable product surface; raw model access is no longer the whole story.
- Files, shell tools, and explicit workflow docs keep showing up because they are legible to both humans and agents.
- Trust handling is moving closer to the substrate: channel rules, egress policy, fixture protection, auth scoping, and traceability.
- “Agentic” increasingly means packaging model capability with boring operational discipline.

