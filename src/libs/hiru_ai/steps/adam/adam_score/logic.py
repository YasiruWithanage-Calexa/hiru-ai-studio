"""The craft score (plan/2026-11-04b §6.2): code rewards craft, so a dull plan with no defects cannot beat a vivid one.

`script_split`'s kernel score counts problems. This one counts what a director would be proud of: twelve signals, each
a list of small checks that name the card they are about. A fidelity break or an overrun is a LOSS before any of it
counts. Weights start equal (tuned on the gold set in Phase 10). Model critics write notes for a person; this decides
which version is kept (Chakrabarty et al.: model judges do not agree with experts on creativity).

The score explains itself: every check says whether it earned its points, which card it concerns and why.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from contracts.adam.plan import (
    MOTIVES,
    SIZE_RANK,
    AdamPlan,
    Moment,
    SceneScript,
    ShotCard,
    blocks_of,
    norm,
    people_of,
    subject_of,
)

SIGNALS: tuple[str, ...] = (
    "turn_seen", "baseline_shown", "pov_kept", "size_arc_kept", "one_rhythm_break", "plant_paid_off",
    "line_placement", "variety", "motivated_cuts", "ending", "sound", "feasibility",
)
DEFAULT_WEIGHTS: dict[str, float] = dict.fromkeys(SIGNALS, 1.0)
SIZE_TOLERANCE = 1  # "shot sizes follow the treatment's arc (tolerance of one step)"
OWNED = 0.5  # the POV owner's shots must be at least this share of their stretch
WIDE_AUTHORITY = ("two", "group")  # arrangements that put several people in one frame


@dataclass
class Check:
    card: int | None
    ok: bool
    why: str


class Ctx:
    """The plan, indexed once for every signal."""

    def __init__(self, scene: SceneScript, plan: AdamPlan, feasibility: dict[str, Any]) -> None:
        self.scene, self.plan, self.feasibility = scene, plan, feasibility
        self.by_id: dict[str, Moment] = {m.id: m for m in plan.moments}
        self.cards = plan.cards
        self.card_of: dict[str, ShotCard] = {mid: c for c in plan.cards for mid in c.moments}
        self.cast = {norm(c) for c in scene.cast}
        self.speaker = {b.line_id: norm(b.speaker) for b in scene.lines if b.line_id}

    def card_with(self, moment: str) -> ShotCard | None:
        return self.card_of.get(moment)

    def index(self, card: ShotCard) -> int:
        return self.cards.index(card)

    def subject(self, card: ShotCard) -> str:
        return subject_of(card, self.by_id)

    def blocks(self, card: ShotCard) -> set[int]:
        return blocks_of(card, self.by_id)


# ── the signals: each returns None when it does not apply to this scene, else its checks ─────────


def turn_seen(c: Ctx) -> list[Check] | None:
    turns = [b for b in c.plan.analysis.beats if b.turn]
    if not turns:
        return None
    out = []
    for beat in turns:
        who = norm(beat.reactor or c.plan.analysis.pov_owner.start)
        holders = [card for card in c.cards if c.blocks(card) & set(beat.blocks)]
        shown = [card for card in holders if who in people_of(card, c.by_id) or c.subject(card) == who]
        out.append(Check(shown[0].number if shown else (holders[0].number if holders else None), bool(shown),
                         f"{who}'s face is in frame while the turn at block {beat.blocks} lands" if shown else
                         f"{who} is not in frame while the turn at block {beat.blocks} lands"))
    return out


def baseline_shown(c: Ctx) -> list[Check] | None:
    base = set(c.plan.analysis.baseline.blocks)
    if not base:
        return None
    own = [card for card in c.cards if c.blocks(card) and c.blocks(card) <= base]
    added = [card for card in c.cards if any(c.by_id[m].kind == "baseline" for m in card.moments if m in c.by_id)]
    hit = (added or own)
    return [Check(hit[0].number if hit else None, bool(hit),
                  "the state before the break has a moment of its own" if hit else
                  "the state before the break never gets a moment of its own")]


def pov_kept(c: Ctx) -> list[Check] | None:
    pov = c.plan.analysis.pov_owner
    if not c.cards:
        return None
    start, end = norm(pov.start), norm(pov.end or pov.start)
    split = len(c.cards)
    out: list[Check] = []
    if end != start:
        handover = c.by_id.get(pov.handover)
        card = c.card_with(pov.handover) if handover else None
        named = bool(handover and card and end in {norm(w) for w in handover.who})
        out.append(Check(card.number if card else None, named, "the handover of the POV is a named moment that shows "
                         f"{end}" if named else f"the POV passes to {end} with no named moment that shows them"))
        if card:
            split = c.index(card)
    stretches = [(start, c.cards[:split]), (end, c.cards[split:])] if end != start else [(start, c.cards)]
    for owner, cards in stretches:
        counted = [x for x in cards if x.size != "INSERT" and (c.subject(x) or people_of(x, c.by_id))]
        if not counted:
            continue
        owned = [x for x in counted if c.subject(x) == owner
                 or (x.arrangement in WIDE_AUTHORITY and owner in people_of(x, c.by_id))]
        out.append(Check(cards[0].number, len(owned) / len(counted) >= OWNED,
                         f"{owner}'s shots are {len(owned)} of {len(counted)} in their stretch (at least half)"))
    return out or None


def size_arc_kept(c: Ctx) -> list[Check] | None:
    sections = c.plan.treatment.sections
    bands = {i: sorted(SIZE_RANK[s] for s in sec.size_band if s in SIZE_RANK) for i, sec in enumerate(sections)}
    if not any(len(b) == 2 for b in bands.values()):
        return None
    beat_of = {b: i for i, beat in enumerate(c.plan.analysis.beats) for b in beat.blocks}
    section_of = {beat: i for i, sec in enumerate(sections) for beat in sec.beats}
    out = []
    for card in c.cards:
        if card.size not in SIZE_RANK or not c.blocks(card):
            continue
        beats = {beat_of[b] for b in c.blocks(card) if b in beat_of}
        sec = next((section_of[x] for x in sorted(beats) if x in section_of), None)
        if sec is None or len(bands.get(sec, [])) != 2:
            continue
        lo, hi = bands[sec]
        ok = lo - SIZE_TOLERANCE <= SIZE_RANK[card.size] <= hi + SIZE_TOLERANCE
        out.append(Check(card.number, ok, f"{card.size} against the treatment's band for section {sec + 1}"
                         + ("" if ok else " (more than one step outside it)")))
    return out or None


def one_rhythm_break(c: Ctx) -> list[Check] | None:
    rb = c.plan.treatment.rhythm_break
    if rb is None:
        return None
    flagged = [x for x in c.cards if x.rhythm_break]
    at = c.card_with(rb.moment)
    key = c.plan.analysis.key_moment.block
    moment = c.by_id.get(rb.moment)
    return [
        Check(flagged[0].number if flagged else None, len(flagged) == 1,
              "exactly one card is the rhythm break" if len(flagged) == 1 else
              f"{len(flagged)} cards are marked as the rhythm break (exactly one)"),
        Check(at.number if at else None, bool(at and at.rhythm_break),
              "the break is the card that holds the treatment's break moment" if at and at.rhythm_break else
              "the card that holds the treatment's break moment is not the marked break"),
        Check(at.number if at else None, bool(moment and key in moment.blocks),
              "the break sits on the key moment" if moment and key in moment.blocks else
              "the break does not sit on the key moment"),
    ]


def plant_paid_off(c: Ctx) -> list[Check] | None:
    plant = c.plan.treatment.plant
    if plant is None:
        return None
    seeded = c.card_with(plant.plant_moment)
    paid = c.card_with(plant.payoff_moment) if plant.payoff_moment else None
    if seeded and paid and c.index(paid) > c.index(seeded):
        return [Check(paid.number, True, f"the {plant.object} planted in card {seeded.number} pays off here")]
    if seeded and plant.payoff_scene and not plant.payoff_moment:
        return [Check(seeded.number, True, f"the {plant.object} pays off in a later scene ({plant.payoff_scene})")]
    return [Check(seeded.number if seeded else None, False,
                  f"the {plant.object} is planted but never pays off in this scene" if seeded else
                  f"the {plant.object} plant moment is in no card")]


def line_placement(c: Ctx) -> list[Check] | None:
    off = [(card, cl) for card in c.cards for cl in card.lines if not cl.on_speaker]
    if not (c.plan.treatment.off_speaker or off):
        return None
    out: list[Check] = []
    if c.plan.treatment.off_speaker:
        present = [(card, cl) for card, cl in off if c.speaker.get(cl.line_id) in c.cast]
        out.append(Check(present[0][0].number if present else None, bool(present),
                         "a line plays over the face that hears it" if present else
                         "the treatment asks for a line over a listener and none is"))
    for card, cl in off:
        who = c.speaker.get(cl.line_id, "")
        if who not in c.cast:
            continue  # a voice that is never in the scene (the phone, a narrator): nothing to lip-sync
        shows_speaker = norm(cl.over_whom) == who or (c.subject(card) == who and card.arrangement == "single")
        out.append(Check(card.number, not shows_speaker,
                         f"line {cl.line_id} plays over {cl.over_whom or 'another face'}, not its speaker" if not
                         shows_speaker else f"line {cl.line_id} is off its speaker but the speaker's mouth is in frame "
                                            "(lip sync would show)"))
    return out


def variety(c: Ctx) -> list[Check] | None:
    if len(c.cards) < 2:
        return None
    out = []
    for a, b in zip(c.cards, c.cards[1:], strict=False):
        same = (a.size, a.angle, a.arrangement, c.subject(a)) == (b.size, b.angle, b.arrangement, c.subject(b))
        out.append(Check(b.number, not same, f"card {b.number} differs from card {a.number}" if not same else
                         f"card {b.number} repeats card {a.number}: same size, angle, arrangement and person"))
    return out


def motivated_cuts(c: Ctx) -> list[Check] | None:
    if len(c.cards) < 2:
        return None
    return [Check(card.number, card.cut_in.motive in MOTIVES or card.cut_in.link == "continuous",
                  f"the cut into card {card.number} is motivated by {card.cut_in.motive or 'a continuous take'}"
                  if card.cut_in.motive in MOTIVES or card.cut_in.link == "continuous" else
                  f"the cut into card {card.number} has no motive (action, look, line or sound)")
            for card in c.cards[1:]]


def ending(c: Ctx) -> list[Check] | None:
    want = c.plan.treatment.ending_moment
    if not want or not c.cards:
        return None
    last = c.cards[-1]
    return [Check(last.number, want in last.moments, "the last card is the treatment's ending image"
                  if want in last.moments else f"the last card is not the ending image ({want})")]


def sound(c: Ctx) -> list[Check] | None:
    turns = [b for b in c.plan.analysis.beats if b.turn]
    if not turns:
        return None
    sm = c.plan.sound_map
    turn_blocks = {b for t in turns for b in t.blocks}
    marked = [m for m in [*(s.moment for s in sm.subjective), *sm.silences] if (mo := c.by_id.get(m))
              and set(mo.blocks) & turn_blocks]
    shift = any(a.state and b.state and a.state != b.state and set(b.blocks) & turn_blocks
                for a, b in zip(sm.sections, sm.sections[1:], strict=False))
    card = c.card_with(marked[0]) if marked else None
    return [Check(card.number if card else None, bool(marked) or shift,
                  "the sound changes state at the turn" if marked or shift else
                  "the sound does not change state at the turn")]


def feasibility(c: Ctx) -> list[Check] | None:
    if not c.cards:
        return None
    bad = [f for f in c.feasibility.get("flags", []) if f["risk"] == "high" and not f["addressed"]]
    if not bad:
        return [Check(None, True, "no high-risk Veo flag is left unaddressed")]
    return [Check(int(f["card"]), False, f"card {f['card']}: {f['why']} ({f['code']}) is not answered in veo_notes")
            for f in bad]


FUNCS = {"turn_seen": turn_seen, "baseline_shown": baseline_shown, "pov_kept": pov_kept,
         "size_arc_kept": size_arc_kept, "one_rhythm_break": one_rhythm_break, "plant_paid_off": plant_paid_off,
         "line_placement": line_placement, "variety": variety, "motivated_cuts": motivated_cuts, "ending": ending,
         "sound": sound, "feasibility": feasibility}


def score(scene: SceneScript, plan: AdamPlan, fidelity: dict[str, Any], fit: dict[str, Any],
          feasibility_report: dict[str, Any], weights: dict[str, float] | None = None) -> dict[str, Any]:
    """The score of one plan, given the code reports that decide whether it loses before it is read for craft."""
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    ctx = Ctx(scene, plan, feasibility_report)
    signals, total, best = [], 0.0, 0.0
    for name in SIGNALS:
        checks = FUNCS[name](ctx)
        if checks is None:
            signals.append({"signal": name, "applicable": False, "weight": w[name], "points": 0.0, "checks": []})
            continue
        each = w[name] / len(checks)
        rows = [{"card": ch.card, "ok": ch.ok, "points": round(each if ch.ok else 0.0, 4), "why": ch.why}
                for ch in checks]
        points = sum(each for ch in checks if ch.ok)
        signals.append({"signal": name, "applicable": True, "weight": w[name], "points": round(points, 4),
                        "checks": rows})
        total, best = total + points, best + w[name]
    breaks = int(fidelity.get("counts", {}).get("breaks", len(fidelity.get("breaks", []))))
    overruns = int(fit.get("overruns", 0))
    reasons = ([f"{breaks} fidelity break(s)"] if breaks else []) + ([f"{overruns} overrun(s)"] if overruns else [])
    return {"loss": bool(reasons), "loss_reasons": reasons, "fidelity_breaks": breaks, "overruns": overruns,
            "score": round(total, 4), "max": round(best, 4), "percent": round(100 * total / best, 1) if best else 0.0,
            "signals": signals}


def rank(result: dict[str, Any]) -> tuple[int, int, float]:
    """Lower is better: fewer fidelity breaks, then fewer overruns, then more craft."""
    return (int(result["fidelity_breaks"]), int(result["overruns"]), -float(result["score"]))
