"""Shared canonicalization helpers for preflight tools.

Entity/vendor/project names in the workspace vary by case, punctuation,
and aliasing. These helpers produce a normalized key plus a simple
match score across candidate names/aliases.
"""
from __future__ import annotations

import re
from typing import Iterable


_PUNCT_RE = re.compile(r"[^\w\s\u4e00-\u9fff]+", re.UNICODE)


def normalize_name(name: str) -> str:
    """Lowercase, strip, collapse whitespace, drop non-word non-CJK chars."""
    if not name:
        return ""
    cleaned = _PUNCT_RE.sub(" ", name)
    return " ".join(cleaned.lower().split())


def score_match(query: str, candidates: Iterable[str]) -> float:
    """Return best match score in [0.0, 1.0] of query against candidates.

    Current rule: exact normalized match = 1.0, else 0.0. Intentionally
    narrow; we'll broaden with fuzzy matching only if bench shows need.
    """
    q = normalize_name(query)
    if not q:
        return 0.0
    for cand in candidates:
        if normalize_name(cand) == q:
            return 1.0
    return 0.0
