"""How an edit sits with the shots around it: compatibility and continuity (PLAN.md §6).

An edit to the script (a line, an action, a new or removed block) can leave a neighbour wrong
without breaking the plan the timing kernel checks. This module says where to look and what it
found, in code, from the scene before and after the edit:

  * the IMPACT SET: the shots the edit touched, the shots either side of them, and every shot
    that carries on from a touched take (a `continuous` or `match` join);
  * NOTES, no model needed: a shot's sound changed with its words, who is in a shot changed (its
    frames and prompts will be marked out of date), a speaker the canon does not know, a joined
    shot whose opening may need to follow, a word the edit took out that another shot still uses,
    the same speaker elsewhere in the scene;
  * the TASK for the continuity specialist (the turn runs it on the impact set): beats and joins
    only, and a note about any neighbouring line that no longer fits. Nothing here rewrites
    dialogue or touches another scene.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from contracts.canon import name_key
from director_chat.engine.kernel import Change, ScenePlanKernel

LINKED = ("continuous", "match")
PUNCT = " .,!?;:\"'“”‘’…()-—"
MIN_TERM = 5  # shorter words ("the", "and", "ඇති") say too little to mean the same thing elsewhere


@dataclass(frozen=True)
class Note:
    shots: tuple[int, ...]
    text: str
    check: bool  # worth a look; False is for information


@dataclass
class Review:
    impact: list[int] = field(default_factory=list)  # shot numbers (after the edit)
    notes: list[Note] = field(default_factory=list)
    scripted: bool = False  # the edit changed the script itself


def codes(numbers: list[int] | tuple[int, ...]) -> str:
    return ", ".join(f"S{n:02d}" for n in numbers)


def terms(text: str) -> set[str]:
    """The words worth looking for in another shot: long enough to mean something, and not
    contractions ("I'll" is not a word the story depends on)."""
    return {w for w in (x.casefold().strip(PUNCT) for x in str(text).split())
            if len(w) >= MIN_TERM and "'" not in w and "’" not in w}


def _numbers(k: ScenePlanKernel, handles: set[str]) -> set[int]:
    return {n for h in handles if (n := k.number_of(h))}


def _text_of(k: ScenePlanKernel, shot: dict[str, Any]) -> str:
    return " ".join(str(i.get("text") or "") for i in k.items[shot["start"]:shot["end"]])


def _sound(k: ScenePlanKernel) -> dict[str, str]:
    return {s["_h"]: f.sound_mode.value for s, f in zip(k.shots, k.fit().shots, strict=True)}


def _cast(k: ScenePlanKernel) -> dict[str, set[str]]:
    names = {str(c["id"]): str(c["name"]) for c in k.canon}
    return {s["_h"]: {names[i] for i in k._present(s) if i in names} for s in k.shots}


def review(before: ScenePlanKernel, after: ScenePlanKernel, applied: list[dict[str, Any]],
           changes: list[Change]) -> Review:
    handles = {h for c in changes for h in c.handles}
    touched = _numbers(after, handles)
    scripted = any(c.kind == "script" for c in changes)
    if not touched:
        return Review(scripted=scripted)

    total = len(after.shots)
    impact = set(touched)
    for n in touched:
        impact |= {m for m in (n - 1, n + 1) if 1 <= m <= total}
        m = n  # a joined run: the shots that carry on from this take
        while m < total and after.shots[m].get("camera_link") in LINKED:
            m += 1
            impact.add(m)
    notes: list[Note] = []
    by_handle = {s["_h"]: n for n, s in enumerate(after.shots, start=1)}

    # sound follows the words in a shot
    was, now = _sound(before), _sound(after)
    for h in handles:
        if h in was and h in now and was[h] != now[h]:
            notes.append(Note((by_handle[h],), f"S{by_handle[h]:02d} is now {now[h]} (it was {was[h]}), because of "
                                               "the words in it.", False))

    # who is in a shot
    cast_was, cast_now = _cast(before), _cast(after)
    for h in handles:
        if h in cast_was and h in cast_now and cast_was[h] != cast_now[h]:
            added, gone = sorted(cast_now[h] - cast_was[h]), sorted(cast_was[h] - cast_now[h])
            moved = ", ".join([*(f"{x} is now in it" for x in added), *(f"{x} is no longer in it" for x in gone)])
            notes.append(Note((by_handle[h],), f"S{by_handle[h]:02d}: {moved}. Frames and prompts made for it will be "
                                               "marked out of date.", False))

    # a speaker the canon does not know
    for op in applied:
        name = op.get("speaker") if op["op"] == "block.insert" else (
            op.get("value") if op["op"] == "block.set" and op.get("field") == "speaker" else None)
        if name and after.canon and after.character_id(str(name)) is None:
            n = int(op.get("shot") or 0)
            notes.append(Note((n,), f"{name} is not in the canon, so S{n:02d} has no matching character or voice.",
                              True))

    # a joined shot carries on from a take that changed
    if scripted:
        for n in sorted(touched):
            if n < total and after.shots[n].get("camera_link") in LINKED:
                notes.append(Note((n, n + 1), f"S{n + 1:02d} carries on from S{n:02d}'s take; check that its opening "
                                              "still follows.", True))

    # words the edit took out that another shot still uses
    gone_terms: dict[str, int] = {}
    for op in applied:
        if op["op"] in ("block.set", "block.remove") and op.get("was") and op.get("field", "text") == "text":
            for w in terms(op["was"]) - terms(op.get("value", "") if op["op"] == "block.set" else ""):
                gone_terms.setdefault(w, int(op.get("shot") or 0))
    if gone_terms:
        for n, shot in enumerate(after.shots, start=1):
            if n in touched:
                continue
            hit = sorted(terms(_text_of(after, shot)) & gone_terms.keys())[:3]
            if hit:
                said = ", ".join(f"“{w}”" for w in hit)
                notes.append(Note((n,), f"S{n:02d} still says {said}, which the change took out of "
                                        f"S{gone_terms[hit[0]]:02d}.", True))

    # the same speaker elsewhere in the scene
    spoke = {name_key(str(op.get("speaker") or "")) for op in applied
             if op["op"] in ("block.set", "block.insert") and op.get("kind") == "dialogue"
             and op.get("field", "text") == "text"} - {""}
    for key in sorted(spoke):
        elsewhere = [n for n, s in enumerate(after.shots, start=1) if n not in touched and any(
            i["kind"] == "dialogue" and name_key(str(i.get("speaker") or "")) == key
            for i in after.items[s["start"]:s["end"]])]
        if elsewhere:
            who = next(str(i["speaker"]) for i in after.items
                       if i["kind"] == "dialogue" and name_key(str(i.get("speaker") or "")) == key)
            notes.append(Note(tuple(elsewhere), f"{who} also speaks in {codes(elsewhere)}: check those lines still "
                                                "agree with the change.", False))

    notes.sort(key=lambda n: not n.check)
    return Review(sorted(impact), notes, scripted)


def words_line(before: ScenePlanKernel, after: ScenePlanKernel, changes: list[Change]) -> str:
    """"S01 words 7 → 9 (room for 13)" for the shots whose words changed."""
    was = {s["_h"]: f for s, f in zip(before.shots, before.fit().shots, strict=True)}
    parts = []
    for n, (s, f) in enumerate(zip(after.shots, after.fit().shots, strict=True), start=1):
        old = was.get(s["_h"])
        if s["_h"] in {h for c in changes for h in c.handles} and old is not None and old.words != f.words:
            parts.append(f"S{n:02d} words {old.words} → {f.words} (room for {f.word_target})")
    return " · ".join(parts)


def checked(rv: Review) -> str:
    """What was looked at, so a person knows how far the check went."""
    if not rv.impact:
        return ""
    outcome = f"{len(rv.notes)} to look at." if rv.notes else "nothing clashes."
    return f"Checked {codes(rv.impact)}: {outcome}"


def continuity_task(rv: Review, summary: str) -> dict[str, Any] | None:
    if not (rv.scripted and rv.impact):
        return None
    return {"agent": "continuity", "shots": rv.impact,
            "instruction": f"The script just changed: {summary}. Change a beat's action, or how a shot joins, only "
                           "where this makes the shot before or after it wrong. You cannot change dialogue: if a "
                           "neighbouring line no longer fits, say which in your note. Return no operations when "
                           "the shots still agree."}

