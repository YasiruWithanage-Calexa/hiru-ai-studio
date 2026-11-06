"""CinemaWire: the shape of the cinematic answer (plan/2026-11-06 §4.2), and its strict JSON schema.

It is David's `DavidWire` plus what a director's plan has and David's lacks: a treatment first (logline, arc, approach,
colour script, geography, key image, advice), sequences, more sizes (EWS, MWS, ECU, POV), the camera's angle and lens,
and `use_s`, the seconds the edit keeps of a take. `to_david()` gives the plan to the existing checks as a `DavidWire`
(the new fields dropped, the new sizes mapped to the nearest old one), so `contracts.david.checks` judges it unchanged.

Field order is the order the model writes: the treatment, then the sequences, then the shots. Like the wire shapes of
`contracts.david.wire`, nothing has a default (strict mode cannot hold a model to one).
"""
from __future__ import annotations

from typing import Any, Literal

from contracts.david.wire import AddedW, DavidWire, EndStateW, ShotW, SoundW, StagingW, _Wire
from hiru_ai.agents.david.wire_schema import wire_schema

Size = Literal["EWS", "WIDE", "MWS", "MS", "MCU", "CU", "ECU", "TWO", "OTS", "INSERT", "POV"]
SIZES: tuple[str, ...] = ("EWS", "WIDE", "MWS", "MS", "MCU", "CU", "ECU", "TWO", "OTS", "INSERT", "POV")
# What the existing checks understand: a size they do not know is read as its nearest (only the staging fit looks).
OLD_SIZE = {"EWS": "WIDE", "MWS": "MS", "ECU": "CU", "POV": "MCU"}
CLOSE = ("MCU", "CU", "ECU")
SCHEMA_NAME = "cinema_plan"


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


class CinemaShotW(_Wire):
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
    why: str  # one sentence: what this shot does for the viewer
    ir: dict[str, Any]  # setting, cinematography{...}, lighting, subjects[], beats[], audio, first_frame{...}
    sound: SoundW

    def david(self) -> ShotW:
        return ShotW(n=self.n, blocks=self.blocks, lines=self.lines, over=self.over, take_s=self.take_s,
                     size=OLD_SIZE.get(self.size, self.size), link=self.link, why=self.why, ir=self.ir,  # type: ignore[arg-type]
                     sound=self.sound)


class CinemaWire(_Wire):
    treatment: TreatmentW
    sequences: list[SequenceW]
    shots: list[CinemaShotW]
    added: list[AddedW]
    staging: StagingW
    end_state: EndStateW

    def shot(self, n: int) -> CinemaShotW | None:
        return next((s for s in self.shots if s.n == n), None)

    def treatment_text(self) -> list[str]:
        t = self.treatment
        return [t.logline, t.approach, t.geography, t.key_image, *t.advice,
                *(f"{a.beat} {a.feeling}" for a in t.arc),
                *(f"{c.palette} {c.light} {c.grade}" for c in t.colour_script),
                *(f"{s.title} {s.purpose}" for s in self.sequences)]

    def to_david(self) -> DavidWire:
        """The plan as the existing checks read it. The notes carry every word of the treatment, so the checks that
        read the notes (a stranger named in them) read the whole treatment."""
        return DavidWire(notes="\n".join(self.treatment_text()), shots=[s.david() for s in self.shots],
                         added=self.added, staging=self.staging, end_state=self.end_state)


def output_schema() -> dict[str, Any]:
    """The strict JSON schema of `CinemaWire`, the Veo clip design written into every shot's `ir`."""
    return wire_schema(CinemaWire, SCHEMA_NAME)
