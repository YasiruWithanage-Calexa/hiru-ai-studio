"""The shot-plan kernel: a proposed grouping of script blocks → renderable, timed shots.

A planner (a model, or the rules in `script_split`) PROPOSES shots as ranges of a scene's
script blocks. This kernel, in code, makes the proposal true to Veo and to the script:

* every block belongs to exactly one shot, in script order (gaps and overlaps are repaired);
* every spoken line is bound to its shot and beat, verbatim; lines are never rewritten, split
  or trimmed, and a shot is never cut inside a line;
* lengths come from the 4/6/8 ladder (or the production's fixed length): the shortest rung that
  holds the speech, longer only when the planner asked for it;
* a shot whose speech cannot fit the longest rung is split at a line boundary into a
  CONTINUOUS follow-on shot (same take carried on from the last frame), not squeezed;
* what still does not fit is REPORTED: a line running past its cut, a shot over its word target,
  a scene longer than its envelope. Nothing is trimmed (PLAN.md, CLAUDE.md "Overruns are
  reported, never auto-trimmed"). A scene is never padded to fill its envelope either.

Pure standard library, so the API (re-timing after a person changes a shot's length) and the
`script_split` function share one implementation.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from contracts.timing import (
    default_beats,
    effective_word_target,
    over_budget,
    overrun_seconds,
    speech_seconds,
    words_in,
)
from contracts.veo import (
    SPOKEN_MODES,
    VEO_DURATIONS,
    CameraLink,
    FrameStrategy,
    SoundMode,
)

LEAD_IN_S = 0.5  # a beat before the first word: Veo needs a moment to establish the frame
LINE_GAP_S = 0.3  # between two lines in one shot
TAIL_S = 0.5  # after the last word, so the cut does not clip it

_VOICEOVER_MARK = ("v.o", "vo)", "voice over", "voiceover", "voice-over", "narrat")
_SUNG_MARK = ("sing", "sung", "song", "chant")


@dataclass(frozen=True)
class Item:
    """One script block as the kernel sees it."""

    index: int
    kind: str  # contracts.production.BlockKind value
    text: str = ""
    speaker: str = ""  # dialogue only
    speaker_id: str | None = None
    delivery: str = ""
    line_id: str | None = None

    @property
    def is_line(self) -> bool:
        return self.kind == "dialogue" and self.line_id is not None

    @property
    def words(self) -> int:
        return words_in(self.text) if self.is_line else 0


@dataclass
class ProposedShot:
    start: int  # first block index (inclusive)
    end: int  # last block index (exclusive)
    framing: str = ""
    title: str = ""
    sound_mode: str | None = None  # a hint; spoken modes are decided by the lines
    duration: int | None = None  # a hint, or exact when `duration_locked`
    duration_locked: bool = False  # a person set this length: keep it, report what overruns
    camera_link: str = CameraLink.CUT.value


@dataclass
class FittedLine:
    line_id: str
    shot_number: int
    beat_index: int
    start_s: float  # from the start of the scene
    end_s: float
    words: int
    overrun_s: float


@dataclass
class Issue:
    code: str  # "line_overrun" | "word_budget" | "envelope" | "repaired" | "long_line"
    message: str
    shot_number: int | None = None
    line_id: str | None = None


@dataclass
class FittedShot:
    number: int
    start: int
    end: int
    framing: str
    title: str
    sound_mode: SoundMode
    camera_link: CameraLink
    frame_strategy: FrameStrategy
    duration_s: int
    start_s: int
    beats: list[tuple[int, int]]
    speaker_id: str | None
    word_target: int
    words: int
    line_ids: list[str] = field(default_factory=list)


@dataclass
class FitResult:
    shots: list[FittedShot]
    lines: list[FittedLine]
    issues: list[Issue]
    total_s: int
    envelope_s: int

    @property
    def over_envelope_s(self) -> int:
        return max(0, self.total_s - self.envelope_s)


def allowed_durations(fixed: int | None) -> tuple[int, ...]:
    return (fixed,) if fixed else VEO_DURATIONS


def line_seconds(item: Item) -> float:
    return speech_seconds(item.words, item.delivery)


def needed_seconds(lines: list[Item]) -> float:
    """How long a shot must run to hold these lines with breathing room."""
    if not lines:
        return 0.0
    speech = sum(line_seconds(ln) for ln in lines)
    return LEAD_IN_S + speech + LINE_GAP_S * (len(lines) - 1) + TAIL_S


def _silent_seconds(items: list[Item]) -> int:
    """A shot with no lines: long enough to play its action."""
    words = sum(len(i.text.split()) for i in items if i.kind == "action")
    if words <= 12:
        return 4
    if words <= 30:
        return 6
    return 8


def _rung(seconds: float, allowed: tuple[int, ...]) -> int:
    """The shortest allowed length that holds `seconds`; the longest when none does."""
    for d in sorted(allowed):
        if d >= seconds:
            return d
    return max(allowed)


def sound_mode_for(lines: list[Item], hint: str | None) -> SoundMode:
    if lines:
        marks = " ".join(f"{ln.delivery} {ln.speaker}".lower() for ln in lines)
        if all(any(m in f"{ln.delivery} {ln.speaker}".lower() for m in _VOICEOVER_MARK) for ln in lines):
            return SoundMode.VOICEOVER
        if any(m in marks for m in _SUNG_MARK):
            return SoundMode.SUNG
        return SoundMode.DIALOGUE
    try:
        mode = SoundMode(hint) if hint else SoundMode.AMBIENT
    except ValueError:
        mode = SoundMode.AMBIENT
    # A spoken mode with nothing to say is the bug that makes Veo invent speech.
    return SoundMode.AMBIENT if mode in SPOKEN_MODES else mode


def normalise(proposal: list[ProposedShot], n_items: int) -> tuple[list[ProposedShot], bool]:
    """Ranges that cover [0, n_items) exactly once, in order. → (shots, repaired?)."""
    if n_items <= 0:
        return [], bool(proposal)
    shots = sorted((p for p in proposal if p.end > p.start), key=lambda p: (p.start, p.end))
    repaired = len(shots) != len(proposal)
    out: list[ProposedShot] = []
    cursor = 0
    for p in shots:
        start, end = max(p.start, cursor), min(p.end, n_items)
        if start != p.start or end != p.end:
            repaired = True
        if end <= start:
            repaired = True
            continue
        if start > cursor:  # a gap: the previous shot takes the uncovered blocks
            repaired = True
            if out:
                out[-1].end = start
            else:
                start = 0
        out.append(ProposedShot(start, end, p.framing, p.title, p.sound_mode, p.duration,
                                p.duration_locked, p.camera_link))
        cursor = end
    if not out:
        return [ProposedShot(0, n_items)], True
    if out[-1].end < n_items:
        out[-1].end = n_items
        repaired = True
    return out, repaired


def _split_long(p: ProposedShot, items: list[Item], longest: int) -> list[ProposedShot]:
    """Split a shot whose lines cannot fit `longest` seconds, at line boundaries only."""
    lines = [i for i in items[p.start:p.end] if i.is_line]
    if p.duration_locked or len(lines) < 2 or needed_seconds(lines) <= longest:
        return [p]
    parts: list[ProposedShot] = []
    start = p.start
    group: list[Item] = []
    for item in items[p.start:p.end]:
        if item.is_line and group and needed_seconds([*group, item]) > longest:
            parts.append(ProposedShot(start, item.index, p.framing, p.title, p.sound_mode, None, False,
                                      p.camera_link if not parts else CameraLink.CONTINUOUS.value))
            start, group = item.index, []
        if item.is_line:
            group.append(item)
    parts.append(ProposedShot(start, p.end, p.framing, p.title, p.sound_mode, None, False,
                              p.camera_link if not parts else CameraLink.CONTINUOUS.value))
    for n, part in enumerate(parts[1:], start=2):
        part.title = f"{p.title} ({n})" if p.title else ""
    return parts


def _beat_of(offset: float, beats: list[tuple[int, int]]) -> int:
    for i, (s, e) in enumerate(beats):
        if s <= offset < e:
            return i
    return len(beats) - 1


def fit(items: list[Item], proposal: list[ProposedShot], *, envelope_s: int,
        fixed_seconds: int | None = None) -> FitResult:
    """The kernel. `items` must be the scene's blocks in order with `index` = position."""
    allowed = allowed_durations(fixed_seconds)
    longest = max(allowed)
    shots, repaired = normalise(proposal, len(items))
    issues: list[Issue] = []
    if repaired:
        issues.append(Issue("repaired", "The proposed shots did not cover the script exactly once "
                                        "in order; gaps and overlaps were closed."))
    expanded: list[ProposedShot] = []
    for p in shots:
        expanded.extend(_split_long(p, items, longest))

    fitted: list[FittedShot] = []
    fitted_lines: list[FittedLine] = []
    clock = 0
    for number, p in enumerate(expanded, start=1):
        block = items[p.start:p.end]
        lines = [i for i in block if i.is_line]
        mode = sound_mode_for(lines, p.sound_mode)
        if fixed_seconds:
            duration = fixed_seconds
        elif p.duration_locked and p.duration in allowed:
            duration = p.duration
        else:
            need = needed_seconds(lines) if lines else _silent_seconds(block)
            duration = _rung(need, allowed)
            if p.duration in allowed and p.duration > duration:  # a planner may ask for longer
                duration = p.duration
        beats = default_beats(duration) if duration in (4, 6, 8) else [(0, duration)]
        speakers = {ln.speaker_id for ln in lines if ln.speaker_id}
        try:
            link = CameraLink(p.camera_link)
        except ValueError:
            link = CameraLink.CUT
        if number == 1 and link is CameraLink.CONTINUOUS:
            link = CameraLink.CUT  # nothing before the first shot to carry on from
        strategy = FrameStrategy.CARRY_LAST_FRAME if link is CameraLink.CONTINUOUS else FrameStrategy.GENERATE
        target = effective_word_target(mode, duration, [ln.delivery for ln in lines])
        words = sum(ln.words for ln in lines)
        shot = FittedShot(number=number, start=p.start, end=p.end, framing=p.framing or "MS",
                          title=p.title, sound_mode=mode, camera_link=link, frame_strategy=strategy,
                          duration_s=duration, start_s=clock, beats=beats,
                          speaker_id=next(iter(speakers)) if len(speakers) == 1 else None,
                          word_target=target, words=words, line_ids=[ln.line_id for ln in lines if ln.line_id])

        t = clock + LEAD_IN_S
        shot_end = clock + duration
        for ln in lines:
            assert ln.line_id is not None
            secs = line_seconds(ln)
            over = round(overrun_seconds(start_sec=t, words=ln.words, shot_end_sec=shot_end,
                                         delivery=ln.delivery), 2)
            fitted_lines.append(FittedLine(ln.line_id, number, _beat_of(t - clock, beats), round(t, 2),
                                           round(t + secs, 2), ln.words, over))
            if over > 0:
                issues.append(Issue("line_overrun", f"A line in S{number:02d} runs {over:.1f} s past the "
                                                    f"cut. Shorten the line, or give it its own shot.",
                                    number, ln.line_id))
            if secs + LEAD_IN_S + TAIL_S > longest:
                issues.append(Issue("long_line", f"A line in S{number:02d} needs about {secs:.0f} s to say; "
                                                 f"the longest shot is {longest} s.", number, ln.line_id))
            t += secs + LINE_GAP_S
        if target and over_budget(words, target):
            issues.append(Issue("word_budget", f"S{number:02d} carries {words} words; a {duration} s shot "
                                               f"holds about {target}.", number))
        fitted.append(shot)
        clock += duration

    if clock > envelope_s:
        issues.append(Issue("envelope", f"The shots run {clock} s; the scene envelope is {envelope_s} s "
                                        f"({clock - envelope_s} s over)."))
    return FitResult(fitted, fitted_lines, issues, clock, envelope_s)
