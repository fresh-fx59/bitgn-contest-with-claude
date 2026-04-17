"""preflight_project tests — FS-based and PCM-mocked.

Covers DEV layout (flat `.md`) and PROD layout (`<slug>/README.MD`).
"""
from pathlib import Path
from unittest.mock import MagicMock

from bitgn_contest_agent.preflight.project import (
    _disambiguate_via_llm,
    run_preflight_project,
    run_project_from_fs,
)
from bitgn_contest_agent.schemas import Req_PreflightProject


FIXTURE = Path(__file__).parent / "fixtures" / "tiny_ws"


def test_fs_project_resolves_name():
    out = run_project_from_fs(
        root=FIXTURE,
        projects_root="30_projects",
        entities_root="20_entities",
        query="Health Baseline",
    )
    assert out["project"] is not None
    assert out["project"]["name"] == "Health Baseline"


def test_fs_project_returns_start_date():
    out = run_project_from_fs(
        root=FIXTURE,
        projects_root="30_projects",
        entities_root="20_entities",
        query="Health Baseline",
    )
    assert out["project"]["start_date"] == "2025-11-14"


def test_fs_no_match_returns_none():
    out = run_project_from_fs(
        root=FIXTURE,
        projects_root="30_projects",
        entities_root="20_entities",
        query="Nonexistent Project",
    )
    assert out["project"] is None


# -- PCM-backed tests (the function used in prod) -----------------------


def _mk_runtime_for_prod_layout():
    """Simulate PROD layout: <projects_root>/<slug>/README.MD with
    bullet-list metadata."""
    runtime = MagicMock()
    slug_entry = MagicMock(is_dir=True)
    slug_entry.name = "studio_parts_library"  # attribute, not ctor arg
    runtime.list.return_value = MagicMock(entries=[slug_entry])

    def _read(req):
        if req.path == "40_projects/studio_parts_library/README.MD":
            return MagicMock(content=(
                "# Studio Parts Library\n"
                "\n"
                "- record_type: project\n"
                "- project: Studio Parts Library\n"
                "- start_date: 2026-04-21\n"
                "- members: alice, bob\n"
            ))
        if req.path == "40_projects/studio_parts_library/README.md":
            raise FileNotFoundError(req.path)
        return MagicMock(content="")

    runtime.read.side_effect = _read
    return runtime


def _summary_line(envelope: str) -> str:
    """Extract the summary field from a build_response envelope."""
    import json
    return json.loads(envelope)["summary"]


def test_pcm_prod_layout_returns_match_with_refs():
    runtime = _mk_runtime_for_prod_layout()
    req = Req_PreflightProject(
        tool="preflight_project",
        projects_root="40_projects",
        entities_root="20_entities",
        query="Studio Parts Library",
    )
    result = run_preflight_project(runtime, req)
    assert result.ok is True
    assert result.refs == ("40_projects/studio_parts_library/README.MD",)
    # Summary must cite the file, not leak the start_date.
    assert "Studio Parts Library" in result.content
    assert "40_projects/studio_parts_library/README.MD" in result.content
    assert "2026-04-21" not in _summary_line(result.content)


def test_pcm_prod_layout_no_match_returns_empty_refs():
    runtime = _mk_runtime_for_prod_layout()
    req = Req_PreflightProject(
        tool="preflight_project",
        projects_root="40_projects",
        entities_root="20_entities",
        query="Nothing Here",
    )
    result = run_preflight_project(runtime, req)
    assert result.ok is True
    assert result.refs == ()
    assert "no project match" in _summary_line(result.content).lower()


def test_pcm_dev_layout_flat_md_still_works():
    """DEV layout: flat <projects_root>/*.md. Must still match."""
    runtime = MagicMock()
    flat_entry = MagicMock(is_dir=False)
    flat_entry.name = "health.md"
    runtime.list.return_value = MagicMock(entries=[flat_entry])
    runtime.read.return_value = MagicMock(content=(
        "---\n"
        "project: Health Baseline\n"
        "start_date: 2025-11-14\n"
        "---\n"
    ))
    req = Req_PreflightProject(
        tool="preflight_project",
        projects_root="30_projects",
        entities_root="20_entities",
        query="Health Baseline",
    )
    result = run_preflight_project(runtime, req)
    assert result.ok is True
    assert result.refs == ("30_projects/health.md",)


def test_pcm_prod_layout_no_record_type_matches_by_heading_and_slug():
    """Real PROD shape — README.MD has `# Heading`, bullet-list with
    `alias` + `owner_id` but NO `project:` or `record_type:` or
    `start_date:`. Must still match by heading/slug and derive start
    date from the slug prefix.
    """
    runtime = MagicMock()
    slug_entry = MagicMock(is_dir=True)
    slug_entry.name = "2026_04_21_studio_parts_library"
    runtime.list.return_value = MagicMock(entries=[slug_entry])

    def _read(req):
        if req.path == "40_projects/2026_04_21_studio_parts_library/README.MD":
            return MagicMock(content=(
                "# Studio Parts Library\n"
                "\n"
                "- alias: `studio_parts_library`\n"
                "- owner_id: `entity.miles`\n"
                "- kind: `home_systems`\n"
                "- status: `active`\n"
                "- goal: Keep printed parts organized.\n"
            ))
        raise FileNotFoundError(req.path)

    runtime.read.side_effect = _read
    req = Req_PreflightProject(
        tool="preflight_project",
        projects_root="40_projects",
        entities_root="10_entities",
        query="Studio Parts Library",
    )
    result = run_preflight_project(runtime, req)
    assert result.ok is True
    assert result.refs == (
        "40_projects/2026_04_21_studio_parts_library/README.MD",
    )
    # Summary cites the file; must not leak the start_date value.
    summary = _summary_line(result.content)
    assert "2026-04-21" not in summary
    assert "40_projects/2026_04_21_studio_parts_library/README.MD" in summary
    # Data payload derives start_date from slug prefix.
    import json
    payload = json.loads(result.content)["data"]
    assert payload["project"]["start_date"] == "2026-04-21"


