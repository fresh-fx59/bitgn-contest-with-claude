from pathlib import Path

from bitgn_contest_agent.preflight.project import run_project_from_fs


FIXTURE = Path(__file__).parent / "fixtures" / "tiny_ws"


def test_project_resolves_name_to_record():
    out = run_project_from_fs(
        root=FIXTURE,
        projects_root="30_projects",
        entities_root="20_entities",
        query="Health Baseline",
    )
    assert out["project"] is not None
    assert out["project"]["name"] == "Health Baseline"


def test_project_returns_start_date():
    out = run_project_from_fs(
        root=FIXTURE,
        projects_root="30_projects",
        entities_root="20_entities",
        query="Health Baseline",
    )
    assert out["project"]["start_date"] == "2025-11-14"


def test_project_no_match_returns_none():
    out = run_project_from_fs(
        root=FIXTURE,
        projects_root="30_projects",
        entities_root="20_entities",
        query="Nonexistent Project",
    )
    assert out["project"] is None
