"""Round-trip tests for the NextStep Union (§5.2 Test 2)."""
from __future__ import annotations

import pytest

from bitgn_contest_agent import schemas


def test_module_imports():
    assert hasattr(schemas, "NextStep")
    assert hasattr(schemas, "ReportTaskCompletion")
