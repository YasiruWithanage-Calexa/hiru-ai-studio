"""adam_fixer hooks (plan/2026-11-05 T3). New for Adam; the reviser's operations, for one problem.

It is given the problem, the cards and moments around it, the scene and the treatment's concept, not the whole plan. Its
operations are applied by the system and code checks the whole plan again; a fix that breaks something is refused and
goes up a rung. There is no fallback: a fixer that cannot answer leaves the problem to the next rung, and then to the
report.
"""
from __future__ import annotations

from contracts.adam.plan import compact
from contracts.adam.problems import problem_line
from hiru_ai.agents.adam.adam_fixer.schema import Input, Output


def user_message(inp: Input) -> str:
    return (f"<script>\n{inp.scene.listing()}\n</script>\n\n"
            f"<concept>\n{inp.concept}\n</concept>\n\n"
            f"<problem>\n{problem_line(inp.problem)}\n</problem>\n\n"
            f"<moments>\n{compact(list(inp.moments))}\n</moments>\n\n"
            f"<cards>\n{compact(list(inp.cards))}\n</cards>"
            + (f"\n\n<report>\n{inp.report}\n</report>" if inp.report else "")
            + (f"\n\n<earlier>\n{inp.earlier}\n</earlier>" if inp.earlier else ""))


def finish(inp: Input, out: Output) -> Output:
    return out
