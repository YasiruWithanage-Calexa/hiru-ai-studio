"""What the scene's reading and staging ask of ONE shot (plan/2026-11-01d, Phase 6).

The reading says what each person wants, where the feeling turns, which moments are held and how the story notes
are played; the staging map says where each person is. This module cuts both down to a shot: for each beat window the
visible behaviour to play, which beats are turns, what a speaker wants while a line is said, and where everyone is
when the shot opens and when it closes. It only READS: it never adds a person, a line or an event.

A reading that is out of date (the script moved on) still gives its holds and turns, which are found by block
identity, but not its unit numbers or story notes, which are found by number.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from contracts import reading as rd
from contracts import stagemap as sm
from contracts.shotplan import Item, shot_clock


@dataclass(frozen=True)
class Place:
    """Where one person is at a moment of a shot."""

    who: str
    zone: str
    facing: str = ""
    frame_side: str = ""
    holding: str = ""

    def text(self) -> str:
        where = "off screen" if self.zone == sm.OFF else f"at the {self.zone}"
        bits = [f"{self.who} {where}", f"facing {self.facing}" if self.facing else "",
                f"{self.frame_side} of frame" if self.frame_side else "",
                f"holding {self.holding}" if self.holding else ""]
        return ", ".join(b for b in bits if b)


@dataclass
class Feeling:
    """What the reading and the map ask of a shot. Empty when the scene has neither."""

    beat_notes: dict[int, list[str]] = field(default_factory=dict)  # beat index → behaviour to play in that window
    turn_beats: set[int] = field(default_factory=set)  # beats in which the feeling turns or a priority-1 reaction plays
    wants: dict[str, str] = field(default_factory=dict)  # line id → "wanting to escape"
    person_wants: dict[str, str] = field(default_factory=dict)  # who → what they want in this part of the scene
    start: list[Place] = field(default_factory=list)  # where people are when the shot opens
    end: list[Place] = field(default_factory=list)  # ... and when it closes

    def empty(self) -> bool:
        return not (self.beat_notes or self.turn_beats or self.wants or self.start)

    def performance_text(self, windows: Sequence[tuple[int, int]]) -> str:
        """The DoP's PERFORMANCE block: one row per beat window that has something to play."""
        turn = ["the feeling turns here"]
        rows = [f"  [{windows[n][0]}-{windows[n][1]}s] "
                + "; ".join([*self.beat_notes.get(n, []), *(turn if n in self.turn_beats else [])])
                for n in sorted({*self.beat_notes, *self.turn_beats}) if n < len(windows)]
        wants = [f"  {who} {verb}" for who, verb in self.person_wants.items()]
        out = (["PERFORMANCE (from the scene's reading; play it as visible behaviour, never as words or thoughts):",
                *rows] if rows else [])
        if wants:
            out += ["WHAT EACH PERSON WANTS IN THIS PART OF THE SCENE:", *wants]
        return "\n".join(out)


def want_phrase(verb: str) -> str:
    """"to escape" → "wanting to escape"."""
    verb = " ".join(verb.split())
    return f"wanting {verb}" if verb.startswith("to ") else f"wanting to {verb}" if verb else ""


def _place(staging: sm.SceneStaging, items: Sequence[Item], who: str, block: int) -> Place | None:
    mark = staging.mark_at(items, who, block)
    return Place(mark.who, mark.zone, mark.facing, mark.frame_side, mark.holding) if mark else None


