"""conductor hooks. Ported from `director_chat/engine/conductor.py` (`by_model`).

The conductor only READS the message and picks a lane; code applies what it writes, re-times the scene and binds the
approved dialogue. What the person typed that a rule can answer exactly (`is_exact_command`) never reaches it, and the
rules read the message when it cannot answer, so there is no fallback here.
"""
from __future__ import annotations

from hiru_ai.agents.conductor.schema import Input

# Added after the message when the first answer would have changed nothing (Nova W6): the system prompt stays
# byte-identical, so the provider's prompt cache still serves it.
AGAIN = ("\n<again>\nYour last answer for this message wrote no operations and no tasks, so nothing would "
         "change. Write the operations or tasks it asks for, or answer lane chat or options and say what is "
         "missing.\n</again>")


def user_message(inp: Input) -> str:
    context = "\n".join(f"- {m}" for m in inp.memory) or "(none)"
    return (f"<production_memory>\n{context}\n</production_memory>\n<recent_chat>\n{inp.history}\n</recent_chat>\n"
            f"<person_messages>\n{inp.said or '(none)'}\n</person_messages>\n"
            f"<shot_list>\n{inp.plan_text}\n</shot_list>\n<message>\n{inp.message}\n</message>"
            + (AGAIN if inp.again else ""))
