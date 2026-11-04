"""The operations the director's agents write: one closed shape, shared by every agent that proposes edits.

The conductor, the four specialists (cinematographer, editor, sound designer, continuity) and the options writer all
answer in these operations; the kernel applies them. Every field is present and nullable, because a strict JSON
schema has no optional field: an operation fills the ones it uses and leaves the rest null. Pydantic and stdlib only.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, model_validator

OP_FIELDS = ("shot", "field", "value", "seconds", "at_block", "end_block", "link", "beat", "after_shot",
             "description", "framing", "title", "block", "kind", "speaker", "delivery")


class Op(BaseModel):
    op: Literal["set", "retime", "unlock_length", "split", "merge", "regroup", "set_join", "beat.set", "insert",
                "remove", "set_envelope", "block.set", "block.insert", "block.remove", "canon.add", "canon.remove",
                "check.waive", "check.restore", "dop_note.set"]
    shot: int | None
    field: str | None
    value: str | None
    seconds: int | None
    at_block: int | None
    end_block: int | None
    link: str | None
    beat: int | None
    after_shot: int | None
    description: str | None
    framing: str | None
    title: str | None
    block: int | None
    kind: str | None
    speaker: str | None
    delivery: str | None

    @model_validator(mode="before")
    @classmethod
    def _unused_is_null(cls, value: Any) -> Any:
        """An operation that leaves a field out is read as leaving it null, as the engine always read it. (The wire
        schema is unchanged: the model is still asked for every field.)"""
        if isinstance(value, dict):
            return {**dict.fromkeys(OP_FIELDS), **value}
        return value
