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

The scene STATE LEDGER (plan/2026-11-09 phase 1): a mark also says a person's posture, which hand holds what, their
condition (dead, unconscious, injured, soaked) and a change of clothes; a `PropMark` says where a prop is when it is in
no hand. Every field is optional (`""`), so a map written before reads unchanged. Code then gives the state at any block
for free (`state_at`, `delta_text`, `clip_state`): the memory every later step reads instead of guessing.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from contracts import bridges
from contracts import holding as hd
from contracts import reading as rd
from contracts.production import Framing
from contracts.shotplan import HEARD_MARKS, FitResult, Item
from contracts.veo import CameraLink

OFF = "off"  # not in the place: before an entrance, after an exit
FRAME_SIDES = ("left", "right", "centre")
FACINGS = ("left", "right", "camera", "away")  # a direction in the frame
POSTURES = ("standing", "sitting", "kneeling", "crouching", "lying", "walking", "running")
HANDS = ("left", "right")
WELL = "well"  # the condition that ends one ("wakes up"): a mark's empty condition keeps the last one
MAX_ZONES = 6
MAX_MARKS = 60
MAX_PROPS = 30
STATE_CHARS = 160  # one person's state phrase, at most
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
    # plan/2026-11-09: the state ledger. All optional; a map written before reads unchanged.
    posture: str = ""  # "" (not said: the last one holds) | one of POSTURES
    left_hand: str = Field(default="", max_length=60)  # what the left hand holds ("the phone"); also in `holding`
    right_hand: str = Field(default="", max_length=60)
    condition: str = Field(default="", max_length=40)  # "" (the last one holds) | "dead" | "injured: left arm" | well
    wearing: str = Field(default="", max_length=80)  # only a change from the canon look ("jacket off")


class PropMark(BaseModel):
    """From block `block` on, `prop` is in no hand: it is `where` ("on the ground by the three-wheeler"), in `state`
    ("open"). A person who takes it ends the mark."""

    model_config = ConfigDict(extra="ignore")

    block: int = Field(ge=0)
    anchor: str = ""
    prop: str = Field(max_length=60)
    where: str = Field(default="", max_length=60)
    state: str = Field(default="", max_length=40)


class SceneStaging(BaseModel):
    model_config = ConfigDict(extra="ignore")

    zones: list[str] = Field(default_factory=list)
    marks: list[Mark] = Field(default_factory=list)
    props: list[PropMark] = Field(default_factory=list)
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

    def placed_props(self, items: Sequence[Item]) -> list[tuple[int, PropMark]]:
        """Every prop mark as (item index in THESE items, mark), in script order; one whose block is gone is out."""
        out = [(at, p) for p in self.props if (at := rd.resolve(p.block, p.anchor, self.basis, items)) is not None]
        return sorted(out, key=lambda r: r[0])

    def text(self, items: Sequence[Item] | None = None) -> str:
        """The map as a prompt or a person reads it (data, not instructions). A mark with none of the ledger's fields
        reads as it always did."""
        rows = [f"Spots: {', '.join(self.zones)}" if self.zones else ""]
        for m in self.marks:
            bits = [m.posture, f"in the {m.zone}" if m.zone != OFF else "off", f"facing {m.facing}" if m.facing else "",
                    f"{m.frame_side} of frame" if m.frame_side else "", f"holding {m.holding}" if m.holding else "",
                    f"{m.left_hand} in the left hand" if m.left_hand else "",
                    f"{m.right_hand} in the right hand" if m.right_hand else "", m.condition,
                    f"wearing {m.wearing}" if m.wearing else ""]
            rows.append(f"From block {m.block}: {m.who} " + ", ".join(b for b in bits if b))
        for p in self.props:
            rows.append(f"From block {p.block}: {p.prop} " + ", ".join(b for b in (p.where, p.state) if b))
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
        posture = _clean(row.get("posture"), 20).casefold()
        left, right = _hand(row.get("left_hand")), _hand(row.get("right_hand"))
        marks.append(Mark(block=block, anchor=rd.block_key(items[block]), who=who, zone=zone, facing=facing,
                          frame_side=side, holding=_with_hands(_clean(row.get("holding"), 80), left, right),
                          posture=posture if posture in POSTURES else "", left_hand=left, right_hand=right,
                          condition=_clean(row.get("condition"), 40), wearing=_clean(row.get("wearing"), 80)))
        if len(marks) == MAX_MARKS:
            break
    marks.sort(key=lambda m: (m.block, m.who.casefold()))
    props: list[PropMark] = []
    seen_props: set[tuple[str, int]] = set()
    for row in raw.get("props") or []:
        try:
            block = int(row["block"])
        except (KeyError, TypeError, ValueError):
            continue
        prop = _clean(row.get("prop"), 60)
        thing = hd.thing_of(prop)
        if not (0 <= block < n) or thing is None or (thing.key, block) in seen_props:
            continue
        seen_props.add((thing.key, block))
        props.append(PropMark(block=block, anchor=rd.block_key(items[block]), prop=prop,
                              where=_clean(row.get("where"), 60), state=_clean(row.get("state"), 40)))
        if len(props) == MAX_PROPS:
            break
    props.sort(key=lambda p: (p.block, p.prop.casefold()))
    if len(zones) < 2:
        marks, props = [], []
    marks, props = settle(marks, props, items)
    return SceneStaging(zones=zones if len(zones) >= 2 else [], marks=marks, props=props, by=by,
                        for_version=version, basis=rd.basis(items))


