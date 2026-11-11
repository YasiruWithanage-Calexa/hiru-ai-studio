"""What Raphael's two agents write (plan/2026-11-08e §3, phase 1): the WIRE shapes, and the bin entries they become.

    EditPlanW   the intended cut: treatment, sequences, moments (stage 1; a reference for the editor)
    ClipW       one whole clip as ONE model writes it: its plan AND its Veo design (`ir`, `sound`); id "" = a new clip
    ExtraW      a cinematic clip (stage 2): a ClipW that is never `must`, with the must clip(s) it sits with and its
    blend
    Clip/Extra  a bin entry: the clip plus the id and slate code gives it (stage 1 / stage 2)

The lab's shapes (`lab/davinci/schema.py`, `lab/raphael/schema.py`) moved into the product, field for field: the JSON
schema the model is held to is the lab's (`tests/raphael/test_lab_parity.py`). Like every wire shape here nothing has a
default (strict JSON-schema mode cannot hold a model to one). The one part decided at run time is a clip's camera
design,
`ir`: it is the Veo clip schema the DoP fills too, so the agents build that part of the JSON schema from the YAML
(`agents/raphael/wire_schema.py`) and here it is a plain object.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

# ── the closed lists (§2.2, DaVinci §3) ──────────────────────────────────────────────────────────

Size = Literal["EWS", "WIDE", "MWS", "MS", "MCU", "CU", "ECU", "TWO", "OTS", "INSERT", "POV"]
SIZES: tuple[str, ...] = ("EWS", "WIDE", "MWS", "MS", "MCU", "CU", "ECU", "TWO", "OTS", "INSERT", "POV")
# What the shared parts know (`contracts.production.Framing`): a size of Raphael's own is read as its nearest there.
FRAMING = {"EWS": "WIDE", "MWS": "MS", "ECU": "CU", "POV": "MCU"}
ROLES: tuple[str, ...] = (
    "master",
    "single",
    "ots",
    "two_shot",
    "reaction",
    "insert",
    "cutaway",
    "establishing",
    "atmosphere",
    "clean_entry",
    "clean_exit",
    "pov",
    "transition_out",
    "transition_in",
)
Role = Literal[
    "master",
    "single",
    "ots",
    "two_shot",
    "reaction",
    "insert",
    "cutaway",
    "establishing",
    "atmosphere",
    "clean_entry",
    "clean_exit",
    "pov",
    "transition_out",
    "transition_in",
]
Priority = Literal["must", "should", "nice"]
PRIORITIES: tuple[str, ...] = ("must", "should", "nice")
TECHNIQUES: tuple[str, ...] = (
    "locked_off",
    "drone_establishing",
    "drone_reveal",
    "drone_pull_away",
    "top_down",
    "orbit",  # aerial
    "crash_zoom",
    "snap_zoom",
    "slow_creep",  # zoom (a dolly zoom is refused)
    "dolly_in",
    "dolly_out",
    "tracking",
    "lead",
    "follow",
    "arc",
    "crane",
    "steadicam",
    "handheld",  # moving
    "whip_pan",
    "slow_pan_reveal",
    "tilt_reveal",  # pan / tilt
    "low_angle",
    "high_angle",
    "dutch",
    "worms_eye",
    "overhead",  # angle
    "rack_focus",
    "shallow_isolation",
    "foreground_framing",  # focus / lens (a split diopter is refused)
    "push_past_foreground",
    "pull_back",
    "enter_held_frame",  # reveal
    "silhouette",
    "shadow_before_person",
    "flare",
    "light_across_face",  # light
    "slow_motion",
    "timelapse",
    "hyperlapse",  # time
    "whip_out",
    "whip_in",
    "match_cut",
    "object_wipe",
    "focus_out",
    "focus_in",
)  # transition halves
Technique = Literal[
    "locked_off",
    "drone_establishing",
    "drone_reveal",
    "drone_pull_away",
    "top_down",
    "orbit",
    "crash_zoom",
    "snap_zoom",
    "slow_creep",
    "dolly_in",
    "dolly_out",
    "tracking",
    "lead",
    "follow",
    "arc",
    "crane",
    "steadicam",
    "handheld",
    "whip_pan",
    "slow_pan_reveal",
    "tilt_reveal",
    "low_angle",
    "high_angle",
    "dutch",
    "worms_eye",
    "overhead",
    "rack_focus",
    "shallow_isolation",
    "foreground_framing",
    "push_past_foreground",
    "pull_back",
    "enter_held_frame",
    "silhouette",
    "shadow_before_person",
    "flare",
    "light_across_face",
    "slow_motion",
    "timelapse",
    "hyperlapse",
    "whip_out",
    "whip_in",
    "match_cut",
    "object_wipe",
    "focus_out",
    "focus_in",
]
NO_DIALOGUE = ("slow_motion", "timelapse", "hyperlapse")  # slow motion carries no dialogue
AERIAL = ("drone_establishing", "drone_reveal", "drone_pull_away", "top_down", "orbit")
TRANSITION = ("transition_out", "transition_in")
Blend = Literal["cut_in", "under_line", "open", "close", "transition"]
BLENDS: tuple[str, ...] = ("cut_in", "under_line", "open", "close", "transition")
# the roles a cinematic clip usually takes (§2.2): named in the prompt, not enforced (the blocking rule is "differs from
# its anchor")
CINEMATIC_ROLES: tuple[str, ...] = (
    "insert",
    "cutaway",
    "reaction",
    "establishing",
    "atmosphere",
    "pov",
    "transition_out",
    "transition_in",
)

# The length cap (§2.1, L1): the whole bin may hold the scene's given length x this, in seconds of takes. A choice.
LENGTH_CAPS: tuple[float, ...] = (1, 1.5, 2, 2.5, 3)


def _a_cap(value: float) -> float:
    if value not in LENGTH_CAPS:
        raise ValueError(f"the length cap is one of {', '.join(f'{c:g}' for c in LENGTH_CAPS)}")
    return float(value)


LengthCap = Annotated[float, AfterValidator(_a_cap)]
DEFAULT_CAP = 2.0
STAGE1_CAP = 1.5  # stage 1 builds the cut, not coverage: it keeps its own hard cap (§2.1)

SCHEMA_EDIT, SCHEMA_PUT, SCHEMA_EXTRAS = "edit_plan", "put_clips", "put_extras"


class _Wire(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SoundW(_Wire):
    ambience: str
    effects: str
    music: str
    silence: bool  # the clip asks for silence: Veo must be told, or it invents speech


# ── the director's breakdown (plan/2026-11-10 §2) ───────────────────────────────────────────────

ShotKind = Literal["story", "detail"]
SHOT_KINDS: tuple[str, ...] = ("story", "detail")


class DirectionW(_Wire):
    """The look of the scene in four short lines."""

    palette: str
    camera: str
    lens: str
    sound: str


class BreakdownShotW(_Wire):
    """One shot of the director's breakdown: one action, the blocks and lines it sits on, what must be readable."""

    n: int
    blocks: list[int]  # the script blocks the shot sits on
    lines: list[str]  # line ids (L7) said on this shot, never the words
    kind: ShotKind  # story: carries the script; detail: an insert that earns its place
    size: Size
    lens: str
    move: Technique  # Raphael's camera vocabulary
    action: str  # ONE action
    why: str
    must_read: str  # what the audience must be able to read in the frame
    about_s: float  # advisory: the `<length>` block and the checks decide
    # the shot card (the person, 2026-11-10): what the planner, the editor and the person reading need per shot.
    # All have defaults, so a breakdown stored before them still loads; the prompt asks for every one.
    takes: list[int] = Field(default_factory=list)  # how it is shot: Veo takes of 4, 6 or 8 s, e.g. [8] or [6, 4]
    mood: str = ""  # what the audience feels and the tension, in a few words
    setting: str = ""  # where the shot is, the time, the weather
    on_screen: list[str] = Field(default_factory=list)  # people the frame shows (never a voice-only person)
    off_screen: list[str] = Field(default_factory=list)  # people heard or just out of frame
    blocking: str = ""  # who is where, which way they face, where they look, the direction they move
    performance: str = ""  # what the face and hands do, from the start of the shot to its end
    props: str = ""  # what is held, worn, wet, lit or in the way (continuity)
    light: str = ""  # the light on this shot, its sources
    sound: str = ""  # what is heard on this shot
    transition: str = ""  # how it comes in from the shot before and goes out to the next
    priority: Literal["must", "optional"] = "must"  # optional: the first to go if the length asks for it


