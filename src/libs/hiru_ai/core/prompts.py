"""Prompts are files in the part's folder, static part first.

OpenAI caches a prompt by its leading bytes, so the system prompt is the file's text, unchanged, on every call,
and per-item data goes in the user message (CLAUDE.md "AI and RAG"). A `Prompt` therefore has no placeholders:
it is the static text and its hash. The hash identifies the prompt in traces and lets `static_first` notice drift.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from hiru_ai.core.errors import ManifestError


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


@dataclass(frozen=True)
class Prompt:
    name: str
    text: str

    @property
    def sha(self) -> str:
        return sha(self.text)

    @classmethod
    def load(cls, path: Path) -> Prompt:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ManifestError(f"prompt file missing: {path}") from exc
        if not text.strip():
            raise ManifestError(f"prompt file is empty: {path}")
        return cls(name=path.stem, text=text)

    def system(self, *shared: str) -> str:
        """The system message: this static text first, then any further static blocks (shared craft notes...).

        Everything passed here must itself be constant across calls; per-item data belongs in the user message.
        """
        return self.text + "".join(f"\n\n{block}" for block in shared)
