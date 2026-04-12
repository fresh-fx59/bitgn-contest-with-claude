"""Tests for ReactiveSkill loader and ReactiveRouter."""
from __future__ import annotations

from pathlib import Path

import pytest

from bitgn_contest_agent.reactive_router import (
    ReactiveDecision,
    ReactiveRouter,
    ReactiveSkill,
    load_reactive_router,
    load_reactive_skill,
)
from bitgn_contest_agent.skill_loader import SkillFormatError

FIX = Path(__file__).parent / "fixtures" / "reactive_skills"


# -- Loader tests ----------------------------------------------------------

class TestLoadReactiveSkill:
    def test_loads_valid_reactive_skill(self) -> None:
        skill = load_reactive_skill(FIX / "test_reactive.md")
        assert skill.name == "test-reactive-read"
        assert skill.category == "TEST_INBOX"
        assert skill.reactive_tool == "read"
        assert skill.reactive_path == "(?i)test-inbox"
        assert skill.type == "rigid"
        assert "Test Reactive Skill" in skill.body

    def test_rejects_missing_reactive_tool(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.md"
        p.write_text(
            "---\nname: x\ndescription: x\ntype: rigid\n"
            "category: X\nreactive_path: foo\n---\nbody\n"
        )
        with pytest.raises(SkillFormatError, match="reactive_tool"):
            load_reactive_skill(p)

    def test_rejects_missing_reactive_path(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.md"
        p.write_text(
            "---\nname: x\ndescription: x\ntype: rigid\n"
            "category: X\nreactive_tool: read\n---\nbody\n"
        )
        with pytest.raises(SkillFormatError, match="reactive_path"):
            load_reactive_skill(p)

    def test_rejects_invalid_type(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.md"
        p.write_text(
            "---\nname: x\ndescription: x\ntype: banana\n"
            "category: X\nreactive_tool: read\nreactive_path: foo\n---\nbody\n"
        )
        with pytest.raises(SkillFormatError, match="type"):
            load_reactive_skill(p)


class TestLoadReactiveRouter:
    def test_loads_from_directory(self) -> None:
        router = load_reactive_router(FIX)
        assert len(router._skills) == 1

    def test_empty_dir_returns_empty_router(self, tmp_path: Path) -> None:
        router = load_reactive_router(tmp_path)
        assert len(router._skills) == 0

    def test_nonexistent_dir_returns_empty_router(self) -> None:
        router = load_reactive_router(Path("/nonexistent"))
        assert len(router._skills) == 0


# -- Router evaluate tests -------------------------------------------------

class TestReactiveRouterEvaluate:
    def _make_router(self) -> ReactiveRouter:
        return load_reactive_router(FIX)

    def test_matches_on_tool_and_path(self) -> None:
        router = self._make_router()
        decision = router.evaluate(
            tool_name="read",
            tool_args={"tool": "read", "path": "/sandbox/test-inbox/msg1.md"},
            tool_result_text="Hello world",
            already_injected=frozenset(),
        )
        assert decision is not None
        assert decision.skill_name == "test-reactive-read"
        assert decision.category == "TEST_INBOX"
        assert "Test Reactive Skill" in decision.body

    def test_no_match_wrong_tool(self) -> None:
        router = self._make_router()
        decision = router.evaluate(
            tool_name="write",
            tool_args={"tool": "write", "path": "/sandbox/test-inbox/msg1.md"},
            tool_result_text="ok",
            already_injected=frozenset(),
        )
        assert decision is None

    def test_no_match_wrong_path(self) -> None:
        router = self._make_router()
        decision = router.evaluate(
            tool_name="read",
            tool_args={"tool": "read", "path": "/sandbox/documents/report.md"},
            tool_result_text="Hello",
            already_injected=frozenset(),
        )
        assert decision is None

    def test_inject_once_skips_already_injected(self) -> None:
        router = self._make_router()
        decision = router.evaluate(
            tool_name="read",
            tool_args={"tool": "read", "path": "/sandbox/test-inbox/msg1.md"},
            tool_result_text="Hello",
            already_injected=frozenset({"test-reactive-read"}),
        )
        assert decision is None

    def test_empty_router_returns_none(self) -> None:
        router = ReactiveRouter(skills=[])
        decision = router.evaluate(
            tool_name="read",
            tool_args={"tool": "read", "path": "/sandbox/test-inbox/msg1.md"},
            tool_result_text="Hello",
            already_injected=frozenset(),
        )
        assert decision is None

    def test_path_regex_is_case_insensitive_per_pattern(self) -> None:
        router = self._make_router()
        decision = router.evaluate(
            tool_name="read",
            tool_args={"tool": "read", "path": "/sandbox/TEST-INBOX/msg1.md"},
            tool_result_text="Hello",
            already_injected=frozenset(),
        )
        assert decision is not None
