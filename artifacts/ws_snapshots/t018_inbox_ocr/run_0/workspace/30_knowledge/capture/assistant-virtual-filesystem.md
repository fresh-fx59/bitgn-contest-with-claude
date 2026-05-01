# Mintlify: virtual filesystem for assistant docs

- **Source URL:** https://www.mintlify.com/blog/how-we-built-a-virtual-filesystem-for-our-assistant
- **Published on:** 2026-03-24
- **Why keep this:** a concrete example of replacing slow repo-clone sandboxes with a file-shaped interface the model can actually use.

## Summary

Mintlify described moving from full sandboxes toward a virtual filesystem backed by the same documentation index they already used for search. The key idea was pragmatic: the assistant did not need a real disk so much as a convincing filesystem surface with `ls`, `cd`, `find`, `cat`, and `grep`.

That shift cut session creation from roughly 46 seconds to about 100 milliseconds. It also turned retrieval into something engineers could debug directly: inspect paths, watch `grep`, and reason about misses without guessing which hidden chunk scored highest.

## Raw notes

- The path tree is materialized up front, then cached in memory so navigation calls stay local.
- Access control is applied before the tree is built, which means hidden files disappear from the assistant's world instead of being filtered after retrieval.
- `cat` reconstructs full pages from stored chunks; `grep` uses the database as a coarse filter and in-memory execution as a fine filter.
- The interesting architectural claim is that “filesystem” is really an interaction contract, not necessarily a literal mounted disk.
