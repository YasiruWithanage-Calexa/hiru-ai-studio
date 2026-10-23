"""Speech timing: how many words a shot holds and where a spoken line overruns its cut.

Ported from PromptMotion (`libs/contracts/vega_production.py`, `pm_contract/timing.py`, commit
1d748dc). Mirrors the frontend's `src/lib/veo/timing.ts`; both are tested against the same
cases (`tests/contracts/test_timing.py`).

Overruns are REPORTED, never auto-trimmed: cutting a line is a writing decision, and code
cannot know which half of a sentence the scene needs. Veo cuts a line off mid-word; it never
speeds speech up to fit.
"""
from __future__ import annotations

import re

from contracts.veo import SPOKEN_MODES, SoundMode

WORDS_PER_SECOND = 2.2  # unhurried on-camera delivery
SLOW_WORDS_PER_SECOND = 1.8  # whisper, halting, trembling ...
SHOT_OVERRUN_FACTOR = 1.35  # a shot is flagged above this multiple of its target
SLOT_OVERRUN_FACTOR = 1.6  # a beat or storyboard slot: looser, the overrun bleeds not cuts
SLOT_MIN_EXCESS_WORDS = 2  # ... and only when at least this many words over

SLOW_CUES: tuple[str, ...] = ("whisper", "slow", "halting", "breaking", "hesitant", "trembling")

# Stage directions are not speech: nobody says "(whispering, barely audible)".
_PARENTHETICAL = re.compile(r"\([^)]*\)")


def words_in(text: str | None) -> int:
    """Spoken words in a line, parenthetical stage directions stripped. The single counter."""
    return len(_PARENTHETICAL.sub(" ", text or "").split())


def is_slow_delivery(delivery: str | None) -> bool:
    """Does this delivery note slow the speech rate?"""
    text = (delivery or "").lower()
    return any(cue in text for cue in SLOW_CUES)


def speech_seconds(words: int, delivery: str | None = None) -> float:
    """Seconds a line of `words` words takes to say."""
    rate = SLOW_WORDS_PER_SECOND if is_slow_delivery(delivery) else WORDS_PER_SECOND
    return words / rate


def shot_word_target(seconds: float) -> int:
    """Words a spoken shot should carry: max(4, floor(seconds × 2.2)). 4→8, 6→13, 8→17."""
    return max(4, int(seconds * WORDS_PER_SECOND))


def word_target(sound_mode: SoundMode, seconds: float) -> int:
    """A shot's word target, or 0 for a mode that carries no words.

    0 means "no requirement", not "underfilled": that distinction is what stops a music-only
    shot from being enriched into dialogue.
    """
    if sound_mode not in SPOKEN_MODES:
        return 0
    return shot_word_target(seconds)


def effective_word_target(sound_mode: SoundMode, seconds: float, deliveries: list[str]) -> int:
    """The word target scaled down when any line in the shot is delivered slowly."""
    target = word_target(sound_mode, seconds)
    if target and any(is_slow_delivery(d) for d in deliveries):
        target = max(1, int(target * SLOW_WORDS_PER_SECOND / WORDS_PER_SECOND))
    return target


def slot_word_budget(seconds: float) -> int:
    """Words a beat or storyboard slot holds. No four-word floor: a 1 s slot holds ~2 words."""
    return max(1, int(seconds * WORDS_PER_SECOND))


def over_budget(words: int, budget: int, *, slot: bool = False) -> bool:
    """Is `words` too many for `budget`? One comparison for shots and slots alike."""
    if budget <= 0:
        return False
    if not slot:
        return words > budget * SHOT_OVERRUN_FACTOR
    return words > budget * SLOT_OVERRUN_FACTOR and words - budget >= SLOT_MIN_EXCESS_WORDS


def exceeds_shot_word_target(words: int, seconds: float) -> bool:
    """True when a shot's spoken words exceed ×1.35 of its target (frontend parity helper)."""
    return over_budget(words, shot_word_target(seconds))


def overrun_seconds(
    *, start_sec: float, words: int, shot_end_sec: float, delivery: str | None = None
) -> float:
    """How far a line runs past its shot's last cut, in seconds (0 when it fits)."""
    end = start_sec + speech_seconds(words, delivery)
    return max(0.0, end - shot_end_sec)


def default_beats(duration: int) -> list[tuple[int, int]]:
    """Timestamped beats covering a continuous shot: 8 s → 0-3, 3-6, 6-8."""
    if duration == 8:
        return [(0, 3), (3, 6), (6, 8)]
    if duration == 6:
        return [(0, 3), (3, 6)]
    if duration == 4:
        return [(0, 2), (2, 4)]
    raise ValueError(f"{duration}s is not a renderable Veo length")
