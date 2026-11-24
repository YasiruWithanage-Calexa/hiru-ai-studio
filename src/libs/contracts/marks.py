"""Fixed marks: a person who does not travel stays on ONE ground spot (plan/2026-11-24d, lab/fixed_marks).

The person's rule (2026-11-24): if people do not walk, they stay in the same position for all the shots; only when
they walk, travel or otherwise change position does their position change. The position is the GROUND position (the
spot in the place, the landmarks around it, the gap to the other person), not the side of the picture. Small steps
keep the mark, within `RADIUS_M`.

* `stretches`   code finds the runs of blocks in which nobody moves, from the staging map (never a model): a move is a
                zone change, `walking` / `running`, or an implied `move:<who>` step; an entrance or an exit (to or
                from `off`) also ends a stretch. A posture change alone (sitting down, kneeling) does not (D1). A shot
                belongs to the stretch of its OPENING block. Shots of a scene planned with line parts count the parts
                (plan/2026-11-20); the map counts whole blocks, so `whole_index` maps one to the other (lab phase 0:
                scene 4's shots 11-14 open at "blocks" 19-22 of a script of 19).
* `check`       the board writer's spots (`GroundMark`, one per person per stretch), what is kept, what is missing.
* `paragraph`   the lab's "Ground marks" words for a stretch (phase 0 `stretch_marks`); `panel_line` the line on each
                panel (still, someone leaves the mark in this shot, a new stretch begins).
* `plate_view`, `plate_label`, `plate_job`, `pin`   the blocking plate's view, its name and job on a board, and what
                makes it out of date.

Words changed from the lab, said here as the plan asks: the gap sentence drops the lab scene's own distance ("about an
arm's length and a little more between their chests, never touching"; the writer's `apart` gives it now); a seated
or kneeling person "sits" / "kneels" on the spot instead of "stands"; the move line names no pronoun ("leaves that
mark in this shot", not "leaves hers"); the plate's words are split into its label and its job, like every other
attached picture of a board. Pure standard library + pydantic (the `contracts` rule).
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from contracts import reading as rd
from contracts.shotplan import Item

RADIUS_M = 0.5  # the person's "small radius": a turn, a lean, half a step stay inside it
MOVING = ("walking", "running")
OFF = "off"
MOVE_BRIDGE = "move:"  # `contracts.bridges`: an implied "crosses to the gate" step, `move:<who>` (lower case)
PLATE_TEMPLATES = ("outside", "inside")  # the views templates whose view 1 is the anchor wide (§3.4)
PLATE_HEAD = "the blocking plate for "
SPOT_CHARS = 300
APART_CHARS = 160
_SITS = {"sitting": "sits", "kneeling": "kneels", "crouching": "crouches", "lying": "lies"}


class GroundMark(BaseModel):
    """The board writer's spot for one person on one stretch (plan/2026-11-24d §3.2)."""

    model_config = ConfigDict(extra="ignore")

    stretch: int = Field(ge=1)
    who: str = Field(min_length=1, max_length=120)
    spot: str = Field(min_length=1, max_length=SPOT_CHARS)  # ground, landmark, side, distance
    apart: str = Field(default="", max_length=APART_CHARS)  # the gap to the next person


@dataclass(frozen=True)
class Stretch:
    """Blocks `start` to `end` (exclusive, whole blocks; None = to the end of the scene) in which nobody moves."""

    n: int
    start: int
    end: int | None
    shot_ids: tuple[str, ...]
    numbers: tuple[int, ...]
    people: tuple[str, ...]  # on the map and still: each holds ONE spot (names as the map writes them)
    postures: tuple[str, ...]  # each still person's posture ("" = not said), in `people` order
    travelling: tuple[str, ...]  # on the map and walking or running: no spot
    left: tuple[str, ...]  # who moved, entered or left at its start (they no longer stand on the marks before it)
    shown: int  # painted shots that show at least one of `people`

    @property
    def label(self) -> str:
        return shots_label(self.numbers)

    @property
    def plate(self) -> bool:
        """A plate only where it holds something: someone still, in two or more painted shots (one panel is its own
        truth)."""
        return bool(self.people) and self.shown >= 2

    def posture_of(self, who: str) -> str:
        key = who.casefold()
        return next((p for n, p in zip(self.people, self.postures, strict=True) if n.casefold() == key), "")


