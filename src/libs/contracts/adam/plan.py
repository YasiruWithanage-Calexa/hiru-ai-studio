"""Shot Planner Adam's plan, as typed data (plan/2026-11-04b §5.1).

A director imagines what the viewer lives through, moment by moment, and then chooses how to film each moment:

    SceneAnalysis → Treatment → Moment list → Staging → ShotCards (+ SoundMap)  =  AdamPlan

Every stage is a pydantic model so an agent's output is checked on the way in and the code steps (fidelity, fit,
continuity, score, feasibility) read plain fields. The models hold SHAPE, not rules: whether a take is a renderable
length, whether a moment invents story and whether a cut is motivated are decisions of the steps, so a plan that
breaks a rule is still a plan that can be read, reported on and sent back.

A block of the scene is named `b<index>` and a moment `m<n>` (any string without spaces is a valid moment id).

Pure standard library + pydantic (the `contracts` rule). The one contract it may import is `contracts.timing`, the
Veo clock.
"""
from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

Size = Literal["EWS", "WS", "MWS", "MS", "MCU", "CU", "ECU", "INSERT"]
SIZES: tuple[str, ...] = ("EWS", "WS", "MWS", "MS", "MCU", "CU", "ECU", "INSERT")
SIZE_RANK: dict[str, int] = {"EWS": 0, "WS": 1, "MWS": 2, "MS": 3, "MCU": 4, "CU": 5, "ECU": 6}  # INSERT has no rank
Arrangement = Literal["single", "two", "ots", "pov", "group"]
Angle = Literal["eye", "high", "low", "dutch"]
LensFeel = Literal["wide", "normal", "long"]
Movement = Literal["static", "push_in", "pull_out", "pan", "tilt", "track", "handheld", "crane", "reveal"]
FrameSide = Literal["left", "center", "right", ""]
Eyeline = Literal["left", "right", "camera", "down", "up", "away", ""]
Axis = Literal["A", "B", ""]
Motive = Literal["action", "look", "line", "sound", ""]
CutLink = Literal["cut", "continuous", "match"]  # contracts.veo.CameraLink values (mapping.py)
TierName = Literal["script", "implied", "elaboration", "invention"]
MOTIVES: tuple[str, ...] = ("action", "look", "line", "sound")

_BLOCK_REF = re.compile(r"^b(\d+)$")


def block_ref(index: int) -> str:
    return f"b{index}"


def block_of(ref: str) -> int | None:
    """"b3" → 3; anything else (a moment id) → None."""
    found = _BLOCK_REF.match(str(ref))
    return int(found.group(1)) if found else None


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


# ── the scene, as Adam is given it ───────────────────────────────────────────────────────────────


class Block(_Model):
    """One block of the script. `kind` is the script's own (action, dialogue, narration, story note ...)."""

    index: int = Field(ge=0)
    kind: str = "action"
    text: str = ""
    speaker: str = ""
    line_id: str | None = None  # a dialogue block's line; the words are bound to it by code, never by a model
    delivery: str = ""

    @property
    def is_line(self) -> bool:
        return self.kind == "dialogue" and self.line_id is not None


class Place(_Model):
    name: str = ""
    objects: list[str] = []  # what the location card has: an elaboration may show these


