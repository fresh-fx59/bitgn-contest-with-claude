"""Task router — regex tier 1, classifier tier 2, UNKNOWN tier 3.

Spec §5.3. Called once per task at the top of the agent loop. On a
non-UNKNOWN hit the caller injects the matching bitgn skill body as a
`role=user` message after the task text. Never breaks the main path:
classifier failures, network errors, and malformed JSON all degrade
to UNKNOWN.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from bitgn_contest_agent import router_config
from bitgn_contest_agent.skill_loader import BitgnSkill, SkillFormatError, load_skill

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    category: str
    source: str  # "regex" | "classifier" | "unknown"
    confidence: float
    extracted: Dict[str, str] = field(default_factory=dict)
    skill_name: Optional[str] = None


_UNKNOWN = RoutingDecision(
    category="UNKNOWN",
    source="unknown",
    confidence=0.0,
    extracted={},
    skill_name=None,
)


@dataclass
class _CompiledSkill:
    skill: BitgnSkill
    patterns: List[re.Pattern]


class Router:
    def __init__(self, skills: List[BitgnSkill]) -> None:
        self._compiled: List[_CompiledSkill] = []
        self._by_category: Dict[str, BitgnSkill] = {}
        for s in skills:
            patterns = [re.compile(p) for p in s.matcher_patterns]
            self._compiled.append(_CompiledSkill(skill=s, patterns=patterns))
            self._by_category[s.category] = s

    def route(self, task_text: str) -> RoutingDecision:
        if not router_config.router_enabled():
            return _UNKNOWN
        if not task_text:
            return _UNKNOWN

        # Tier 1 — regex matchers.
        for c in self._compiled:
            for pat in c.patterns:
                m = pat.search(task_text)
                if m is None:
                    continue
                extracted: Dict[str, str] = {}
                # Named groups first; then positional groups as group_N.
                for k, v in m.groupdict().items():
                    if v is not None:
                        extracted[k] = v
                for i, g in enumerate(m.groups(), start=1):
                    if g is not None:
                        extracted.setdefault(f"group_{i}", g)
                return RoutingDecision(
                    category=c.skill.category,
                    source="regex",
                    confidence=1.0,
                    extracted=extracted,
                    skill_name=c.skill.name,
                )

        # Tier 2 — classifier LLM.
        if not self._compiled:
            return _UNKNOWN
        try:
            parsed = _call_classifier(
                task_text=task_text,
                categories=[c.skill.category for c in self._compiled],
            )
        except Exception as exc:  # noqa: BLE001 — router never breaks the main path
            _LOG.warning("classifier failed, degrading to UNKNOWN: %s", exc)
            return _UNKNOWN

        if not isinstance(parsed, dict):
            return _UNKNOWN
        category = parsed.get("category")
        confidence = parsed.get("confidence", 0.0)
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            confidence = 0.0
        extracted = parsed.get("extracted") or {}
        if not isinstance(extracted, dict):
            extracted = {}

        if not isinstance(category, str) or category not in self._by_category:
            return RoutingDecision(
                category="UNKNOWN",
                source="classifier",
                confidence=confidence,
                extracted={},
                skill_name=None,
            )

        if confidence < router_config.confidence_threshold():
            return RoutingDecision(
                category="UNKNOWN",
                source="classifier",
                confidence=confidence,
                extracted={},
                skill_name=None,
            )

        skill = self._by_category[category]
        return RoutingDecision(
            category=category,
            source="classifier",
            confidence=confidence,
            extracted={k: str(v) for k, v in extracted.items()},
            skill_name=skill.name,
        )

    def skill_body_for(self, skill_name: str) -> Optional[str]:
        for c in self._compiled:
            if c.skill.name == skill_name:
                return c.skill.body
        return None


def load_router(skills_dir: Path | str) -> Router:
    skills: List[BitgnSkill] = []
    p = Path(skills_dir)
    if p.exists() and p.is_dir():
        for md in sorted(p.glob("*.md")):
            try:
                skills.append(load_skill(md))
            except SkillFormatError as exc:
                _LOG.error("skill %s failed to load: %s", md, exc)
                raise
    return Router(skills=skills)


# Module-level singleton + legacy route() convenience wrapper.
_ROUTER_SINGLETON: Optional[Router] = None
_DEFAULT_SKILLS_DIR = (
    Path(__file__).parent / "skills"
)


def _get_default_router() -> Router:
    global _ROUTER_SINGLETON
    if _ROUTER_SINGLETON is None:
        _ROUTER_SINGLETON = load_router(_DEFAULT_SKILLS_DIR)
    return _ROUTER_SINGLETON


def route(task_text: str) -> RoutingDecision:
    return _get_default_router().route(task_text)


def _call_classifier(*, task_text: str, categories: List[str]) -> Any:
    """Tier 2 — single call to a small GPT model via cliproxyapi.

    Returns the parsed dict on success. Any failure raises; the caller
    (`Router.route`) degrades to UNKNOWN on raised exceptions.
    """
    import json as _json
    client = _get_openai_client()
    category_list = "\n".join(f"- {c}" for c in categories) + "\n- UNKNOWN (none of the above apply confidently)"
    system = (
        "You classify bitgn benchmark tasks into one of these categories:\n"
        f"{category_list}\n"
        "\n"
        "Return ONLY a JSON object of the form:\n"
        "  {\"category\": \"<one of above>\", \"confidence\": <0.0-1.0>, "
        "\"extracted\": {\"target_name\": \"<optional>\"}}\n"
        "No prose. No markdown fences."
    )
    resp = client.chat.completions.create(
        model=router_config.classifier_model(),
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": task_text},
        ],
        response_format={"type": "json_object"},
        temperature=0.0,
        timeout=10.0,
    )
    content = resp.choices[0].message.content
    return _json.loads(content)


def _get_openai_client():  # pragma: no cover — thin factory, tested via patching
    import os
    from openai import OpenAI
    return OpenAI(
        base_url=os.environ.get("OPENAI_BASE_URL"),
        api_key=os.environ.get("OPENAI_API_KEY", "sk-proxy"),
    )