@dataclass(frozen=True)
class Blocking:
    """A scene's stretches, and for each shot its stretch and who moves during it."""

    stretches: tuple[Stretch, ...] = ()
    of_shot: Mapping[str, int] = field(default_factory=dict)  # shot id -> stretch n
    moves_in: Mapping[str, tuple[str, ...]] = field(default_factory=dict)  # shot id -> who moves during it

    def stretch(self, n: int) -> Stretch | None:
        return self.stretches[n - 1] if 1 <= n <= len(self.stretches) else None

    def stretch_of(self, shot_id: str) -> Stretch | None:
        n = self.of_shot.get(str(shot_id))
        return self.stretch(n) if n else None


def shots_label(numbers: Iterable[int]) -> str:
    """ "shot 16", "shots 1 to 15", "shots 1 to 5 and 7" (a cinematic clip can open out of order)."""
    nums = sorted(set(numbers))
    if not nums:
        return ""
    if len(nums) == 1:
        return f"shot {nums[0]}"
    runs: list[list[int]] = [[nums[0]]]
    for x in nums[1:]:
        if x == runs[-1][-1] + 1:
            runs[-1].append(x)
        else:
            runs.append([x])
    if len(runs) == 1 and len(nums) == 2:
        return f"shots {nums[0]} and {nums[1]}"
    bits = [str(r[0]) if len(r) == 1 else f"{r[0]}, {r[1]}" if len(r) == 2 else f"{r[0]} to {r[-1]}" for r in runs]
    return "shots " + (bits[0] if len(bits) == 1 else ", ".join(bits[:-1]) + f" and {bits[-1]}")


def whole_index(items: Sequence[Item]) -> list[int]:
    """Item index (a scene planned with line parts counts each part) → the index of its whole block (the staging map's
    numbering). Whole items map to themselves."""
    out: list[int] = []
    whole = -1
    for item in items:
        if item.part <= 1:
            whole += 1
        out.append(whole)
    return out


# ── the stretches ──────────────────────────────────────────────────────────────────────────────────────────────


@dataclass
class _At:
    at: int
    zone: str
    posture: str


def _marks(staging: Mapping[str, Any], items: Sequence[Item]) -> dict[str, list[_At]]:
    """Each person's marks as (whole block, zone, posture with "" carried from before), in block order. A map written
    for THESE items (or one with no `basis`, as the breakdown writes it) is read by number; another is read through
    its anchors, and a mark whose block is gone is left out."""
    basis = str(staging.get("basis") or "")
    rows: dict[str, list[tuple[int, int, Mapping[str, Any]]]] = {}
    names: dict[str, str] = {}
    for k, m in enumerate(staging.get("marks") or []):
        if not isinstance(m, Mapping) or not str(m.get("who") or "").strip():
            continue
        try:
            block = int(m.get("block") or 0)
        except (TypeError, ValueError):
            continue
        at = rd.resolve(block, str(m.get("anchor") or ""), basis, items) if basis else block
        if at is None:
            continue
        who = str(m["who"]).strip()
        names.setdefault(who.casefold(), who)
        rows.setdefault(who.casefold(), []).append((at, k, m))
    out: dict[str, list[_At]] = {}
    for key, marks in rows.items():
        line: list[_At] = []
        for at, _, m in sorted(marks, key=lambda r: (r[0], r[1])):
            zone = str(m.get("zone") or "").strip() or (line[-1].zone if line else "")
            posture = str(m.get("posture") or "").strip().casefold() or (line[-1].posture if line else "")
            line.append(_At(at, zone, posture))
        out[names[key]] = line
    return out


def _boundaries(people: Mapping[str, list[_At]], items: Sequence[Item]) -> dict[int, set[str]]:
    """Block → who moves, enters or leaves there (a new stretch starts at that block)."""
    out: dict[int, set[str]] = {}
    for who, line in people.items():
        prev: _At | None = None
        for x in line:
            off = x.zone.casefold() == OFF
            if prev is None:
                starts = x.at > 0 and not off  # an entrance after the scene began
            else:
                starts = (x.zone.casefold() != prev.zone.casefold() or x.posture in MOVING
                          or prev.posture in MOVING)  # a move, an exit, an arrival
            if starts:
                out.setdefault(x.at, set()).add(who)
            prev = x
    by_key = {w.casefold(): w for w in people}
    for item in items:
        if item.bridge.startswith(MOVE_BRIDGE):
            name = item.bridge[len(MOVE_BRIDGE):]
            out.setdefault(item.index, set()).add(by_key.get(name.casefold(), name))
    return out


def _state(line: list[_At], block: int) -> _At | None:
    rows = [x for x in line if x.at <= block]
    return rows[-1] if rows else None


