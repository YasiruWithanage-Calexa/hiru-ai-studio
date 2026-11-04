"""A scene's reading: what the scene is about, before anyone cuts it (plan/2026-11-01d, Phase 1).

The shot list used to be decided from timing and speaker turns alone, and the meaning (purpose, emotional beat)
was painted on afterwards. The reading comes first and every later agent shares it:

* `about`, `value` (the feeling at the start and the end: "joy" → "dread"), `tone`;
* `units`: stretches of the scene in which each person wants one playable thing (Weston: "to charm", "to hide"),
  with the block where the feeling turns;
* `subtext`: every STORY NOTE (a block nobody can film) turned into behaviour an actor could play, or marked
  "narration only" with a reason;
* `breath`: moments to hold (a reaction, a transition, an atmosphere, a button), each with seconds, a priority and
  the reason (`why`);
* `ending`: the last image.

A reading never changes a word of the script and never adds a person, a line or a story event. It is validated in
code, entry by entry: an invalid entry is DROPPED, not repaired. `apply` turns it into time on the kernel's picture
clock (`Item.hold_s`). A person's reading (`by: person`) is never replaced; a script edit marks it stale.

Pure standard library + pydantic (the `contracts` rule).
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from contracts.shotplan import HEARD_MARKS, Item
from contracts.timing import HOLD_RANGE_S

ReadingBy = Literal["", "model", "rules", "person"]
BREATH_KINDS = ("reaction", "transition", "atmosphere", "button")
PRIORITIES = (1, 2, 3)
MAX_BREATH = 12
RULES_REACTION_S = 1.5
RULES_BUTTON_S = 2.0

_ARRIVAL = re.compile(r"\b(?:ring|rings|rang|ringing|buzz|buzzes|buzzed|knock|knocks|knocked|arrive|arrives|arrived|"
                      r"enter|enters|entered|appear|appears|appeared|burst|bursts)\b", re.IGNORECASE)


class Value(BaseModel):
    model_config = ConfigDict(extra="ignore")

    start: str = Field(default="", max_length=60)
    end: str = Field(default="", max_length=60)


class Unit(BaseModel):
    """A stretch of the scene, blocks `from_block`..`to_block` inclusive, in which each person wants one thing."""

    model_config = ConfigDict(extra="ignore")

    from_block: int = Field(ge=0)
    to_block: int = Field(ge=0)
    wants: dict[str, str] = Field(default_factory=dict)  # character name → a playable verb ("to charm", "to hide")
    turn_block: int | None = None  # where the feeling turns inside the unit
    turn_anchor: str = ""  # that block's `block_key`, so the turn survives a script edit


class Subtext(BaseModel):
    model_config = ConfigDict(extra="ignore")

    block: int = Field(ge=0)
    who: str = Field(default="", max_length=120)
    behaviour: str = Field(default="", max_length=400)  # visible behaviour an actor could play
    narration_only: bool = False
    reason: str = Field(default="", max_length=300)  # why a note stays narration


class Breath(BaseModel):
    """A moment to hold, after block `after_block`. `why` names the turn, unit or subtext entry that earns it."""

    model_config = ConfigDict(extra="ignore")

    after_block: int = Field(ge=0)
    anchor: str = ""  # that block's `block_key`, so the breath follows its block through a script edit
    kind: str
    who: str = Field(default="", max_length=120)
    seconds: float
    priority: int
    why: str = Field(default="", max_length=300)
    off: bool = False  # not played: dropped to fit the envelope (`off_by` "envelope") or switched off by a person
    off_by: str = ""


class SceneReading(BaseModel):
    model_config = ConfigDict(extra="ignore")

    about: str = Field(default="", max_length=400)
    value: Value = Field(default_factory=Value)
    tone: str = Field(default="", max_length=80)
    units: list[Unit] = Field(default_factory=list)
    subtext: list[Subtext] = Field(default_factory=list)
    breath: list[Breath] = Field(default_factory=list)
    ending: str = Field(default="", max_length=400)
    by: ReadingBy = ""
    for_version: int = 0  # the scene's script_version it was written for
    basis: str = ""  # `basis(items)` when it was written: a different script is a stale reading
    written_at: str | None = None

    @classmethod
    def of(cls, scene: Mapping[str, Any] | None) -> SceneReading | None:
        raw = (scene or {}).get("reading") or {}
        if not raw:
            return None
        try:
            reading = cls.model_validate(raw)
        except ValueError:
            return None
        return reading if reading.by else None

    def stale(self, items: Sequence[Item], version: int) -> bool:
        return self.for_version != version or self.basis != basis(items)

    def turns(self, items: Sequence[Item]) -> list[int]:
        """Item indexes where the reading says feeling turns."""
        return sorted(self._turn_index(items).values())

    def _turn_index(self, items: Sequence[Item]) -> dict[int, int]:
        """Unit position → item index of its turn block, resolved against THESE items."""
        out: dict[int, int] = {}
        for n, u in enumerate(self.units):
            at = _resolve(u.turn_block, u.turn_anchor, self.basis, items)
            if at is not None:
                out[n] = at
        return out

    def resolved(self, items: Sequence[Item]) -> list[tuple[Breath, int]]:
        """Every breath with the item index it sits after in THESE items; a breath whose block is gone is left out."""
        out: list[tuple[Breath, int]] = []
        for b in self.breath:
            at = _resolve(b.after_block, b.anchor, self.basis, items)
            if at is not None:
                out.append((b, at))
        return out

    def text(self, *, with_off: bool = False) -> str:
        """The reading as the planner and the intent agent read it (data, not instructions)."""
        rows = [f"About: {self.about}" if self.about else "",
                f"Feeling: {self.value.start} → {self.value.end}" if self.value.start or self.value.end else "",
                f"Tone: {self.tone}" if self.tone else ""]
        for n, u in enumerate(self.units, start=1):
            wants = "; ".join(f"{who} {verb}" for who, verb in u.wants.items())
            turn = f"; feeling turns at block {u.turn_block}" if u.turn_block is not None else ""
            rows.append(f"Unit {n}: blocks {u.from_block}-{u.to_block}" + (f"; {wants}" if wants else "") + turn)
        for t in self.subtext:
            rows.append(f"Block {t.block} stays narration ({t.reason})" if t.narration_only
                        else f"Block {t.block} is played as: {t.who} {t.behaviour}")
        for b in self.breath:
            if b.off and not with_off:
                continue
            rows.append(f"Breath after block {b.after_block}: {b.kind}{f' ({b.who})' if b.who else ''}, "
                        f"{b.seconds:g} s, priority {b.priority}, because {b.why}")
        if self.ending:
            rows.append(f"Ending image: {self.ending}")
        return "\n".join(r for r in rows if r)


# ── blocks, by identity ────────────────────────────────────────────────────────────────────


def block_key(item: Item) -> str:
    """A block's identity that survives a re-numbering: its kind and its words (a line: its id)."""
    raw = f"{item.kind}|{item.line_id or ''}|{' '.join(item.text.split())}"
    return hashlib.sha1(raw.encode("utf-8"), usedforsecurity=False).hexdigest()[:10]