class SceneScript(_Model):
    """What every Adam step is given of the scene."""

    blocks: list[Block]
    cast: list[str] = []  # the people PRESENT; an elaboration may use these and no one else
    place: Place = Place()
    envelope_s: float | None = Field(None, gt=0)  # the seconds the episode leaves this scene, when known

    def block(self, index: int) -> Block | None:
        return next((b for b in self.blocks if b.index == index), None)

    @property
    def lines(self) -> list[Block]:
        return [b for b in self.blocks if b.is_line]

    def fits(self, thing: str) -> bool:
        """An object fits the place when the script names it or the location card has it (either may be the longer
        phrase). The rule `adam_fidelity` holds an added moment to."""
        want = norm(thing)
        haystacks = [norm(b.text) for b in self.blocks] + [norm(o) for o in self.place.objects]
        return any(want in h or (h and h in want) for h in haystacks)

    def listing(self) -> str:
        """The scene as an agent reads it: who is present, the place, then one numbered row per block. A line carries
        its id (`[L1]`): a card or a moment names a line by that id, never by its words."""
        head = [f"Present: {', '.join(self.cast)}" if self.cast else "",
                f"Place: {self.place.name}" + (f" (objects: {', '.join(self.place.objects)})" if self.place.objects
                                               else "") if self.place.name else "",
                f"The episode leaves this scene about {self.envelope_s:g} s." if self.envelope_s else ""]
        rows = []
        for b in self.blocks:
            if b.is_line:
                how = f", {b.delivery}" if b.delivery else ""
                rows.append(f'b{b.index} line [{b.line_id}] {b.speaker}{how}: "{b.text}"')
            else:
                rows.append(f"b{b.index} {b.kind}: {b.text}")
        return chr(10).join([r for r in head if r] + rows)


# ── ① the analysis ───────────────────────────────────────────────────────────────────────────────


class Value(_Model):
    start: str
    end: str


class Beat(_Model):
    blocks: list[int] = []
    action: str = ""
    reaction: str = ""
    turn: bool = False  # the value turns here
    reactor: str = ""  # whose face carries the turn; default: the POV owner


class Subtext(_Model):
    block: int
    who: str = ""
    behaviour: str = ""
    object: str = ""
    sound: str = ""


class PovOwner(_Model):
    start: str
    end: str = ""  # who has it after the handover; "" = the same person throughout
    why: str = ""
    handover: str = ""  # the moment that hands it over, by id; required when start != end


class Knows(_Model):
    fact: str
    who_doesnt: str = ""
    from_block: int = 0


class Baseline(_Model):
    blocks: list[int] = []
    state: str = ""


class BreakAt(_Model):
    block: int | None = None


class Aftermath(_Model):
    state: str = ""


class KeyMoment(_Model):
    block: int
    why: str = ""


class Question(_Model):
    """Something the script leaves open that changes what is filmed ("Does Anudi take her phone when she leaves?").
    Shown to a person, never answered by a model: an answer becomes a director's note the next plan reads."""

    question: str
    blocks: list[int] = []  # the blocks it concerns
    source: Literal["dramaturg", "continuity"] = "dramaturg"


class SceneAnalysis(_Model):
    about: str
    dramatic_question: str = ""
    value: Value
    tone: str = ""
    beats: list[Beat] = []
    wants: dict[str, str] = {}  # who → a playable verb ("to enjoy", "to hide")
    obstacles: list[str] = []
    subtext: list[Subtext] = []
    pov_owner: PovOwner
    audience_knows: list[Knows] = []
    baseline: Baseline = Baseline()
    break_: BreakAt = Field(BreakAt(), alias="break")
    aftermath: Aftermath = Aftermath()
    key_moment: KeyMoment
    questions: list[Question] = []  # what the script leaves open (plan/2026-11-04c F7)


# ── ② the treatment ──────────────────────────────────────────────────────────────────────────────


class Section(_Model):
    beats: list[int] = []  # indexes into SceneAnalysis.beats
    camera_behaviour: str = ""
    size_band: list[Size] = []  # [smallest, largest] size this section may use; empty = not stated
    sound_state: str = ""


class Plant(_Model):
    object: str
    plant_moment: str
    payoff_moment: str = ""
    payoff_scene: str = ""  # a LATER scene, named, when the payoff is not in this one
    plant_when: str = ""  # the director's words for where it is planted, before any moment has an id (Phase 3)
    payoff_when: str = ""


class RhythmBreak(_Model):
    moment: str
    kind: Literal["silence", "long_hold", "sudden_cut"] = "silence"
    when: str = ""  # the director's words for where it falls, before any moment has an id (Phase 3)


