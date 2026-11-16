"""board_writer hooks (plan/2026-11-14 §3.2). Ported from the storyboard lab's writer call (`lab/storyboard/run.py`).

The message is built in code (`contracts.board.writer_message`) so the engine and the lab say the same thing; the
reference pictures follow it at detail low. No fallback: without a key the board is not painted, and the person is told.
A quality problem is fixed in `prompts/system.md` with a principle and examples from OTHER stories, never with one
scene's words (plan/2026-11-14 §0).
"""
from __future__ import annotations

from hiru_ai.agents.board_writer.schema import Input


def user_message(inp: Input) -> str:
    return inp.message


def images(inp: Input) -> list[tuple[str, str]]:
    return [(p.mime, p.b64) for p in inp.pictures]