class BreakdownW(_Wire):
    """What `raphael_breakdown` writes: a director's shot breakdown of one scene, in English, lines by id."""

    objective: str  # one sentence: what the scene must do
    direction: DirectionW
    shots: list[BreakdownShotW]
    notes: list[str]  # director notes


# ── the intended cut (§2) ────────────────────────────────────────────────────────────────────────


class SpanW(_Wire):
    first: int
    last: int


class ArcW(_Wire):
    beat: str  # what happens, in plain words
    blocks: SpanW  # the script blocks it spans
    feeling: str  # what the audience should feel


class ColourW(_Wire):
    sequence: str  # a sequence id
    palette: str
    light: str  # the physical light: continuous across the scene (rain, daylight), it does not jump
    grade: str  # the grade may move with the story


class TreatmentW(_Wire):
    logline: str  # one sentence
    arc: list[ArcW]  # the emotional beats in order
    approach: str  # lenses, movement, framing philosophy, in plain words
    colour_script: list[ColourW]  # one per sequence
    geography: str  # what is on screen left and right, the camera's side of the line, how it changes
    key_image: str  # the one image the scene is remembered by
    advice: list[str]  # advice for the person: shown, never applied (0-5 items)


class SequenceW(_Wire):
    id: str  # "A", "B", ...
    title: str
    purpose: str
    shots: SpanW  # here: the first and last MOMENT number