class Treatment(_Model):
    name: str
    stance: str = ""  # how the director plays it: "restrained", "intimate" or "heightened" (one of three per scene)
    concept: str  # "we make the viewer feel X by Y"
    pov: str = ""  # who the camera belongs to, in a phrase
    sound_concept: str = ""
    sections: list[Section] = []
    size_arc: list[Size] = []
    motif: str = ""
    plant: Plant | None = None
    rhythm: list[str] = []  # the tempo of each section
    rhythm_break: RhythmBreak | None = None  # the ONE break, on the key moment
    entry: str = ""
    exit: str = ""
    ending_image: str = ""
    ending_moment: str = ""  # the moment that is the ending image; the last card must hold it
    transition_in: str = ""
    transition_out: str = ""
    off_speaker: bool = False  # the treatment asks for at least one line played over a listener


# ── ③ the moments ────────────────────────────────────────────────────────────────────────────────


class Moment(_Model):
    id: str = Field(min_length=1, pattern=r"^\S+$")
    tier: TierName
    kind: str = ""  # an ELABORATION_KINDS entry for an elaboration; free for script and implied
    serves: list[str] = []  # script: the blocks it presents ("b3"); implied/elaboration: the moments/blocks it supports
    who: list[str] = []
    seen: str = ""  # what the camera can film
    heard: str = ""
    feeling: str = ""
    seconds_need: float = Field(0.0, ge=0)
    lines: list[str] = []  # line ids spoken in this moment (script moments only)
    objects: list[str] = []  # objects the picture shows that the moment names

    @field_validator("tier", mode="before")
    @classmethod
    def _lower(cls, value: Any) -> Any:
        return value.strip().lower() if isinstance(value, str) else value

    @property
    def blocks(self) -> list[int]:
        return [i for i in (block_of(r) for r in self.serves) if i is not None]


# ── ④ the staging ────────────────────────────────────────────────────────────────────────────────


class Mark(_Model):
    moment: str
    who: str
    zone: str
    facing: str = ""
    holding: list[str] = []  # objects in this person's hands


class Move(_Model):
    moment: str
    who: str
    from_zone: str = ""
    to_zone: str = ""
    why: Literal["power", "avoidance", "approach", "need", "enter", "exit", ""] = ""


class Staging(_Model):
    marks: list[Mark] = []
    moves: list[Move] = []


# ── ⑤ the cards ──────────────────────────────────────────────────────────────────────────────────


class Focus(_Model):
    kind: Literal["deep", "shallow", "rack"] = "deep"
    from_: str = Field("", alias="from")
    to: str = ""


class Composition(_Model):
    foreground: str = ""
    negative_space: str = ""
    frame_side: FrameSide = ""  # which side of the frame the subject sits on


class CardBeat(_Model):
    window: list[float] = []  # [from_s, to_s] inside the take
    action: str = ""
    performance: str = ""  # visible micro-action, not a feeling word
    camera: str = ""


class CardLine(_Model):
    line_id: str
    on_speaker: bool = True
    over_whom: str = ""  # when off the speaker: whose face the line plays over


class CardSound(_Model):
    ambience: str = ""
    effects: str = ""
    music: str = ""
    silence: bool = False
    pre_lap: str = ""
    carries_over: str = ""


class CutIn(_Model):
    link: CutLink = "cut"
    motive: Motive = ""


class ShotCard(_Model):
    number: int = Field(ge=1)
    moments: list[str]
    title: str = ""
    size: Size
    arrangement: Arrangement = "single"
    subject: str = ""  # who the frame is on; default: the first person of its first moment
    angle: Angle = "eye"
    height: str = ""
    lens_feel: LensFeel = "normal"
    movement: Movement = "static"
    focus: Focus = Field(default_factory=lambda: Focus.model_validate({}))
    composition: Composition = Composition()
    eyeline: Eyeline = ""  # where the subject looks, as the viewer sees it
    axis: Axis = ""  # which side of the line between the two main people the camera is on
    blocking_in_shot: str = ""
    beats: list[CardBeat] = []
    lines: list[CardLine] = []
    sound: CardSound = CardSound()
    cut_in: CutIn = CutIn()
    purpose: str = ""
    emotional_beat: str = ""
    rhythm_break: bool = False  # this card is the scene's one deliberate break in rhythm
    veo_notes: str = ""  # how the designer has handled what Veo renders badly
    take_s: int = Field(ge=1)  # 4, 6 or 8 for Veo; `adam_fit` reports any other length
    use_s: float | None = Field(None, gt=0)  # the part kept in the final cut (§5.6); None = the whole take
    in_s: float = Field(0.0, ge=0)  # where in the take the kept part starts (§5.6); 0 = the start of the take


