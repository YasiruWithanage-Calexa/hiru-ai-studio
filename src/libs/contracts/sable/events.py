"""What Sable's function answers and stores (plan/2026-11-08 §4.7, §4.8).

A TURN (`SableTurnPayload`, API → function) streams server-sent events; the API sends its own `accepted` first:

    accepted {thread_id, message}       the person's message as stored (the API's frame)
    status {text}                       plain words while it works: "Reading E1S2", "Thinking this through"
    delta {text}                        reply text (the name Zora and the classic chat use; the plan said `token`)
    card {block}                        a staged change, a memory card, or a handoff card (`Card`)
    citations {citations}               [{chunk_id, label}] the passages the tools returned
    message {…}                         the reply as stored (`SableMessage`)
    done {message_id, used}             the memory entries the reply was given
    error {message}                     one sentence for the person, never an exception's text

No tier, model, cost or tool id ever reaches the browser: the turn's record (`TurnMeta`) is stored in
`chat_turn_meta` (schema v18) for `hiru-ai review` and the lab; no browser can read that table.

Pure standard library + pydantic (the `contracts` rule).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

EVENTS: tuple[str, ...] = ("accepted", "status", "delta", "card", "citations", "message", "done", "error")
CHAT = "sable"  # chat_threads.chat for Sable's threads (schema v18); every other thread is 'scene'
SPEAKER = "Sable"
UNAVAILABLE = "Sable is not available right now. Please try again in a moment."
NO_MODEL = "Sable is not available right now: its model is switched off. Please try again later."
STOPPED = "Stopped."

# The plain words shown while a tool runs (§4.7): never a tool id. `{scene}` is filled from the call's own argument when
# it names one ("Reading E1S2"); without it the words read on their own.
STATUS: dict[str, str] = {
    "canon_find": "Looking through the canon",
    "canon_read": "Reading the canon",
    "change_propose": "Preparing a change for you to accept",
    "continuity_check": "Checking continuity{in_scene}",
    "dialogue_read": "Reading the lines{of_scene}",
    "episode_read": "Reading the episode",
    "frame_read": "Looking at the frames{of_scene}",
    "glossary_read": "Checking names and spellings",
    "memory_propose": "Preparing a rule for you to accept",
    "memory_search": "Looking through what the team decided",
    "plan_try": "Trying the change on a copy{of_scene}",
    "prompt_check": "Checking the prompts{of_scene}",
    "questions_read": "Reading the open questions",
    "sable_overview": "Looking over the production",
    "sable_scene_find": "Finding the scenes",
    "sable_think_harder": "Thinking this through",
    "scene_read": "Reading {scene}",
    "scene_reading_read": "Reading the feeling of {scene}",
    "search_kb": "Searching the documents",
    "shot_read": "Reading the shot{of_scene}",
    "staging_check": "Checking who stands where{in_scene}",
    "sable_state_propose": "Preparing a change of state for you to accept",
    "technique_lookup": "Looking up the craft",
    "timing_check": "Checking the timing{of_scene}",
    "veo_fit": "Checking what fits a clip",
}
WORKING = "Working on it"


def status_text(tool: str, args: dict[str, Any] | None = None) -> str:
    """The words for a tool call: its scene when it named one, never the tool's id."""
    scene = str((args or {}).get("scene") or (args or {}).get("scene_id") or (args or {}).get("around_scene") or "")
    scene = scene if 1 <= len(scene) <= 8 else ""  # a label like E1S2, never an id
    words = STATUS.get(tool, WORKING)
    return words.format(scene=scene or "the scene", of_scene=f" of {scene}" if scene else "",
                        in_scene=f" in {scene}" if scene else "")


RefKind = Literal["scene", "shot", "person", "prop", "place", "block"]
MAX_REFS = 12


class Ref(BaseModel):
    """What the person pointed at with @ (plan/2026-11-09b phase 4). `id` is the thing's own id (a scene, shot or canon
    entity uuid); for a `block` it is the block's number in the scene (`scene_id`, default the open scene). The API
    checks every one is in this production; the browser only ever sends what the picker gave it."""

    model_config = ConfigDict(extra="forbid")

    kind: RefKind
    id: str = Field(min_length=1, max_length=64)
    label: str = Field(default="", max_length=80)  # what the chip says ("S04", "Kamal"); the API re-reads it
    scene_id: UUID | None = None  # a block's scene


class Mention(BaseModel):
    """A `Ref` the API resolved from trusted data. `text` is the line the agent reads under MENTIONED."""

    kind: RefKind
    id: str
    label: str
    scene: str = ""  # "E1S2"
    outside: bool = False  # a shot, block or scene other than the open one: for reading, never for changing
    text: str = ""


class MentionOption(BaseModel):
    """One row of the @ picker (`GET …/sable/mentions`): names only, no model."""

    kind: RefKind
    id: str
    label: str
    detail: str = ""
    scene_id: UUID | None = None
    scene: str = ""


class SableTurnRequest(BaseModel):
    """Browser → API."""

    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=4000)
    thread_id: UUID | None = None  # None: a new thread, titled from the message
    scene_id: UUID | None = None  # the scene the person is looking at, if any
    replaces: UUID | None = None  # Edit / Ask again: the person's last message, which this one replaces
    refs: list[Ref] = Field(default_factory=list, max_length=MAX_REFS)  # what @ pointed at


