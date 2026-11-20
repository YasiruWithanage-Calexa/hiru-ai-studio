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

from contracts.sentences import sentence_breaks
from contracts.veo import SPOKEN_MODES, SoundMode

WORDS_PER_SECOND = 2.2  # unhurried on-camera delivery (Omni speaks ~2.6 words/s without its pauses: lab/sinhala_pace)
SLOW_WORDS_PER_SECOND = 1.8  # whisper, halting, trembling ...
# plan/2026-11-20 D1: Omni pauses 0.75 to 1 s at every sentence end INSIDE a line (lab/sinhala_pace run 1); the clock
# counts one of these per break (`contracts.sentences.sentence_breaks`). Mirrors the interface's SENTENCE_PAUSE_SEC.
SENTENCE_PAUSE_S = 0.8
SHOT_OVERRUN_FACTOR = 1.35  # a shot is flagged above this multiple of its target
SLOT_OVERRUN_FACTOR = 1.6  # a beat or storyboard slot: looser, the overrun bleeds not cuts
SLOT_MIN_EXCESS_WORDS = 2  # ... and only when at least this many words over

# Picture time (PLAN 2026-11-01b §4 Phase 1): what an action block adds to a shot's clock before the next
# thing can start. First guesses, tuned by `scripts/eval_staging.py`. A move through space needs room to be
# seen; an action that plays under the line that follows it (a smile, a look) costs only a beat; information
# the camera must carry some other way (an insert, a line) and a thought take no picture time of their own.
SCREEN_SECONDS: dict[str, float] = {"move": 2.5, "act": 1.5, "with_line": 0.5, "info": 0.0, "inner": 0.0}
SCREEN_KINDS: tuple[str, ...] = tuple(SCREEN_SECONDS)

# Feeling needs time (PLAN 2026-11-01d §5 Phases 2-3). A scene's reading (`contracts.reading`) can hold a moment
# for `HOLD_RANGE_S` seconds (a smile fading, a look held); the pause before a line that answers a turn in feeling
# is `TURN_GAP_S` instead of `LINE_GAP_S`; and reading-backed breath should fill `BREATH_BAND` of a scene's seconds.
# A turn in feeling that is a small action (`with_line`) takes an `act`'s time, not half a second. First guesses,
# tuned with the A/B in Phase 8.
HOLD_RANGE_S: tuple[float, float] = (1.0, 3.0)
TURN_GAP_S = 1.0
BREATH_BAND: tuple[float, float] = (0.15, 0.30)

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


def speech_seconds(words: int, delivery: str | None = None, breaks: int = 0) -> float:
    """Seconds a line of `words` words takes to say, with a `SENTENCE_PAUSE_S` at each of its `breaks` (the sentence
    ends inside it, `contracts.sentences.sentence_breaks`)."""
    rate = SLOW_WORDS_PER_SECOND if is_slow_delivery(delivery) else WORDS_PER_SECOND
    return words / rate + SENTENCE_PAUSE_S * max(0, int(breaks))


def spoken_seconds(text: str | None, delivery: str | None = None) -> float:
    """Seconds a line takes to say, from its words: the word count and its sentence pauses (plan/2026-11-20 D1)."""
    return speech_seconds(words_in(text), delivery, sentence_breaks(text))


def action_seconds(screen: str | None = "act", events: int = 1) -> float:
    """Seconds an action block takes on screen. An unknown screen kind counts as `act`; each extra
    visible event in the block adds its own time (a block that holds two events needs two)."""
    base = SCREEN_SECONDS.get(screen or "act", SCREEN_SECONDS["act"])
    return base * max(1, int(events or 1))


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
    *, start_sec: float, words: int, shot_end_sec: float, delivery: str | None = None, breaks: int = 0
) -> float:
    """How far a line runs past its shot's last cut, in seconds (0 when it fits). `breaks`: its sentence pauses."""
    end = start_sec + speech_seconds(words, delivery, breaks)
    return max(0.0, end - shot_end_sec)


def default_beats(duration: int) -> list[tuple[int, int]]:
    """Timestamped beats covering a continuous shot: 8 s → 0-3, 3-6, 6-8. Up to 5 s, two beats split at the middle
    (4 s → 0-2, 2-4); longer, 3 s beats with a last one of 2 to 4 s (10 s → 0-3, 3-6, 6-10; plan/2026-11-19). Mirrors
    the interface's `defaultBeats`."""
    total = int(duration)
    if total < 1:
        raise ValueError(f"{duration}s is not a length a shot can have")
    if total <= 5:
        mid = -(-total // 2)
        return [(0, mid), (mid, total)] if mid < total else [(0, total)]
    out = [(start, min(start + 3, total)) for start in range(0, total, 3)]
    if len(out) > 1 and out[-1][1] - out[-1][0] < 2:
        out.pop()
        out[-1] = (out[-1][0], total)
    return out
