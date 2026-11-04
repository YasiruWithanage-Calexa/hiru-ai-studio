"""Errors the core raises. Each says what a caller can do about it."""
from __future__ import annotations


class HiruAIError(Exception):
    """Base class: catch this to catch any error raised on purpose by hiru_ai."""


class ModelUnavailable(HiruAIError):
    """No API key, or the model cannot be reached. Callers take the rules-only path (absent-safe)."""


class ManifestError(HiruAIError):
    """A component.yaml is malformed or names something that does not exist."""


class UnknownComponent(HiruAIError, KeyError):
    """`registry.get(kind, id)` for a part that is not there (or is disabled)."""


class DialogueChanged(HiruAIError):
    """A part that may not write dialogue changed a line (language_guard)."""


class StaticPrefixError(HiruAIError):
    """A prompt's static part was altered or placed after per-item data (static_first)."""


class ToolRefused(HiruAIError):
    """A tool was asked for something it must not do (a scene of another production, a line it may not change).
    The message is written for whoever asked: a model reads it as the tool's answer, a person as the reason.

    `how_to_fix` says what to change in the call and `example` shows a call that works (plan/2026-11-04 §4.6); a model
    that reads them can correct itself instead of guessing. Both are optional, so a plain refusal still works."""

    def __init__(self, message: str, how_to_fix: str = "", example: str = "") -> None:
        super().__init__(message)
        self.how_to_fix, self.example = how_to_fix, example

    def as_result(self) -> dict[str, str]:
        """What a model reads: `{"error", "how_to_fix", "example"}`, the last two only when given."""
        out = {"error": str(self)}
        if self.how_to_fix:
            out["how_to_fix"] = self.how_to_fix
        if self.example:
            out["example"] = self.example
        return out


class PortMissing(HiruAIError):
    """A part needs a port the composition root did not provide (RunContext.ports)."""
