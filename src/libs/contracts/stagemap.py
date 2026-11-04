"""The staging map: where everyone is, block by block (plan/2026-11-01d, Phase 4).

A shot list is only as continuous as the places it puts people. Nothing used to know that a person ends one shot
at the gate and starts the next at the stall. The map gives a scene 2 to 6 named SPOTS (zones) and, for each person,
MARKS: from this block on, this person is in this zone, facing this way, on this side of the frame. A mark holds
until the person's next mark, so the model only says what changes.

Free checks, in code, never by a prompt:

* `teleports`     a person changes zone between two blocks and nothing in between moves them. Entering from or
                  leaving to `off` is not one (the script says "enters"). Each is fixed by ONE implied step,
                  `bridges.move_block` ("Anudi crosses to the gate"), unless a person removed it before.
* `line_crossed`  two shots in a row put the same two people on opposite sides of the frame with no `match` link
                  (the 180 degree rule), and neither moved.
* `eyeline`       a shot / reverse shot whose two singles look the same way, so the two never look at each other.

A map never changes a word of the script and never adds a person, a line or a story event. It is validated entry by
entry: an invalid entry is DROPPED, not repaired. Pure standard library + pydantic (the `contracts` rule).
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from contracts import bridges
from contracts import reading as rd
from contracts.production import Framing
from contracts.shotplan import HEARD_MARKS, FitResult, Item
from contracts.veo import CameraLink

OFF = "off"  # not in the place: before an entrance, after an exit
FRAME_SIDES = ("left", "right", "centre")
FACINGS = ("left", "right", "camera", "away")  # a direction in the frame
MAX_ZONES = 6
MAX_MARKS = 60
SINGLES = (Framing.MS.value, Framing.MCU.value, Framing.CU.value)

StagingBy = Literal["", "model", "person"]


class Mark(BaseModel):
    """From block `block` on, `who` is in `zone` (until their next mark)."""

    model_config = ConfigDict(extra="ignore")

    block: int = Field(ge=0)
    anchor: str = ""  # that block's `block_key`, so the mark follows its block through a script edit
    who: str = Field(max_length=120)
    zone: str = Field(max_length=60)  # one of the map's zones, or `off`
    facing: str = ""  # "" (not said) | left | right | camera | away: the way they look in the frame
    frame_side: str = ""  # "" | left | right | centre: where they stand in the frame when they share it
    holding: str = Field(default="", max_length=80)  # what is in their hands ("the phone", "a plate")


class SceneStaging(BaseModel):
    model_config = ConfigDict(extra="ignore")

    zones: list[str] = Field(default_factory=list)
    marks: list[Mark] = Field(default_factory=list)
    by: StagingBy = ""
    for_version: int = 0  # the scene's script_version it was written for
    basis: str = ""  # `reading.basis(items)` when it was written; a different script is a stale map
    written_at: str | None = None

    @classmethod
    def of(cls, scene: Mapping[str, Any] | None) -> SceneStaging | None:
        raw = (scene or {}).get("staging") or {}
        if not raw:
            return None
        try:
            staging = cls.model_validate(raw)
        except ValueError:
            return None
        return staging if staging.by else None

    def stale(self, items: Sequence[Item], version: int) -> bool:
        return self.for_version != version or self.basis != rd.basis(items)

    def placed(self, items: Sequence[Item]) -> dict[str, list[tuple[int, Mark]]]:
        """casefolded name → their marks as (item index in THESE items, mark), in script order. A mark whose block
        is gone is left out."""
        out: dict[str, list[tuple[int, Mark]]] = {}
        for m in self.marks:
            at = rd.resolve(m.block, m.anchor, self.basis, items)
            if at is not None:
                out.setdefault(m.who.casefold(), []).append((at, m))
        for rows in out.values():
            rows.sort(key=lambda r: r[0])
        return out

    def mark_at(self, items: Sequence[Item], who: str, block: int) -> Mark | None:
        """Where `who` is at `block`: their latest mark at or before it."""
        rows = [m for at, m in self.placed(items).get(who.casefold(), []) if at <= block]
        return rows[-1] if rows else None

    def text(self, items: Sequence[Item] | None = None) -> str:
        """The map as a prompt or a person reads it (data, not instructions)."""
        rows = [f"Spots: {', '.join(self.zones)}" if self.zones else ""]
        for m in self.marks:
            bits = [f"in the {m.zone}" if m.zone != OFF else "off", f"facing {m.facing}" if m.facing else "",
                    f"{m.frame_side} of frame" if m.frame_side else "", f"holding {m.holding}" if m.holding else ""]
            rows.append(f"From block {m.block}: {m.who} " + ", ".join(b for b in bits if b))
        return "\n".join(r for r in rows if r)


# ── validation: an invalid entry is dropped, not repaired ───────────────────────────────────


def _clean(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def validate(raw: Mapping[str, Any], items: Sequence[Item], cast: Iterable[str] = (), *, version: int,
             by: StagingBy, keep_zones: Iterable[str] = ()) -> SceneStaging:
    """A model's (or a person's) answer → a map that is true to THESE items: zones are 2 to 6 distinct names (never
    `off`); a mark names a block that exists, a person who is in the scene, one of the zones (or `off`), a direction
    and frame side from the closed lists; a person has one mark per block."""
    here = rd.present(items, cast)
    n = len(items)
    zones: list[str] = []
    for z in [*(raw.get("zones") or []), *keep_zones]:
        name = _clean(z, 60)
        if name and name.casefold() != OFF and name.casefold() not in {x.casefold() for x in zones}:
            zones.append(name)
    zones = zones[:MAX_ZONES]
    by_name = {z.casefold(): z for z in zones}

    marks: list[Mark] = []
    seen: set[tuple[str, int]] = set()
    for row in raw.get("marks") or []:
        try:
            block = int(row["block"])
        except (KeyError, TypeError, ValueError):
            continue
        who = _clean(row.get("who"), 120)
        zone_said = _clean(row.get("zone"), 60).casefold()
        zone = OFF if zone_said == OFF else by_name.get(zone_said, "")
        facing, side = _clean(row.get("facing"), 10).casefold(), _clean(row.get("frame_side"), 10).casefold()
        if not (0 <= block < n) or not rd.is_present(who, here) or not zone:
            continue
        if facing not in ("", *FACINGS) or side not in ("", *FRAME_SIDES):
            continue
        if (who.casefold(), block) in seen:
            continue
        seen.add((who.casefold(), block))
        marks.append(Mark(block=block, anchor=rd.block_key(items[block]), who=who, zone=zone, facing=facing,
                          frame_side=side, holding=_clean(row.get("holding"), 80)))
        if len(marks) == MAX_MARKS:
            break
    marks.sort(key=lambda m: (m.block, m.who.casefold()))
    return SceneStaging(zones=zones if len(zones) >= 2 else [], marks=marks if len(zones) >= 2 else [], by=by,
                        for_version=version, basis=rd.basis(items))


def remap(staging: SceneStaging, items: Sequence[Item], where: Sequence[int]) -> SceneStaging:
    """The map carried across blocks that were INSERTED (implied moves); `where[old index]` is the new index."""
    marks = [m.model_copy(update={"block": where[m.block] if 0 <= m.block < len(where) else m.block})
             for m in staging.marks]
    return staging.model_copy(update={"marks": marks, "basis": rd.basis(items)})


def unplaced(staging: SceneStaging, items: Sequence[Item], cast: Iterable[str] = ()) -> list[str]:
    """People the scene has (they speak or the action names them) that the map gives no mark: nothing about them is
    checked. Names as the script spells them."""
    placed = staging.placed(items)
    names = {i.speaker.casefold(): i.speaker for i in items if i.is_line and i.speaker}
    for c in cast:
        if c and c.casefold() not in names and c.casefold() in rd.present(items, [c]):
            names[c.casefold()] = c
    return sorted(v for k, v in names.items() if k not in placed)


# ── who is in a shot ───────────────────────────────────────────────────────────────────────


def _heard(item: Item) -> bool:
    return item.is_line and any(m in f"{item.delivery} {item.speaker}".lower() for m in HEARD_MARKS)


def people_in(block: Sequence[Item], cast: Iterable[str] = (), *, holds: bool = True) -> list[str]:
    """Casefolded names of the people a shot visibly has: who speaks on camera, who the action names, and (with
    `holds`) whose face a hold is for. A voice that is only heard is not here."""
    cast = list(cast)
    out: list[str] = []

    def add(name: str) -> None:
        if name and name.casefold() not in out:
            out.append(name.casefold())

    for it in block:
        if it.is_line and not _heard(it):
            add(it.speaker)
        elif it.kind == "action":
            for c in cast:
                if re.search(rf"\b{re.escape(c)}\b", it.text, re.IGNORECASE):
                    add(c)
        if holds:
            add(it.hold_who)
    return out


# ── teleports ──────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Finding:
    """A staging problem a person should see. `code`: teleport | line_crossed | eyeline."""

    code: str
    message: str
    block: int | None = None  # teleport: the block where the person is already somewhere else
    shot: int | None = None  # line_crossed, eyeline: the shot number that follows the cut
    who: tuple[str, ...] = ()
    zone: str = ""  # teleport: where they are now


def _moves(item: Item, who: str, cast: Sequence[str]) -> bool:
    """Does this block move `who` through space? A move names them, or names no one (a pronoun: "She walked away")."""
    if item.kind != "action" or item.screen != "move":
        return False
    named = [c for c in cast if re.search(rf"\b{re.escape(c)}\b", item.text, re.IGNORECASE)]
    return not named or who.casefold() in {c.casefold() for c in named}


def teleports(staging: SceneStaging | None, items: Sequence[Item], cast: Iterable[str] = ()) -> list[Finding]:
    """Everyone whose zone changes between two marks with no move between them (entrances and exits excepted)."""
    if staging is None or not staging.marks:
        return []
    cast = [*cast, *dict.fromkeys(i.speaker for i in items if i.is_line and i.speaker)]
    out: list[Finding] = []
    for rows in staging.placed(items).values():
        for (a, before), (b, after) in pairwise(rows):
            if before.zone == after.zone or OFF in (before.zone, after.zone):
                continue
            if any(_moves(i, after.who, cast) for i in items[a + 1:b + 1]):
                continue
            out.append(Finding("teleport", f"{after.who} is at the {before.zone}, and by block {b} at the "
                                           f"{after.zone}, with nothing to show the way.", block=b,
                               who=(after.who,), zone=after.zone))
    return sorted(out, key=lambda f: (f.block or 0, f.who))


def plan_moves(staging: SceneStaging | None, items: Sequence[Item], cast: Iterable[str] = ()
               ) -> list[tuple[int, str, str]]:
    """→ [(item index to come before, who, zone)]: one implied step for each teleport, except a move a person
    already removed (it is remembered on the block after it, `bridges.move_kind`)."""
    out = []
    for f in teleports(staging, items, cast):
        assert f.block is not None
        if bridges.move_kind(f.who[0]) in items[f.block].skip:
            continue
        out.append((f.block, f.who[0], f.zone))
    return out


# ── the cuts: 180 degree rule and eyeline ──────────────────────────────────────────────────


def _side(staging: SceneStaging, items: Sequence[Item], who: str, block: int) -> str:
    mark = staging.mark_at(items, who, block)
    return mark.frame_side if mark and mark.frame_side in ("left", "right") else ""


def _zone(staging: SceneStaging, items: Sequence[Item], who: str, block: int) -> str:
    mark = staging.mark_at(items, who, block)
    return mark.zone if mark else ""


def line_crossed(staging: SceneStaging | None, items: Sequence[Item], result: FitResult,
                 cast: Iterable[str] = ()) -> list[Finding]:
    """Cuts that swap two people's sides of the frame without a `match` (a deliberate re-angle)."""
    if staging is None or not staging.marks:
        return []
    cast = list(cast)
    out: list[Finding] = []
    for a, b in pairwise(result.shots):
        if b.camera_link is CameraLink.MATCH:
            continue
        both = [w for w in people_in(items[a.start:a.end], cast) if w in people_in(items[b.start:b.end], cast)]
        for w1, w2 in pairwise(both):
            sa1, sa2 = _side(staging, items, w1, a.start), _side(staging, items, w2, a.start)
            sb1, sb2 = _side(staging, items, w1, b.start), _side(staging, items, w2, b.start)
            if not (sa1 and sa2 and sb1 and sb2 and sa1 != sa2 and sb1 != sb2) or (sa1 == sb1):
                continue
            moved = any(_zone(staging, items, w, a.start) != _zone(staging, items, w, b.start) for w in (w1, w2))
            if not moved:
                out.append(Finding("line_crossed", f"The cut into S{b.number:02d} swaps {w1.title()} and "
                                                   f"{w2.title()} to opposite sides of the frame.", shot=b.number,
                                   who=(w1, w2)))
    return out


