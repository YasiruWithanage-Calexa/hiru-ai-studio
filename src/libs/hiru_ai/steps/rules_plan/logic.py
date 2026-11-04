"""The rules half of `script_split/engine/planner.py`, unchanged: free, deterministic shots for a scene (plan/2026-11-03
Phase 6). Used without a key, whenever the model fails, and as the rival the kernel score compares the model's plan
with.

The model half is the `scene_planner` agent; the numbered listing it reads is the `scene_listing` step.
"""
from __future__ import annotations

import logging
import re

from contracts import reading as scene_reading
from contracts.production import Framing
from contracts.shotplan import (
    Item,
    ProposedShot,
    allowed_durations,
    fit,
    needed_seconds,
    sound_mode_for,
    split_to_fit,
)
from contracts.veo import SoundMode

_logger = logging.getLogger(__name__)

SHORT_ACTION_WORDS = 25  # an action this short that precedes a line is part of that line's shot
TITLE_WORDS = 6


def _title_from(text: str) -> str:
    first = text.strip().split(". ")[0].strip(" .")
    words = first.split()
    return " ".join(words[:TITLE_WORDS]) + ("…" if len(words) > TITLE_WORDS else "")


def _action_words(items: list[Item]) -> int:
    return sum(len(i.text.split()) for i in items if i.kind == "action")


def _heard_only(lines: list[Item]) -> bool:
    """Every one of these lines is a voice heard, not seen (a phone call, off screen, narration)."""
    return bool(lines) and sound_mode_for(lines, None) is SoundMode.VOICEOVER


def _listener(items: list[Item], at: int) -> str:
    """Who is on screen while the line at `at` is heard: the nearest on-camera speaker before it,
    else the next one after it. "" when nobody on camera speaks in the scene."""
    on_camera = [i for i in items if i.is_line and not _heard_only([i])]
    names = {i.speaker for i in on_camera}
    spoke = max((i.index for i in on_camera if i.index < at), default=-1)  # a line since then settles it
    for block in reversed([i for i in items[spoke + 1:at] if i.kind == "action"][-3:]):
        named = [n for n in names if re.search(rf"\b{re.escape(n)}\b", block.text, re.IGNORECASE)]
        if named:  # "her phone rings" after "Anudi smiles back": the phone is in Anudi's hand
            return max(named, key=lambda n: block.text.lower().rfind(n.lower()))
    before = [i for i in on_camera if i.index < at]
    after = [i for i in on_camera if i.index > at]
    nearest = before[-1] if before else after[0] if after else None
    return nearest.speaker if nearest else ""


def fold_silent(items: list[Item], shots: list[ProposedShot], *, envelope_s: int,
                fixed_seconds: int | None = None) -> list[ProposedShot]:
    """While the plan runs over the envelope, fold the longest silent shot into its neighbour: the
    action rides with the next shot (the previous one, for a trailing action). Speech is never
    touched, so what the scene says is kept and only a beat's own shot is given up."""
    shots = list(shots)
    longest = max(allowed_durations(fixed_seconds))
    while len(shots) > 1:
        result = fit(items, shots, envelope_s=envelope_s, fixed_seconds=fixed_seconds)
        if result.total_s <= envelope_s:
            break
        length = {s.start: s.duration_s for s in result.shots}
        silent = [n for n, p in enumerate(shots)
                  if not any(i.is_line or i.hold_s > 0 for i in items[p.start:p.end])]  # a shot with breath stays
        # A fold must not crowd the shot that takes the action in: past that, the scene reports that it
        # needs more than its envelope (the director decides) instead of squeezing its pictures.
        silent = [n for n in silent if _fold_fits(items, shots, n, longest)]
        if not silent:
            break
        n = max(silent, key=lambda k: length.get(shots[k].start, 0))
        p = shots[n]
        if n + 1 < len(shots):
            nxt = shots[n + 1]
            shots[n:n + 2] = [ProposedShot(p.start, nxt.end, nxt.framing, nxt.title, nxt.sound_mode, nxt.duration,
                                           nxt.duration_locked, p.camera_link)]
        else:
            prev = shots[n - 1]
            shots[n - 1:n + 1] = [ProposedShot(prev.start, p.end, prev.framing, prev.title, prev.sound_mode,
                                               prev.duration, prev.duration_locked, prev.camera_link)]
    return shots


