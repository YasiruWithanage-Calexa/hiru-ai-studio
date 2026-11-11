"""The wire shapes of the two-memories lab (plan/2026-11-11 §4) and the stored memories (§5).

Every wire shape is pointers: line ranges and word spans, never document text. Provenance (§3.3): every value is
`script` (a line range code checks), `inferred` (a one-line reason) or `person` (an edit, always wins)."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _W(BaseModel):
    model_config = ConfigDict(extra="forbid")


Source = Literal["script", "inferred", "person"]
Presence = Literal["on_screen", "voice_message", "phone", "recording", "voice_over", "thought", "body"]
ThingRole = Literal["hero", "used", "dressing", "worn", "mentioned"]
PlaceKind = Literal["region", "set", "spot", "vehicle"]
EventFunction = Literal["setup", "reveal", "turn", "texture"]
SECTIONS = ("title_page", "overview", "cast", "canon", "direction", "story", "other")
ABOUT = ("palette", "lens", "lighting", "editing", "sound", "slow_motion", "action", "other")


class RangeW(_W):
    start: int
    end: int


class SpanW(_W):
    line: int
    w_from: int
    w_to: int


class SectionW(_W):
    label: Literal["title_page", "overview", "cast", "canon", "direction", "story", "other"]
    lines: RangeW
    note: str = ""  # only for `other`: what the notes are


class FieldW(_W):
    name: str  # age, gender, appearance, wardrobe, voice, look, details
    span: SpanW


class CardW(_W):
    kind: Literal["person", "place", "thing"]
    name: SpanW  # where the document writes the name: code cuts it (a model never types a name)
    lines: RangeW
    fields: list[FieldW] = Field(default_factory=list)
    place_kind: PlaceKind | None = None
    seen: bool = True  # False: mentioned only, pictured only, or in a direction note only
    within: int = -1  # index in `cards` of the region card this place is in (a set in Colombo), -1 none


class RuleW(_W):
    about: Literal["palette", "lens", "lighting", "editing", "sound", "slow_motion", "action", "other"]
    lines: RangeW
    scope_kind: Literal["all", "place", "episode", "scene"] = "all"
    scope_card: int = -1  # place scope: index in `cards` of the place card
    scope_number: int = 0  # episode or scene scope: the document's own number


class SceneCutW(_W):
    number: int  # the document's own number
    heading: int  # heading line
    last: int  # last line of the scene


class EpisodeCutW(_W):
    number: int  # 0 when the document has no episodes
    heading: int
    scenes: list[SceneCutW]


class SplitW(_W):
    """Step 1's answer for one document: labels over line ranges."""

    sections: list[SectionW]
    cards: list[CardW]
    rules: list[RuleW]
    episodes: list[EpisodeCutW]


# --- step 4: one episode ---------------------------------------------------------------------------------------------------------

class EventW(_W):
    actors: list[str] = Field(default_factory=list)  # C ids
    things: list[str] = Field(default_factory=list)  # P ids
    spot: str = ""  # L id
    speech: bool = False  # someone speaks: its block must be a dialogue block (§4.4; catches a spoken line lost in action)
    visible: bool = True  # a camera can show it
    change: str = ""
    function: EventFunction = "texture"


class BlockW(_W):
    kind: Literal["action", "dialogue", "text", "sound", "transition"]
    spans: list[SpanW]  # word ranges: the block's exact words are cut by code
    speaker: str = ""  # C id (dialogue)
    presence: Presence = "on_screen"
    device: str = ""
    addressee: str = ""
    heard_by: list[str] = Field(default_factory=list)
    intent: str = ""
    delivery_hint: str = ""
    source: Source = "script"  # of the intent and delivery hint: `script`, or `inferred` (never a prefix inside the text)
    events: list[EventW] = Field(default_factory=list)


class PresenceW(_W):
    person: str  # C id
    presence: Presence = "on_screen"
    wants: str = ""
    feeling_start: str = ""
    feeling_end: str = ""
    source: Source = "script"


class ThingUseW(_W):
    thing: str  # P id
    role: ThingRole
    holder_start: str = ""
    holder_end: str = ""
    source: Source = "script"


class SceneBriefW(_W):
    scene: str  # E01-S01
    title: str
    summary: str
    purpose: str
    place: str = ""  # L id of the set this scene happens in
    mood: list[str] = Field(default_factory=list)
    people: list[PresenceW]
    things: list[ThingUseW] = Field(default_factory=list)
    blocks: list[BlockW]
    turns: list[int] = Field(default_factory=list)  # block numbers (1-based)
    source: Source = "inferred"  # of the purpose and the mood
    rules_met: list[str] | None = None  # D ids of the conditional direction rules (lens for love or action scenes) this scene meets


