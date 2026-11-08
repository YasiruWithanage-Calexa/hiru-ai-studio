"""sable_think_harder: the model's way to ask for the deep tier (plan/2026-11-08 §4.4 step 2). It changes no data.

The tool itself only answers "ok". The `tiering` middleware (core/middleware/tiering.py) sees the call and runs every
later model call of the turn on the deep tier, which continues the same thread with every tool result already read.
"""
from __future__ import annotations

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from hiru_ai.core import tooling
from hiru_ai.core.context import RunContext


class Args(BaseModel):
    reason: str = Field(min_length=3, max_length=200, description="One sentence: why this needs more thought")


class Result(BaseModel):
    ok: bool
    next: str


def run(args: Args, ctx: RunContext) -> Result:
    return Result(ok=True, next="Continuing more carefully, with everything already read. Do not call this again.")


def as_tool() -> StructuredTool:
    return tooling.from_part(__package__ or "", Args, run)
