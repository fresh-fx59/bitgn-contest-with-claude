"""Shared lightweight LLM classifier for tier-2 routing decisions.

Both the pre-task router and reactive router use the same classifier
model (claude-haiku-4-5 via cliproxyapi) with the same confidence
threshold and JSON response format.  This module provides the shared
plumbing so neither router duplicates the OpenAI client factory,
prompt construction, or response parsing.

Callers build a system prompt and user message specific to their
routing context, then call ``classify()`` which returns the parsed
JSON dict.  Any failure raises; callers are expected to catch and
degrade gracefully (UNKNOWN / no-injection).
"""
from __future__ import annotations

import json as _json
import os
import re as _re
from typing import Any, List

from bitgn_contest_agent import router_config


def classify(*, system: str, user: str) -> Any:
    """Call the classifier model and return the parsed JSON response.

    Args:
        system: the system prompt (describes categories + output format).
        user: the user message (task text, tool result, etc.).

    Returns:
        Parsed JSON dict on success.

    Raises:
        Any exception from the OpenAI client or JSON parsing — the
        caller is responsible for catching and degrading gracefully.
    """
    client = _get_openai_client()
    resp = client.chat.completions.create(
        model=router_config.classifier_model(),
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.0,
        timeout=10.0,
    )
    content = resp.choices[0].message.content
    if content is None:
        raise ValueError("classifier returned empty content (None)")
    return _json.loads(_strip_markdown_fences(content))


def build_category_list(categories: List[str], *, fallback: str = "UNKNOWN") -> str:
    """Format a category list for a classifier system prompt.

    Returns a newline-separated bulleted list with a fallback entry.
    """
    lines = [f"- {c}" for c in categories]
    lines.append(f"- {fallback} (none of the above apply confidently)")
    return "\n".join(lines)


def parse_response(
    raw: Any,
    *,
    valid_categories: set[str],
) -> tuple[str | None, float]:
    """Extract (category, confidence) from a classifier JSON response.

    Returns ``(None, confidence)`` if the category is missing, not a
    string, or not in ``valid_categories``.
    """
    if not isinstance(raw, dict):
        return None, 0.0

    category = raw.get("category")
    confidence = raw.get("confidence", 0.0)
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        confidence = 0.0

    if not isinstance(category, str) or category not in valid_categories:
        return None, confidence

    return category, confidence


_FENCE_RE = _re.compile(r"```(?:json)?\s*\n?(.*?)\n?\s*```", _re.DOTALL)


def _strip_markdown_fences(text: str) -> str:
    """Remove markdown code fences wrapping JSON (e.g. from Claude models)."""
    m = _FENCE_RE.search(text)
    return m.group(1).strip() if m else text.strip()


def _get_openai_client():  # pragma: no cover — thin factory, tested via patching
    from openai import OpenAI
    return OpenAI(
        base_url=os.environ.get("OPENAI_BASE_URL"),
        api_key=os.environ.get("OPENAI_API_KEY", "sk-proxy"),
    )
