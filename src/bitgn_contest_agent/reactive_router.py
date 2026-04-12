"""Reactive routing — mid-task skill injection based on tool dispatch.

Complements the pre-task Router (spec §5.3) with a second routing
stage that fires after each non-terminal tool call.  When a tool
dispatch matches a reactive skill's trigger (tool name + path regex),
the skill body is injected as a user message before the next LLM call.

Reactive skills live in ``skills/reactive/`` and use flat frontmatter
keys ``reactive_tool`` and ``reactive_path`` instead of
``matcher_patterns``.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from bitgn_contest_agent.skill_loader import (
    SkillFormatError,
    _parse_frontmatter,
    _split_frontmatter,
)

_LOG = logging.getLogger(__name__)

_REACTIVE_REQUIRED_KEYS = (
    "name", "description", "type", "category",
    "reactive_tool", "reactive_path",
)
_VALID_TYPES = ("rigid", "flexible")


@dataclass(frozen=True, slots=True)
class ReactiveSkill:
    name: str
    description: str
    type: str
    category: str
    reactive_tool: str
    reactive_path: str
    body: str


@dataclass(frozen=True, slots=True)
class ReactiveDecision:
    skill_name: str
    category: str
    body: str


def load_reactive_skill(path: Path) -> ReactiveSkill:
    """Parse a reactive skill file and return a ReactiveSkill.

    Raises SkillFormatError on any format violation.
    """
    text = Path(path).read_text(encoding="utf-8")
    frontmatter_text, body = _split_frontmatter(text, path)
    parsed = _parse_frontmatter(frontmatter_text, path)
    _validate_reactive(parsed, path)
    return ReactiveSkill(
        name=parsed["name"],
        description=parsed["description"],
        type=parsed["type"],
        category=parsed["category"],
        reactive_tool=parsed["reactive_tool"],
        reactive_path=parsed["reactive_path"],
        body=body.strip() + "\n",
    )


def _validate_reactive(parsed: dict, path: Path) -> None:
    for key in _REACTIVE_REQUIRED_KEYS:
        if key not in parsed:
            raise SkillFormatError(
                f"{path}: missing required frontmatter key `{key}`"
            )
    if parsed["type"] not in _VALID_TYPES:
        raise SkillFormatError(
            f"{path}: type must be one of rigid|flexible, got {parsed['type']!r}"
        )


class ReactiveRouter:
    """Evaluates tool dispatch results against reactive skill triggers.

    Stateless — injection tracking is owned by the caller via the
    ``already_injected`` parameter.  Safe to share across concurrent
    tasks.
    """

    def __init__(self, skills: List[ReactiveSkill]) -> None:
        self._skills: List[tuple[ReactiveSkill, re.Pattern]] = []
        for s in skills:
            try:
                compiled = re.compile(s.reactive_path)
            except re.error as exc:
                raise SkillFormatError(
                    f"reactive skill {s.name}: invalid regex in reactive_path: {exc}"
                ) from exc
            self._skills.append((s, compiled))

    def evaluate(
        self,
        tool_name: str,
        tool_args: dict,
        tool_result_text: str,
        already_injected: frozenset[str] = frozenset(),
    ) -> Optional[ReactiveDecision]:
        """Check if a tool dispatch triggers a reactive skill injection.

        Returns a ReactiveDecision if a skill matches, None otherwise.
        The caller should add the returned ``skill_name`` to its
        tracking set to prevent duplicate injection (inject-once
        semantics).
        """
        for skill, pattern in self._skills:
            if skill.reactive_tool != tool_name:
                continue
            if skill.name in already_injected:
                continue
            path = tool_args.get("path") or tool_args.get("root") or ""
            if not pattern.search(path):
                continue
            return ReactiveDecision(
                skill_name=skill.name,
                category=skill.category,
                body=skill.body,
            )
        return None


def load_reactive_router(skills_dir: Path | str) -> ReactiveRouter:
    """Load all reactive skills from a directory and return a ReactiveRouter."""
    skills: List[ReactiveSkill] = []
    p = Path(skills_dir)
    if p.exists() and p.is_dir():
        for md in sorted(p.glob("*.md")):
            try:
                skills.append(load_reactive_skill(md))
            except SkillFormatError as exc:
                _LOG.error("reactive skill %s failed to load: %s", md, exc)
                raise
    return ReactiveRouter(skills=skills)
