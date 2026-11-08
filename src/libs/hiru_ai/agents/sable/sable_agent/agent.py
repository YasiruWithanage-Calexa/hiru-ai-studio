"""sable_agent hooks (plan/2026-11-08 §4.3). The system prompt is static; everything about the turn is the user message.

The message names the scene in view (or none: Sable is production-wide), the person's role, what the older part of the
thread said, the recent chat, and the message, which the model reads last. The tools read everything else; their
scope (the production, the scene in view) comes from the run, never from the model.
"""
from __future__ import annotations

from typing import Any

from hiru_ai.agents.sable.sable_agent.schema import Input, Output


def user_message(inp: Input) -> str:
    scene = inp.scene or "none (the person is not looking at a scene)"
    cards = "yes" if inp.can_stage else "no: answer, and do not propose a card (change_propose, memory_propose)"
    parts = [f"<scene_in_view>{scene}</scene_in_view>",
             f"<person role=\"{inp.role or 'member'}\">can accept cards: {cards}</person>"]
    if inp.summary.strip():
        parts.append(f"<earlier_in_this_chat>\n{inp.summary.strip()}\n</earlier_in_this_chat>")
    parts.append(f"<recent_chat>\n{inp.history.strip()}\n</recent_chat>")
    parts.append(f"<message>\n{inp.message.strip()}\n</message>")
    return "\n".join(parts)


def memory_scope(inp: Input) -> dict[str, Any] | None:
    """The production memory narrowed to the scene in view; with none, every entry of the production."""
    return dict(inp.memory_scope) or None


def fallback(inp: Input) -> Output | None:
    """No model: the system says plainly that Sable is unavailable (absent-safe), so there is no rules-only answer."""
    return None
