"""The shot-plan kernel: a proposed grouping of script blocks → renderable, timed shots.

A planner (a model, or the rules in `script_split`) PROPOSES shots as ranges of a scene's
script blocks. This kernel, in code, makes the proposal true to Veo and to the script:

* every block belongs to exactly one shot, in script order (gaps and overlaps are repaired);
* every spoken line is bound to its shot and beat, verbatim; lines are never rewritten, split
  or trimmed, and a shot is never cut inside a line;
* lengths come from the 4/6/8 ladder (or the production's fixed length): the shortest rung that
  holds the shot's PICTURES AND SPEECH on one clock (an action takes `timing.action_seconds`, a line
  starts after the pictures before it), longer only when the planner asked for it;
* a shot that cannot fit the longest rung is split at a block boundary (an action or a line, never
  inside a line) into a follow-on shot, not squeezed;
* what still does not fit is REPORTED: a line running past its cut, a shot that holds more than it
  can show (`crowded`), a shot over its word target, a scene longer than its envelope. Nothing is
  trimmed (PLAN.md, CLAUDE.md "Overruns are reported, never auto-trimmed"). A scene is never padded
  to fill its envelope either.

Pure standard library, so the API (re-timing after a person changes a shot's length) and the
`script_split` function share one implementation.
"""
from __future__ import annotations

import itertools
import math
from collections.abc import Callable
from dataclasses import dataclass, field

