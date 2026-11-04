"""emotion_critic hooks. Ported from `script_split/engine/critic.py` (`review`, the EMOTION lens)."""
from __future__ import annotations

from hiru_ai.agents.emotion_critic.schema import Input, Output


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
