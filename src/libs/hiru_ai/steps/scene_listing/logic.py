"""The scene as the planner and the critics read it: each block with its kind and the seconds it takes.

Ported from `script_split/engine/planner.py` (`scene_listing`, `_listing_rows`, `_held`; plan/2026-11-03 Phase 4). Four
agents put this listing in their user message, so it is one step they reach instead of four copies.
"""
from __future__ import annotations

from contracts.shotplan import Item, line_seconds


def _held(i: Item) -> str:
    """What the reading adds to a block: a turn in feeling, and the time to hold after it."""
    turn = " [FEELING TURNS HERE]" if i.turn else ""
    if i.hold_s <= 0:
        return turn
    who = f" for {i.hold_who}" if i.hold_who else ""
    return f"{turn} [HOLD {i.hold_s:.1f} s after it: {i.hold_kind}{who}, priority {i.hold_priority}]"


def scene_listing(items: list[Item], speaker_names: dict[str, str]) -> str:
    """The scene as the planner and the critic read it: each block with its kind and the seconds it takes."""
    return "\n".join(f"{row}{_held(i)}" for row, i in zip(_listing_rows(items, speaker_names), items, strict=True))


def _listing_rows(items: list[Item], speaker_names: dict[str, str]) -> list[str]:
    out = []
    for i in items:
        if i.is_line:
            who = speaker_names.get(i.speaker_id or "", i.speaker)
            delivery = f", {i.delivery}" if i.delivery else ""
            out.append(f"[{i.index}] DIALOGUE ({who}{delivery}, {i.words} words, "
                       f"{line_seconds(i):.1f} s): {i.text}")
        elif i.kind == "action" and i.screen == "inner":
            out.append(f"[{i.index}] STORY NOTE (not filmed): {i.text}")
        elif i.kind == "action" and i.screen == "info":
            out.append(f"[{i.index}] INFO (needs a carrier): {i.text}")
        elif i.kind == "action":
            events = f" x{i.events}" if i.events > 1 else ""
            tag = "implied, " if i.implied else ""
            out.append(f"[{i.index}] ACTION ({tag}{i.screen}{events}, {i.picture_s:.1f} s): {i.text}")
        else:
            out.append(f"[{i.index}] {i.kind.upper()}: {i.text}")
    return out
