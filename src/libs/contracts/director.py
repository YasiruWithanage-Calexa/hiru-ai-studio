"""The Director panel (screen 2d): personas, the production's director board, chat threads and
the streamed turn (PLAN.md §6, §10).

A turn is synchronous and streamed: the API proxies the browser's request to the
`director_chat` function and pipes its server-sent events back. The function reads the scene,
lets the model propose OPERATIONS on the shot plan, applies them in code (`ScenePlanKernel`),
re-times the scene with `contracts.shotplan`, stores the result and the messages, and streams:

    status   {"text"}                      what the director is doing ("Reading the scene")
    delta    {"text"}                      reply text as it is written
    plan     {"shots": [...], "issues"}    the scene's shots after this turn's edits
    message  ChatMessage                   the stored director message
    done     {"message_id", "lane"}       lane: chat | edit | craft | reshape (offered, not applied)
    error    {"message"}                   a sentence for the user, never an exception's text

No prices anywhere: personas are a library, not a shop (CLAUDE.md: the UI shows no costs).
"""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from contracts.production import BlockKind, Framing
from contracts.veo import CameraLink, SoundMode


class Seat(StrEnum):
    LEAD = "lead"
    ADVISOR = "advisor"


MAX_ADVISORS = 3


class PersonaTrait(BaseModel):
    label: Literal["Realism", "Tone", "Pacing", "Audience"]
    value: int = Field(ge=0, le=100)


class Persona(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID
    slug: str
    name: str
    initials: str
    color: str  # avatar background, hex
    specialty: str
    traits: list[PersonaTrait] = Field(default_factory=list)
    style_note: str = ""


class BoardSeat(BaseModel):
    model_config = ConfigDict(extra="forbid")

    persona_id: UUID
    seat: Seat


class BoardUpdate(BaseModel):
    """The whole board at once: exactly one lead, at most three advisors, no persona twice."""

    model_config = ConfigDict(extra="forbid")

    seats: list[BoardSeat] = Field(min_length=1, max_length=1 + MAX_ADVISORS)

    @model_validator(mode="after")
    def _shape(self) -> BoardUpdate:
        if sum(1 for s in self.seats if s.seat is Seat.LEAD) != 1:
            raise ValueError("a board has exactly one lead")
        if len({s.persona_id for s in self.seats}) != len(self.seats):
            raise ValueError("a persona can hold one seat")
        return self


class BoardMember(BaseModel):
    persona: Persona
    seat: Seat


# ── messages ───────────────────────────────────────────────────────────────────────────────


class TextBlock(BaseModel):
    kind: Literal["text"] = "text"
    text: str


class Position(BaseModel):
    who: str
    text: str


class DisagreementBlock(BaseModel):
    """Two board members disagree; the lead's view landed, the other is shown, not lost."""

    kind: Literal["disagreement"] = "disagreement"
    title: str
    positions: list[Position]
    actions: list[str] = Field(default_factory=list)


class EditNoteBlock(BaseModel):
    kind: Literal["edit-note"] = "edit-note"
    count: int
    text: str


class ContinuityBlock(BaseModel):
    kind: Literal["continuity"] = "continuity"
    text: str


DirectorBlock = Annotated[TextBlock | DisagreementBlock | EditNoteBlock | ContinuityBlock,
                          Field(discriminator="kind")]


class MessageKind(StrEnum):
    USER = "user"
    DIRECTOR = "director"


class Citation(BaseModel):
    """Where a fact in the reply came from: a document passage or production memory."""

    chunk_id: UUID | None = None
    label: str = ""


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID
    thread_id: UUID
    kind: MessageKind
    author_user_id: UUID | None = None
    speaker: str = ""  # the persona's name for director messages, the person's for user ones
    tone: Literal["lead", "board"] | None = None
    text: str = ""  # a user message
    blocks: list[DirectorBlock] = Field(default_factory=list)
    ops: list[dict[str, Any]] = Field(default_factory=list)  # what the turn applied
    citations: list[Citation] = Field(default_factory=list)
    created_at: datetime


class ChatThread(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID
    production_id: UUID
    scene_id: UUID | None
    title: str
    created_at: datetime
    updated_at: datetime


class TurnRequest(BaseModel):
    """Browser → API."""

    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=4000)
    thread_id: UUID | None = None  # None: the scene's main thread (created on first use)


# `accepted` is the API's own first frame: {thread_id, message} (the stored user message).
TURN_EVENTS = ("accepted", "status", "delta", "plan", "message", "done", "error")


# ── the scene, edited by people (screen 2d) ────────────────────────────────────────────────


class ShotUpdate(BaseModel):
    """A person's change to one shot. Only the fields sent change. The scene is re-timed by
    `contracts.shotplan` afterwards: a length a person sets is LOCKED (kept, and what overruns
    is reported); `duration_s: null` releases it back to the planner."""

    model_config = ConfigDict(extra="forbid")

    duration_s: int | None = None
    sound_mode: SoundMode | None = None
    framing: Framing | None = None
    camera_link: CameraLink | None = None
    title: str | None = Field(default=None, max_length=200)


class ScriptBlockEdit(BaseModel):
    """One block of the edited script. Dialogue carries its spoken text here; `line_id` names
    the existing line it edits (kept, so its shot stays bound), or is null for a new line."""

    model_config = ConfigDict(extra="forbid")

    kind: BlockKind
    text: str = Field(default="", max_length=2000)
    speaker: str = Field(default="", max_length=120)
    delivery: str = Field(default="", max_length=200)
    line_id: UUID | None = None

    @model_validator(mode="after")
    def _dialogue(self) -> ScriptBlockEdit:
        if self.kind is BlockKind.DIALOGUE:
            if not self.speaker.strip() or not self.text.strip():
                raise ValueError("a dialogue block needs a speaker and a line")
        elif self.line_id is not None or self.speaker:
            raise ValueError("only dialogue blocks have a speaker or a line id")
        return self


class ScriptUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    blocks: list[ScriptBlockEdit] = Field(max_length=600)
    # The version the edit was made against; a scene edited meanwhile answers 409.
    script_version: int = Field(ge=1)

    @model_validator(mode="after")
    def _unique_lines(self) -> ScriptUpdate:
        ids = [b.line_id for b in self.blocks if b.line_id is not None]
        if len(ids) != len(set(ids)):
            raise ValueError("a line can appear once in the script")
        return self


class MemoryKind(StrEnum):
    DECISION = "decision"
    NOTE = "note"
    ANSWER = "answer"  # a live-build question a person answered


class MemoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["decision", "note"] = "note"
    text: str = Field(min_length=1, max_length=2000)
    scene_id: UUID | None = None


class MemoryItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID
    production_id: UUID
    scene_id: UUID | None = None
    kind: MemoryKind
    text: str
    source_ref: dict[str, Any] = Field(default_factory=dict)
    created_by: UUID | None = None
    created_at: datetime


class TurnPayload(BaseModel):
    """API → director_chat. Everything the function may not decide for itself is decided here
    from trusted data: who is asking, whether they may edit, which scene, which thread."""

    model_config = ConfigDict(extra="forbid")

    production_id: UUID
    scene_id: UUID
    thread_id: UUID
    actor_user_id: UUID
    actor_name: str
    can_edit: bool  # Permission.DIRECT: without it the director answers and proposes, never applies
    message: str
    user_message_id: UUID
