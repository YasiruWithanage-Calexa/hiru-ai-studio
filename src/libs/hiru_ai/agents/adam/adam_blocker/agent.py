"""adam_blocker hooks. Ported from `agents/stager` (its prompt and the idea of a mark that holds until the next one);
see ORIGIN.md for the source commit and every change.

The answer is validated in code entry by entry (an invalid entry is dropped, not repaired): a mark or a move that names
a moment the plan does not have, or a person who is not in the scene, is dropped. Code, not the model, finds the
teleports and the props that change hands unseen (`adam_continuity`). There is no fallback: a scene with no staging is
still planned, but that is the system's decision (an empty `Staging`), not this agent's.
"""
from __future__ import annotations

from contracts.adam.plan import Moment, compact, norm
from hiru_ai.agents.adam.adam_blocker.schema import Input, Output


def moments_text(moments: list[Moment]) -> str:
    """One row a moment: the id, who is in it, what the camera sees and the objects it shows."""
    rows = []
    for m in moments:
        who = ", ".join(m.who) or "-"
        things = f" | objects: {', '.join(m.objects)}" if m.objects else ""
        rows.append(f"{m.id} [{m.tier}] who: {who} | {m.seen}{things}")
    return "\n".join(rows)


def user_message(inp: Input) -> str:
    return (f"<place>\n{inp.scene.place.name}\nObjects: {', '.join(inp.scene.place.objects)}\n</place>\n\n"
            f"<analysis>\n{compact(inp.analysis)}\n</analysis>\n\n"
            f"<treatment>\n{compact(inp.treatment)}\n</treatment>\n\n"
            f"Moments:\n<moments>\n{moments_text(inp.moments)}\n</moments>")


def finish(inp: Input, out: Output) -> Output:
    moments = {m.id for m in inp.moments}
    people = {norm(c) for c in inp.scene.cast} | {norm(w) for m in inp.moments for w in m.who}
    return Output(marks=[m for m in out.marks if m.moment in moments and norm(m.who) in people],
                  moves=[m for m in out.moves if m.moment in moments and norm(m.who) in people])
