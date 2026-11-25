"""board_counter hooks (plan/2026-11-25 B, lab/board_hands R5: the blind count).

Looks at ONE painted Scene board panel told only the mannequins' colours, never what the panel should show: the lab
found `board_inspector`, given the expected hands, copies them back and misses a third arm (R0-R3 caught 0 of 4); told
nothing, the same model caught 1 to 3 of 4 with no false alarm (R5). It counts each mannequin's arms and hands and
says where each held thing is; CODE calls the fault (`contracts.board.count_faults`: more than two arms or hands, a
thing in the air). The board job runs it beside `board_inspector` (`frame_render.board._check_panel`). No key, or a
failed call, gives no count: there is no fallback.
"""
from __future__ import annotations

from hiru_ai.agents.board_counter.schema import Input


def user_message(inp: Input) -> str:
    return "MANNEQUINS IN THIS PANEL:\n" + "\n".join(f"- the {c} mannequin" for c in inp.mannequins)


def images(inp: Input) -> list[tuple[str, str]]:
    """The panel only (lab R5: no view crop)."""
    return [(inp.mime, inp.image_b64)]