def basis(items: Sequence[Item]) -> str:
    """A fingerprint of the blocks a reading was written for. A different script (or implied step) changes it."""
    return hashlib.sha1("\n".join(block_key(i) for i in items).encode("utf-8"), usedforsecurity=False).hexdigest()[:16]


def _resolve(index: int | None, anchor: str, written_for: str, items: Sequence[Item]) -> int | None:
    """Where a stored block reference is in THESE items: the same number while the script is the one the reading
    was written for, else the block with the same identity (None when it is gone)."""
    if index is None:
        return None
    if written_for == basis(items) and 0 <= index < len(items):
        return index
    if not anchor:
        return None
    return next((i.index for i in items if block_key(i) == anchor), None)


def resolve(index: int | None, anchor: str, written_for: str, items: Sequence[Item]) -> int | None:
    """`_resolve` for the other modules that store block references (the staging map)."""
    return _resolve(index, anchor, written_for, items)


def remap(reading: SceneReading, items: Sequence[Item], where: Sequence[int]) -> SceneReading:
    """The reading carried across blocks that were INSERTED (implied moves): `where[old index]` is the new index of
    that block in `items`. Words, authors and anchors do not change; only block numbers and the basis do."""

    def go(block: int) -> int:
        return where[block] if 0 <= block < len(where) else block

    units = [u.model_copy(update={"from_block": go(u.from_block), "to_block": go(u.to_block),
                                  "turn_block": None if u.turn_block is None else go(u.turn_block)})
             for u in reading.units]
    return reading.model_copy(update={
        "units": units,
        "subtext": [t.model_copy(update={"block": go(t.block)}) for t in reading.subtext],
        "breath": [b.model_copy(update={"after_block": go(b.after_block)}) for b in reading.breath],
        "basis": basis(items)})


