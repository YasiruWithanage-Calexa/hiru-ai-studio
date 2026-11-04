"""look_drafter hooks. Ported from `structure_build/engine/looks.py` (`listing`). Drafts only: nothing here marks a look
ready, and a character that already has a look is not sent (the system filters with `wanted`)."""
from __future__ import annotations

from hiru_ai.agents.look_drafter.schema import Input

CARD_PARTS = ("wardrobe", "appearance", "summary", "notes")


def user_message(inp: Input) -> str:
    parts = [f"Episodes: {max(inp.episodes, 1)}"]
    for c in inp.characters:
        body = "\n".join(f"{k}: {c.card[k]}" for k in CARD_PARTS if c.card.get(k))
        parts.append(f'<character name="{c.name}">\n{body}\n</character>')
    return "\n\n".join(parts)
