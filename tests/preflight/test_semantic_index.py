from pathlib import Path

from bitgn_contest_agent.preflight.semantic_index import extract_cast_entries


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
