"""scene_planner hooks. Ported from `script_split/engine/planner.py` (`plan_by_model`).

It PROPOSES shots as ranges of blocks. Code (`contracts.shotplan.fit`) makes the proposal renderable, binds the lines
verbatim and decides the timing; an answer with no shots is an error the system answers with the rules' plan, so
there is no fallback here.
"""
from __future__ import annotations

from hiru_ai.agents.scene_planner.schema import Input
from hiru_ai.steps.scene_listing.logic import scene_listing


def user_message(inp: Input) -> str:
    user = (f"Scene: {inp.heading}\nEnvelope: {inp.envelope_s} s. "
            f"Allowed shot lengths: {', '.join(map(str, inp.allowed))} s.\n"
            + (f"<context>\n{inp.context}\n</context>\n" if inp.context else "")
            + (f"<reading>\n{inp.reading}\n</reading>\n" if inp.reading else "")
            + f"Blocks 0 to {len(inp.items) - 1}:\n<script>\n"
            + scene_listing(list(inp.items), inp.speaker_names) + "\n</script>")
    if inp.notes:
        user += "\n\nA reviewer found these problems in the previous plan; fix them:\n" + "\n".join(
            f"- {n}" for n in inp.notes)
    return user