def stretches(staging: Mapping[str, Any] | None, items: Sequence[Item], shots: Sequence[Mapping[str, Any]], *,
              to_whole: Sequence[int] | None = None, seen: Mapping[str, Sequence[str]] | None = None,
              painted: Iterable[str] | None = None) -> Blocking:
    """The scene's stretches. `staging`: `scenes.staging`; `items`: the scene's WHOLE items (`sceneplan.scene_items`
    with `parts=False`: the map's numbering, and its implied steps); `shots`: rows with `id`, `number`,
    `block_start`, `block_end`; `to_whole`: `whole_index` of the items the shots count (a scene planned with line
    parts), None when they count whole blocks; `seen`: shot id → the names the camera sees; `painted`: the ids of
    the painted shots (None = all). No map, or a map with no marks: no stretches (the board paints as before)."""
    people = _marks(staging or {}, items)
    if not people or not shots:
        return Blocking()
    bounds = _boundaries(people, items)
    starts = sorted({0, *bounds})

    def whole(block: int) -> int:
        if not to_whole:
            return block
        return to_whole[min(max(block, 0), len(to_whole) - 1)]

    def start_of(block: int) -> int:
        return max(s for s in starts if s <= block)

    rows = sorted(shots, key=lambda s: int(s.get("number") or 0))
    painted_ids = None if painted is None else {str(p) for p in painted}
    by_start: dict[int, list[Mapping[str, Any]]] = {}
    moves_in: dict[str, tuple[str, ...]] = {}
    for s in rows:
        opening = whole(int(s.get("block_start") or 0))
        last = whole(max(int(s.get("block_end") or 0) - 1, int(s.get("block_start") or 0)))
        by_start.setdefault(start_of(opening), []).append(s)
        inside = sorted({w for b, who in bounds.items() if opening < b <= last for w in who}, key=str.casefold)
        if inside:
            moves_in[str(s["id"])] = tuple(inside)
    out: list[Stretch] = []
    of_shot: dict[str, int] = {}
    for k, start in enumerate(starts):
        members = by_start.get(start)
        if not members:
            continue
        end = starts[k + 1] if k + 1 < len(starts) else None
        still: list[str] = []
        postures: list[str] = []
        travelling: list[str] = []
        for who, line in people.items():
            x = _state(line, start)
            if x is None or x.zone.casefold() == OFF:
                continue
            (travelling if x.posture in MOVING else still).append(who)
            if x.posture not in MOVING:
                postures.append(x.posture)
        still_keys = {w.casefold() for w in still}
        shown = sum(1 for s in members
                    if (painted_ids is None or str(s["id"]) in painted_ids)
                    and any(str(n).casefold() in still_keys for n in (seen or {}).get(str(s["id"]), [])))
        n = len(out) + 1
        out.append(Stretch(n=n, start=start, end=end, shot_ids=tuple(str(s["id"]) for s in members),
                           numbers=tuple(int(s.get("number") or 0) for s in members), people=tuple(still),
                           postures=tuple(postures), travelling=tuple(travelling),
                           left=tuple(sorted(bounds.get(start, set()), key=str.casefold)), shown=shown))
        of_shot.update({str(s["id"]): n for s in members})
    return Blocking(stretches=tuple(out), of_shot=of_shot, moves_in=moves_in)


def stretch_rows(blocking: Blocking) -> list[dict[str, Any]]:
    """What the board writer reads about the stretches (plan/2026-11-24d §3.2): each one's number, its shots, who is
    still in it (one spot each) and who is on the move, and what ends it."""
    out: list[dict[str, Any]] = []
    for s in blocking.stretches:
        row: dict[str, Any] = {"stretch": s.n, "shots": list(s.numbers), "still": list(s.people)}
        if s.travelling:
            row["on_the_move"] = list(s.travelling)
        after = blocking.stretch(s.n + 1)
        if after is not None and after.left:
            moved = list(after.left)
            row["ends"] = (f"{_names(moved)} {'moves' if len(moved) == 1 else 'move'} before "
                           f"{shots_label(after.numbers[:1])}")
        out.append(row)
    return out


# ── the board writer's spots ───────────────────────────────────────────────────────────────────────────────────


# Board v20: the writer began a spot with its own verb ("Standing on the same concrete landing strip ..."), and the
# paragraph read "Kasun stands Standing on ...". Code says the verb (`paragraph`), so the writer's is taken off.
_LEAD_VERB = re.compile(r"^(?:is\s+|are\s+)?(?:standing|stands|stand|sitting|sits|sit|kneeling|kneels|crouching|"
                        r"crouches|lying|lies)\b[\s,]*", re.IGNORECASE)
