"""jonathan_revise hooks (plan/2026-11-06b §4.1): the cinematic lab's revise pass, the stabiliser's one model step.

The reviser is the author again: the same prompt (`prompts/system.md` is the author's to the letter; a test compares
them) and the same user message, followed by its own draft and what code found in it (the lab's `revise_message`, word
for word). It returns the complete corrected plan, not a patch: the lab measured that a whole plan converges in two
passes
and that a patch cannot move the treatment or the sequences. Code then mends and checks it, and keeps it only when it is
better (`systems/jonathan`). The cleaning here is the author's: a reference to a block or a line the scene lacks goes.
"""
from __future__ import annotations

import json
from typing import Any

from contracts.jonathan.measures import Measure
from contracts.jonathan.plan import Problem
from contracts.jonathan.scene import clean
from contracts.jonathan.wire import JonathanWire
from hiru_ai.agents.jonathan.jonathan_revise.schema import Input, Output
from hiru_ai.agents.jonathan.wire_schema import wire_schema

SCHEMA_NAME = "jonathan_plan"
# the lab's words, to the letter
ASK = ("The draft is your own first answer. Return the complete corrected plan in the same shape. Change only what "
       "the findings need: keep every shot, sequence and choice that already works, and never remove coverage, a "
       "block or a line to fix a problem.")


def output_schema() -> dict[str, Any]:
    return wire_schema(JonathanWire, SCHEMA_NAME)


def findings(problems: list[Problem], gaps: list[Measure], note: str = "") -> str:
    """What code found, as the lab wrote it: the problems to fix, then the craft gaps to improve; a person's note
    last."""
    rows = ["Problems code found in the draft (fix every one):",
            "\n".join(f"- {p.sentence}" for p in problems) or "- none", "",
            "Craft gaps (improve them where the scene allows it):",
            "\n".join(f"- {m.label}: {m.detail}" for m in gaps) or "- none"]
    if note.strip():
        rows += ["", "A person's note on the plan (do what it asks, within the rules that never bend):",
                 f"- {' '.join(note.split())}"]
    return "\n".join(rows)


def user_message(inp: Input) -> str:
    draft = json.dumps(inp.draft.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))
    return (f"{inp.pack}\n\n<draft>\n{draft}\n</draft>\n\n<findings>\n{findings(inp.problems, inp.gaps, inp.note)}\n"
            f"</findings>\n\n{ASK}")


def finish(inp: Input, out: Output) -> Output:
    return Output.model_validate(clean(inp.scene, out).model_dump())