def _hand(value: Any) -> str:
    text = _clean(value, 60)
    return "" if text.casefold() in hd.EMPTY else text


def _with_hands(holding: str, *hands: str) -> str:
    """`holding` with what a named hand holds added when it is missing, so `holding.Ledger` keeps one holder a prop."""
    keys = {t.key for t in hd.things_of(holding)}
    extra = [h for h in hands if h and (t := hd.thing_of(h)) is not None and t.key not in keys]
    return ", ".join(p for p in (holding, *extra) if p)[:80] if extra else holding


def _without(holding: str, key: str) -> str:
    """`holding` with the thing `key` taken out (it was put down)."""
    parts = re.split(r",|;|&|\+|\band\b|\bwith\b|\bthen\b", holding, flags=re.IGNORECASE)
    kept = [" ".join(p.split()) for p in parts if p.strip() and getattr(hd.thing_of(p), "key", "") != key]
    return ", ".join(kept)


def settle(marks: list[Mark], props: list[PropMark], items: Sequence[Item]) -> tuple[list[Mark], list[PropMark]]:
    """Code, so the hands and the props never disagree (plan/2026-11-09 phase 1). A prop mark at block N for a thing a
    person's mark AT N still holds is dropped (the person's mark wins at its own block); for a thing a person's EARLIER
    mark still holds, the person gets a mark at N that no longer holds it (it left their hand there). A person who takes
    the thing later ends the prop mark by their own mark (`state_at` reads the later of the two)."""
    marks = list(marks)
    kept: list[PropMark] = []
    for p in props:
        thing = hd.thing_of(p.prop)
        assert thing is not None
        key = thing.key
        latest: dict[str, Mark] = {}
        for m in sorted(marks, key=lambda x: x.block):
            if m.block <= p.block:
                latest[m.who.casefold()] = m
        # one holder a thing: of the people whose latest mark holds it, the one who took it last
        takers = [m for m in latest.values() if key in {t.key for t in hd.things_of(m.holding)}]
        holder = max(takers, key=lambda m: m.block) if takers else None
        if holder is None:
            kept.append(p)
            continue
        if holder.block == p.block:
            continue  # the person's own mark at this block says the thing is in a hand
        if len(marks) >= MAX_MARKS:
            continue
        drop = {"holding": _without(holder.holding, key), "block": p.block, "anchor": rd.block_key(items[p.block])}
        for hand in ("left_hand", "right_hand"):
            held = hd.thing_of(getattr(holder, hand))
            if held is not None and held.key == key:
                drop[hand] = ""
        marks.append(holder.model_copy(update=drop))
        kept.append(p)
    marks.sort(key=lambda m: (m.block, m.who.casefold()))
    return marks, kept


def remap(staging: SceneStaging, items: Sequence[Item], where: Sequence[int]) -> SceneStaging:
    """The map carried across blocks that were INSERTED (implied moves); `where[old index]` is the new index."""
    marks = [m.model_copy(update={"block": where[m.block] if 0 <= m.block < len(where) else m.block})
             for m in staging.marks]
    props = [p.model_copy(update={"block": where[p.block] if 0 <= p.block < len(where) else p.block})
             for p in staging.props]
    return staging.model_copy(update={"marks": marks, "props": props, "basis": rd.basis(items)})


def pinned(staging: SceneStaging, items: Sequence[Item], onto: Sequence[Item]) -> SceneStaging:
    """The map with every mark and prop mark resolved against `items` (the scene's script) and written for `onto`, a
    copy of the same blocks another way (a planner's own scene shape, the same block numbers): what is gone is left
    out, and `onto` reads the map with no anchors to look up."""
    by_index = {i.index: i for i in onto}
    marks = [m.model_copy(update={"block": at, "anchor": rd.block_key(by_index[at])})
             for rows in staging.placed(items).values() for at, m in rows if at in by_index]
    props = [p.model_copy(update={"block": at, "anchor": rd.block_key(by_index[at])})
             for at, p in staging.placed_props(items) if at in by_index]
    marks.sort(key=lambda m: (m.block, m.who.casefold()))
    return staging.model_copy(update={"marks": marks, "props": props, "basis": rd.basis(onto), "written_at": None})


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