def fold_breath(items: list[Item], shots: list[ProposedShot], *, envelope_s: int,
                fixed_seconds: int | None = None) -> tuple[list[Item], list[ProposedShot]]:
    """While the plan runs over the envelope: give up optional breath first, lowest priority first (3, then 2;
    later blocks first), keeping each drop that shortens the plan. Priority 1 is never dropped by code. Then fold
    the silent shots that carry no breath (`fold_silent`). -> (items without the dropped holds, shots)."""
    items = list(items)

    def total(its: list[Item]) -> int:
        return fit(its, shots, envelope_s=envelope_s, fixed_seconds=fixed_seconds).total_s

    now = total(items)
    for candidate in scene_reading.optional_breath(items):
        if now <= envelope_s:
            break
        trial = scene_reading.release(items, candidate.index)
        after = total(trial)
        if after < now:  # a hold that costs no whole rung is free: keep it
            items, now = trial, after
    return items, fold_silent(items, shots, envelope_s=envelope_s, fixed_seconds=fixed_seconds)


def _fold_fits(items: list[Item], shots: list[ProposedShot], n: int, longest: int) -> bool:
    """Would folding silent shot `n` into its neighbour still fit the longest shot?"""
    p = shots[n]
    other = shots[n + 1] if n + 1 < len(shots) else shots[n - 1]
    start, end = min(p.start, other.start), max(p.end, other.end)
    return needed_seconds(items[start:end]) <= longest


def rules_plan(items: list[Item], *, envelope_s: int | None = None,
               fixed_seconds: int | None = None) -> tuple[list[Item], list[ProposedShot]]:
    """-> (the items to plan and fit with, the shots). With an envelope, a plan that runs over it gives up optional
    breath, then silent shots that carry none (`fold_breath`); the returned items still carry their holds."""
    shots = _rules_shots(items, max(allowed_durations(fixed_seconds)))
    if envelope_s:
        return fold_breath(items, shots, envelope_s=envelope_s, fixed_seconds=fixed_seconds)
    return list(items), shots


def plan_by_rules(items: list[Item], *, envelope_s: int | None = None,
                  fixed_seconds: int | None = None) -> list[ProposedShot]:
    """The rules' shots (see `rules_plan`)."""
    return rules_plan(items, envelope_s=envelope_s, fixed_seconds=fixed_seconds)[1]


def _moves(group: list[Item]) -> bool:
    return any(i.kind == "action" and i.screen == "move" for i in group)


def _rules_shots(items: list[Item], longest: int = 8) -> list[ProposedShot]:
    shots: list[ProposedShot] = []
    cur: list[Item] = []

    def emit(group: list[Item], link: str) -> None:
        lines = [i for i in group if i.is_line]
        actions = [i for i in group if i.kind == "action" and i.picture_s > 0] or [
            i for i in group if i.kind == "action"]
        hint: str | None = None
        if lines and _heard_only(lines):
            listener = _listener(items, lines[0].index).title()
            framing, hint = Framing.MCU, SoundMode.VOICEOVER.value  # the listener is what the viewer sees
            title = _title_from(actions[0].text) if actions else (f"{listener} listens" if listener else "Voice heard")
        elif lines:
            speakers = {ln.speaker for ln in lines}
            framing = Framing.MCU if len(speakers) == 1 else Framing.TWO
            end = group[-1]  # a reaction held at the end of the shot belongs to someone listening: show both
            if (framing is Framing.MCU and end.hold_kind == "reaction" and end.hold_who
                    and end.hold_who.casefold() not in {sp.casefold() for sp in speakers}):
                framing = Framing.TWO
            who = lines[0].speaker.title() if len(speakers) == 1 else " and ".join(sorted(s.title() for s in speakers))
            title = _title_from(actions[0].text) if actions else f"{who} speaks"
        else:
            # A move through space is seen whole; the rest of a silent run is a medium shot.
            wide_yet = any(s.framing == Framing.WIDE.value for s in shots)
            framing = Framing.WIDE if (not shots or (_moves(group) and not wide_yet)) else Framing.MS
            title = _title_from(actions[0].text) if actions else (group[0].text[:40] or "Moment")
        shots.append(ProposedShot(group[0].index, group[-1].index + 1, framing.value, title, hint, None, False, link))

    def close() -> None:
        if not cur:
            return
        # A group that needs more than the longest shot is cut where the kernel would cut it, so each
        # part gets the size and sound it needs (a ring is seen; a voice is heard on its listener).
        for part in split_to_fit(ProposedShot(cur[0].index, cur[-1].index + 1), items, longest):
            emit(items[part.start:part.end], part.camera_link)
        cur.clear()

    for item in items:
        if item.kind == "cut":
            cur.append(item)
            close()
            continue
        cur_lines = [i for i in cur if i.is_line]
        if item.is_line:
            if cur_lines and cur_lines[-1].speaker != item.speaker:
                close()  # a new speaker: reverse shot
            elif not cur_lines and _action_words(cur) > SHORT_ACTION_WORDS:
                close()  # a long action plays as its own shot; a short one introduces the line
            cur.append(item)
        elif item.kind == "action":
            if cur_lines:
                close()  # action after a line starts the next shot
            cur.append(item)
        else:  # sound, beat: ride with whatever is on screen
            cur.append(item)
    close()
    return shots
