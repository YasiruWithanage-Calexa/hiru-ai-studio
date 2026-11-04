"""options_writer hooks. Ported from `director_chat/engine/options.py` (`propose`).

Each option is tried on a copy of the scene and dropped if its operations do not reach the goal its label promises; that
check is code (the `scene_kernel` step), not this agent. A model that fails offers nothing, so there is no fallback.
"""
from __future__ import annotations

from hiru_ai.agents.options_writer.schema import Input


def user_message(inp: Input) -> str:
    context = "\n".join(f"- {m}" for m in inp.memory) or "(none)"
    return (f"<lead_director>\n{inp.lead_charter or 'Direct for a family teledrama audience.'}\n</lead_director>\n"
            f"<production_memory>\n{context}\n</production_memory>\n<recent_chat>\n{inp.history}\n</recent_chat>\n"
            f"<shot_list>\n{inp.shot_list}\n</shot_list>\n<message>\n{inp.message}\n</message>")


def tools_user_message(inp: Input) -> str:
    """The message of the `with_tools` form: no memory list (`memory_search` reads it when an option needs it)."""
    return (f"<lead_director>\n{inp.lead_charter or 'Direct for a family teledrama audience.'}\n</lead_director>\n"
            f"<recent_chat>\n{inp.history}\n</recent_chat>\n"
            f"<shot_list>\n{inp.shot_list}\n</shot_list>\n<message>\n{inp.message}\n</message>")
