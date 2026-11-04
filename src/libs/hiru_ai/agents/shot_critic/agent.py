"""shot_critic hooks. Ported from `shot_producer/engine/critique.py` (`review`).

Bounded on purpose: ONE review, at most ONE revision, and the system keeps a revised shot only when the free checks find
no more problems in it than in the first draft. No notes means the first draft stands, which is also the fallback.
"""
from __future__ import annotations

from hiru_ai.agents.shot_critic.schema import Input, Output

MAX_NOTES = 4


def user_message(inp: Input) -> str:
    return ("<scene>\n" + f"SCENE {inp.scene_number}: {inp.heading}\n" + inp.context
            + ("\nCOVERAGE PLAN:\n" + inp.plan if inp.plan else "")
            + "\n\n" + "\n\n".join(inp.drafts) + "\n</scene>\n\nFREE CHECKS:\n"
            + ("\n".join(f"- {f}" for f in inp.free) or "- none"))


def finish(inp: Input, out: Output) -> Output:
    """At most four short notes; none when the model is content and code found nothing."""
    notes = [" ".join(n.split()) for n in out.notes if n.strip()]
    if out.acceptable and not inp.free:
        notes = []
    return Output(acceptable=out.acceptable, notes=notes[:MAX_NOTES])


def fallback(inp: Input) -> Output:
    return Output(acceptable=True, notes=[])
