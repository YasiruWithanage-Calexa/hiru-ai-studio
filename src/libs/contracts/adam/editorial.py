"""The editorial layer (plan/2026-11-04b §5.6, Phase 9): a take is what Veo made, a CUT is the part of it that is kept.

A card carries `take_s` (4, 6 or 8), `use_s` (the part kept, at least 2 s) and `in_s` (where the kept part starts).
Editors cut shorter than the take, and a 2 s reaction becomes a 4 s take cut down to 2 s. The sound map reaches
across cuts the same way film does it:

    pre-lap   a card's sound arrives BEFORE its picture (a J cut): the clip's audio starts `lead_s` early, under the
              end of the shot before it. It needs `lead_s` of take BEFORE the kept part, so the trim starts later.
    carry     a card's sound carries INTO the next picture (an L cut): the clip's audio runs `tail_s` on.

`plan_cuts` turns cards into clips on a timeline; the assembler (`infra/assemble` `/cut`) turns clips into one video.
Pure standard library (the `contracts` rule); it imports the plan only for the card type.
"""
from __future__ import annotations

from dataclasses import dataclass

from contracts.adam.plan import ShotCard

PRE_LAP_S = 1.0  # how early a pre-lapped sound arrives
CARRY_S = 1.0  # how long a carried sound runs into the next picture
MIN_USE_S = 2.0  # the shortest part of a take worth keeping
STEP_S = 0.5  # trims land on half seconds


@dataclass(frozen=True)
class Clip:
    number: int  # the card
    take_s: float
    in_s: float  # where the kept part starts in the take
    use_s: float  # how long it plays
    lead_s: float  # its sound starts this much before its picture (needs lead_s <= in_s)
    tail_s: float  # its sound runs this much past its picture
    start_s: float  # where its picture starts on the scene's timeline


def _up(seconds: float) -> float:
    steps = -(-seconds // STEP_S)
    return float(steps * STEP_S)


def plan_cuts(cards: list[ShotCard], *, editorial: bool, pre_lap_s: float = PRE_LAP_S,
              carry_s: float = CARRY_S) -> list[Clip]:
    """The scene's clips in order. Off (`editorial` False) every take plays whole and nothing is laid across a cut.
    On, a clip keeps `use_s` from `in_s`; a pre-lap or a carry is given only as much as the take can spare, and never
    more than was asked."""
    clips: list[Clip] = []
    at = 0.0
    for card in cards:
        take = float(card.take_s)
        if not editorial:
            clips.append(Clip(card.number, take, 0.0, take, 0.0, 0.0, at))
            at += take
            continue
        use = float(card.use_s) if card.use_s is not None else take
        start = max(0.0, min(card.in_s, take - use))
        lead = min(pre_lap_s, start) if card.sound.pre_lap else 0.0
        tail = min(carry_s, max(0.0, take - start - use)) if card.sound.carries_over else 0.0
        clips.append(Clip(card.number, take, start, use, lead, tail, at))
        at += use
    return clips


def runtime_s(clips: list[Clip]) -> float:
    return sum(c.use_s for c in clips)


def propose_trims(cards: list[ShotCard], *, pre_lap_s: float = PRE_LAP_S, carry_s: float = CARRY_S
                  ) -> tuple[list[ShotCard], list[str]]:
    """Where an editor would cut, by rule: -> (the cards with `use_s` and `in_s`, a line for each change).

    A card is trimmed only when it is quiet (no word is said in it, a line is never trimmed), is not the scene's last
    shot (the button plays whole), is not the one deliberate break (it needs its time), and when the trim keeps at least
    `MIN_USE_S` and saves at least a second. It keeps up to where its last beat ends, to the half second. A card with a
    pre-lap starts its kept part `pre_lap_s` in, when the take can spare it, so its sound has something to arrive early
    with."""
    out: list[ShotCard] = []
    notes: list[str] = []
    for i, card in enumerate(cards):
        spoken = bool(card.lines)
        last = i == len(cards) - 1
        ends = [b.window[1] for b in card.beats if len(b.window) >= 2]
        use = max(MIN_USE_S, _up(max(ends))) if ends else float(card.take_s)
        start = 0.0
        if card.sound.pre_lap and card.take_s - use >= pre_lap_s:
            start = pre_lap_s
        if card.sound.carries_over:
            use = min(use, card.take_s - start - min(carry_s, 0.5))
        if spoken or last or card.rhythm_break or (use >= card.take_s - 1.0 + 1e-9 and not start):
            out.append(card)
            continue
        use = max(MIN_USE_S, min(use, card.take_s - start))
        out.append(card.model_copy(update={"use_s": use, "in_s": start}))
        notes.append(f"card {card.number}: keep {use:g} s from {start:g} s of the {card.take_s} s take")
    return out, notes
