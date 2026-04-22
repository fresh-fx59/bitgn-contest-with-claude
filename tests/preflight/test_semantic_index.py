from pathlib import Path

from bitgn_contest_agent.preflight.semantic_index import extract_cast_entries
from bitgn_contest_agent.preflight.semantic_index import extract_project_entries


FIXTURE = Path(__file__).parent / "fixtures" / "semantic_index_ws"


def test_extract_cast_entries_parses_bullet_and_yaml_skips_malformed():
    entries = extract_cast_entries(FIXTURE / "10_entities" / "cast")
    # Expect exactly 2 entries (nina + elena), malformed skipped.
    aliases = sorted(e.alias for e in entries)
    assert aliases == ["elena", "nina"]

    nina = next(e for e in entries if e.alias == "nina")
    assert nina.id == "entity.nina"
    assert nina.relationship == "startup_partner"
    assert nina.summary == "Pushes Miles to narrow the product and find a real buyer."

    elena = next(e for e in entries if e.alias == "elena")
    assert elena.id == "entity.elena"
    assert elena.relationship == "day_job_ceo"
    assert elena.summary.startswith("Founder and CEO who cares")


def test_extract_project_entries_prefers_goal_field_falls_back_to_prose():
    entries = extract_project_entries(FIXTURE / "40_projects")
    aliases = sorted(e.alias for e in entries)
    assert aliases == ["black_library_evenings", "harbor_body"]

    harbor = next(e for e in entries if e.alias == "harbor_body")
    assert harbor.id == "project.harbor_body"
    assert harbor.lane == "health"
    assert harbor.status == "active"
    # `goal:` field wins over body prose.
    assert harbor.goal.startswith("Stay functional enough")

    library = next(e for e in entries if e.alias == "black_library_evenings")
    assert library.lane == "family"
    # No `goal:` field → first prose line.
    assert library.goal.startswith("Preserve a protected evening lane")
