"""veo_fit: which Veo length a number of words (or seconds) needs. Pure; reports an overrun, never trims.

Veo renders 4, 6 or 8 s (10 s stays off until verified) and cuts a line off mid-word rather than speeding it up, so
the length that fits is the shortest one that is not shorter than the speech. The rules are `contracts.timing`
(2.2 words a second, slower for a whispered or halting delivery), which the frontend's `timing.ts` mirrors.
"""
from __future__ import annotations

from typing import Self

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, model_validator

from contracts.timing import (
    SLOW_WORDS_PER_SECOND,
    WORDS_PER_SECOND,
    effective_word_target,
    is_slow_delivery,
    speech_seconds,
)
from contracts.veo import VEO_DURATIONS, SoundMode, snap_duration
from hiru_ai.core import tooling
from hiru_ai.core.context import RunContext


class Args(BaseModel):
    words: int = Field(0, ge=0, description="Spoken words (stage directions in brackets are not counted by the caller)")
    seconds: float | None = Field(None, ge=0, description="Instead of words: the seconds the shot needs")
    delivery: str = Field("", description="How the line is delivered; a slow delivery needs more time")
    sound_mode: SoundMode = SoundMode.DIALOGUE
    fixed_seconds: int | None = Field(None, description="Every shot runs this long when the production fixes it")

    @model_validator(mode="after")
    def _some_measure(self) -> Self:
        if self.seconds is None and not self.words:
            raise ValueError("give the words or the seconds to fit")
        return self


class Result(BaseModel):
    needed_s: float
    duration_s: int
    fits: bool
    over_s: float
    nearest_s: int
    word_target: int
    over_words: int
    rate_words_per_s: float
    allowed_s: list[int]


def run(args: Args, ctx: RunContext) -> Result:  # pure: `ctx` is part of every tool's signature, unused here
    allowed = (args.fixed_seconds,) if args.fixed_seconds else VEO_DURATIONS
    needed = args.seconds if args.seconds is not None else speech_seconds(args.words, args.delivery)
    rung = next((d for d in sorted(allowed) if d >= needed - 1e-9), max(allowed))
    fits = needed <= rung + 1e-9
    target = effective_word_target(args.sound_mode, rung, [args.delivery])
    slow = is_slow_delivery(args.delivery)
    return Result(needed_s=round(needed, 2), duration_s=rung, fits=fits, over_s=round(max(0.0, needed - rung), 2),
                  nearest_s=snap_duration(needed, allowed), word_target=target,
                  over_words=max(0, args.words - target) if target and args.words else 0,
                  rate_words_per_s=SLOW_WORDS_PER_SECOND if slow else WORDS_PER_SECOND, allowed_s=list(allowed))


def as_tool() -> StructuredTool:
    return tooling.from_part(__package__ or "", Args, run)