# -- LLM disambiguation tests -----------------------------------------


def test_pcm_llm_disambiguation_fallback():
    """When no exact match exists, Phase 3 LLM fallback should pick the
    correct project from the candidate list."""
    from unittest.mock import patch

    runtime = MagicMock()
    # Two project subdirs — neither matches "sci-fi reading lane" exactly.
    slug_a = MagicMock(is_dir=True)
    slug_a.name = "2026_04_27_reading_spine"
    slug_b = MagicMock(is_dir=True)
    slug_b.name = "2026_04_25_black_library_evenings"
    runtime.list.return_value = MagicMock(entries=[slug_a, slug_b])

    def _read(req):
        if "reading_spine" in req.path and "README.MD" in req.path:
            return MagicMock(content="# Reading Spine\n\n- alias: `reading_spine`\n")
        if "black_library" in req.path and "README.MD" in req.path:
            return MagicMock(content="# Black Library Evenings\n\n- alias: `black_library_evenings`\n")
        raise FileNotFoundError(req.path)

    runtime.read.side_effect = _read

    # Mock the LLM disambiguator to return "Reading Spine".
    with patch(
        "bitgn_contest_agent.preflight.project._disambiguate_via_llm",
        return_value="Reading Spine",
    ) as mock_disamb:
        req = Req_PreflightProject(
            tool="preflight_project",
            projects_root="40_projects",
            entities_root="10_entities",
            query="sci-fi reading lane",
        )
        result = run_preflight_project(runtime, req)

    assert result.ok is True
    assert result.refs == ("40_projects/2026_04_27_reading_spine/README.MD",)
    mock_disamb.assert_called_once()
    # The candidates list should contain both project names.
    call_args = mock_disamb.call_args
    assert "sci-fi reading lane" in call_args[0][0]  # query
    assert "Reading Spine" in call_args[0][1]  # candidates
    assert "Black Library Evenings" in call_args[0][1]


def test_pcm_llm_disambiguation_returns_none_on_failure():
    """When LLM disambiguation returns None, result should be no-match."""
    from unittest.mock import patch

    runtime = MagicMock()
    slug_a = MagicMock(is_dir=True)
    slug_a.name = "2026_04_27_reading_spine"
    runtime.list.return_value = MagicMock(entries=[slug_a])

    def _read(req):
        if "README.MD" in req.path:
            return MagicMock(content="# Reading Spine\n")
        raise FileNotFoundError(req.path)

    runtime.read.side_effect = _read

    with patch(
        "bitgn_contest_agent.preflight.project._disambiguate_via_llm",
        return_value=None,
    ):
        req = Req_PreflightProject(
            tool="preflight_project",
            projects_root="40_projects",
            entities_root="10_entities",
            query="totally unknown project",
        )
        result = run_preflight_project(runtime, req)

    assert result.ok is True
    assert result.refs == ()
    assert "no project match" in _summary_line(result.content).lower()


def test_disambiguate_via_llm_returns_match():
    """_disambiguate_via_llm returns the LLM's chosen candidate."""
    from unittest.mock import patch

    stub = {"match": "Reading Spine", "confidence": 0.92}
    with patch("bitgn_contest_agent.classifier.classify", return_value=stub):
        result = _disambiguate_via_llm(
            "sci-fi reading lane",
            ["Reading Spine", "Black Library Evenings", "Harbor Body"],
        )
    assert result == "Reading Spine"


def test_disambiguate_via_llm_returns_none_on_low_confidence():
    from unittest.mock import patch

    stub = {"match": "Reading Spine", "confidence": 0.3}
    with patch("bitgn_contest_agent.classifier.classify", return_value=stub):
        result = _disambiguate_via_llm(
            "totally unrelated",
            ["Reading Spine", "Black Library Evenings"],
        )
    assert result is None


def test_disambiguate_via_llm_returns_none_on_exception():
    from unittest.mock import patch

    with patch(
        "bitgn_contest_agent.classifier.classify",
        side_effect=RuntimeError("network"),
    ):
        result = _disambiguate_via_llm(
            "some query",
            ["Proj A", "Proj B"],
        )
    assert result is None


def test_disambiguate_via_llm_returns_none_on_hallucinated_name():
    """If the LLM returns a name not in the candidate list, return None."""
    from unittest.mock import patch

    stub = {"match": "Nonexistent Project", "confidence": 0.95}
    with patch("bitgn_contest_agent.classifier.classify", return_value=stub):
        result = _disambiguate_via_llm(
            "query",
            ["Proj A", "Proj B"],
        )
    assert result is None


def test_pcm_exact_match_skips_llm_disambiguation():
    """When an exact match exists, LLM disambiguation should NOT be called."""
    from unittest.mock import patch

    runtime = _mk_runtime_for_prod_layout()

    with patch(
        "bitgn_contest_agent.preflight.project._disambiguate_via_llm",
    ) as mock_disamb:
        req = Req_PreflightProject(
            tool="preflight_project",
            projects_root="40_projects",
            entities_root="20_entities",
            query="Studio Parts Library",
        )
        result = run_preflight_project(runtime, req)

    assert result.ok is True
    assert result.refs == ("40_projects/studio_parts_library/README.MD",)
    mock_disamb.assert_not_called()
