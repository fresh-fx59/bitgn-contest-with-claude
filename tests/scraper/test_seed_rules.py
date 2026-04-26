"""score_detail string parsing tests.

Fixture strings copied verbatim from real PROD logs:
  - cf90740 22LAfu4 t000 outcome trace
  - cf90740 22LAfu4 t066 outcome trace
  - vm-03owny32f4y68f9cda.eu.bitgn.com.txt server log
"""
from __future__ import annotations

from bitgn_scraper.seed_rules import ExtractedRule, extract_rules


def test_extracts_expected_answer() -> None:
    rules = extract_rules("answer is incorrect. Expected: '1989-02-16'")
    assert rules == [ExtractedRule(rule_kind="expected_answer", rule_value="1989-02-16")]


def test_extracts_required_write() -> None:
    rules = extract_rules(
        "missing file write '50_finance/purchases/2026_01_31__eur_000050__bill__hearthline_sensor_bundle.md'"
    )
    assert rules == [ExtractedRule(
        rule_kind="required_write",
        rule_value="50_finance/purchases/2026_01_31__eur_000050__bill__hearthline_sensor_bundle.md",
    )]


def test_extracts_required_ref() -> None:
    rules = extract_rules(
        "answer missing required reference '20_projects/cabin/plan.md'"
    )
    assert rules == [ExtractedRule(
        rule_kind="required_ref",
        rule_value="20_projects/cabin/plan.md",
    )]


def test_extracts_expected_outcome() -> None:
    rules = extract_rules(
        "expected outcome OUTCOME_OK, got OUTCOME_NONE_CLARIFICATION"
    )
    assert rules == [ExtractedRule(
        rule_kind="expected_outcome",
        rule_value="OUTCOME_OK",
    )]


def test_extracts_multiple_rules_from_one_string() -> None:
    """t066 had concatenated missing-write strings in one detail entry."""
    rules = extract_rules(
        "missing file write '50_finance/purchases/A.md' / "
        "missing file write '50_finance/purchases/B.md'"
    )
    assert ExtractedRule(rule_kind="required_write", rule_value="50_finance/purchases/A.md") in rules
    assert ExtractedRule(rule_kind="required_write", rule_value="50_finance/purchases/B.md") in rules
    assert len(rules) == 2


def test_returns_empty_for_unrecognized_string() -> None:
    rules = extract_rules("the agent panicked")
    assert rules == []


def test_handles_double_quotes_variant() -> None:
    """Some log lines use double quotes instead of single."""
    rules = extract_rules('answer is incorrect. Expected: "1989-02-16"')
    assert rules == [ExtractedRule(rule_kind="expected_answer", rule_value="1989-02-16")]
