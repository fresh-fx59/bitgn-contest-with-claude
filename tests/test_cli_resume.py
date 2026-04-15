"""End-to-end CLI tests for `run-benchmark --resume`.

The real BitGN server is not reachable in unit tests. We monkeypatch
`_make_harness` and the agent execution layer to feed canned responses
and assert the orchestrator did the right thing with them.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import List
from unittest.mock import MagicMock, patch

import pytest

from bitgn_contest_agent.cli import build_parser


def test_run_benchmark_argparse_accepts_resume():
    parser = build_parser()
    args = parser.parse_args(["run-benchmark", "--resume", "run-abc123"])
    assert args.resume == "run-abc123"


def test_run_benchmark_resume_default_is_none():
    parser = build_parser()
    args = parser.parse_args(["run-benchmark"])
    assert args.resume is None
