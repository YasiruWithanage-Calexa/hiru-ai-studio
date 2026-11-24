"""board_inspector hooks (plan/2026-11-23c F2).

Looks at ONE painted Scene board panel for the faults a person found on the board of 2026-11-23: a mannequin with a
third arm, an umbrella held up by nothing, feet hovering over a drain, a thing in the wrong hand; and a background that
shows another view of the place than the one the panel names (plan/2026-11-24c §2.7). The board job paints
a failed panel again ALONE, once, told what was wrong (`frame_render.board._mend`). No key, or a failed call, gives no
check and the panel is kept: there is no fallback.
"""
from __future__ import annotations

from hiru_ai.agents.board_inspector.schema import Input


def user_message(inp: Input) -> str:
    people = "\n".join(f"- {p}" for p in inp.people) or "- no mannequin (an insert or a place)"
    return ("<expected>\nMANNEQUINS:\n" + people
            + f"\nTHE PANEL SHOULD SHOW: {inp.panel or 'as above'}"
            + (f"\nHANDS: {inp.hands}" if inp.hands else "")
            + (f"\nVIEW: {inp.view} (the second picture is this view of the place, cut from its sheet)"
               if inp.view and inp.view_b64 else "") + "\n</expected>")


def images(inp: Input) -> list[tuple[str, str]]:
    """The panel first; then the view it names, cut from the place's sheet (plan/2026-11-24c §2.7)."""
    return [(inp.mime, inp.image_b64)] + ([("image/png", inp.view_b64)] if inp.view and inp.view_b64 else [])
