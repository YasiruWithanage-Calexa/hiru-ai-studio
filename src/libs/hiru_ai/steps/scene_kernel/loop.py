"""The loop breaker (plan/2026-11-01c, Phase 5): the same unmet request twice in a row is answered, not tried again.

Every turn that has a goal writes it on its reply (`TextBlock.goal`, with `met`): the translation asked for
(`dialogue.si`), or the thing the chat cannot do (`cannot:<route>`). When the person's next message has the
same goal and the last reply left it unmet, nothing is run again: the reply is fixed text in code, says what
is not possible and the exact route, and when a card is open that "the card above is waiting". The third
repeat gets the same reply, because the reply itself carries the goal. A card that was chosen (Apply or Keep)
ends the run: asking again after a "Keep" is a new request.
"""
from __future__ import annotations

import re
from typing import Any

WAITING = "That is waiting on the card above: choose Apply to put it in, or Keep to leave the script as it is."
AGAIN = "Asking again will not change that."


def cannot_goal(cannot: dict[str, str]) -> str:
    """One goal per way out: the same route is the same unmet need, however the request was worded."""
    return "cannot:" + " ".join(re.sub(r"[^a-z0-9→ ]+", " ", cannot.get("route", "").lower()).split())[:60]


def translate_goal(spec: Any) -> str:
    return f"dialogue.{spec.to}" if spec.to else ""


def goal_of(message: dict[str, Any]) -> tuple[str, bool]:
    """→ (goal, met) a director reply recorded, ("", True) when it had none."""
    for block in message.get("blocks") or []:
        if block.get("kind") == "text" and block.get("goal"):
            return str(block["goal"]), block.get("met") is True
    return "", True


def repeated(history: list[dict[str, Any]], goal: str) -> bool:
    """Is `goal` the one the director's last replies left unmet? Walks back over the replies that carry the same
    goal: any that was met, or whose card the person chose on (Apply or Keep), ends the run, and asking again
    is a new request."""
    if not goal:
        return False
    run = 0
    for message in reversed(history):
        if message.get("kind") != "director":
            continue
        earlier, met = goal_of(message)
        if earlier != goal:
            break
        if met or any(b.get("kind") == "options" and b.get("chosen") is not None for b in message.get("blocks") or []):
            return False
        run += 1
    return run > 0


def card_open(history: list[dict[str, Any]]) -> bool:
    """Is the director's latest card still waiting for a choice?"""
    for message in reversed(history[-8:]):
        if message.get("kind") != "director":
            continue
        cards = [b for b in message.get("blocks") or [] if b.get("kind") == "options"]
        if cards:
            return any(b.get("chosen") is None and any(o.get("ops") or o.get("prompt") for o in b.get("options") or [])
                       for b in cards)
    return False


def reply(history: list[dict[str, Any]], *, cannot_text: str = "", waiting: bool = False) -> str:
    """What to say instead of trying again. `cannot_text`: why it is not possible and where (the request is one
    the chat cannot do). `waiting`: a pending action or card is open."""
    if waiting or card_open(history):
        return WAITING
    if cannot_text:
        return f"{cannot_text} {AGAIN}"
    previous = next((str(b.get("text", "")) for m in reversed(history) if m.get("kind") == "director"
                     for b in m.get("blocks") or [] if b.get("kind") == "text"), "")
    return f"{previous} {AGAIN}".strip()
