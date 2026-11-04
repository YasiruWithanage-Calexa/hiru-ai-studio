"""The cards a `stage` tool leaves for a person: a list the run's owner reads back (plan/2026-11-04 §4.3).

A model never changes stored data. A `stage` tool (`change_propose`, `memory_propose`) puts a card here instead; the
director turn reads `staged()` after the agent finished and shows each card the way it already shows an options card,
where a person accepts or ignores it. So the "staging" port needs no table: a card is only a card until a person says
yes."""
from __future__ import annotations

from hiru_ai.core.ports import Row


class StagedCards:
    """`Staging`: the run's cards, oldest first. One instance per run (it is built with the run's context)."""

    def __init__(self) -> None:
        self.cards: list[Row] = []

    def add(self, card: Row) -> str:
        card_id = str(card.get("id") or f"card-{len(self.cards) + 1}")
        self.cards.append({**card, "id": card_id})
        return card_id

    def staged(self) -> list[Row]:
        return [dict(c) for c in self.cards]
