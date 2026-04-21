"""Pre-completion verification trigger (v1, 3 reasons).

Spec: docs/superpowers/specs/2026-04-21-preflight-trim-verify-design.md

Fires before report_completion is accepted, at most once per task.
All reason detection is deterministic — no LLM calls in this module.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from bitgn_contest_agent.schemas import NextStep, ReportTaskCompletion


class AnswerShape(str, Enum):
    NUMERIC = "NUMERIC"
    DATE = "DATE"
    PATH_LIST = "PATH_LIST"
    MESSAGE_QUOTE = "MESSAGE_QUOTE"
    ACTION_CONFIRMATION = "ACTION_CONFIRMATION"
    NONE_CLARIFICATION = "NONE_CLARIFICATION"
    FREEFORM = "FREEFORM"


class VerifyReason(str, Enum):
    MISSING_REF = "MISSING_REF"
    NUMERIC_MULTIREF = "NUMERIC_MULTIREF"
    INBOX_GIVEUP = "INBOX_GIVEUP"


@dataclass(frozen=True)
class WriteOp:
    """Record of a single write/delete/move the agent performed."""
    op: str           # "write" | "delete" | "move"
    path: str
    step: int
    content: Optional[str] = None  # None for delete/move


_NUMERIC_RE = re.compile(r"^-?\d+(\.\d+)?$")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DMY_RE = re.compile(r"^\d{2}[-/]\d{2}[-/]\d{4}$")
_MDY_RE = re.compile(r"^\d{2}/\d{2}/\d{4}$")

_TASK_NUMBER_ONLY_RE = re.compile(
    r"(?i)\b(answer\s+with\s+(a|the)?\s*number|number\s+only|numeric\s+only)\b"
)
_TASK_DATE_ONLY_RE = re.compile(
    r"(?i)\b(date\s+only|answer\s+(with|in)\s+(a|the)?\s*date|yyyy-mm-dd|date\s+format)\b"
)


def classify_answer_shape(next_step: NextStep, task_text: str) -> AnswerShape:
    """Deterministically classify the answer shape of a completion.

    Precedence:
      1. NONE_CLARIFICATION — outcome says so
      2. NUMERIC — answer matches numeric regex OR task demands a number
      3. DATE — answer matches a date regex OR task demands a date
      4. FREEFORM — otherwise
    """
    fn = next_step.function
    if not isinstance(fn, ReportTaskCompletion):
        return AnswerShape.FREEFORM
    if fn.outcome == "OUTCOME_NONE_CLARIFICATION":
        return AnswerShape.NONE_CLARIFICATION
    answer = (fn.message or "").strip()
    task = task_text or ""
    if _NUMERIC_RE.match(answer) or _TASK_NUMBER_ONLY_RE.search(task):
        return AnswerShape.NUMERIC
    if (_ISO_DATE_RE.match(answer) or _DMY_RE.match(answer)
            or _MDY_RE.match(answer) or _TASK_DATE_ONLY_RE.search(task)):
        return AnswerShape.DATE
    return AnswerShape.FREEFORM


# should_verify and build_verification_message are added in C2/C3.
def should_verify(*args, **kwargs):
    """Placeholder until C2 introduces the real trigger logic."""
    return []


def build_verification_message(*args, **kwargs):
    """Placeholder until C2 introduces the real message builder."""
    raise NotImplementedError