# ── the sound map ────────────────────────────────────────────────────────────────────────────────


class SoundSection(_Model):
    blocks: list[int] = []
    ambience: str = ""
    music: str = ""
    state: str = ""  # a word for how the world sounds here ("warm", "narrowed to breath")


class SubjectiveSound(_Model):
    moment: str
    kind: str = ""  # narrowing, drop, ringing, heartbeat ...
    description: str = ""


class PreLap(_Model):
    card: int
    into: str = ""  # the next scene or card whose sound arrives first


class MusicCue(_Model):
    moment: str
    action: Literal["in", "out"] = "in"


class SoundMap(_Model):
    sections: list[SoundSection] = []
    subjective: list[SubjectiveSound] = []  # point of audition
    silences: list[str] = []  # moment ids
    pre_laps: list[PreLap] = []
    music: list[MusicCue] = []


# ── the whole plan ───────────────────────────────────────────────────────────────────────────────


class AdamPlan(_Model):
    analysis: SceneAnalysis
    treatment: Treatment
    moments: list[Moment]
    staging: Staging = Staging()
    cards: list[ShotCard] = []
    sound_map: SoundMap = SoundMap()
    report: dict[str, Any] = {}

    def moment(self, ident: str) -> Moment | None:
        return next((m for m in self.moments if m.id == ident), None)


def compact(value: BaseModel | list[BaseModel]) -> str:
    """A model (or a list of them) as one line of JSON for a prompt: aliases, no defaults, no spaces. What a stage hands
    the next one, so a model reads the same keys it was asked to write."""
    items = value if isinstance(value, list) else [value]
    dumped = [m.model_dump(mode="json", by_alias=True, exclude_defaults=True) for m in items]
    return json.dumps(dumped if isinstance(value, list) else dumped[0], ensure_ascii=False, separators=(",", ":"))


def errors_of(exc: ValidationError) -> str:
    """A pydantic error as one line a person reads: where, then why."""
    return "; ".join(f"{'.'.join(str(p) for p in e['loc']) or 'plan'}: {e['msg']}" for e in exc.errors())[:600]



# ── reading a payload and asking a plan ──────────────────────────────────────────────────────────


def norm(name: str) -> str:
    """A name or an object compared the way a person reads it: case and spacing do not matter."""
    return " ".join(str(name).lower().split())


def part_of(payload: dict[str, Any], key: str) -> Any:
    """`payload[key]`, or `payload["plan"][key]` when the whole plan was handed over."""
    if key in payload:
        return payload[key]
    plan = payload.get("plan")
    return plan.get(key) if isinstance(plan, dict) else None


def scene_of(payload: dict[str, Any]) -> SceneScript:
    return SceneScript.model_validate(payload.get("scene"))


def moments_of(payload: dict[str, Any]) -> list[Moment]:
    return [Moment.model_validate(m) for m in part_of(payload, "moments") or []]


def cards_of(payload: dict[str, Any]) -> list[ShotCard]:
    return [ShotCard.model_validate(c) for c in part_of(payload, "cards") or []]


def subject_of(card: ShotCard, by_id: dict[str, Moment]) -> str:
    """Who a frame is on: the card's own `subject`, else the first person of its first moment."""
    if card.subject:
        return norm(card.subject)
    first = by_id.get(card.moments[0]) if card.moments else None
    return norm(first.who[0]) if first and first.who else ""


def people_of(card: ShotCard, by_id: dict[str, Moment]) -> set[str]:
    """Everyone the card's moments put in the picture."""
    return {norm(w) for ident in card.moments if (m := by_id.get(ident)) for w in m.who}


def blocks_of(card: ShotCard, by_id: dict[str, Moment]) -> set[int]:
    return {b for ident in card.moments if (m := by_id.get(ident)) for b in m.blocks}
