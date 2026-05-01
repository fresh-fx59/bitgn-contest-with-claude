# Karpathy gist: persistent LLM wiki pattern

- **Source URL:** https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f
- **Captured on:** 2026-04-05
- **Why keep this:** a compact articulation of the “compiled knowledge base” idea that sits between raw sources and one-off answers.

## Summary

Karpathy's core claim was that most document workflows make the model rediscover the same knowledge from scratch every time. His alternative was a persistent wiki maintained by the model: summaries, entity pages, concept pages, and cross-links that keep compounding as more sources arrive.

The useful shift here is from retrieval as a repeated query-time act to maintenance as an ongoing write-time act. The wiki becomes the living artifact. Raw sources stay immutable, but the model keeps the intermediate knowledge layer coherent.

## Raw notes

- The architecture is raw sources, the wiki, and a schema file that teaches the model how to maintain the wiki.
- A good answer can become a new durable page instead of disappearing into chat history.
- Index and log files matter for navigation: one is content-oriented, the other chronological.
- The maintenance burden is the whole game. The claim is that LLMs make wiki upkeep cheap enough to be realistic.


