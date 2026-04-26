"""Regex extractors that turn grader score_detail strings into rules.

This module is shared by:
  - Phase 1.5 (mining existing PROD JSONL traces + server logs)
  - Phase 2  (parsing live probe responses)

It MUST stay pure: no I/O, no DB, no network. Add new patterns by
appending to PATTERNS. Each pattern is a (regex, rule_kind) pair.
The regex's first capture group becomes the rule_value; if there is
a second capture group, see the per-pattern handling in extract_rules.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Pattern


@dataclass(frozen=True)
class ExtractedRule:
    rule_kind: str
    rule_value: str


_QUOTE = r"['\"]"

# Patterns ordered by specificity. Each entry compiles to a finditer
# call on the full score_detail string so that concatenated detail
# entries (e.g. "missing X / missing Y") yield multiple rules.
_PATTERNS: list[tuple[Pattern[str], str]] = [
    (re.compile(rf"answer is incorrect\. Expected:\s*{_QUOTE}([^'\"]+){_QUOTE}"), "expected_answer"),
    (re.compile(rf"missing file write\s*{_QUOTE}([^'\"]+){_QUOTE}"), "required_write"),
    (re.compile(rf"answer missing required reference\s*{_QUOTE}([^'\"]+){_QUOTE}"), "required_ref"),
    (re.compile(r"expected outcome\s+(\w+),\s*got\s+(\w+)"), "expected_outcome"),
]


def extract_rules(score_detail: str) -> list[ExtractedRule]:
    """Run every pattern across the input string and collect all matches."""
    out: list[ExtractedRule] = []
    for pattern, kind in _PATTERNS:
        for m in pattern.finditer(score_detail):
            value = m.group(1)
            out.append(ExtractedRule(rule_kind=kind, rule_value=value))
    return out
