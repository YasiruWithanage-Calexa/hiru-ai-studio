"""What David's author and repairer write (plan/2026-11-05e §5): the WIRE shapes, and the plan they are.

A model that answers in strict JSON-schema mode cannot be held to defaults, so the wire shapes have none. They ARE the
plan: David has one shape, not a wire shape and a plan shape (a field exists only if code or the interface reads it,
pattern rule 6). The only part decided at run time is the camera design inside each shot, `ir`: it is the Veo clip
schema the DoP fills too (`steps/serialize/schemas/clip_schema_veo_3_1.yaml`), so the author agent builds that part of
the JSON schema from the YAML (its `output_schema` hook) and here it is a plain object.

    DavidWire    (david_author)   the whole scene: notes, shots with their camera, what was added, staging, end state
    PatchWire    (david_repair)   replacements of numbered runs of shots, and an optional new staging and end state

The conversions keep the model's words and decide nothing: whether a line is missing, a take too short or a person
invented is for the checks (`david_check`). `renumbered`, `without` and `patched` only move shots about.
Pure standard library + pydantic (the `contracts` rule).
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class _Wire(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SoundW(_Wire):
    ambience: str
    effects: str
    music: str
    silence: bool  # the shot asks for silence: Veo must be told, or it invents speech


class ShotW(_Wire):
    n: int
    blocks: list[int]  # script blocks this shot shows ([] for an added shot)
    lines: list[str]  # line ids (L4) spoken in it, never the words
    over: str  # "" or who is SHOWN while a line is heard (a listener shot)
    take_s: Literal[4, 6, 8]
    size: Literal["WIDE", "MS", "MCU", "CU", "TWO", "OTS", "INSERT"]
    link: Literal["cut", "continuous", "match"]
    why: str  # one sentence: what this shot does for the viewer
    ir: dict[str, Any]  # setting, cinematography{...}, lighting, subjects[], beats[], audio, first_frame{...}
    sound: SoundW


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


class DavidWire(_Wire):
    notes: str  # FIRST: what the scene is about, where it turns, whose scene it is, the plan in plain words
    shots: list[ShotW]
    added: list[AddedW]
    staging: StagingW
    end_state: EndStateW

    def renumbered(self) -> DavidWire:
        """The shots numbered 1.. in the order they play, the additions following their shots."""
        return self.model_copy(update=renumber(self.shots, self.added))

    def shot(self, n: int) -> ShotW | None:
        return next((s for s in self.shots if s.n == n), None)

    def without(self, numbers: set[int]) -> DavidWire:
        """The plan without these shots (and their additions); the rest renumbered."""
        shots = [s for s in self.shots if s.n not in numbers]
        added = [a for a in self.added if a.shot not in numbers]
        return self.model_copy(update=renumber(shots, added))

    def patched(self, patch: PatchWire) -> DavidWire:
        """The plan with each replacement spliced in. A replacement removes the shots numbered `replace_from` to
        `replace_to` (inclusive; `replace_to` below `replace_from` removes none, it inserts before `replace_from`) and
        puts its own shots there. A shot the patch leaves alone keeps its additions; those of a removed shot go with
        it, and the replacement's own come with it."""
        order: list[tuple[str, ShotW]] = []
        added: list[tuple[str, int, AddedW]] = []  # (where the shot comes from, its number there, the addition)
        replaced: set[int] = set()
        by_start: dict[int, ReplaceW] = {}
        for r in patch.replaces:
            by_start.setdefault(r.replace_from, r)
            replaced.update(range(r.replace_from, r.replace_to + 1))
        for s in self.shots:
            if s.n in by_start:
                r = by_start.pop(s.n)
                order += [(f"new{id(r)}", x) for x in r.shots]
                added += [(f"new{id(r)}", a.shot, a) for a in r.added]
            if s.n not in replaced:
                order.append(("old", s))
        for r in by_start.values():  # an insertion after the last shot
            order += [(f"new{id(r)}", x) for x in r.shots]
            added += [(f"new{id(r)}", a.shot, a) for a in r.added]
        added += [("old", a.shot, a) for a in self.added if a.shot not in replaced]
        shots: list[ShotW] = []
        where: dict[tuple[str, int], int] = {}
        for source, s in order:
            shots.append(s)
            where.setdefault((source, s.n), len(shots))
        moved = [a.model_copy(update={"shot": where[(source, n)]}) for source, n, a in added if (source, n) in where]
        out = {"shots": [s.model_copy(update={"n": i}) for i, s in enumerate(shots, start=1)],
               "added": sorted(moved, key=lambda a: a.shot)}
        if patch.staging:
            out["staging"] = patch.staging[0]
        if patch.end_state:
            out["end_state"] = patch.end_state[0]
        return self.model_copy(update=out)


class ReplaceW(_Wire):
    replace_from: int
    replace_to: int
    shots: list[ShotW]
    added: list[AddedW]  # additions of the replacement shots; `shot` is the number the replacement shot carries


class PatchWire(_Wire):
    """The repairer's answer: what to replace, and nothing else. It cannot rewrite the plan."""

    replaces: list[ReplaceW]
    staging: list[StagingW]  # [] = unchanged; one entry = the scene's new staging map (a teleport is mended here)
    end_state: list[EndStateW]  # [] = unchanged; one entry = the scene's new end state


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
    """David's size in the vocabulary of the shot card the shared card reader (`serialize.card`) knows."""
    return {"WIDE": "WS", "TWO": "MS", "OTS": "MS"}.get(size, size)

