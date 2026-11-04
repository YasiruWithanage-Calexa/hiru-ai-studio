"""coverage_critic hooks. Ported from `script_split/engine/critic.py` (`review`).

Model critics write notes; the kernel score in code picks the plan. The three lenses (coverage, emotion, editor)
read the same brief; each is its own agent so a lens can be switched off or given another tier in its manifest.
"""
from __future__ import annotations

from hiru_ai.agents.coverage_critic.schema import Input, Output


def user_message(inp: Input) -> str:
    parts = [f"<script>\n{inp.listing}\n</script>"]
    if inp.reading:
        parts.append(f"<reading>\n{inp.reading}\n</reading>")
    if inp.staging:
        parts.append(f"<staging>\n{inp.staging}\n</staging>")
    if inp.found:
        parts.append("CODE FOUND:\n" + "\n".join(f"- {f}" for f in inp.found))
    parts.append(f"Shot list:\n{inp.shot_list}")
    return "\n\n".join(parts)


def fallback(inp: Input) -> Output:
    """A reviewer that cannot answer has no notes; the other lenses still count."""
    return Output(acceptable=True, notes=[])
