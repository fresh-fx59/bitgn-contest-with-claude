"""Unit tests for the shared classifier module."""
from __future__ import annotations

import pytest

from bitgn_contest_agent.classifier import _strip_markdown_fences, parse_response


class TestStripMarkdownFences:
    def test_strips_json_fences(self) -> None:
        text = '```json\n{"category": "X", "confidence": 0.9}\n```'
        assert _strip_markdown_fences(text) == '{"category": "X", "confidence": 0.9}'

    def test_strips_bare_fences(self) -> None:
        text = '```\n{"category": "X"}\n```'
        assert _strip_markdown_fences(text) == '{"category": "X"}'

    def test_passthrough_plain_json(self) -> None:
        text = '{"category": "X", "confidence": 0.9}'
        assert _strip_markdown_fences(text) == '{"category": "X", "confidence": 0.9}'

    def test_strips_whitespace(self) -> None:
        text = '  {"category": "X"}  '
        assert _strip_markdown_fences(text) == '{"category": "X"}'


class TestParseResponse:
    def test_valid_response(self) -> None:
        cat, conf = parse_response(
            {"category": "FOO", "confidence": 0.85},
            valid_categories={"FOO", "BAR"},
        )
        assert cat == "FOO"
        assert conf == 0.85

    def test_unknown_category(self) -> None:
        cat, conf = parse_response(
            {"category": "NOPE", "confidence": 0.9},
            valid_categories={"FOO"},
        )
        assert cat is None
        assert conf == 0.9

    def test_non_dict_returns_none(self) -> None:
        cat, conf = parse_response("not a dict", valid_categories={"FOO"})
        assert cat is None
        assert conf == 0.0

    def test_missing_confidence_defaults_zero(self) -> None:
        cat, conf = parse_response(
            {"category": "FOO"},
            valid_categories={"FOO"},
        )
        assert cat == "FOO"
        assert conf == 0.0
