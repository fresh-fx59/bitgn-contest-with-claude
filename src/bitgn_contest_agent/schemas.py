"""Pydantic schemas for the planner tool surface.

Single source of truth: the NextStep Union mirrors the PcmRuntime RPC
surface exactly. The coverage test in tests/test_tool_coverage.py keeps
this correspondence mechanical.
"""
from __future__ import annotations

from typing import Annotated, List, Literal, Union

from pydantic import BaseModel, Field
from pydantic.types import StringConstraints

NonEmptyStr = Annotated[str, StringConstraints(min_length=1)]


class Req_Read(BaseModel):
    tool: Literal["read"]
    path: NonEmptyStr


class Req_Write(BaseModel):
    tool: Literal["write"]
    path: NonEmptyStr
    content: str


class Req_Delete(BaseModel):
    tool: Literal["delete"]
    path: NonEmptyStr


class Req_MkDir(BaseModel):
    tool: Literal["mkdir"]
    path: NonEmptyStr


class Req_Move(BaseModel):
    tool: Literal["move"]
    from_name: NonEmptyStr
    to_name: NonEmptyStr


class Req_List(BaseModel):
    tool: Literal["list"]
    name: NonEmptyStr


class Req_Tree(BaseModel):
    tool: Literal["tree"]
    root: NonEmptyStr


class Req_Find(BaseModel):
    tool: Literal["find"]
    root: NonEmptyStr
    name: str = ""
    type: Literal["TYPE_ALL", "TYPE_FILES", "TYPE_DIRS"] = "TYPE_ALL"
    limit: int = Field(default=100, ge=1, le=10_000)


class Req_Search(BaseModel):
    tool: Literal["search"]
    root: NonEmptyStr
    pattern: NonEmptyStr
    limit: int = Field(default=100, ge=1, le=10_000)


class Req_Context(BaseModel):
    tool: Literal["context"]


class ReportTaskCompletion(BaseModel):
    tool: Literal["report_completion"]
    message: NonEmptyStr
    grounding_refs: List[str]
    rulebook_notes: NonEmptyStr
    outcome_justification: NonEmptyStr
    completed_steps_laconic: List[str]
    outcome: Literal[
        "OUTCOME_OK",
        "OUTCOME_DENIED_SECURITY",
        "OUTCOME_NONE_CLARIFICATION",
        "OUTCOME_NONE_UNSUPPORTED",
        "OUTCOME_ERR_INTERNAL",
    ]


FunctionUnion = Union[
    Req_Tree,
    Req_Find,
    Req_Search,
    Req_List,
    Req_Read,
    Req_Write,
    Req_Delete,
    Req_MkDir,
    Req_Move,
    Req_Context,
    ReportTaskCompletion,
]


class NextStep(BaseModel):
    current_state: NonEmptyStr
    plan_remaining_steps_brief: Annotated[List[str], Field(min_length=1, max_length=5)]
    identity_verified: bool
    observation: NonEmptyStr
    outcome_leaning: Literal[
        "GATHERING_INFORMATION",
        "OUTCOME_OK",
        "OUTCOME_DENIED_SECURITY",
        "OUTCOME_NONE_CLARIFICATION",
        "OUTCOME_NONE_UNSUPPORTED",
    ]
    function: FunctionUnion = Field(..., discriminator="tool")


# Convenience: the set of all Req_* model classes, in canonical order.
REQ_MODELS: tuple[type[BaseModel], ...] = (
    Req_Read,
    Req_Write,
    Req_Delete,
    Req_MkDir,
    Req_Move,
    Req_List,
    Req_Tree,
    Req_Find,
    Req_Search,
    Req_Context,
)
