"""Veo 3.1 capabilities: what the video model can render, and the per-shot choices that follow.

Ported from PromptMotion `libs/contracts/vega_production.py` (commit 1d748dc). Mirrors the
frontend's `src/lib/veo/timing.ts`; a change here changes there in the same PR.
"""
from __future__ import annotations

from enum import StrEnum


class Orientation(StrEnum):
    """Per production. Veo 3.1 renders 16:9 and 9:16 only."""

    HORIZONTAL = "horizontal"  # TV, YouTube
    VERTICAL = "vertical"  # Shorts, Reels, TikTok


ASPECT_RATIO: dict[Orientation, str] = {
    Orientation.HORIZONTAL: "16:9",
    Orientation.VERTICAL: "9:16",
}

# The shot lengths Veo 3.1 renders. PromptMotion's code also allows 10 s but its guide says
# 4/6/8; 10 s stays off until it is verified against the current Veo API (PLAN.md Q4).
VEO_DURATIONS: tuple[int, ...] = (4, 6, 8)
DEFAULT_SHOT_SECONDS = 8


class SoundMode(StrEnum):
    """How a shot carries its meaning in sound. One per shot."""

    DIALOGUE = "dialogue"  # characters speak on camera
    VOICEOVER = "voiceover"  # narration over picture
    SUNG = "sung"  # lyrics carry the beat
    AMBIENT = "ambient"  # diegetic sound only, no words
    MUSIC_ONLY = "music_only"  # scored, no words
    SILENT = "silent"  # deliberate silence; must be stated in the prompt or Veo invents speech


# Modes that put words in someone's mouth and therefore have a word target. Every other mode
# must never be measured against a word floor: padding a silent shot with words is a bug.
SPOKEN_MODES: frozenset[SoundMode] = frozenset(
    {SoundMode.DIALOGUE, SoundMode.VOICEOVER, SoundMode.SUNG}
)


class CameraLink(StrEnum):
    """How a shot joins the previous one (Nova's `camera_link`)."""

    CUT = "cut"
    CONTINUOUS = "continuous"  # the same take carrying on
    MATCH = "match"  # a deliberate re-angle


class FrameStrategy(StrEnum):
    """How a shot's opening frame is obtained."""

    GENERATE = "generate"  # a new camera setup or scene
    CARRY_LAST_FRAME = "carry_last_frame"  # same unbroken take, previous take accepted
    STORYBOARD = "storyboard"  # several moments in one clip; needs a free-length engine


class Transition(StrEnum):
    CUT = "cut"
    DISSOLVE = "dissolve"
    FADE = "fade"
    SMASH_CUT = "smash_cut"


def snap_duration(seconds: float, allowed: tuple[int, ...] = VEO_DURATIONS) -> int:
    """The nearest renderable length; a tie goes to the LONGER one.

    Longer wins because shot count, not runtime, is what multiplies generation work: two 4 s
    shots and one 8 s shot deliver the same runtime, so a tie is never resolved downward.
    """
    return min(allowed, key=lambda d: (abs(d - (seconds or 0)), -d))


def reachable_totals(shot_count: int, allowed: tuple[int, ...] = VEO_DURATIONS) -> set[int]:
    """Every runtime `shot_count` shots can sum to. On 4/6/8 every total is even."""
    totals = {0}
    for _ in range(max(0, shot_count)):
        totals = {t + d for t in totals for d in allowed}
    return totals


def nearest_reachable_total(
    requested: int, shot_count: int, allowed: tuple[int, ...] = VEO_DURATIONS
) -> int:
    """The renderable runtime closest to `requested` for this many shots (ties go shorter)."""
    if shot_count <= 0:
        return 0
    return min(reachable_totals(shot_count, allowed), key=lambda t: (abs(t - requested), t))
