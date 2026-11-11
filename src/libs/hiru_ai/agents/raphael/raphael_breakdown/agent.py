"""raphael_breakdown hooks (plan/2026-11-10 §2): ONE request, no tools, the director's breakdown of a scene.

The user message is the one stage 1 already gets, then the ask. There is no fallback here: the caller
(`systems/raphael/.../scene.py`) checks the answer with `contracts.raphael.checks.breakdown_faults`, asks once more
with the faults, and otherwise goes on without a breakdown.
"""

from __future__ import annotations

from hiru_ai.agents.raphael.raphael_breakdown.schema import Input

ASK = "Write the director's shot breakdown of this scene."


def user_message(inp: Input) -> str:
    asked = f"{inp.opening}\n\n{ASK}"
    if not inp.faults:
        return asked
    return (
        asked
        + "\n\nYour last breakdown had these problems. Write it again with every one of them put right:\n"
        + "\n".join(f"- {f}" for f in inp.faults)
    )
