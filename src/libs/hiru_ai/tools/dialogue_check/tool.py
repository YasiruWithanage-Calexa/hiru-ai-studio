"""dialogue_check: would these operations put words in a line that the person did not write? Read-only.

The person's words are `RunContext.said` (the system fills it from the conversation); a model passes only the
operations."""
from __future__ import annotations

from typing import Any, ClassVar

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from hiru_ai.core import parts, tooling, views
from hiru_ai.core.context import RunContext


class Args(tooling.ToolArgs):
    NARROW_WITH: ClassVar[str] = "fewer `ops`"

    ops: list[views.ToolOp] = Field(min_length=1, max_length=8, description="The operations to check")


class Result(BaseModel):
    all_theirs: bool
    person_wrote_nothing: bool
    results: list[dict[str, Any]]


def unwritten(op: dict[str, Any], said: str) -> list[str]:
    """The words of the operation that are not the person's (a longer word a typo away from theirs is theirs)."""
    logic = parts.module("step", "verbatim_check", "logic")
    pool = set(logic.words(said))
    out: list[str] = []
    for field in ("value", "speaker", "delivery"):
        text = str(op.get(field) or "").strip()
        if not text or logic.flat(text) in logic.flat(said):
            continue
        out += [w for w in logic.words(text) if w not in pool and not (len(w) >= 5 and _near(w, pool))]
    return list(dict.fromkeys(out))


def _near(word: str, pool: set[str]) -> bool:
    import difflib

    return bool(difflib.get_close_matches(word, pool, n=1, cutoff=0.8))


def run(args: Args, ctx: RunContext) -> Result:
    script_ops = parts.module("step", "scene_kernel", "logic").SCRIPT_OPS
    check = parts.module("step", "verbatim_check", "step").check
    results = []
    for op in views.op_dicts(args.ops):
        if op["op"] not in script_ops:
            results.append({"op": op["op"], "dialogue": False})
            continue
        ok = check(op, ctx.said)
        bad = {"not_theirs": unwritten(op, ctx.said)} if not ok else {}
        results.append({"op": op["op"], "dialogue": True, "ok": ok, **bad})
    return Result(all_theirs=all(r.get("ok", True) for r in results), person_wrote_nothing=not ctx.said.strip(),
                  results=results)


def as_tool() -> StructuredTool:
    return tooling.from_part(__package__ or "", Args, run)