from contracts.timing import (
    TURN_GAP_S,
    action_seconds,
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

# A voice that is heard, not seen: narration, or a speaker who is off screen, on the phone, on the
# radio or television, or over an intercom. The ONE list: `contracts.staging` reads it too.
HEARD_MARKS = ("v.o", "vo)", "voice over", "voiceover", "voice-over", "narrat",
               "o.s", "off screen", "off-screen", "on the phone", "over the phone", "on phone", "phone call",
               "on the radio", "on tv", "on television", "intercom")
_VOICEOVER_MARK = HEARD_MARKS
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
    screen: str = "act"  # action blocks: a contracts.timing.SCREEN_SECONDS key (move / act / with_line / info / inner)
    events: int = 1  # action blocks: how many visible events the block holds
    implied: bool = False  # a step the script implies but does not write (contracts.bridges)
    by: str = ""  # who classified or added the block: "rules" | "model" | "person" ("" = never classified)
    for_version: int = 0  # the script version `screen` / `events` were read for (0 = never)
    skip: tuple[str, ...] = ()  # a phone line: implied steps a person removed (contracts.bridges)
    bridge: str = ""  # an implied block: which bridge it is
    # Feeling's time (plan/2026-11-01d, `contracts.reading.apply`): extra seconds that belong to THIS block (a smile
    # fading, a look held, a last image), counted by the picture clock. Never a new block, so block numbers do not move.
    hold_s: float = 0.0
    hold_kind: str = ""  # reaction | transition | atmosphere | button
    hold_priority: int = 0  # 1 is never dropped by code; 2 and 3 go first when the scene is over its envelope
    hold_who: str = ""  # whose face the hold is for
    turn: bool = False  # the reading says feeling turns here: the answer to a turn line waits `TURN_GAP_S`

    @property
    def is_line(self) -> bool:
        return self.kind == "dialogue" and self.line_id is not None

    @property
    def picture_s(self) -> float:
        """Seconds this block takes to SHOW. Only an action has a picture."""
        return action_seconds(self.screen, self.events) if self.kind == "action" else 0.0

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


@dataclass(frozen=True)
class Slot:
    """One block on a shot's clock: seconds from the start of the shot."""

    index: int  # the block's index in the scene
    start_s: float
    end_s: float
    is_line: bool


@dataclass
class Issue:
    # "line_overrun" | "word_budget" | "envelope" | "repaired" | "long_line" | "multi_speaker" | "crowded" | "split"
    code: str
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
    picture_s: float = 0.0  # seconds the shot's actions take to show
    need_s: float = 0.0  # seconds the whole shot needs to show its pictures and say its lines
    holds: list[tuple[int, float, str]] = field(default_factory=list)  # (block, seconds, kind) of the reading's breath


@dataclass
class FitResult:
    shots: list[FittedShot]
    lines: list[FittedLine]
    issues: list[Issue]
    total_s: int
    envelope_s: int
    # What the split decided about the reading's breath (plan/2026-11-01d, set by `script_split`; empty otherwise):
    # item indexes whose optional hold was given up to fit the envelope, and what the report says about it.
    breath_dropped: list[int] = field(default_factory=list)
    breath_extra: dict[str, object] = field(default_factory=dict)

    @property
    def need_s(self) -> int:
        """Seconds the scene needs on screen: each shot's length, or what it holds when that is more."""
        return math.ceil(sum(max(s.duration_s, s.need_s) for s in self.shots) - 1e-9)

    @property
    def crowded(self) -> list[int]:
        """Numbers of the shots that hold more than they can show."""
        return [i.shot_number for i in self.issues if i.code == "crowded" and i.shot_number is not None]

    @property
    def over_envelope_s(self) -> int:
        return max(0, max(self.total_s, self.need_s) - self.envelope_s)

    @property
    def silent_s(self) -> int:
        """Seconds of shots that carry no spoken line."""
        return sum(s.duration_s for s in self.shots if not s.line_ids)

    @property
    def silent_share(self) -> float:
        return self.silent_s / self.total_s if self.total_s else 0.0

    @property
    def breath_s(self) -> float:
        """Seconds the scene gives to breath the reading asked for (holds), whatever shot they sit in."""
        return sum(sec for s in self.shots for _, sec, _ in s.holds)

    @property
    def unearned_silent_s(self) -> int:
        """Silent seconds that no breath asks for: a shot with no spoken line, less the holds inside it. A scene
        with no reading has no holds, so this is `silent_s` exactly."""
        return math.ceil(sum(max(0.0, s.duration_s - sum(sec for _, sec, _ in s.holds))
                             for s in self.shots if not s.line_ids) - 1e-9)

    @property
    def unearned_silent_share(self) -> float:
        return self.unearned_silent_s / self.total_s if self.total_s else 0.0


def allowed_durations(fixed: int | None) -> tuple[int, ...]:
    return (fixed,) if fixed else VEO_DURATIONS


def line_seconds(item: Item) -> float:
    return speech_seconds(item.words, item.delivery)


def shot_clock(items: list[Item]) -> tuple[list[Slot], float]:
    """One shot's blocks on one clock → (where each timed block sits, seconds the shot needs).

    An action adds its picture time. A line starts when the pictures before it are done, never
    before `LEAD_IN_S` (an action before the first line replaces the lead-in) and `LINE_GAP_S` after
    a line that comes right before it (`TURN_GAP_S` after a line the reading marks as a turn in feeling).
    A block's hold (`hold_s`, from the reading's breath) is a pause after it: the next thing starts after it, and
    when the shot ends there it is the end of the shot. `TAIL_S` is added only when the shot ends on a line with no
    hold, so the cut does not clip it. A shot of lines alone, and any scene with no reading, times as it always has."""
    slots: list[Slot] = []
    clock = 0.0
    after_line = False
    turn_line = False
    pause = 0.0
    for item in items:
        if item.is_line:
            gap = (TURN_GAP_S if turn_line else LINE_GAP_S) if after_line else 0.0
            start = max(clock + max(gap, pause), LEAD_IN_S)
            clock = start + line_seconds(item)
            slots.append(Slot(item.index, start, clock, True))
            after_line = True
            turn_line = item.turn
            pause = item.hold_s
        elif item.picture_s > 0:
            clock += pause
            slots.append(Slot(item.index, clock, clock + item.picture_s, False))
            clock += item.picture_s
            after_line = False
            pause = item.hold_s
        elif item.hold_s > 0:  # a block with no picture of its own can still be held
            pause = max(pause, item.hold_s)
    return slots, clock + (pause if pause > 0 else TAIL_S if after_line else 0.0)


def timeline_text(items: list[Item], name_of: Callable[[Item], str] | None = None) -> str:
    """A shot's timeline in words, for a prompt: "0.0–1.5 Anudi smiled back · 1.5–3.0 Suddenly, her
    phone rang · 3.0–4.5 Anudi answers the phone (implied) · 4.5–10.4 LINE Father (on the phone)".
    The seconds are the kernel's (`shot_clock`), so a prompt and the timeline strip agree. A block
    that takes no picture time (information, a thought) is not on the clock; the prompts name those
    separately."""
    slots, _ = shot_clock(items)
    by_index = {i.index: i for i in items}
    parts = []
    for slot in slots:
        item = by_index[slot.index]
        if slot.is_line:
            who = name_of(item) if name_of else item.speaker.title()
            mark = f" ({item.delivery})" if item.delivery else ""
            label = f"LINE {who}{mark}"
        else:
            label = item.text.strip().rstrip(".") + (" (implied)" if item.implied else "")
        if item.hold_s > 0:  # the pause after it: the reaction, the look held, the last image
            label += f" [then hold {item.hold_s:.1f} s{f', {item.hold_kind}' if item.hold_kind else ''}]"
        parts.append(f"{slot.start_s:.1f}\u2013{slot.end_s:.1f} {label}")
    return " \u00b7 ".join(parts)


def needed_seconds(items: list[Item]) -> float:
    """How long a shot must run to show these blocks and say these lines, with breathing room."""
    return shot_clock(items)[1]


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


def split_to_fit(p: ProposedShot, items: list[Item], longest: int) -> list[ProposedShot]:
    """Split an unlocked shot that needs more than `longest` seconds, at block boundaries only.

    Blocks are added in order until the next one would not fit; the cut goes before it (never inside
    a line). An action that plays under the line after it (`with_line`) stays with that line. A
    follow-on that starts on a line carries the take on (`continuous`); one that starts on an
    action is a new picture (`cut`)."""
    block = items[p.start:p.end]
    if p.duration_locked or len(block) < 2 or needed_seconds(block) <= longest:
        return [p]
    cuts: list[int] = []  # block indexes where a new shot starts
    group: list[Item] = []
    for item in block:
        timed = any(g.is_line or g.picture_s > 0 for g in group)
        if timed and needed_seconds([*group, item]) > longest:
            at = item.index
            last = group[-1]
            if item.is_line and last.kind == "action" and last.screen == "with_line" and len(group) > 1:
                at = last.index
                group = [last]
            else:
                group = []
            cuts.append(at)
        group.append(item)
    if not cuts:
        return [p]
    bounds = [p.start, *cuts, p.end]
    parts: list[ProposedShot] = []
    for n, (a, b) in enumerate(itertools.pairwise(bounds)):
        if n == 0:
            link, title = p.camera_link, p.title
        else:
            link = CameraLink.CONTINUOUS.value if items[a].is_line else CameraLink.CUT.value
            title = f"{p.title} ({n + 1})" if p.title else ""
        parts.append(ProposedShot(a, b, p.framing, title, p.sound_mode, None, False, link))
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
    first_of: dict[int, int] = {}  # a split shot: where its first part sits → how many parts it became
    expanded_end: dict[int, int] = {}  # ... and where the whole shot ended before the cut
    for p in shots:
        parts = split_to_fit(p, items, longest)
        if len(parts) > 1 and any(i.picture_s > 0 for i in items[p.start:p.end]):
            first_of[len(expanded)] = len(parts)
            expanded_end[len(expanded)] = p.end
        expanded.extend(parts)

    fitted: list[FittedShot] = []
    fitted_lines: list[FittedLine] = []
    clock = 0
    for number, p in enumerate(expanded, start=1):
        if number - 1 in first_of:  # the proposal held more than one shot can show: say so (it lost a point)
            held = needed_seconds(items[p.start:expanded_end[number - 1]])
            issues.append(Issue("split", f"S{number:02d} would need {held:.1f} s to show what it holds; the longest "
                                         f"shot is {longest} s, so it becomes {first_of[number - 1]} shots.", number))
        block = items[p.start:p.end]
        lines = [i for i in block if i.is_line]
        mode = sound_mode_for(lines, p.sound_mode)
        slots, need = shot_clock(block)
        picture_s = sum(i.picture_s for i in block)
        if fixed_seconds:
            duration = fixed_seconds
        elif p.duration_locked and p.duration in allowed:
            duration = p.duration
        else:
            duration = _rung(need if lines else max(need, _silent_seconds(block)), allowed)
            if p.duration in allowed and p.duration > duration:  # a planner may ask for longer
                duration = p.duration
        beats = default_beats(duration) if duration in (4, 6, 8) else [(0, duration)]
        speakers = {ln.speaker_id for ln in lines if ln.speaker_id}
        voices = {ln.speaker_id or ln.speaker.casefold() for ln in lines}  # unlinked speakers count too
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
                          word_target=target, words=words, line_ids=[ln.line_id for ln in lines if ln.line_id],
                          picture_s=round(picture_s, 2), need_s=round(need, 2),
                          holds=[(i.index, i.hold_s, i.hold_kind) for i in block if i.hold_s > 0])

        starts = {slot.index: slot.start_s for slot in slots if slot.is_line}
        shot_end = clock + duration
        for ln in lines:
            assert ln.line_id is not None
            secs = line_seconds(ln)
            t = clock + starts[ln.index]
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
        # A locked or fixed-length shot is crowded whenever it holds more than its length. An unlocked one
        # can only be when the kernel could not cut it (one block shows more than the longest shot);
        # a line that is too long already says so itself.
        line_reported = any(i.shot_number == number and i.code in ("line_overrun", "long_line") for i in issues)
        if need > duration + 1e-9 and (fixed_seconds or p.duration_locked or not line_reported):
            issues.append(Issue("crowded", f"S{number:02d} needs about {need:.1f} s to show what it holds; "
                                           f"it is {duration} s.", number))
        if mode is SoundMode.DIALOGUE and len(voices) > 1:
            issues.append(Issue("multi_speaker", f"S{number:02d} has {len(voices)} speakers in one shot; Veo can "
                                                 f"give a line to the wrong face. Give each speaker a shot.",
                                number))
        if target and over_budget(words, target):
            issues.append(Issue("word_budget", f"S{number:02d} carries {words} words; a {duration} s shot "
                                               f"holds about {target}.", number))
        fitted.append(shot)
        clock += duration

    result = FitResult(fitted, fitted_lines, issues, clock, envelope_s)
    if result.over_envelope_s:
        issues.append(Issue("envelope", f"The scene needs {max(clock, result.need_s)} s on screen; its envelope "
                                        f"is {envelope_s} s ({result.over_envelope_s} s over)."))
    return result
