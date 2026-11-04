"""Moments and cards onto the Veo clock (plan/2026-11-04b §5.3, §5.6).

A take is 4, 6 or 8 seconds. A card needs its PICTURES and its SPEECH on one clock: each moment takes the longer of
the seconds it asks for and the time its lines take to say, a lead-in comes before the first word and a tail after the
last. What does not fit is REPORTED (a line running past its cut, a card over its word budget, a card that holds more
than eight seconds can show, a scene longer than its envelope); nothing is trimmed, split or squeezed here. Dialogue
is never cut: that is a writing decision.

The rates are the repo's one clock (`contracts.timing`), so the frontend's `timing.ts` and this step agree.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from contracts.adam.plan import Moment, SceneScript, ShotCard
from contracts.shotplan import LEAD_IN_S, LINE_GAP_S, TAIL_S
from contracts.timing import (
    over_budget,
    overrun_seconds,
    shot_word_target,
    speech_seconds,
    words_in,
)
from contracts.veo import VEO_DURATIONS, snap_duration

MIN_USE_S = 2.0  # the shortest part of a take worth keeping (§5.6)
OVERRUN = "overrun"  # the card cannot hold what it is asked to: reported, never repaired
WARNING = "warning"


@dataclass(frozen=True)
class Issue:
    # line_overrun | word_budget | crowded | bad_length | use_over_take | use_too_short | trim_not_ready | envelope
    code: str
    level: str  # overrun | warning
    message: str
    card: int | None = None
    line_id: str | None = None


def _line_facts(scene: SceneScript) -> dict[str, tuple[int, str]]:
    """line id → (spoken words, delivery note)."""
    return {b.line_id: (words_in(b.text), b.delivery) for b in scene.lines if b.line_id}


def card_clock(scene: SceneScript, moments: list[Moment], card: ShotCard) -> dict[str, Any]:
    """One card on the clock: what it needs, what it holds, and where each of its lines starts and ends."""
    facts = _line_facts(scene)
    by_id = {m.id: m for m in moments}
    offset, spoken, picture, words_total = 0.0, False, 0.0, 0
    lines: list[dict[str, Any]] = []
    last_end = 0.0
    for ident in card.moments:
        m = by_id.get(ident)
        if m is None:
            continue
        own = [facts[ln] for ln in m.lines if ln in facts]
        said = sum(speech_seconds(w, d) for w, d in own) + LINE_GAP_S * max(0, len(own) - 1)
        length = max(m.seconds_need, said)
        picture += m.seconds_need
        start = offset + (LEAD_IN_S if own else 0.0)
        for ln in m.lines:
            if ln not in facts:
                continue
            words, delivery = facts[ln]
            spoken = True
            words_total += words
            end = start + speech_seconds(words, delivery)
            lines.append({"line_id": ln, "start_s": round(start, 2), "end_s": round(end, 2), "words": words,
                          "delivery": delivery})
            start, last_end = end + LINE_GAP_S, end
        offset += length + (LEAD_IN_S if own else 0.0)
    need = offset + (TAIL_S if spoken else 0.0)
    return {"lines": lines, "need_s": round(need, 2), "picture_s": round(picture, 2), "words": words_total,
            "speech_end_s": round(last_end, 2), "spoken": spoken}


def check(scene: SceneScript, moments: list[Moment], cards: list[ShotCard], *,
          editorial: bool = False) -> dict[str, Any]:
    issues: list[Issue] = []
    rows: list[dict[str, Any]] = []
    for card in cards:
        clock = card_clock(scene, moments, card)
        need, take = float(clock["need_s"]), card.take_s
        end_limit = take - TAIL_S
        if take not in VEO_DURATIONS:
            issues.append(Issue("bad_length", OVERRUN, f"a {take} s take cannot be rendered; Veo makes "
                                                       f"{', '.join(str(d) for d in VEO_DURATIONS)} s (nearest: "
                                                       f"{snap_duration(take)} s)", card.number))
        for ln in clock["lines"]:
            over = overrun_seconds(start_sec=ln["start_s"], words=ln["words"], shot_end_sec=end_limit,
                                   delivery=ln["delivery"])
            ln["overrun_s"] = round(over, 2)
            if over > 0:
                issues.append(Issue("line_overrun", OVERRUN, f"line {ln['line_id']} runs {over:.1f} s past the end of "
                                                             f"the {take} s take (it is never trimmed)", card.number,
                                    ln["line_id"]))
        target = shot_word_target(take) if clock["spoken"] else 0
        if clock["spoken"] and over_budget(int(clock["words"]), target):
            issues.append(Issue("word_budget", OVERRUN, f"{clock['words']} words is more than a {take} s take carries "
                                                        f"(about {target})", card.number))
        suggest = next((d for d in VEO_DURATIONS if d >= need), None)
        if need > max(VEO_DURATIONS):
            issues.append(Issue("crowded", OVERRUN, f"it needs {need:.1f} s, more than the longest take "
                                                    f"({max(VEO_DURATIONS)} s): move a moment to another card",
                                card.number))
        elif need > take and not any(i.card == card.number and i.level == OVERRUN for i in issues):
            issues.append(Issue("crowded", OVERRUN, f"it needs {need:.1f} s but the take is {take} s; a "
                                                    f"{suggest} s take would hold it", card.number))
        use = card.use_s if card.use_s is not None else float(take)
        if use > take:
            issues.append(Issue("use_over_take", OVERRUN, f"use_s {use:g} is longer than the {take} s take",
                                card.number))
        elif use < MIN_USE_S:
            issues.append(Issue("use_too_short", WARNING, f"use_s {use:g} is under {MIN_USE_S:g} s: too short to read",
                                card.number))
        if not editorial and use != take:
            issues.append(Issue("trim_not_ready", WARNING, "the final cut cannot trim a take yet (Phase 9): the whole "
                                                           f"{take} s plays", card.number))
        rows.append({"number": card.number, "take_s": take, "use_s": use, "need_s": clock["need_s"],
                     "picture_s": clock["picture_s"], "words": clock["words"], "word_target": target,
                     "fits": need <= take and not any(i.card == card.number and i.level == OVERRUN for i in issues),
                     "suggest_take_s": suggest, "lines": clock["lines"]})
    runtime = sum(float(r["take_s"] if not editorial else r["use_s"]) for r in rows)
    wanted = sum(max(float(m.seconds_need), 0.0) for m in moments)
    envelope = scene.envelope_s
    over_envelope = max(0.0, runtime - envelope) if envelope else 0.0
    if over_envelope > 0:
        issues.append(Issue("envelope", WARNING, f"the cards play {runtime:g} s against an envelope of {envelope:g} s "
                                                 f"({over_envelope:g} s over): reported, never squeezed"))
    overruns = [i for i in issues if i.level == OVERRUN]
    return {"ok": not overruns, "cards": rows, "issues": [asdict(i) for i in issues], "overruns": len(overruns),
            "runtime_s": runtime, "moments_s": round(wanted, 2), "envelope_s": envelope,
            "over_envelope_s": round(over_envelope, 2)}