# ── who is in the scene ────────────────────────────────────────────────────────────────────


def present(items: Sequence[Item], cast: Iterable[str] = ()) -> set[str]:
    """Names (casefolded) of the people the scene has: who speaks, and who the action names."""
    names = {i.speaker.casefold() for i in items if i.is_line and i.speaker}
    action = " ".join(i.text for i in items if i.kind == "action")
    for name in cast:
        if name and re.search(rf"\b{re.escape(name)}\b", action, re.IGNORECASE):
            names.add(name.casefold())
    return names


def is_present(who: str, here: set[str]) -> bool:
    return who.casefold() in here


# ── validation: an invalid entry is dropped, not repaired ──────────────────────────────────


def validate(raw: Mapping[str, Any], items: Sequence[Item], cast: Iterable[str] = (), *, version: int,
             by: ReadingBy) -> SceneReading:
    """A model's (or a person's) answer → a reading that is true to THESE items."""
    here = present(items, cast)
    n = len(items)

    def in_range(x: Any) -> bool:
        return isinstance(x, int) and not isinstance(x, bool) and 0 <= x < n

    def text(value: Any, limit: int) -> str:
        return " ".join(str(value or "").split())[:limit]

    units: list[Unit] = []
    for row in raw.get("units") or []:
        try:
            a, b = int(row["from_block"]), int(row["to_block"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (in_range(a) and in_range(b) and a <= b) or (units and a <= units[-1].to_block):
            continue  # a unit that does not fit, or overlaps the one before, is dropped
        wants = _wants(row.get("wants"))
        wants = {w: v for w, v in wants.items() if is_present(w, here)}
        said = row.get("turn_block")
        turn: int | None = said if in_range(said) and a <= said <= b else None
        units.append(Unit(from_block=a, to_block=b, wants=wants, turn_block=turn,
                          turn_anchor=block_key(items[turn]) if turn is not None else ""))

    # What earns a breath: a turn, the last block of a unit, or a block with subtext. A button needs no turn.
    earned = {u.turn_block for u in units if u.turn_block is not None} | {u.to_block for u in units}
    subtext: list[Subtext] = []
    for row in raw.get("subtext") or []:
        try:
            block = int(row["block"])
        except (KeyError, TypeError, ValueError):
            continue
        if not in_range(block) or any(t.block == block for t in subtext):
            continue
        who, behaviour = text(row.get("who"), 120), text(row.get("behaviour"), 400)
        reason = text(row.get("reason"), 300)
        if row.get("narration_only"):
            if reason:
                subtext.append(Subtext(block=block, who=who, narration_only=True, reason=reason))
        elif behaviour and is_present(who, here):
            subtext.append(Subtext(block=block, who=who, behaviour=behaviour))
    earned |= {t.block for t in subtext if not t.narration_only}

    breath: list[Breath] = []
    lo, hi = HOLD_RANGE_S
    for row in raw.get("breath") or []:
        try:
            after, kind = int(row["after_block"]), str(row["kind"])
            seconds, priority = float(row["seconds"]), int(row["priority"])
        except (KeyError, TypeError, ValueError):
            continue
        who, why = text(row.get("who"), 120), text(row.get("why"), 300)
        if not in_range(after) or kind not in BREATH_KINDS or priority not in PRIORITIES or not lo <= seconds <= hi:
            continue
        if not why or (who and not is_present(who, here)):
            continue
        if any(b.after_block == after for b in breath):
            continue  # at most one breath per block
        if kind == "button" and any(b.kind == "button" for b in breath):
            continue  # at most one button per scene
        if kind != "button" and after not in earned:
            continue  # `why` must name a turn, a unit or a subtext entry
        off = bool(row.get("off"))  # a person's switch-off (or the envelope's) is kept
        breath.append(Breath(after_block=after, anchor=block_key(items[after]), kind=kind, who=who,
                             seconds=round(seconds, 2), priority=priority, why=why, off=off,
                             off_by=text(row.get("off_by"), 20) if off else ""))
        if len(breath) == MAX_BREATH:
            break

    said_value = raw.get("value")
    value: Mapping[str, Any] = said_value if isinstance(said_value, Mapping) else {}
    reading = SceneReading(about=text(raw.get("about"), 400), value=Value(start=text(value.get("start"), 60),
                                                                          end=text(value.get("end"), 60)),
                           tone=text(raw.get("tone"), 80), units=units, subtext=subtext, breath=breath,
                           ending=text(raw.get("ending"), 400), by=by, for_version=version, basis=basis(items))
    return complete_subtext(reading, items)


def _wants(value: Any) -> dict[str, str]:
    """Wants as a model sends them (a list of {character, verb}) or as stored (a dict)."""
    if isinstance(value, Mapping):
        return {str(k).strip(): " ".join(str(v).split())[:80] for k, v in value.items() if str(v).strip()}
    out: dict[str, str] = {}
    for row in value or []:
        if isinstance(row, Mapping) and str(row.get("character", "")).strip() and str(row.get("verb", "")).strip():
            out[str(row["character"]).strip()] = " ".join(str(row["verb"]).split())[:80]
    return out


def story_notes(items: Sequence[Item]) -> list[int]:
    """Blocks nobody can film (`inner`): each one needs behaviour or a reason it stays narration."""
    return [i.index for i in items if i.kind == "action" and i.screen == "inner"]


def _narration(items: Sequence[Item], have: Iterable[int] = ()) -> list[Subtext]:
    """A "narration only" entry for every STORY NOTE not in `have`."""
    skip = set(have)
    return [Subtext(block=b, narration_only=True, reason="no visible behaviour was found for it")
            for b in story_notes(items) if b not in skip]


def complete_subtext(reading: SceneReading, items: Sequence[Item]) -> SceneReading:
    """Every STORY NOTE has an entry: one the reading gave, or "narration only" with the reason that no behaviour
    was found. Nothing is invented here."""
    extra = _narration(items, (t.block for t in reading.subtext))
    return reading.model_copy(update={"subtext": sorted([*reading.subtext, *extra], key=lambda t: t.block)})


# ── the free reading (no key, or the call failed) ──────────────────────────────────────────


def _on_camera(items: Sequence[Item]) -> list[Item]:
    return [i for i in items if i.is_line and not any(m in f"{i.delivery} {i.speaker}".lower() for m in HEARD_MARKS)]


def _listener(items: Sequence[Item], line: Item, cast: Sequence[str] = ()) -> str:
    """Who hears this line. A voice that is only heard (a phone call) is heard by whoever the action just named; any
    other line, by the nearest on-camera speaker who is not its speaker (before it, else after)."""
    if line not in _on_camera(items):
        spoke = max((i.index for i in _on_camera(items) if i.index < line.index), default=-1)
        for block in reversed([i for i in items[spoke + 1:line.index] if i.kind == "action"]):
            named = [c for c in cast if re.search(rf"\b{re.escape(c)}\b", block.text, re.IGNORECASE)]
            if named:
                return max(named, key=lambda c: block.text.lower().rfind(c.lower()))
    others = [i for i in _on_camera(items) if i.speaker.casefold() != line.speaker.casefold()]
    before = [i for i in others if i.index < line.index]
    after = [i for i in others if i.index > line.index]
    near = before[-1] if before else after[0] if after else None
    return near.speaker if near else ""


def by_rules(items: Sequence[Item], cast: Sequence[str] = (), *, version: int) -> SceneReading:
    """The free reading. A turn is a line that follows a small reaction (`with_line`) or a ring/arrival; the reaction
    is the turn when it comes right before the line. Each turn gets one reaction (priority 1), and the last filmed
    action gets the button (priority 1). No subtext (a note stays narration), no verbs."""
    cast = [*cast, *dict.fromkeys(i.speaker for i in items if i.is_line and i.speaker and i.speaker not in cast)]
    turns: list[tuple[int, str]] = []  # (turn block, who reacts)
    for line in (i for i in items if i.is_line):
        prev = items[line.index - 1] if line.index else None
        if prev is not None and prev.kind == "action" and prev.screen == "with_line":
            turns.append((prev.index, line.speaker))  # "She looked at Kasun" before her own line
        elif any(i.kind == "action" and _ARRIVAL.search(i.text) for i in items[max(0, line.index - 3):line.index]):
            turns.append((line.index, _listener(items, line, cast)))  # the call, the knock, the arrival
    turns = sorted(dict(reversed(turns)).items())  # the earliest reading of a block wins

    units: list[Unit] = []
    start = 0
    for b, _ in turns:
        units.append(Unit(from_block=start, to_block=b, turn_block=b, turn_anchor=block_key(items[b])))
        start = b + 1
    if turns and start < len(items):
        units.append(Unit(from_block=start, to_block=len(items) - 1))

    breath = [Breath(after_block=b, anchor=block_key(items[b]), kind="reaction", who=who, seconds=RULES_REACTION_S,
                     priority=1, why=f"the feeling turns at block {b}") for b, who in turns if who]
    filmed = [i for i in items if i.kind == "action" and i.screen not in ("inner", "info") and not i.implied]
    if filmed and turns:
        last = filmed[-1]
        taken = {b.after_block for b in breath}
        who = next((c for c in cast if re.search(rf"\b{re.escape(c)}\b", last.text, re.IGNORECASE)), "")
        if last.index not in taken and who:
            breath.append(Breath(after_block=last.index, anchor=block_key(last), kind="button", who=who,
                                 seconds=RULES_BUTTON_S, priority=1, why="the last image of the scene"))
    breath.sort(key=lambda b: b.after_block)
    return SceneReading(units=units, breath=breath, by="rules", for_version=version, basis=basis(items),
                        subtext=_narration(items))


# ── onto the kernel's clock ────────────────────────────────────────────────────────────────


def apply(items: Sequence[Item], reading: SceneReading | None, *, off: Iterable[int] = ()) -> list[Item]:
    """The kernel items with the reading's time on them: each active breath becomes `hold_s` on its block, each turn
    marks its block, and a small action (`with_line`) that is a turn counts as an `act`, not half a second.
    `off` is item indexes whose breath is not played. With no reading the items come back unchanged."""
    if reading is None:
        return list(items)
    skip = set(off)
    out = list(items)
    for b, at in reading.resolved(items):
        if b.off or at in skip:
            continue
        out[at] = replace(out[at], hold_s=b.seconds, hold_kind=b.kind, hold_priority=b.priority,
                             hold_who=b.who)
    for at in reading.turns(items):
        item = out[at]
        out[at] = replace(item, turn=True, screen="act" if item.kind == "action" and item.screen == "with_line"
                          else item.screen)
    return out


def optional_breath(items: Sequence[Item]) -> list[Item]:
    """Items that carry breath a scene may give up when it is over its envelope (priority 2 or 3), lowest priority
    first and the later block first. Priority 1 is never in this list."""
    held = [i for i in items if i.hold_s > 0 and i.hold_priority in (2, 3)]
    return sorted(held, key=lambda i: (-i.hold_priority, -i.index))


def release(items: Sequence[Item], at: int) -> list[Item]:
    """The items with the hold on block `at` taken off."""
    return [replace(i, hold_s=0.0, hold_kind="", hold_priority=0, hold_who="") if i.index == at else i
            for i in items]


def mark_off(reading: SceneReading, items: Sequence[Item], dropped: Iterable[int], *,
             by: str = "envelope") -> SceneReading:
    """The reading with the breath after these item indexes switched off (given up to fit the envelope). Its words
    and its author do not change: a person's reading stays a person's."""
    gone = set(dropped)
    at = {id(b): i for b, i in reading.resolved(items)}
    breath = [b.model_copy(update={"off": True, "off_by": by}) if at.get(id(b)) in gone else b for b in reading.breath]
    return reading.model_copy(update={"breath": breath})


def clear_envelope(reading: SceneReading) -> SceneReading:
    """A new split weighs the envelope again: breath given up for it comes back (a person's own switch-off stays)."""
    breath = [b.model_copy(update={"off": False, "off_by": ""}) if b.off and b.off_by == "envelope" else b
              for b in reading.breath]
    return reading.model_copy(update={"breath": breath})
