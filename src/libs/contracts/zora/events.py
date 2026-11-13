"""What Zora's function answers (plan/2026-11-06e §4.10; plan/2026-11-13 §3.4, §3.10).

A TURN is the director chat's `contracts.director.TurnPayload` and streams server-sent events:

    status {text} · plan {shots, total_s, revision} · delta {text} · message {…} · done {message_id, lane} · error
    {message}, as the classic chat, plus Nova's:
    ops {changes, refused, undelivered, nothing_changed, staged, mended, stale}   the ledger (nothing_changed explicit)
    gate {problems, overruns, seams}                                             warnings under the panel header
    proposals {options}                                                          variants a person can "Use"
    confirm {ops, made_on, reasons, lines, state, fix}                           a change that waits for Accept/Reject

An ACTION is plain JSON in and out: Accept or Reject a card, use a proposal, undo, redo, a lock or an unlock (a
person's click). The change is code, never a model; Zora's sentence after it is the `message` (stored in the thread).

Pure standard library + pydantic (the `contracts` rule).
"""
from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

EVENTS: tuple[str, ...] = ("status", "plan", "delta", "ops", "gate", "proposals", "confirm", "message", "done", "error")
ActionKind = Literal["accept", "reject", "use", "undo", "redo", "lock", "unlock"]


class ZoraAction(BaseModel):
    """API → zora_chat: an action a person took in the panel. Everything here is decided by the API from trusted data
    (who, whether they may edit); `message_id`/`block`/`option` name a stored proposal, `path` a lock."""

    model_config = ConfigDict(extra="forbid")

    kind: ActionKind
    production_id: UUID
    scene_id: UUID
    actor_user_id: UUID
    actor_name: str = ""
    can_edit: bool
    thread_id: UUID | None = None
    message_id: UUID | None = None
    block: int = 0
    option: int = 0
    path: str = Field(default="", max_length=120)


class ZoraActionResult(BaseModel):
    ok: bool
    text: str  # what happened, in a sentence for the person
    revision: int = 0  # the revision this action saved (0 = none)
    ops: dict[str, Any] = Field(default_factory=dict)  # the ledger event, as a turn's
    gate: dict[str, Any] = Field(default_factory=dict)
    can_undo: bool = False
    can_redo: bool = False
    message: dict[str, Any] | None = None  # Zora's reply to the click, as stored in the thread


class Revision(BaseModel):
    """One row of `scene_plan_revisions`, as the panel lists it (the stored plan is not sent)."""

    model_config = ConfigDict(extra="ignore")

    revision: int
    kind: Literal["base", "turn", "use", "undo", "redo"]
    restores: int | None = None
    made_by: UUID | None = None
    message_id: UUID | None = None
    created_at: str = ""
