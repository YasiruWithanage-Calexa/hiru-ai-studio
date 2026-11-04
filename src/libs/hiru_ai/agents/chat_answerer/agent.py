"""chat_answerer hooks. Ported from `director_chat/engine/turn.py` (`_reply`).

The reply is written from the turn's facts: what was applied, refused, waiting or not possible, and the scene as it now
is. The facts are the last thing the model reads (Nova W2). A reply is read as it is written, so there is no fallback
here: a model that fails is answered in code by `template_reply`, which the system decides.
"""
from __future__ import annotations

from hiru_ai.agents.chat_answerer.schema import Input


def user_message(inp: Input) -> str:
    return (f"<persona>{inp.persona}</persona>\n<recent_chat>\n{inp.history}\n</recent_chat>\n"
            f"<shot_list>\n{inp.shot_list}\n</shot_list>\n"
            f"<message>\n{inp.message}\n</message>\n"
            "<turn>\n" + "\n".join(inp.turn) + "\n</turn>")


def tools_user_message(inp: Input) -> str:
    """The message of the `with_tools` form: the scene is a one-line summary (the shot list is read with the tools)."""
    return (f"<persona>{inp.persona}</persona>\n<recent_chat>\n{inp.history}\n</recent_chat>\n"
            f"<scene>\n{inp.shot_list}\n</scene>\n"
            f"<message>\n{inp.message}\n</message>\n"
            "<turn>\n" + "\n".join(inp.turn) + "\n</turn>")
