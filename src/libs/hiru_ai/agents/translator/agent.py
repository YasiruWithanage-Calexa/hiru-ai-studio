"""translator hooks. Ported from `director_chat/engine/translate.py` (`_ask_for`).

The script stays in the language it was written in. Only when a person asks for the dialogue in another language does
this agent run, and it writes nothing itself: the system stages its lines as `block.set` operations on a copy of the
scene, shows each line before and after as a card, and the person applies it (the original words are then kept as the
line's source). `writes_dialogue: true` lifts the `language_guard` for this agent alone.

Code, not this agent, decides which lines are in scope, which already are in the language, which go back to their stored
source, and whether each translation really came back in the language's script.
"""
from __future__ import annotations

import json

from hiru_ai.agents.translator.schema import Input


def user_message(inp: Input) -> str:
    rows = [json.dumps({"line_id": ln.line_id, "speaker": ln.speaker, "delivery": ln.delivery, "text": ln.text},
                       ensure_ascii=False) for ln in inp.lines]
    rules = "\n".join(f"- {m}" for m in inp.memory) or "(none)"
    return (f"<target language=\"{inp.language}\" code=\"{inp.code or '-'}\">\n"
            f"<style>{inp.style or '(none given)'}</style>\n<production>{inp.production or '(none)'}</production>\n"
            f"<production_rules>\n{rules}\n</production_rules>\n<lines>\n" + "\n".join(rows) + "\n</lines>")
