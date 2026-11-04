"""Every model call of a director turn, behind one object: the agents are found by id, the specialists and advisors run
through the `director_board` panel. The turn's code (`edits.py`, `turn.py`) asks `models` and never knows which agent
answered, so a craft added to the panel's manifest, or an agent switched off, changes nothing else.
"""
from __future__ import annotations

from typing import Any

from hiru_ai.core import agents, llm, parts
from hiru_ai.core.context import RunContext
from hiru_ai.core.panels import PanelKit

Row = dict[str, Any]


class Outputs(list):
    """The specialists' outputs, in task order, with what the board settled from them."""

    settled: Any = None


def _plain(out: Any) -> Row:
    return dict(out.model_dump(mode="json"))


class Models:
    def __init__(self, ctx: RunContext) -> None:
        self.ctx = ctx
        self.enabled = llm.models_enabled()
        self._board_module = parts.module("panel", "director_board", "graph")
        self._board = self._board_module.build(ctx)
        self._kit = PanelKit(self._board_module.ID, ctx)
        self.allowed: dict[str, tuple[str, ...]] = self._board_module.allowed_ops(self._kit.manifest)

    def _ask(self, agent: str, inp: Row) -> Row:
        return _plain(agents.build(agent).run(inp, self.ctx))

    # the conductor, the options writer and the translator: one typed call each
    def conductor(self, inp: Row) -> Row:
        return self._ask("conductor", inp)

    def options(self, inp: Row) -> Row:
        if agents.build("options_writer").uses_tools:  # it reads the remembered decisions with `memory_search`
            inp = {**inp, "memory": []}
        return self._ask("options_writer", inp)

    def translator(self, inp: Row) -> Row:
        return self._ask("translator", inp)

    def specialists(self, tasks: list[Row], *, scene_text: str, lead_charter: str) -> Outputs:
        """One result per task, in order (a craft that failed or has no member answers with no operations)."""
        out = self._board.invoke({"brief": {"scene_text": scene_text, "lead_charter": lead_charter}, "tasks": tasks})
        outputs = Outputs(out["outputs"])
        outputs.settled = out["settled"]
        return outputs

    def settle(self, outputs: Outputs) -> Any:
        """Who wins a collision, decided by the manifest's `wins:` table in code."""
        return outputs.settled

    def advice(self, reviews: list[Row], *, scene_text: str) -> list[Row | None]:
        """What each advisor says after the changes landed; None for one who agrees or cannot answer."""
        if not reviews:
            return []
        out = self._board.invoke({"brief": {"scene_text": scene_text}, "reviews": reviews})
        return list(out.get("advice") or [])