# ── the state ledger: the state at any block, from the map, by code (plan/2026-11-09 phase 1) ───────────────────


@dataclass(frozen=True)
class PersonState:
    """One person as a block ends: where, how they stand, what each hand holds, their condition and clothes."""

    who: str
    zone: str = ""
    posture: str = ""
    held: tuple[tuple[str, str, str], ...] = ()  # (key, how to say it, hand: left | right | "") in a hand
    worn: tuple[str, ...] = ()  # how to say what they carry without a hand (a bag on the shoulder)
    condition: str = ""
    wearing: str = ""
    facing: str = ""
    side: str = ""

    def keys(self) -> set[str]:
        return {k for k, _, _ in self.held}

    def hand_of(self, key: str) -> str:
        return next((h for k, _, h in self.held if k == key), "")

    def place_text(self) -> str:
        return "off" if self.zone == OFF else f"at the {self.zone}" if self.zone else ""

    def hands_text(self) -> list[str]:
        out = [f"{text} in {hand} hand" if hand else f"holding the {text}" for _, text, hand in self.held]
        return out + [f"carrying the {text}" for text in self.worn]

    def text(self) -> str:
        """ "Kasun: running, at the pavement, phone in right hand" (at most `STATE_CHARS`)."""
        if self.zone == OFF:
            return f"{self.who}: off"
        bits = [self.posture, self.place_text(), *self.hands_text(), self.condition,
                f"wearing {self.wearing}" if self.wearing else ""]
        return f"{self.who}: {', '.join(b for b in bits if b)}"[:STATE_CHARS]


@dataclass(frozen=True)
class PropState:
    """One prop as a block ends: in whose hand, or where it lies."""

    key: str
    text: str
    holder: str = ""
    hand: str = ""
    worn: bool = False
    where: str = ""
    state: str = ""

    def __str__(self) -> str:
        if self.holder:
            how = f"{self.holder}'s {self.hand} hand" if self.hand else (
                f"carried by {self.holder}" if self.worn else f"held by {self.holder}")
            return f"{self.text}: {how}"
        bits = [b for b in (self.where, self.state) if b]
        return f"{self.text}: {', '.join(bits)}" if bits else ""


@dataclass(frozen=True)
class SceneState:
    """Everyone and every prop the map knows, as one block ends. Empty: no map, or before anyone is placed."""

    people: dict[str, PersonState] = field(default_factory=dict)  # casefolded name → state
    props: dict[str, PropState] = field(default_factory=dict)  # thing key → state

    def __bool__(self) -> bool:
        return bool(self.people or self.props)

    def person(self, who: str) -> PersonState | None:
        return self.people.get(who.casefold())

    def person_text(self, who: str) -> str:
        p = self.person(who)
        return p.text() if p else ""

    def prop_text(self, key: str) -> str:
        p = self.props.get(key)
        return str(p) if p else ""

    def loose(self) -> list[PropState]:
        """The props in no hand that the map places somewhere."""
        return [p for p in self.props.values() if not p.holder and str(p)]

    def text(self, *, props: bool = True) -> str:
        rows = [p.text() for p in self.people.values()]
        if props:
            rows += [str(p) for p in self.loose()]
        return "; ".join(r for r in rows if r)


def _held_after(ledger: hd.Ledger, block: int) -> dict[str, tuple[str, int]]:
    """key → (who holds it, the block they took it) once block `block` has played (every change at or before it)."""
    holder: dict[str, tuple[str, int]] = {}
    for c in ledger.changes:
        if c.block > block:
            continue
        if c.taker:
            holder[c.key] = (c.taker, c.block)
        elif holder.get(c.key, ("", 0))[0] == c.giver:
            del holder[c.key]
    return holder


def _latest(values: Iterable[str]) -> str:
    out = ""
    for v in values:
        if v:
            out = "" if v.casefold() == WELL else v
    return out


def ledger_of(staging: SceneStaging | None, items: Sequence[Item]) -> hd.Ledger:
    """The map's holdings as a `holding.Ledger`, at the block numbers of THESE items, with the hand each mark names."""
    if staging is None:
        return hd.Ledger()
    return hd.Ledger.of({"block": at, "who": m.who, "holding": m.holding, "left_hand": m.left_hand,
                         "right_hand": m.right_hand}
                        for marks in staging.placed(items).values() for at, m in marks)


