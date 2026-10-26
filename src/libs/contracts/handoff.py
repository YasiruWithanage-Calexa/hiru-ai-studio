"""Screen 4, Prompt & handoff: the checks a prompt must pass before it leaves for Flow, and the
takes that come back (PLAN.md §10, §13 Phase 5).

`check_prompt` is free and model-free (PLAN.md §2.2 `prompt_check`): it reads the prompt as it
will be pasted and the shot as it is now, and reports. Nothing is rewritten: an overrun is a
writing decision, a banned name is the writer's to replace (CLAUDE.md "Report overruns, never
auto-trim dialogue").

Pure standard library + pydantic (the `contracts` rule): the API runs it on every read.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from contracts.producer import Check

# Brands a prompt must not name: Veo renders logos it is told about, and a broadcaster cannot air
# them unlicensed. A starting list; a production adds its own (`ProductionSettings.banned_terms`,
# where public figures belong too: real people are the production's call to list).
DEFAULT_BANNED_TERMS: tuple[str, ...] = (
    "Coca-Cola", "Coke", "Pepsi", "Nike", "Adidas", "Puma", "Apple", "iPhone", "Samsung", "Google",
    "YouTube", "Facebook", "Instagram", "TikTok", "WhatsApp", "McDonald's", "KFC", "Pizza Hut",
    "Toyota", "Honda", "Suzuki", "Nestlé", "Nestle", "Unilever", "Sunlight", "Lipton", "Dilmah",
    "Marvel", "Disney", "Netflix",
)

SILENCE_MARKERS = ("nobody speaks", "no dialogue")
_ASPECT = re.compile(r"Aspect ratio (\d+:\d+)")
_DURATION = re.compile(r"Duration (\d+) seconds")


@dataclass
class LineNow:
    """One approved line of the shot as it is now."""

    text: str
    speaker: str
    overrun_s: float = 0.0


@dataclass
class SpeakerNow:
    name: str
    voice_pin: str = ""


@dataclass
class ShotNow:
    code: str
    duration_s: int
    aspect_ratio: str
    sound_mode: str
    lines: list[LineNow] = field(default_factory=list)
    speakers: list[SpeakerNow] = field(default_factory=list)


def _term_hits(prose: str, terms: Iterable[str]) -> list[str]:
    hits = []
    for term in dict.fromkeys(t.strip() for t in terms if t and t.strip()):
        if re.search(rf"(?<![\w]){re.escape(term)}(?![\w])", prose, re.IGNORECASE):
            hits.append(term)
    return hits


def check_prompt(*, prose: str, sinhala: Sequence[str], shot: ShotNow,
                 banned_terms: Iterable[str] = DEFAULT_BANNED_TERMS) -> list[Check]:
    """Handoff checks on one prompt. `sinhala`: its Sinhala segments, in order."""
    checks: list[Check] = []
    lower = prose.lower()

    spoken = shot.sound_mode in ("dialogue", "voiceover", "sung") and bool(shot.lines)
    if spoken:
        verbatim = list(sinhala) == [ln.text for ln in shot.lines]
        checks.append(Check(label="Lines match the approved script" if verbatim
                            else "A line differs from the approved script", tone="pass" if verbatim else "fail"))
        for ln in shot.lines:
            if ln.overrun_s > 0.05:
                checks.append(Check(label=f"{ln.speaker}'s line runs {ln.overrun_s:.1f} s past the cut in "
                                          f"{shot.code} (shorten it or give it its own shot)", tone="advisory"))
        for sp in shot.speakers:
            if not sp.voice_pin:
                checks.append(Check(label=f"No voice pin · {sp.name}", tone="advisory"))
            elif sp.voice_pin.strip().rstrip(".").lower() not in lower:
                checks.append(Check(label=f"{sp.name}'s voice pin changed since this prompt", tone="advisory"))
    else:
        silent = any(m in lower for m in SILENCE_MARKERS) and not sinhala
        checks.append(Check(label="Silence stated" if silent else "The prompt does not say nobody speaks",
                            tone="pass" if silent else "fail"))

    aspect = _ASPECT.search(prose)
    if aspect and aspect.group(1) != shot.aspect_ratio:
        checks.append(Check(label=f"Aspect ratio {aspect.group(1)}; the production is {shot.aspect_ratio}",
                            tone="fail"))
    elif aspect:
        checks.append(Check(label=f"Aspect ratio {shot.aspect_ratio}", tone="pass"))
    duration = _DURATION.search(prose)
    if duration and int(duration.group(1)) != shot.duration_s:
        checks.append(Check(label=f"The prompt says {duration.group(1)} s; {shot.code} is {shot.duration_s} s",
                            tone="fail"))
    elif duration:
        checks.append(Check(label=f"{shot.duration_s} s on the Veo ladder", tone="pass"))

    hits = _term_hits(prose, banned_terms)
    checks.append(Check(label="No brands or listed names" if not hits else f"Names to remove: {', '.join(hits)}",
                        tone="pass" if not hits else "fail"))
    return checks


def blocking(checks: Iterable[Check]) -> bool:
    return any(c.tone == "fail" for c in checks)


# ── takes ──────────────────────────────────────────────────────────────────────────────────


class TakeStatus(StrEnum):
    UPLOADED = "uploaded"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


# What a person may upload as a take: what Flow exports. The API reads the first bytes.
MAX_TAKE_BYTES = 30 * 1024 * 1024  # Cloud Run's request limit is 32 MB; an 8 s Veo clip is ~5-20 MB


def video_kind(data: bytes) -> tuple[str, str] | None:
    """(extension, mime) by content: MP4 / MOV (ISO base media `ftyp`) or WebM (EBML)."""
    if len(data) >= 12 and data[4:8] == b"ftyp":
        brand = data[8:12]
        return ("mov", "video/quicktime") if brand == b"qt  " else ("mp4", "video/mp4")
    if data[:4] == b"\x1aE\xdf\xa3":
        return "webm", "video/webm"
    return None
