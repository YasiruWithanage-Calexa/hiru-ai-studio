"""The kernel score: the code that picks a plan. Model critics write notes; this, in code, chooses
(plan/2026-11-01d). Lower is better, compared left to right."""
from __future__ import annotations

# Ported from services/script_split/script_split/engine/critic.py (plan/2026-11-03 Phase 2).
import math
from collections.abc import Sequence

from contracts import stagemap
from contracts.production import Framing
from contracts.reading import SceneReading
from contracts.shotplan import FitResult, Item
from contracts.timing import BREATH_BAND
from contracts.veo import SoundMode

_SIGNIFICANT = ("line_overrun", "word_budget", "repaired", "long_line", "crowded", "split")


SILENT_SHARE_MAX = 0.4  # more of a scene than this, without a spoken line or the breath the reading asked for,


Score = tuple[int, int, int, int, int, int, int, int, int, int]


def issue_count(result: FitResult) -> int:
    """The problems a person would have to fix: the kernel's significant issues, plus one when
    UNEARNED silence fills too much of a scene that has speech (an action-only scene is exempt). Silence the
    reading asked for (a hold) is breath, not a problem."""
    count = sum(1 for i in result.issues if i.code in _SIGNIFICANT)
    if result.lines and result.unearned_silent_share > SILENT_SHARE_MAX:
        count += 1
    return count


def breath_missing(result: FitResult, reading: SceneReading | None, items: list[Item] | None) -> int:
    """How many priority-1 moments the reading asked for (a reaction at a turn, the button) that this plan does not
    play. Code never drops one, so a plan only loses them when it was fitted without them."""
    if reading is None or items is None:
        return 0
    kept = {block for s in result.shots for block, _, _ in s.holds}
    return sum(1 for b, at in reading.resolved(items) if b.priority == 1 and not b.off and at not in kept)


def breath_band_s(result: FitResult, reading: SceneReading | None) -> int:
    """Seconds of reading-backed breath outside `BREATH_BAND` of the scene. 0 for a scene whose reading asks for none
    (a talking-heads scene plans as it always did)."""
    if reading is None or not any(not b.off for b in reading.breath) or not result.total_s:
        return 0
    low, high = BREATH_BAND[0] * result.total_s, BREATH_BAND[1] * result.total_s
    return math.ceil(max(0.0, low - result.breath_s, result.breath_s - high) - 1e-9)


_WIDE_ENOUGH = (Framing.TWO.value, Framing.OTS.value, Framing.WIDE.value)


def turn_unseen(result: FitResult, reading: SceneReading | None, items: list[Item] | None,
                staging: stagemap.SceneStaging | None = None, cast: Sequence[str] = ()) -> int:
    """Turns whose reaction is played while the face that reacts is NOT in frame: a priority-1 reaction held after a
    line, by someone who is not its speaker, in a single of the speaker. A reaction held after an action is the face
    of that action, a heard voice is played on its listener, and a TWO, OTS or WIDE shows the listener (when the map
    says where people are, a listener who is in another spot is not in it). 0 without a reading."""
    if reading is None or items is None:
        return 0
    cast = list(cast)
    count = 0
    for b, at in reading.resolved(items):
        if b.priority != 1 or b.off or b.kind != "reaction" or not b.who or not items[at].is_line:
            continue
        shot = next((s for s in result.shots if s.start <= at < s.end and any(h[0] == at for h in s.holds)), None)
        if shot is None or shot.sound_mode is SoundMode.VOICEOVER:
            continue  # not played at all (breath_missing counts that), or a voice played on its listener
        who = b.who.casefold()
        block = items[shot.start:shot.end]
        if who == items[at].speaker.casefold():
            continue  # a single of the speaker, and the reaction is theirs
        here = stagemap.people_in(block, cast, holds=False)  # who speaks on camera or is named by the action
        others = [p for p in here if p != who]
        if who in here or (shot.framing in _WIDE_ENOUGH and (staging is None or not others or any(
                _same_spot(staging, items, who, p, at) for p in others))):
            continue
        count += 1
    return count


