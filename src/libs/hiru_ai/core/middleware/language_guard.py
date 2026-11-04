"""`language_guard`: dialogue keeps the language it was written in; only approved parts may change a line.

Parts without `writes_dialogue` get this guard: whatever lines a result carries (`call.lines_after`) must equal the
lines the call was given (`call.lines_before`), byte for byte. A part with `writes_dialogue: true` (today only the
translator, and always staged as a card a person accepts) is not checked here. A line that is missing from the
result is not a change; a line whose text differs, or an id that was not given, is.
"""
from __future__ import annotations

from typing import Any

from hiru_ai.core.context import RunContext
from hiru_ai.core.errors import DialogueChanged
from hiru_ai.core.middleware.base import ModelCall, Next

name = "language_guard"


def changed_lines(before: dict[str, str] | Any, after: dict[str, str] | Any) -> list[str]:
    """Ids of lines whose text differs from the given one, or that were not given."""
    return sorted(i for i, text in after.items() if i not in before or before[i] != text)


class LanguageGuard:
    name = name

    def __init__(self, writes_dialogue: bool = False) -> None:
        self.writes_dialogue = writes_dialogue

    def __call__(self, call: ModelCall, ctx: RunContext, nxt: Next) -> Any:
        result = nxt(call)
        if self.writes_dialogue or call.lines_before is None or call.lines_after is None:
            return result
        bad = changed_lines(call.lines_before, call.lines_after(result))
        if bad:
            raise DialogueChanged(f"{call.component} changed dialogue it may not write: {', '.join(bad)}")
        return result
