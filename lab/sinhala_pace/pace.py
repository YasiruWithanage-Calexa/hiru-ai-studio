"""Pure helpers for the Sinhala pace lab: the clock's estimate today, syllables, and where speech sits in a take's audio.

No network. `speech_span` reads RMS every 50 ms through ffmpeg (voice band only) and calls a frame speech when it is
well above the take's own noise floor.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "libs"))

from contracts.shotplan import LEAD_IN_S, TAIL_S  # noqa: E402
from contracts.timing import speech_seconds, words_in  # noqa: E402

FRAME_S = 0.05
MERGE_GAP_S = 0.30  # a pause shorter than this is inside the line, not a gap between phrases

_SI_CONSONANT = re.compile("[ක-ෆ]")
_SI_VOWEL = re.compile("[අ-ඖ]")
_SI_DEAD = re.compile("[ක-ෆ]්")  # a consonant with al-lakuna has no vowel of its own
_LATIN_WORD = re.compile(r"[A-Za-z]+")
_LATIN_VOWELS = re.compile(r"[aeiouy]+", re.I)


def syllables(text: str) -> dict[str, int]:
    """Spoken syllables: Sinhala aksharas (consonants + independent vowels, minus dead consonants) and Latin vowel
    groups (at least one per word). Parenthetical stage directions are not spoken."""
    text = re.sub(r"\([^)]*\)", " ", text or "")
    si = len(_SI_CONSONANT.findall(text)) + len(_SI_VOWEL.findall(text)) - len(_SI_DEAD.findall(text))
    latin = 0
    for w in _LATIN_WORD.findall(text):
        latin += max(1, len(_LATIN_VOWELS.findall(w)) - (1 if w.lower().endswith("e") and len(w) > 3 else 0))
    return {"si": si, "latin": latin, "total": si + latin}


def clock_estimate(text: str, delivery: str = "") -> dict[str, float]:
    """What the product's clock says today: words, seconds to say them, and the take a lone line needs."""
    words = words_in(text)
    said = speech_seconds(words, delivery)
    return {"words": words, "said_s": round(said, 2), "need_s": round(said + LEAD_IN_S + TAIL_S, 2)}


@dataclass(frozen=True)
class Span:
    start_s: float  # first speech
    end_s: float  # last speech
    voiced_s: float  # speech time with pauses over MERGE_GAP_S taken out
    pauses: int  # pauses over MERGE_GAP_S inside the line
    floor_db: float
    threshold_db: float
    take_s: float
    cut: bool  # speech still running in the last 0.3 s: the line may be cut off

    @property
    def span_s(self) -> float:
        return round(self.end_s - self.start_s, 2)


def rms_frames(video: Path) -> list[float]:
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    samples = int(48000 * FRAME_S)
    cmd = [ffmpeg, "-hide_banner", "-nostats", "-i", str(video), "-vn", "-ac", "1", "-ar", "48000", "-af",
           f"highpass=f=120,lowpass=f=4000,asetnsamples=n={samples}:p=0,astats=metadata=1:reset=1,"
           "ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-", "-f", "null", "-"]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout  # noqa: S603  our own file
    vals = []
    for line in out.splitlines():
        if "RMS_level=" in line:
            v = line.split("=", 1)[1].strip()
            vals.append(-120.0 if v in ("-inf", "inf", "nan") else float(v))
    return vals


def speech_span(video: Path, take_s: float | None = None) -> Span | None:
    rms = rms_frames(video)
    if not rms:
        return None
    take_s = take_s or len(rms) * FRAME_S
    ordered = sorted(rms)
    floor = ordered[len(ordered) // 10]
    peak = ordered[int(len(ordered) * 0.98) - 1]
    threshold = max(floor + 12.0, peak - 30.0)
    on = [i for i, v in enumerate(rms) if v >= threshold]
    if not on:
        return None
    runs: list[list[int]] = [[on[0], on[0]]]
    for i in on[1:]:
        if (i - runs[-1][1]) * FRAME_S <= MERGE_GAP_S:
            runs[-1][1] = i
        else:
            runs.append([i, i])
    runs = [r for r in runs if (r[1] - r[0] + 1) * FRAME_S >= 0.1]  # a click is not speech
    if not runs:
        return None
    start, end = runs[0][0] * FRAME_S, (runs[-1][1] + 1) * FRAME_S
    voiced = sum((r[1] - r[0] + 1) * FRAME_S for r in runs)
    return Span(start_s=round(start, 2), end_s=round(end, 2), voiced_s=round(voiced, 2), pauses=len(runs) - 1,
                floor_db=round(floor, 1), threshold_db=round(threshold, 1), take_s=round(take_s, 2),
                cut=end >= take_s - 0.3)
