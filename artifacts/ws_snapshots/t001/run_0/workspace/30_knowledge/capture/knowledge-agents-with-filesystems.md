# Vercel: knowledge agents without embeddings

- **Source URL:** https://vercel.com/blog/build-knowledge-agents-without-embeddings
- **Published on:** 2026-03-19
- **Why keep this:** a concise argument for filesystem search as a more debuggable retrieval primitive than embeddings for many agent tasks.

## Summary

Vercel argued that many knowledge-agent failures come from hidden retrieval machinery: chunk boundaries, embedding choice, and similarity thresholds that are hard to inspect after the fact. Their answer was to give the model a sandboxed filesystem and basic shell tools, then let it search documents the same way it would search code.

The most compelling part of the piece is not that embeddings are “bad,” but that filesystem search often produces a cleaner debugging loop. When the answer is wrong, the engineer can inspect the actual commands and files instead of reverse-engineering a retrieval score.

## Raw notes

- The template stores synced content in a snapshot repo and lets the agent use `grep`, `find`, and `cat`.
- The article compares black-box retrieval scoring against transparent shell commands.
- The cost claim is notable: one internal sales-call agent dropped from about $1.00 to about $0.25 per call.
- The broader pattern matches other captures: agents do well when the interface looks like files and tools they already know.

