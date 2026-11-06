"""What Jonathan's author and reviser write (plan/2026-11-06b §4.1): the WIRE shape, and the plan it is.

The cinematic lab's `CinemaWire` (lab/cinematic/schema.py), moved into the product: David's wire plus what a director's
plan
has and David's lacks. A TREATMENT first (logline, arc, approach, colour script, geography, key image, advice), then
SEQUENCES, then the shots with more sizes (EWS, MWS, ECU, POV), the camera's angle and lens, and `use_s`, the seconds
the
edit keeps of a take.

A model that answers in strict JSON-schema mode cannot be held to defaults, so the wire shapes have none. Field order is
the order the model writes (the treatment, then the sequences, then the shots) and is the lab's to the letter: the JSON
schema the model is held to is the lab's (a test compares them). The only part decided at run time is the camera design
inside each shot, `ir`: it is the Veo clip schema the DoP fills too, so the agents build that part of the JSON schema
from
the YAML (`agents/jonathan/wire_schema.py`) and here it is a plain object.

    JonathanWire    (jonathan_author, jonathan_revise)   the whole scene, as written and as corrected

Both agents answer the whole plan: the reviser returns a corrected plan from its own draft and code's findings (the
lab's
stabiliser), never a patch. The conversions keep the model's words and decide nothing: whether a line is missing, a take
too short or a person invented is for the checks (`jonathan_check`). Pure standard library + pydantic (the `contracts`
rule).
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

Size = Literal["EWS", "WIDE", "MWS", "MS", "MCU", "CU", "ECU", "TWO", "OTS", "INSERT", "POV"]
# The sizes the shared parts know (`contracts.production.Framing`, the `shots.framing` check): a size of Jonathan's own
# is
# read as its nearest there. The plan keeps Jonathan's size; only the shared parts see the nearest one.
FRAMING = {"EWS": "WIDE", "MWS": "MS", "ECU": "CU", "POV": "MCU"}
CLOSE: tuple[str, ...] = ("MCU", "CU", "ECU")


class _Wire(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SoundW(_Wire):
    ambience: str
    effects: str
    music: str
    silence: bool  # the shot asks for silence: Veo must be told, or it invents speech


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
    advice: list[str]  # director's advice for the person: shown, never applied (0-5 items)


class SequenceW(_Wire):
    id: str  # "A", "B", ...
    title: str
    purpose: str
    shots: SpanW  # first and last shot number


class ShotW(_Wire):
    n: int
    sequence: str  # the id of the sequence it belongs to
    blocks: list[int]  # script blocks this shot shows ([] for an added shot)
    lines: list[str]  # line ids (L4) spoken in it, never the words
    over: str  # "" or who is SHOWN while a line is heard (a listener shot)
    size: Size
    angle: str  # eye level, low, high, dutch...
    lens: str  # the lens and why, e.g. "85mm: intimacy"
    take_s: Literal[4, 6, 8]  # what Veo makes
    use_s: int  # the seconds the edit keeps (2..take_s): the editor's call
    link: Literal["cut", "continuous", "match"]
    why: str  # one sentence: the shot's story function, then how it delivers it
    ir: dict[str, Any]  # setting, cinematography{...}, lighting, subjects[], beats[], audio, first_frame{...}
    sound: SoundW

    @property
    def framing(self) -> str:
        """The size as the shared parts know it (`shots.framing`, the staging kernel)."""
        return FRAMING.get(self.size, self.size)


class AddedW(_Wire):
    shot: int
    kind: Literal["baseline", "reaction", "listener", "insert_detail", "hands", "pov", "atmosphere", "hold", "plant",
                  "transition", "empty_frame", "implied_action", "move"]
    what: str
    who: list[str]
    object: str  # the object an insert or a plant shows, "" when none: it must be in the script or on the place card


class MarkW(_Wire):
    block: int  # from this block on...
    who: str
    zone: str
    facing: Literal["", "left", "right", "camera", "away"]
    frame_side: Literal["", "left", "right", "centre"]
    holding: str


class StagingW(_Wire):
    zones: list[str]
    marks: list[MarkW]


class PersonW(_Wire):
    who: str
    where: str
    facing: str
    holding: str
    look: str  # what they wear and how they look at the end (an injury, a wet shirt)


class PropW(_Wire):
    what: str
    where: str


class EndStateW(_Wire):
    people: list[PersonW]
    props: list[PropW]
    time: str
    light: str


class JonathanWire(_Wire):
    treatment: TreatmentW
    sequences: list[SequenceW]
    shots: list[ShotW]
    added: list[AddedW]
    staging: StagingW
    end_state: EndStateW

    def shot(self, n: int) -> ShotW | None:
        return next((s for s in self.shots if s.n == n), None)

    def treatment_text(self) -> list[str]:
        """Every word of the treatment and the sequences: the checks that read free text (a stranger named, speech
        quoted) read all of it."""
        t = self.treatment
        return [t.logline, t.approach, t.geography, t.key_image, *t.advice,
                *(f"{a.beat} {a.feeling}" for a in t.arc),
                *(f"{c.palette} {c.light} {c.grade}" for c in t.colour_script),
                *(f"{s.title} {s.purpose}" for s in self.sequences)]

    @property
    def notes(self) -> str:
        """The treatment as one text (where a shared part wants the plan in words)."""
        return "\n".join(self.treatment_text())

    def renumbered(self) -> JonathanWire:
        """The shots numbered 1.. in the order they play, the additions following their shots, the sequences' spans
        written again from the shots."""
        return self.model_copy(update=renumber(self.shots, self.added)).respanned()

    def without(self, numbers: set[int]) -> JonathanWire:
        """The plan without these shots (and their additions); the rest renumbered."""
        shots = [s for s in self.shots if s.n not in numbers]
        added = [a for a in self.added if a.shot not in numbers]
        return self.model_copy(update=renumber(shots, added)).respanned()

    def respanned(self) -> JonathanWire:
        """Each sequence's first and last shot, written again from the shots' own `sequence` (shots move when one is
        cut, dropped or split). A sequence left with no shot keeps its span; the check reports it."""
        spans = []
        for q in self.sequences:
            mine = [s.n for s in self.shots if s.sequence == q.id]
            spans.append(q.model_copy(update={"shots": SpanW(first=min(mine), last=max(mine))}) if mine else q)
        return self.model_copy(update={"sequences": spans})


def renumber(shots: list[ShotW], added: list[AddedW]) -> dict[str, Any]:
    """`{"shots": ..., "added": ...}` with the shots numbered 1.. in order; an addition follows its shot, one that
    names a shot the list lacks is dropped."""
    new = {s.n: i for i, s in enumerate(shots, start=1)}
    if len(new) != len(shots):  # numbers repeated: the model's numbering is unusable, so keep list order and drop none
        return {"shots": [s.model_copy(update={"n": i}) for i, s in enumerate(shots, start=1)],
                "added": [a for a in added if 1 <= a.shot <= len(shots)]}
    return {"shots": [s.model_copy(update={"n": new[s.n]}) for s in shots],
            "added": sorted((a.model_copy(update={"shot": new[a.shot]}) for a in added if a.shot in new),
                            key=lambda a: a.shot)}


def card_size(size: str) -> str:
    """Jonathan's size in the vocabulary of the shot card the shared card reader (`serialize.card`) knows."""
    near = FRAMING.get(size, size)
    return {"WIDE": "WS", "TWO": "MS", "OTS": "MS"}.get(near, near)
