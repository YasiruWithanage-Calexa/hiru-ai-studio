"""The translator agent (plan/2026-11-01c, Phase 4; decision D1 accepted).

The script stays in the language it was written in. Only when the person asks for the dialogue in another
language ("all dialogue in Sinhala", "translate S02 to Tamil, formal", "back to English") does this agent run:
one strict-JSON call at the `high` tier, the spoken lines in, `{line_id, text}` out. It writes nothing itself.
It hands back `block.set` operations marked `translated_to`; the turn TRIES them on a copy of the scene
(`turn._stage`, `by="translator"`), shows every line before and after as a card, and the person applies it
(`choice.apply_choice`), which is also when the line's original words are kept as its source.

What code decides, not the model: which lines are in scope, which already are in the language (left alone),
which can simply go back to their stored source (no model call), and whether each translation really came back
in the language's script (a line that did not is left out, never shown as done).
"""
from __future__ import annotations

import logging
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from contracts import director_capabilities as caps
from hiru_ai.steps.scene_kernel.logic import ScenePlanKernel

_logger = logging.getLogger(__name__)
Ask = Callable[[dict[str, Any]], dict[str, Any]]  # the translator agent's input -> its answer
CHUNK = 30  # lines per call: the answer stays short enough to be exact
MAX_LINE_CHARS = 2000  # as the kernel's `SCRIPT_LIMITS["text"]`

@dataclass(frozen=True)
class Spec:
    """What the person asked for: a language (its name; `code` when it is one we can check), a style, and the
    shots to cover (empty: every spoken line in the scene)."""

    language: str = ""
    code: str = ""
    style: str = ""
    shots: tuple[int, ...] = ()

    @staticmethod
    def of(raw: dict[str, Any] | None) -> Spec:
        raw = raw or {}
        return Spec(str(raw.get("language") or ""), str(raw.get("code") or ""), str(raw.get("style") or ""),
                    tuple(int(n) for n in raw.get("shots") or []))

    @property
    def known(self) -> caps.Language | None:
        return caps.language_by_code(self.code) or caps.language_named(self.language)

    @property
    def name(self) -> str:
        return self.known.name if self.known else self.language

    @property
    def to(self) -> str:
        """What a translated line is marked with: the language's code, else its name."""
        return self.known.code if self.known else self.language


@dataclass
class Result:
    ops: list[dict[str, Any]] = field(default_factory=list)  # block.set, translated_to: ready for `_stage`
    scope: list[int] = field(default_factory=list)  # the blocks asked about (the lines in the shots named)
    already: int = 0  # lines that were in the language already: left alone
    restored: int = 0  # lines put back from their stored source, no model involved
    left_out: list[str] = field(default_factory=list)  # lines the translator did not deliver, and why
    error: str = ""  # the translator could not run


def lines_in_scope(kernel: ScenePlanKernel, spec: Spec, line_blocks: dict[int, list[int]]) -> list[int]:
    """The blocks of the spoken lines the request covers."""
    if spec.shots:
        wanted = sorted({b for n in spec.shots for b in line_blocks.get(n, [])})
    else:
        wanted = [b for b, item in enumerate(kernel.items) if item["kind"] == "dialogue"]
    return [b for b in wanted if str(kernel.items[b].get("text") or "").strip()]


def _op(block: int, text: str, was: str, spec: Spec) -> dict[str, Any]:
    return {"op": "block.set", "block": block, "field": "text", "value": text, "translated_to": spec.to,
            "translated_from": caps.script_of(was)}


def propose(ask: Ask, *, kernel: ScenePlanKernel, spec: Spec, line_blocks: dict[int, list[int]], production: str,
            memory: list[str]) -> Result:
    """Translate the lines in scope. Never raises: a translator that cannot answer is `Result.error`."""
    result = Result(scope=lines_in_scope(kernel, spec, line_blocks))
    known = spec.known
    need: list[int] = []
    for b in result.scope:
        item = kernel.items[b]
        text = str(item.get("text") or "")
        if known and caps.script_of(text) == known.code:
            result.already += 1  # nothing to do
        elif known and item.get("source_text") and item.get("source_lang") == known.code:
            result.ops.append(_op(b, str(item["source_text"]), text, spec))  # back to the words it was written in
            result.restored += 1
        else:
            need.append(b)
    for start in range(0, len(need), CHUNK):
        _ask_for(ask, kernel, spec, need[start:start + CHUNK], production, memory, result)
    result.ops.sort(key=lambda o: o["block"])
    return result


def _ask_for(ask: Ask, kernel: ScenePlanKernel, spec: Spec, blocks: list[int], production: str, memory: list[str],
             result: Result) -> None:
    lines = [{"line_id": str(kernel.items[b]["line_id"]), "speaker": str(kernel.items[b].get("speaker", "")),
              "delivery": str(kernel.items[b].get("delivery", "")), "text": str(kernel.items[b].get("text", ""))}
             for b in blocks]
    try:
        answer = ask({"language": spec.name, "code": spec.code, "style": spec.style, "production": production,
                      "memory": memory, "lines": lines})
    except Exception:
        _logger.warning("translator failed", exc_info=True)
        result.error = "the translator did not answer"
        return
    given = {str(r.get("line_id")): unicodedata.normalize("NFC", str(r.get("text") or "")).strip()
             for r in answer.get("lines") or [] if isinstance(r, dict)}
    for b in blocks:
        item = kernel.items[b]
        text, was = given.get(str(item["line_id"]), ""), str(item.get("text") or "")
        who = f"{item.get('speaker') or 'a line'}'s line"
        if not text:
            result.left_out.append(f"{who} did not come back")
        elif text == was:
            result.left_out.append(f"{who} came back unchanged")
        elif len(text) > MAX_LINE_CHARS:
            result.left_out.append(f"{who} came back too long")
        elif spec.known and caps.script_of(text) != spec.known.code:
            result.left_out.append(f"{who} did not come back in {spec.name}")
        else:
            result.ops.append(_op(b, text, was, spec))
