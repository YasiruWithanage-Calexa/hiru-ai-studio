"""The cards a model's `stage` tool left, shown as the options card the turn already shows (plan/2026-11-04 §8).

A tool that stages (`change_propose`, `memory_propose`) puts a plain card in the run's `staging` port and changes
nothing. After the reply is written the turn reads the cards back and turns each into one option of an options block, so
a person accepts or ignores it with the controls they already have, through the existing pending-action route (D4):

  change   the operations the kernel confirmed would land, pinned to the shots' ids like any option's. Accepting
           applies them in code, exactly as a button press does.
  memory   a message for the board, "Remember from now on: ...". Choosing it sends it as the next turn, and the
           conductor files the rule as it files any other.

Nothing here applies anything. A card for another scene than the one in scope is dropped.
"""
from __future__ import annotations

import logging
from typing import Any

from hiru_ai.steps.scene_kernel.logic import ScenePlanKernel
from hiru_ai.steps.scene_kernel.turn_logic import describe_op, pin

_logger = logging.getLogger(__name__)
MAX_OPTIONS = 4
Row = dict[str, Any]


def option_of(card: Row, kernel: ScenePlanKernel, scene_id: str) -> Row | None:
    """The option a staged card becomes, or None when the card cannot be shown (another scene, nothing to apply)."""
    option: Row = {"label": "", "detail": "", "change": "", "impact": "", "ops": [], "prompt": "", "intent": ""}
    if card.get("kind") == "change":
        if str(card.get("scene_id")) != scene_id:
            return None
        handles = kernel.handles()
        ops = [pin(o, handles) for o in card.get("ops") or []]
        if not ops or not all(ops):
            return None
        touched = card.get("touched") or []
        option |= {"label": str(card.get("summary") or "").strip()[:80], "ops": ops,
                   "change": "; ".join(describe_op(o) for o in card.get("ops") or []),
                   "impact": f"Touches {', '.join(touched)}" if touched else ""}
        return option if option["label"] else None
    if card.get("kind") == "memory":
        rule = str(card.get("rule") or "").strip()
        if not rule:
            return None
        option |= {"label": "Remember this rule", "detail": rule[:300], "prompt": f"Remember from now on: {rule}"[:500]}
        return option
    _logger.warning("a staged card of kind %r cannot be shown", card.get("kind"))
    return None


def merge(options: Row | None, cards: list[Row], kernel: ScenePlanKernel, scene_id: str) -> Row | None:
    """`options` (the block the turn already has, or None) plus the staged cards as options, at most four in all."""
    shown = [o for c in cards if (o := option_of(c, kernel, scene_id)) is not None]
    if not shown:
        return options
    if options is None:
        return {"kind": "options", "question": "Do you want this?", "options": shown[:MAX_OPTIONS]}
    return {**options, "options": [*options["options"], *shown][:MAX_OPTIONS]}
