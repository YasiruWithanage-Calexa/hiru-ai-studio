"""stager hooks. Ported from `script_split/engine/staging.py` (`_user`).

The answer is validated in code entry by entry (an invalid entry is dropped, not repaired), and code, not the model,
finds the teleports. No answer, or one with no usable marks, leaves the scene without a map and nothing about places is
checked (absent-safe), so there is no fallback here.
"""
from __future__ import annotations

from hiru_ai.agents.stager.schema import Input
from hiru_ai.steps.scene_listing.logic import scene_listing


def user_message(inp: Input) -> str:
    return ((f"<place>\n{inp.place}\n</place>\n\n" if inp.place else "")
            + (f"<reading>\n{inp.reading_text}\n</reading>\n\n" if inp.reading_text else "")
            + f"Blocks 0 to {len(inp.items) - 1}:\n<script>\n"
            + scene_listing(list(inp.items), inp.speaker_names) + "\n</script>")
