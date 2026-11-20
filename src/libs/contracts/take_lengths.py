"""The lengths a production's takes may have (plan/2026-11-19 §3).

Omni Flash 1.2 makes clips of 3 to 15 s. A production picks, when it is created, the longest take it allows (10 or
15 s, `ProductionSettings.max_take_s`) and how its shots are cut (`ProductionSettings.take_lengths`):

- ``steps``: 4/6/8/10, and 15 when the maximum is 15 (plan/2026-11-20 D3, the person's; it replaced 4 ... 14);
- ``any``: every whole second from 3 up to the maximum.

Every place that asks "which lengths may this shot have" reads `for_settings`. The other scene planners keep
`contracts.veo.VEO_DURATIONS` (4/6/8) until they are removed. Mirrors the interface's `src/lib/takes/lengths.ts`.
"""

from __future__ import annotations

from typing import Any, Literal

MIN_TAKE_S = 3  # the shortest clip Omni Flash 1.2 makes
LONGEST_TAKE_S = 15  # the longest
MAX_TAKE_CHOICES: tuple[int, ...] = (10, 15)  # what a production may choose as its longest take
DEFAULT_MAX_TAKE_S = 10  # what the create form offers first
TakeMode = Literal["steps", "any"]
DEFAULT_TAKE_MODE: TakeMode = "steps"
STEP_FROM_S = 4
STEPS: tuple[int, ...] = (4, 6, 8, 10, 15)  # plan/2026-11-20 D3: a step past the maximum is left out
# Past this a take is long: Raphael goes past it only for one continuous action or one line (D5). Face and clothes hold
# over a long take is not proven, so a clip over it with more than one line is reported (advisory).
SOFT_CAP_S = 8


def take_lengths(mode: str = DEFAULT_TAKE_MODE, max_s: int = DEFAULT_MAX_TAKE_S) -> tuple[int, ...]:
    """The lengths, shortest first. An unknown mode reads as steps; the maximum is held to 3 ... 15."""
    top = max(MIN_TAKE_S, min(int(max_s or DEFAULT_MAX_TAKE_S), LONGEST_TAKE_S))
    if mode == "any":
        return tuple(range(MIN_TAKE_S, top + 1))
    return tuple(n for n in STEPS if n <= top) or (top,)


LEGACY_TAKES: tuple[int, ...] = (4, 6, 8)  # a production made before plan/2026-11-19 (no `max_take_s`)


def for_settings(settings: Any) -> tuple[int, ...]:
    """The lengths a production allows, from its `ProductionSettings` (or a dict of them). A production with no
    `max_take_s` was made before this plan and keeps 4/6/8 (D1): the scene view re-fits its shots with these."""
    if isinstance(settings, dict):
        mode, top = settings.get("take_lengths"), settings.get("max_take_s")
    else:
        mode, top = getattr(settings, "take_lengths", None), getattr(settings, "max_take_s", None)
    if not top:
        return LEGACY_TAKES
    return take_lengths(str(mode or DEFAULT_TAKE_MODE), int(top))


def renderable(seconds: int) -> bool:
    """Whether Omni Flash 1.2 can make a clip this long at all."""
    return MIN_TAKE_S <= int(seconds) <= LONGEST_TAKE_S


def describe(lengths: tuple[int, ...]) -> str:
    """The lengths in words: "4, 6, 8 or 10 s", or "3 to 15 s" when every second between is allowed."""
    if not lengths:
        return ""
    if len(lengths) > 3 and list(lengths) == list(range(lengths[0], lengths[-1] + 1)):
        return f"{lengths[0]} to {lengths[-1]} s"
    if len(lengths) == 1:
        return f"{lengths[0]} s"
    return f"{', '.join(str(n) for n in lengths[:-1])} or {lengths[-1]} s"


def not_allowed(seconds: int, lengths: tuple[int, ...]) -> str | None:
    """Why a shot cannot be this long in this production, or None."""
    if int(seconds) in lengths:
        return None
    return f"A shot here is {describe(lengths)}, not {seconds} s."