class EpisodeW(_W):
    scenes: list[SceneBriefW]


# --- stored: the breakdown memory (§5) ---------------------------------------------------------------------------------------------

class Value(BaseModel):
    """One value with its provenance and version (§3.3, §5)."""

    value: Any
    source: Source = "script"
    lines: tuple[int, int] | None = None  # `script`: where it was read
    reason: str = ""  # `inferred`: why
    owner: str = "split"  # the step that owns this kind of fact
    version: int = 1


class Entity(BaseModel):
    id: str
    kind: Literal["person", "place", "thing"]
    name: str
    lines: tuple[int, int]
    card: dict[str, Value] = Field(default_factory=dict)
    place_kind: PlaceKind | None = None
    seen: bool = True
    within: str = ""  # L id of the region this place is in


class Rule(BaseModel):
    id: str
    about: str
    text: str
    lines: tuple[int, int]
    scope_kind: str = "all"
    scope_id: str = ""


class Scene(BaseModel):
    id: str
    episode: int
    number: int
    heading: str
    heading_line: int
    first: int  # first body line
    last: int
    brief: dict[str, Any] | None = None
    blocks: list[dict[str, Any]] = Field(default_factory=list)
    stage: dict[str, Any] | None = None  # step 6: zones, marks (where something changes) and props


class Finding(BaseModel):
    code: str  # words | ids | sources | presence | time | continuity | direction | safe | length | packet
    scene: str = ""
    message: str
    blocking: bool = False


class Breakdown(BaseModel):
    """The breakdown memory of one production (lab form: JSON, D7)."""

    document: str
    entities: list[Entity] = Field(default_factory=list)
    rules: list[Rule] = Field(default_factory=list)
    scenes: list[Scene] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)

    def entity(self, id_: str) -> Entity | None:
        return next((e for e in self.entities if e.id == id_), None)

    def scene(self, id_: str) -> Scene | None:
        return next((s for s in self.scenes if s.id == id_), None)


# --- step 3: continuity (one call over every episode) -------------------------------------------------------------------------------

class _Prov(_W):
    """Every continuity fact says where it comes from (§3.3): `script` with its line range, or `inferred` with a reason."""

    source: Literal["script", "inferred"] = "script"
    lines: RangeW | None = None
    reason: str = ""


class TimeW(_Prov):
    scene: str  # E01-S03
    story_order: int  # 1 is the first thing that happens in the story, not the first on the page
    story_day: int = 0  # 0: not stated
    relative: str = ""  # "six hours before E01-S02"
    kind: Literal["normal", "flashback", "cold_open", "flash_forward"] = "normal"
    anchor: str = ""  # the scene a flashback or relative time is measured from


class SynopsisW(_Prov):
    episode: int
    text: str


class ArcW(_Prov):
    person: str  # C id
    change: str
    from_scene: str
    to_scene: str


class KnowledgeW(_Prov):
    scene: str
    person: str = ""  # C id; empty when it is the audience alone (irony)
    learns: str = ""
    audience_only: bool = False  # the audience knows, the people do not


class BeatW(_Prov):
    scene: str
    note: str


class ThreadW(_Prov):
    kind: Literal["setup_payoff", "open_question", "journey"]
    subject: str = ""  # P or C id when the thread follows a thing or a person
    summary: str
    beats: list[BeatW]  # a journey: who holds the thing, scene by scene


class LookW(_Prov):
    person: str
    kind: Literal["wardrobe", "injury", "death", "condition"]
    from_scene: str
    to_scene: str = ""  # empty: to the end
    note: str


class RelationW(_Prov):
    a: str
    b: str
    state: str
    scene: str  # where it stands or changes


class ScopeW(_Prov):
    rule: str  # D id
    scenes: list[str] = Field(default_factory=list)
    moment_scene: str = ""  # a named moment ("Nimal's key falling") and the scene it is in
    moment_note: str = ""


class ContinuityW(_W):
    timeline: list[TimeW]
    synopses: list[SynopsisW]
    arcs: list[ArcW]
    knowledge: list[KnowledgeW]
    threads: list[ThreadW]
    looks: list[LookW]
    relationships: list[RelationW]
    scopes: list[ScopeW]