class MomentW(_Wire):
    n: int
    sequence: str  # a sequence id
    blocks: list[int]  # the script blocks of this moment (every block belongs to one moment)
    what: str  # what happens, in plain words
    feeling: str  # what the audience should feel
    cut_uses: str  # which clip (role and angle) the intended cut uses here, and why


class EditPlanW(_Wire):
    treatment: TreatmentW
    sequences: list[SequenceW]
    moments: list[MomentW]
    editor_notes: list[str]  # risky match cuts; techniques left for post; what was avoided because Veo cannot do it


# ── the shoot bin (§2) ───────────────────────────────────────────────────────────────────────────


class MenuW(_Wire):
    """One clip's plan."""

    moment: int  # the moment this clip covers (MomentW.n)
    role: Role
    setup: str  # one capital letter: clips from the same camera position share it (the slate's "B")
    blocks: list[int]  # the script blocks the clip overlaps ([] for an establishing, atmosphere or transition clip)
    lines: list[str]  # line ids (L7) heard on this clip, never the words
    speaks: bool  # the person's lips perform the line in this clip (D2); false: it plays silent under the chosen audio
    over: str  # "" or who is SHOWN while a line is heard (a listener or reaction clip)
    size: Size
    angle: str  # eye level, low, high, dutch ...
    lens: str  # the lens and why
    technique: Technique
    why: str  # one sentence: the story reason for this clip and for its technique
    take_s: Literal[4, 6, 8]  # what Veo makes
    handle_in_s: float  # about 1 s of the take before the action starts
    handle_out_s: float  # about 1 s after it ends
    priority: Priority
    editor_note: str  # what the editor can do with it ("" when nothing to add)


class ClipW(MenuW):
    """A whole clip as ONE model writes it: the plan and the Veo design together."""

    id: str  # "" for a new clip; the id of a clip in the bin (c07) to replace it
    ir: dict[str, Any]  # setting, cinematography{...}, lighting, subjects[], beats[], audio, first_frame{...}
    sound: SoundW

    def menu(self) -> MenuW:
        return MenuW.model_validate(self.model_dump(exclude={"id", "ir", "sound"}))


class PutW(_Wire):
    clips: list[ClipW]


class ExtraW(ClipW):
    """A cinematic clip as stage 2 writes it: a whole clip (plan + design), never `must`, with the must clip(s) it sits
    with and how post blends it in."""

    priority: Literal["should", "nice"]  # the schema itself refuses `must`: the must clips are stage 1's
    # the must clip id(s) it sits with (c07); for `transition`, a must clip of the neighbouring moment
    anchor: list[str]
    blend: Blend

    def menu(self) -> MenuW:
        return MenuW.model_validate(self.model_dump(exclude={"id", "ir", "sound", "anchor", "blend"}))


class ExtrasW(_Wire):
    clips: list[ExtraW]


class ReviewRow(_Wire):
    """One moment of the cinematic pass's review: `earns` true when it has cinematic clips (and what they give), false
    when it has none (and why it needs none)."""

    moment: int
    earns: bool
    why: str


class Clip(MenuW):
    """A bin entry. `ir` and `sound` are None until written. Stage 1's clips are plain `Clip` (stage 1)."""

    id: str
    slate: str
    ir: dict[str, Any] | None = None
    sound: SoundW | None = None
    stage: int = 1
    anchor: list[str] = Field(default_factory=list)
    blend: str = ""

    @property
    def is_extra(self) -> bool:
        return self.stage == 2


def extra_of(fields: dict[str, Any]) -> Clip:
    """A stage 2 bin entry from a clip's fields."""
    return Clip.model_validate({**fields, "stage": 2})