class SableTurnPayload(BaseModel):
    """API → function. Everything the function may not decide for itself is decided by the API from trusted data."""

    model_config = ConfigDict(extra="forbid")

    production_id: UUID
    thread_id: UUID
    actor_user_id: UUID
    actor_name: str
    role: str = ""  # the person's production role ("director"; "admin" for an app admin)
    can_stage: bool = False  # Permission.DIRECT: the cards Sable may propose need it (D8: a viewer gets none)
    message: str
    user_message_id: UUID
    scene_id: UUID | None = None  # the scene in view, inside the production (checked by the API)
    replaces: UUID | None = None
    mentions: list[Mention] = Field(default_factory=list, max_length=MAX_REFS)  # `refs`, resolved by the API
    attachments: int = 0  # files sent with the message (none yet; the pre-route's rule is ready for them)


class StagedChange(BaseModel):
    """A change to a scene's shot list Sable proposed (`change_propose`): the operations the kernel confirmed land.
    Accepting applies them through the director function, as a button press does
    (`POST …/sable/messages/{id}/cards/{i}/accept`)."""

    kind: Literal["sable_change"] = "sable_change"
    scene_id: UUID
    scene: str  # "E1S2"
    summary: str
    ops: list[dict[str, Any]] = Field(default_factory=list)
    changes: list[str] = Field(default_factory=list)
    touched: list[str] = Field(default_factory=list)
    notes: list[dict[str, Any]] = Field(default_factory=list)  # DoP notes: [{shot, before, after}] (plan/2026-11-09b)
    status: Literal["open", "accepted", "dismissed", "failed"] = "open"
    note: str = ""  # why it failed, in a sentence


class StagedState(BaseModel):
    """A change to the open scene's state ledger Sable proposed (`sable_state_propose`, plan/2026-11-09b): who is where,
    how they stand and their condition, from a block on. Accepting merges the marks into the scene's map as a person's
    own (`by: "person"`), by code (`POST …/sable/messages/{id}/cards/{i}/accept`)."""

    kind: Literal["sable_state"] = "sable_state"
    scene_id: UUID
    scene: str  # "E1S2"
    summary: str
    script_version: int = 0  # the scene's script when proposed: block numbers mean nothing against another script
    marks: list[dict[str, Any]] = Field(default_factory=list)  # `stagemap.StateMark`s
    changes: list[str] = Field(default_factory=list)  # "Kamal: lying, dead, from block 12"
    touched: list[str] = Field(default_factory=list)  # the shots that open or end in a different state
    in_doubt: list[str] = Field(default_factory=list)  # report only: a shot whose words still contradict the change
    status: Literal["open", "accepted", "dismissed", "failed"] = "open"
    note: str = ""


class StagedMemory(BaseModel):
    """A rule to remember (`memory_propose`). Accepted, it becomes a remembered decision of the production."""

    kind: Literal["sable_memory"] = "sable_memory"
    rule: str
    scope: Literal["scene", "production"] = "production"
    scene_id: UUID | None = None
    status: Literal["open", "accepted", "dismissed", "failed"] = "open"
    note: str = ""


class Handoff(BaseModel):
    """"Open E1S2 with this request" (§4.6): the panel writes the request into that scene's chat composer (Zora's when
    the scene is Zora's, else the classic chat's) and opens the scene. The person sends it; nothing is changed here."""

    kind: Literal["handoff"] = "handoff"
    scene_id: UUID
    episode_id: UUID | None = None  # the panel builds the scene's URL from it
    scene: str
    request: str
    target: Literal["zora", "classic", ""] = ""  # filled by the API from `zora.routes_here` when a thread is read


class TextBlock(BaseModel):
    kind: Literal["text"] = "text"
    text: str
    stopped: bool = False


class SableCitation(BaseModel):
    chunk_id: str = ""
    label: str = ""


Card = StagedChange | StagedState | StagedMemory | Handoff


class SableMessage(BaseModel):
    """A message of a Sable thread as the panel reads it. `meta` is never part of it."""

    model_config = ConfigDict(extra="ignore")

    id: UUID
    thread_id: UUID
    kind: Literal["user", "director"]
    speaker: str = ""
    text: str = ""
    blocks: list[dict[str, Any]] = Field(default_factory=list)  # TextBlock, Card, the `used` and `replaces` blocks
    citations: list[SableCitation] = Field(default_factory=list)
    created_at: datetime


class SableThread(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID
    production_id: UUID
    title: str
    created_at: datetime
    updated_at: datetime


class TurnMeta(BaseModel):
    """The turn's record, stored in `chat_turn_meta`: read by `hiru-ai review` and the lab, never by a browser."""

    tier_start: str = ""
    tier_end: str = ""
    escalated_by: Literal["", "route", "model", "refusals", "cap", "stage"] = ""
    reason: str = ""
    route_rule: str = ""  # the pre-route rule that started the turn deep
    tools: list[str] = Field(default_factory=list)  # the tools called, in order
    tool_errors: int = 0
    guard: list[str] = Field(default_factory=list)  # what the quote guard removed
    stopped: bool = False
    failed: bool = False