def feeling_for(reading: rd.SceneReading | None, staging: sm.SceneStaging | None, scene_items: Sequence[Item],
                shot_items: Sequence[Item], windows: Sequence[tuple[int, int]], cast: Sequence[str]) -> Feeling:
    """The reading and the map, for one shot. `scene_items` are the scene's (with the reading's time on them),
    `shot_items` the shot's own blocks, `windows` its beat windows in seconds."""
    out = Feeling()
    if not shot_items or not windows:
        return out
    slots = {s.index: s for s in shot_clock(list(shot_items))[0]}
    fresh = reading is not None and reading.basis == rd.basis(scene_items)
    held = {at: b for b, at in reading.resolved(scene_items)} if reading else {}
    story = {t.block: t for t in reading.subtext} if reading and fresh else {}

    def beat_of(seconds: float) -> int:
        for n, (a, b) in enumerate(windows):
            if a <= seconds < b:
                return n
        return len(windows) - 1

    here = 0  # the beat of the last thing seen: a story note, which takes no time, plays there
    for it in shot_items:
        slot = slots.get(it.index)
        if slot is not None:
            here = beat_of(slot.start_s)
        note = story.get(it.index)
        if note is not None and not note.narration_only and note.behaviour:
            out.beat_notes.setdefault(here, []).append(f"{note.who} {note.behaviour}".strip())
        if it.turn:
            out.turn_beats.add(here)
        if it.hold_s > 0 and slot is not None:
            n = beat_of(min(slot.end_s, windows[-1][1] - 0.01))
            b = held.get(it.index)
            who = it.hold_who or (b.who if b else "")
            why = f" ({b.why})" if b and b.why else ""
            what = {"reaction": f"{who}'s face receives it", "button": f"{who} holds the last image",
                    "transition": "a beat between places or moods", "atmosphere": "the place is held"}.get(
                it.hold_kind, "a moment is held")
            out.beat_notes.setdefault(n, []).append(f"{what}, held {it.hold_s:g} s{why}")
            if it.hold_kind == "reaction" and it.hold_priority == 1:
                out.turn_beats.add(n)
            here = n

    if reading is not None and fresh:
        first, last = shot_items[0].index, shot_items[-1].index
        here_now = set(sm.people_in(shot_items, cast))
        for u in reading.units:
            if u.to_block < first or u.from_block > last:
                continue  # a unit that does not touch this shot
            for who, verb in u.wants.items():
                if who.casefold() in here_now and verb:
                    out.person_wants.setdefault(who.title(), want_phrase(verb))
            for it in shot_items:
                if it.is_line and it.line_id and u.from_block <= it.index <= u.to_block:
                    verb = next((v for w, v in u.wants.items() if w.casefold() == it.speaker.casefold()), "")
                    if verb:
                        out.wants[it.line_id] = want_phrase(verb)

    if staging is not None:
        people = sm.people_in(shot_items, cast)
        first, last = shot_items[0].index, shot_items[-1].index
        out.start = [p for w in people if (p := _place(staging, scene_items, w, first)) is not None]
        out.end = [p for w in people if (p := _place(staging, scene_items, w, last)) is not None]
    return out


def positions_text(places: Sequence[Place]) -> str:
    return "; ".join(p.text() for p in places)


# ── free checks on a draft (plan/2026-11-01d, Phase 6) ─────────────────────────────────────


def performance_missing(feeling: Feeling, beats: Sequence[Mapping[str, object]],
                        windows: Sequence[tuple[int, int]]) -> list[str]:
    """The windows ("3-5s") of beats where the feeling turns and the draft wrote no performance."""
    return [f"{windows[n][0]}-{windows[n][1]}s" for n in sorted(feeling.turn_beats)
            if n < len(windows) and not (n < len(beats) and " ".join(str(beats[n].get("performance") or "").split()))]


def position_jump(zones: Sequence[str], expected: Sequence[Place], ir: Mapping[str, object]) -> str:
    """A sentence when the first frame is set in a spot of the map that is not where the people stood (the previous
    shot's end positions, or the map at the start of this one); "" when it agrees, names no spot, or there is no map."""
    raw = ir.get("first_frame")
    frame: Mapping[str, object] = raw if isinstance(raw, Mapping) else {}
    text = " ".join(str(v) for v in (frame.get("composition"), frame.get("setting"),
                                     *(frame.get("subjects") or [])) if v).casefold()  # type: ignore[attr-defined]
    named = {z for z in zones if z.casefold() in text}
    want = {p.zone for p in expected if p.zone and p.zone != sm.OFF}
    if not named or not want or {w.casefold() for w in want} & {n.casefold() for n in named}:
        return ""
    return (f"the first frame is at the {', '.join(sorted(named))}, but the people stood at the "
            f"{', '.join(sorted(want))}")