_LEAD_WORD = re.compile(r"^(On|At|In|Beside|Behind|Near|By|Just|About|Level|Against|Under|Inside|Outside|One|Two|"
                        r"Half|A|The)\b")


def clean_spot(text: str) -> str:
    """A spot as the paragraph's verb continues it: one line, the writer's own leading verb taken off, a leading
    preposition or article in lower case ("Standing on the strip" → "on the strip")."""
    spot = _LEAD_VERB.sub("", " ".join(str(text or "").split()))
    return _LEAD_WORD.sub(lambda m: m.group(1).lower(), spot)


def check(raw: Iterable[Any], blocking: Blocking) -> tuple[list[GroundMark], list[str]]:
    """The writer's `marks` kept (one per person per stretch, the first; a mark for an unknown stretch or person, or
    an invalid one, is dropped) and a `conflicts` line for each still person of a stretch left without a spot."""
    kept: list[GroundMark] = []
    have: set[tuple[int, str]] = set()
    for row in raw:
        try:
            mark = row if isinstance(row, GroundMark) else GroundMark.model_validate(row)
        except ValidationError:
            continue
        s = blocking.stretch(mark.stretch)
        if s is None or not mark.spot.strip():
            continue
        who = next((p for p in s.people if p.casefold() == mark.who.strip().casefold()), None)
        if who is None or (s.n, who.casefold()) in have:
            continue
        have.add((s.n, who.casefold()))
        spot = clean_spot(mark.spot)
        if not spot:
            continue
        kept.append(mark.model_copy(update={"who": who, "spot": spot, "apart": " ".join(mark.apart.split())}))
    named = {s.n for s in blocking.stretches if any((s.n, p.casefold()) in have for p in s.people)}
    problems = [f"{s.label.capitalize()}: the board writer gave no ground mark for {who}; "
                + ("the other spots place them." if s.n in named else "nothing holds the people's spots.")
                for s in blocking.stretches for who in s.people if (s.n, who.casefold()) not in have]
    return kept, problems


def of_stretch(stretch: Stretch, marks: Sequence[GroundMark]) -> list[GroundMark]:
    """The stretch's spots in its people's order."""
    mine = {m.who.casefold(): m for m in marks if m.stretch == stretch.n}
    return [mine[p.casefold()] for p in stretch.people if p.casefold() in mine]


def complete(stretch: Stretch, marks: Sequence[GroundMark]) -> bool:
    """The stretch has at least one spot, so it gets its words and its plate. Board v20 (2026-11-24): the writer gave
    Kasun's spot ("1.4 metres to Anudi's left") and not Anudi's, and requiring EVERY spot switched the whole stretch
    off. One spot with its gap places the others; a person without one is told to keep one spot too (`paragraph`),
    and the missing spot is still reported in `conflicts` (`check`)."""
    return bool(stretch.people) and bool(of_stretch(stretch, marks))


# ── the words (lab/fixed_marks phase 0 `stretch_marks`, `PANEL_LINE`, the walk panels' lines) ───────────────

RADIUS = ("Small movements (a turn of the head or body, a lean, a shift of weight, half a step) stay within half a "
          "metre of the mark; the feet never travel further.")
GAP = "The gap between them is the same in every panel: a closer camera makes them larger, never closer together."
BEHIND = "What is behind each of them follows from these spots and the panel's camera."


def _still_head(label: str) -> str:
    return (f"Ground marks ({label}): nobody walks in these shots, so each person stands on ONE spot on the ground for "
            "all of them, and every panel of them shows them on that same spot, seen from its own camera.")


