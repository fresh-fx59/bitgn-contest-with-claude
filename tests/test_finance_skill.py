"""Tests for the finance-lookup pre-task skill."""
from __future__ import annotations

from pathlib import Path

from bitgn_contest_agent.router import load_router

SKILLS_DIR = Path(__file__).parent.parent / "src" / "bitgn_contest_agent" / "skills"


class TestFinanceLookupSkillLoads:
    def test_skill_file_loads_without_error(self) -> None:
        router = load_router(skills_dir=SKILLS_DIR)
        body = router.skill_body_for("finance-lookup")
        assert body is not None
        assert "progressive" in body.lower() or "search" in body.lower() or "broaden" in body.lower()

    def test_skill_has_no_hardcoded_paths(self) -> None:
        router = load_router(skills_dir=SKILLS_DIR)
        body = router.skill_body_for("finance-lookup")
        assert body is not None
        assert "50_finance" not in body
        assert "purchases/" not in body
        assert "YYYY_MM_DD" not in body


class TestFinanceLookupRouting:
    def test_routes_on_charge_total_line_item(self) -> None:
        router = load_router(skills_dir=SKILLS_DIR)
        decision = router.route(
            "How much did Müller Bürobedarf charge me in total for the line item label tape refill 51 days ago?"
        )
        assert decision.skill_name == "finance-lookup"
        assert decision.category == "FINANCE_LOOKUP"

    def test_routes_on_invoice_days_ago(self) -> None:
        router = load_router(skills_dir=SKILLS_DIR)
        decision = router.route(
            "What was the total from Hörnbach Österreich for seal set 139 days ago?"
        )
        assert decision.skill_name == "finance-lookup"

    def test_does_not_route_on_unrelated_task(self) -> None:
        router = load_router(skills_dir=SKILLS_DIR)
        decision = router.route("Handle the next inbox item.")
        assert decision.skill_name != "finance-lookup"
