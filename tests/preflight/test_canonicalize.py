from bitgn_contest_agent.preflight.canonicalize import (
    normalize_name,
    score_match,
)


def test_normalize_name_strips_punctuation_and_lowercases():
    assert normalize_name("  Harbor Body!  ") == "harbor body"
    assert normalize_name("深圳市海云电子") == "深圳市海云电子"


def test_score_match_exact():
    assert score_match("Harbor Body", ["Harbor Body"]) == 1.0


def test_score_match_alias():
    assert score_match("walking buddy", ["Harbor Body", "walking buddy"]) == 1.0


def test_score_match_case_insensitive():
    assert score_match("HARBOR BODY", ["Harbor Body"]) == 1.0


def test_score_match_no_match():
    assert score_match("nonexistent", ["Harbor Body"]) == 0.0