def _names(names: Sequence[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + f" and {names[-1]}"


def paragraph(stretch: Stretch, marks: Sequence[GroundMark], colours: Mapping[str, str]) -> str:
    """The "Ground marks" paragraph of a stretch, "" when it has no spot at all. `colours`: name → the person's
    mannequin colour on the board."""
    if not complete(stretch, marks):
        return ""
    spots = []
    for m in of_stretch(stretch, marks):
        colour = next((c for n, c in colours.items() if n.casefold() == m.who.casefold()), "")
        verb = _SITS.get(stretch.posture_of(m.who), "stands")
        who = f"{m.who} (the {colour} mannequin)" if colour else m.who
        spots.append(f"{who} {verb} {m.spot.rstrip('.')}" + (f", {m.apart.rstrip('.')}" if m.apart else "") + ".")
    placed = {m.who.casefold() for m in of_stretch(stretch, marks)}
    for name in (p for p in stretch.people if p.casefold() not in placed):  # a spot the writer left out
        colour = next((c for n, c in colours.items() if n.casefold() == name.casefold()), "")
        who = f"{name} (the {colour} mannequin)" if colour else name
        spots.append(f"{who} also keeps ONE spot for all these shots, where the spots above place them.")
    still = len(stretch.numbers) >= 2 and not stretch.travelling
    bits = [_still_head(stretch.label) if still else f"Ground marks ({stretch.label}):", RADIUS, *spots]
    if stretch.travelling:
        t = list(stretch.travelling)
        bits.append(f"{_names(t)} {'is' if len(t) == 1 else 'are'} on the move in these shots and "
                    f"{'holds' if len(t) == 1 else 'hold'} no mark.")
    if len(stretch.people) >= 2:
        bits.append(GAP)
    bits.append(BEHIND)
    return " ".join(bits)


def panel_line(blocking: Blocking, shot_id: str) -> str:
    """The marks line at the head of a shot's panel (plan/2026-11-24d §3.3), "" when its stretch holds nobody still.
    Someone leaving the mark in this shot wins over a new stretch, which wins over the plain line."""
    s = blocking.stretch_of(shot_id)
    if s is None or not s.people:
        return ""
    movers = [m for m in blocking.moves_in.get(str(shot_id), ()) if m.casefold() in {p.casefold() for p in s.people}]
    if movers:
        stay = [p for p in s.people if p.casefold() not in {m.casefold() for m in movers}]
        lead = (f"{_names(stay)} {'stays' if len(stay) == 1 else 'stay'} on the ground marks of {s.label}; "
                if stay else "")
        return (f"Marks: {lead}{_names(movers)} {'leaves that mark' if len(movers) == 1 else 'leave those marks'} "
                "in this shot.")
    first = min(zip(s.numbers, s.shot_ids, strict=True))[1] == str(shot_id)
    before = blocking.stretch(s.n - 1)
    if first and before is not None and before.people:
        gone = [p for p in before.people if p.casefold() in {x.casefold() for x in s.left}]
        if gone:
            tail = ("nobody stands on the marks of " if len(gone) == len(before.people)
                    else f"{_names(gone)} no longer {'stands' if len(gone) == 1 else 'stand'} on the marks of ")
            return f"Marks: the ground marks of {s.label}; {tail}{before.label}."
    if len(s.people) >= 2 and len(s.numbers) >= 2:
        return f"Marks: on the ground marks of {s.label}, the same gap as in every panel of them."
    return f"Marks: on the ground {'marks' if len(s.people) >= 2 else 'mark'} of {s.label}."


# ── the blocking plate ─────────────────────────────────────────────────────────────────────────────────────────


def plate_view(panel_views: Sequence[int], views: Sequence[Mapping[str, Any]],
               template: str) -> Mapping[str, Any] | None:
    """The view the plate is painted from: the one most of the stretch's panels name (the earliest of a tie); when
    none names one, view 1 of an `outside` or `inside` sheet (its anchor wide). None: no plate (a `both` or a vehicle
    sheet's view 1 is its outside, §3.4). `panel_views`: the `view` of each panel of the stretch, in shot order."""
    known = {int(v.get("n") or 0): v for v in views if int(v.get("n") or 0) > 0}
    named = [v for v in panel_views if v in known]
    if named:
        counts = Counter(named)
        best = max(counts.values())
        return known[next(v for v in named if counts[v] == best)]
    return known.get(1) if template in PLATE_TEMPLATES else None


def plate_label(stretch: Stretch) -> str:
    return f"{PLATE_HEAD}{stretch.label}: one still of this place, the people standing on their ground marks"


def plate_job(label: str) -> str:
    """What a board (or a panel) takes from the plate (lab `PLATE_CHAIN`)."""
    shots = label[len(PLATE_HEAD):].split(":", 1)[0]
    return ("only where each person stands on the ground, what stands behind each of them and the gap between them; "
            f"every panel of {shots} keeps them on exactly these spots, seen from its own camera. Not its framing, "
            "its light or its poses")


def pin(stretch: Stretch, marks: Sequence[GroundMark], colours: Mapping[str, str], sources: Sequence[str]) -> str:
    """What the plate was painted against: the stretch's shots and people, their spots, the colours and the
    pictures it was painted from (the views sheet, the vehicles). A different pin is an out-of-date plate."""
    raw = json.dumps({"shots": list(stretch.shot_ids), "people": list(stretch.people),
                      "marks": [m.model_dump() for m in of_stretch(stretch, marks)],
                      "colours": {k: colours[k] for k in sorted(colours)}, "sources": list(sources)},
                     sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(raw.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]