def _same_spot(staging: stagemap.SceneStaging, items: list[Item], a: str, b: str, block: int) -> bool:
    za, zb = staging.mark_at(items, a, block), staging.mark_at(items, b, block)
    return za is None or zb is None or za.zone == zb.zone


def no_button(result: FitResult, reading: SceneReading | None, items: list[Item] | None) -> int:
    """1 when the reading asks for a last image (a button, not switched off) and the plan does not end on it: the
    hold is not played, or it is played before the last shot."""
    if reading is None or items is None or not result.shots:
        return 0
    buttons = [at for b, at in reading.resolved(items) if b.kind == "button" and not b.off]
    if not buttons:
        return 0
    last = result.shots[-1]
    return 0 if any(last.start <= at < last.end and any(h[0] == at for h in last.holds) for at in buttons) else 1


def kernel_score(result: FitResult, reading: SceneReading | None = None, items: list[Item] | None = None,
                 staging: stagemap.SceneStaging | None = None, cast: Sequence[str] = ()) -> Score:
    """Lower is better, compared left to right: significant issues, shots with two speakers, priority-1 breath the
    plan does not play, turns whose reaction is not in frame, people who teleport, crossed lines and broken
    eyelines, a missing last image, seconds of breath outside the band, seconds over the envelope, seconds of silence
    nobody earned. A plan that clips a line always loses to one that does not; the later terms only break ties. The
    model critics write notes; this score, in code, picks the plan (plan/2026-11-01d)."""
    two_speakers = sum(1 for i in result.issues if i.code == "multi_speaker")
    cast = list(cast)
    placed = items is not None and staging is not None
    teleports = len(stagemap.teleports(staging, items, cast)) if placed and items is not None else 0
    crossed = (len(stagemap.line_crossed(staging, items, result, cast)) + len(stagemap.eyeline(staging, items, result))
               if placed and items is not None else 0)
    return (issue_count(result), two_speakers, breath_missing(result, reading, items),
            turn_unseen(result, reading, items, staging, cast), teleports, crossed, no_button(result, reading, items),
            breath_band_s(result, reading), result.over_envelope_s, result.unearned_silent_s)


def coverage_lines(result: FitResult, items: list[Item]) -> list[str]:
    """What the kernel cannot see but a reviewer should: the sizes used, crowded shots, no wide."""
    sizes: dict[str, int] = {}
    for s in result.shots:
        sizes[s.framing] = sizes.get(s.framing, 0) + 1
    rows = ["Sizes: " + ", ".join(f"{k} x{v}" for k, v in sizes.items())]
    crowded = [f"S{s.number:02d} (needs {s.need_s:.1f} s, is {s.duration_s} s)" for s in result.shots
               if s.number in result.crowded]
    if crowded:  # measured by the picture clock, whatever the shot's length
        rows.append("CROWDED: " + ", ".join(crowded))
    opens_on_action = bool(items) and items[0].kind == "action"
    if opens_on_action and len(result.shots) > 2 and "WIDE" not in sizes:
        rows.append("No WIDE: the scene opens on action and never shows the whole place.")
    return rows


def describe(result: FitResult, items: list[Item]) -> str:
    breath = f" Breath held: {result.breath_s:.1f} s." if result.breath_s else ""
    rows = [f"Envelope: {result.envelope_s} s. Plan runs {result.total_s} s. Silent: {result.silent_s} s.{breath}",
            *coverage_lines(result, items)]
    for s in result.shots:
        blocks = ", ".join(str(i) for i in range(s.start, s.end))
        need = f" need {s.need_s:.1f} s in {s.duration_s} s," if s.picture_s else ""
        moments = ", ".join(f"{sec:g} s {kind} after block {b}" for b, sec, kind in s.holds)
        held = f" holds {moments}," if s.holds else ""
        rows.append(f"S{s.number:02d} {s.framing} {s.duration_s}s {s.sound_mode.value}{need}{held} \"{s.title}\" "
                    f"blocks [{blocks}]")
    return "\n".join(rows)