def state_at(staging: SceneStaging | None, items: Sequence[Item], block: int) -> SceneState:
    """The scene as block `block` ends (`block` -1: before anything). For each person their latest mark at or before
    it (posture, condition and clothes hold until a mark says otherwise; `well` ends a condition); for each prop its
    holder (`holding.Ledger`, one holder a prop) or, when its latest prop mark is later than the hand that took it, the
    place the mark gives."""
    if staging is None or not (staging.marks or staging.props):
        return SceneState()
    placed = staging.placed(items)
    ledger = ledger_of(staging, items)
    held = _held_after(ledger, block)
    loose: dict[str, tuple[int, PropMark]] = {}
    for at, pm in staging.placed_props(items):
        thing = hd.thing_of(pm.prop)
        if thing is not None and at <= block:
            loose[thing.key] = (at, pm)
    for key, (at, _) in loose.items():
        if key in held and at > held[key][1]:
            del held[key]  # it left the hand after it was taken
    people: dict[str, PersonState] = {}
    props: dict[str, PropState] = {}
    for name, marks in placed.items():
        mine = [(at, m) for at, m in marks if at <= block]
        if not mine:
            continue
        last = mine[-1][1]
        hands: list[tuple[str, str, str]] = []
        worn: list[str] = []
        for key, (who, _) in sorted(held.items()):
            if who.casefold() != name:
                continue
            thing = ledger.things[key]
            side = ledger.side(who, key, block)
            if thing.worn:
                worn.append(thing.text)
            else:
                hands.append((key, thing.text, side))
            props[key] = PropState(key=key, text=thing.text, holder=last.who, hand=side, worn=thing.worn)
        people[name] = PersonState(
            who=last.who, zone=last.zone, posture=_latest(m.posture for _, m in mine), held=tuple(hands),
            worn=tuple(worn), condition=_latest(m.condition for _, m in mine),
            wearing=_latest(m.wearing for _, m in mine), facing=last.facing, side=last.frame_side)
    for key, (_, pm) in loose.items():
        if key not in props:
            thing = hd.thing_of(pm.prop)
            assert thing is not None
            props[key] = PropState(key=key, text=thing.text, where=pm.where, state=pm.state)
    return SceneState(people=people, props=props)


def state_before(staging: SceneStaging | None, items: Sequence[Item], block: int) -> SceneState:
    """The scene as block `block` opens: the state after the block before it, and the people who come into the scene
    at this block as they arrive (Anudi steps out of the car holding the umbrella)."""
    before, at = state_at(staging, items, block - 1), state_at(staging, items, block)
    arriving = {k: v for k, v in at.people.items() if k not in before.people}
    if not arriving:
        return before
    props = dict(before.props)
    for key, p in at.props.items():
        if p.holder.casefold() in arriving:
            props[key] = p
    return SceneState(people={**before.people, **arriving}, props=props)


def delta_text(before: SceneState, after: SceneState) -> str:
    """Only what changed, person by person ("Anudi: phone in left hand"), then the props that came to rest somewhere
    ("phone: on the ground by the three-wheeler"). A prop in a hand is said once, on its holder."""
    out: list[str] = []
    for key, a in after.people.items():
        b = before.people.get(key)
        if b is None or (a.zone == OFF) != (b.zone == OFF):
            out.append(a.text())
            continue
        if a.zone == OFF:
            continue
        bits = [a.posture if a.posture != b.posture else "", a.place_text() if a.zone != b.zone else ""]
        if (a.held, a.worn) != (b.held, b.worn):
            bits += a.hands_text() or ["hands empty"]
        if a.condition != b.condition:
            bits.append(a.condition or WELL)
        if a.wearing != b.wearing and a.wearing:
            bits.append(f"wearing {a.wearing}")
        said = [x for x in bits if x]
        if said:
            out.append(f"{a.who}: {', '.join(said)}"[:STATE_CHARS])
    for p in after.loose():
        if str(before.props.get(p.key, "")) != str(p):
            out.append(str(p))
    return "; ".join(out)


def clip_state(staging: SceneStaging | None, items: Sequence[Item], blocks: Iterable[int]
               ) -> tuple[SceneState, SceneState]:
    """→ (the state as a clip over these blocks opens, as it ends). With no block there is nothing to say: the
    caller gives a clip with no block of its own the blocks it plays over (`holding.window`)."""
    covered = sorted(set(blocks))
    if not covered:
        return SceneState(), SceneState()
    return state_before(staging, items, covered[0]), state_at(staging, items, covered[-1])