def eyeline(staging: SceneStaging | None, items: Sequence[Item], result: FitResult) -> list[Finding]:
    """A shot / reverse shot (two singles on two people) whose singles face the same way."""
    if staging is None or not staging.marks:
        return []
    out: list[Finding] = []
    for a, b in pairwise(result.shots):
        if a.framing not in SINGLES or b.framing not in SINGLES:
            continue
        first, second = _subject(items[a.start:a.end]), _subject(items[b.start:b.end])
        if not first or not second or first[0].speaker.casefold() == second[0].speaker.casefold():
            continue
        fa = staging.mark_at(items, first[0].speaker, first[0].index)
        fb = staging.mark_at(items, second[0].speaker, second[0].index)
        if fa and fb and fa.facing in ("left", "right") and fa.facing == fb.facing:
            out.append(Finding("eyeline", f"S{a.number:02d} and S{b.number:02d} are a shot and a reverse shot, but "
                                          f"both {first[0].speaker.title()} and {second[0].speaker.title()} face "
                                          f"{fa.facing}, so they do not look at each other.", shot=b.number,
                               who=(first[0].speaker.casefold(), second[0].speaker.casefold())))
    return out


def _subject(block: Sequence[Item]) -> list[Item]:
    """The lines of a single: all by one on-camera speaker."""
    lines = [i for i in block if i.is_line and not _heard(i)]
    return lines if lines and len({i.speaker.casefold() for i in lines}) == 1 else []


def checks(staging: SceneStaging | None, items: Sequence[Item], result: FitResult,
           cast: Iterable[str] = ()) -> list[Finding]:
    """Every staging problem in this plan: teleports, crossed lines, eyelines."""
    cast = list(cast)
    return [*teleports(staging, items, cast), *line_crossed(staging, items, result, cast),
            *eyeline(staging, items, result)]
