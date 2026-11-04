"""Middleware a manifest can switch on by name. `hitl`, `retry`, `fallback`, `limits`, `clear_old_results` and
`tool_retry` (react.py) apply to `react` agents."""
from __future__ import annotations

from collections.abc import Callable, Sequence

from hiru_ai.core.errors import ManifestError
from hiru_ai.core.middleware.absent_safe import AbsentSafe
from hiru_ai.core.middleware.base import Document, Middleware, ModelCall, Next, run_chain
from hiru_ai.core.middleware.language_guard import LanguageGuard
from hiru_ai.core.middleware.static_first import StaticFirst
from hiru_ai.core.middleware.untrusted_text import UntrustedText
from hiru_ai.core.middleware.usage import Usage

# name → factory(writes_dialogue) so a manifest's flags reach the middleware that needs them
_FACTORIES: dict[str, Callable[[bool], Middleware]] = {
    "absent_safe": lambda writes: AbsentSafe(),
    "usage": lambda writes: Usage(),
    "untrusted_text": lambda writes: UntrustedText(),
    "static_first": lambda writes: StaticFirst(),
    "language_guard": lambda writes: LanguageGuard(writes_dialogue=writes),
}
NAMES = tuple(_FACTORIES)
# LangChain middleware, built by core.middleware.react (its NAMES; kept here so the registry need not import LangChain)
REACT_NAMES = ("hitl", "retry", "fallback", "limits", "clear_old_results", "tool_retry")
ALL_NAMES = (*NAMES, *REACT_NAMES)


def build(names: Sequence[str], *, writes_dialogue: bool = False) -> list[Middleware]:
    """Middleware in manifest order (outermost first). The language guard is added to every part that may not write
    dialogue, whether or not its manifest lists it: that rule is not optional."""
    unknown = [n for n in names if n not in ALL_NAMES]
    if unknown:
        raise ManifestError(f"unknown middleware {', '.join(unknown)}; known: {', '.join(ALL_NAMES)}")
    wanted = [n for n in names if n in _FACTORIES]  # react-only names are built by react.build
    if not writes_dialogue and "language_guard" not in wanted:
        wanted.append("language_guard")
    return [_FACTORIES[n](writes_dialogue) for n in wanted]


__all__ = ["ALL_NAMES", "NAMES", "REACT_NAMES", "Document", "Middleware", "ModelCall", "Next", "build", "run_chain"]
