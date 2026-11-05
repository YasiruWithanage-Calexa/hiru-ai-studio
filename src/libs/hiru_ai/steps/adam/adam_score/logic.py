"""The craft score (plan/2026-11-04b §6.2): code rewards craft, so a dull plan with no defects cannot beat a vivid one.

`script_split`'s kernel score counts problems. This one counts what a director would be proud of: fourteen signals, each
a list of small checks that name the card they are about. A fidelity break or an overrun is a LOSS before any of it
counts. Weights start equal, apart from `coverage` (tuned on the gold set in Phase 10). Model critics write notes for a
person; this decides which version is kept (Chakrabarty et al.: model judges do not agree with experts on creativity).

The score explains itself: every check says whether it earned its points, which card it concerns and why.

Plan/2026-11-04c made the yardstick able to see what a bare plan lacks: every signal scores the SHARE of what it needs,
`coverage` asks for the faces the analysis says must be seen (`adam_coverage`), `one_job_per_card` for a card that stays
on one face, and the required cells also GATE the percent (a plan missing a face cannot read as 100 %). The rank adds
the cells a plan LOSES to the other candidate, so a revision cannot win by deleting what the scene needs.
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
    "line_placement", "variety", "motivated_cuts", "ending", "sound", "feasibility", "coverage", "one_job_per_card",
)
DEFAULT_WEIGHTS: dict[str, float] = {**dict.fromkeys(SIGNALS, 1.0), "coverage": 3.0}  # it carries what the rest miss
LINKING_MOVES = ("pan", "track", "reveal", "crane")  # a camera move that carries the frame from one face to another
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

    def __init__(self, scene: SceneScript, plan: AdamPlan, feasibility: dict[str, Any],
                 coverage: dict[str, Any] | None = None) -> None:
        self.scene, self.plan, self.feasibility = scene, plan, feasibility
        self.coverage = coverage or {}
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
    """Each block of the state before the break has a moment of its own (a baseline moment, or a card that is only about
    the baseline): one check per block, so one baseline card does not earn it for a scene with two."""
    base = set(c.plan.analysis.baseline.blocks)
    if not base:
        return None
    out = []
    for block in sorted(base):
        added = [card for card in c.cards if any((m := c.by_id.get(i)) and m.kind == "baseline" and block in m.blocks
                                                 for i in card.moments)]
        own = [card for card in c.cards if block in c.blocks(card) and c.blocks(card) <= base]
        hit = added or own
        out.append(Check(hit[0].number if hit else None, bool(hit),
                         f"the state before the break (block {block}) has a moment of its own" if hit else
                         f"the state before the break (block {block}) never gets a moment of its own"))
    return out


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
    arc = sorted(SIZE_RANK[s] for s in c.plan.treatment.size_arc if s in SIZE_RANK)
    used = sorted(SIZE_RANK[card.size] for card in c.cards if card.size in SIZE_RANK)
    reach: list[Check] = []
    if len(set(arc)) > 1 and used:  # the cards travel the arc: they get as wide and as close as the treatment says
        for label, want, got in (("widest", arc[0], used[0]), ("closest", arc[-1], used[-1])):
            ok = abs(want - got) <= SIZE_TOLERANCE
            reach.append(Check(None, ok, f"the {label} card reaches the treatment's {label} size (arc)" if ok else
                               f"the {label} card is more than one step from the treatment's {label} size (arc)"))
    if not any(len(b) == 2 for b in bands.values()):
        return reach or None
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
    return [*out, *reach] or None


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


def hears(c: Ctx, cl: Any) -> bool:
    """A line off its speaker plays over a LISTENER: a person present who is not the one speaking."""
    who = norm(cl.over_whom)
    return bool(who in c.cast and who != c.speaker.get(cl.line_id, ""))


def line_placement(c: Ctx) -> list[Check] | None:
    """Never over an object, over nobody or over the speaker's own face or hands (plan/2026-11-04c F6)."""
    off = [(card, cl) for card in c.cards for cl in card.lines if not cl.on_speaker]
    if not (c.plan.treatment.off_speaker or off):
        return None
    out: list[Check] = []
    if c.plan.treatment.off_speaker:
        heard = [(card, cl) for card, cl in off if hears(c, cl)]
        out.append(Check(heard[0][0].number if heard else None, bool(heard),
                         "a line plays over the face that hears it" if heard else
                         "the treatment asks for a line over a listener and none is"))
    for card, cl in off:
        ok = hears(c, cl)
        own = norm(cl.over_whom) == c.speaker.get(cl.line_id, "")
        out.append(Check(card.number, ok, f"line {cl.line_id} plays over {cl.over_whom}, who hears it" if ok else
                         f"line {cl.line_id} is off its speaker but plays over {cl.over_whom or 'no one'}"
                         + (", the speaker's own face" if own else ": it needs a person present who is not the "
                            "speaker")))
    return out


def variety(c: Ctx) -> list[Check] | None:
    """Each card differs from the one before it. Counted per card (the first always passes), so a plan is not rewarded
    for having fewer cards, which leaves fewer neighbours to repeat."""
    if len(c.cards) < 2:
        return None
    out = [Check(c.cards[0].number, True, "the first card has nothing to repeat")]
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


def coverage(c: Ctx) -> list[Check] | None:
    """One check per required cell of the coverage grid (`adam_coverage`): the faces the analysis says must be seen."""
    cells = c.coverage.get("cells") or []
    if not cells:
        return None
    return [Check(cell.get("card"), bool(cell["ok"]), cell["why"] if cell["ok"] else f"missing: {cell['why']}")
            for cell in cells]


def one_job_per_card(c: Ctx) -> list[Check] | None:
    """A card has one main job: a change of the face we are on, or of the beat, starts a new card, unless a move or a
    rack carries the frame across (plan/2026-11-04c F6). Two things are looked for in a card of two moments or more: a
    moment about someone other than the person the frame is on, and moments from two beats of the analysis (a plant
    serves the block where it pays off, so it does not count towards the beats a card spans)."""
    beat_of = {b: i for i, beat in enumerate(c.plan.analysis.beats) for b in beat.blocks}
    out = []
    for card in c.cards:
        if len(card.moments) < 2:
            continue
        held = [m for ident in card.moments if (m := c.by_id.get(ident))]
        on = c.subject(card)
        away = [m.id for m in held if m.who and on and on not in {norm(w) for w in m.who}
                and card.arrangement not in WIDE_AUTHORITY]
        beats = {beat_of[b] for m in held if m.kind != "plant" for b in m.blocks if b in beat_of}
        carried = card.focus.kind == "rack" or card.movement in LINKING_MOVES
        ok = (not away and len(beats) < 2) or carried
        why = (f"card {card.number} stays on one face and one beat" if ok else
               f"card {card.number} is on {on} but {', '.join(away)} is about someone else" if away else
               f"card {card.number} holds moments from {len(beats)} beats")
        out.append(Check(card.number, ok, why if ok else why + ", with no move or rack between them: one job per "
                                                              "card, so cut"))
    return out or None


FUNCS = {"turn_seen": turn_seen, "baseline_shown": baseline_shown, "pov_kept": pov_kept,
         "size_arc_kept": size_arc_kept, "one_rhythm_break": one_rhythm_break, "plant_paid_off": plant_paid_off,
         "line_placement": line_placement, "variety": variety, "motivated_cuts": motivated_cuts, "ending": ending,
         "sound": sound, "feasibility": feasibility, "coverage": coverage, "one_job_per_card": one_job_per_card}


def score(scene: SceneScript, plan: AdamPlan, fidelity: dict[str, Any], fit: dict[str, Any],
          feasibility_report: dict[str, Any], weights: dict[str, float] | None = None,
          coverage_report: dict[str, Any] | None = None) -> dict[str, Any]:
    """The score of one plan, given the code reports that decide whether it loses before it is read for craft."""
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    ctx = Ctx(scene, plan, feasibility_report, coverage_report)
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
    share = float((coverage_report or {}).get("coverage", 1.0))  # the share of required faces gates the percent
    craft = 100 * total / best if best else 0.0
    return {"loss": bool(reasons), "loss_reasons": reasons, "fidelity_breaks": breaks, "overruns": overruns,
            "score": round(total, 4), "max": round(best, 4), "percent": round(craft * share, 1),
            "craft_percent": round(craft, 1), "coverage": round(share, 4),
            "filled": [x["id"] for x in (coverage_report or {}).get("cells", []) if x["ok"]], "signals": signals}


def rank(result: dict[str, Any], lost: int = 0) -> tuple[int, int, int, float]:
    """Lower is better: fewer fidelity breaks, then fewer required cells lost to the other candidate, then fewer
    overruns, then more craft. A candidate that leaves empty a cell another candidate fills loses the way a break loses
    (plan/2026-11-04c F4), so deleting what the scene needs is never the way to win. A break still comes first: craft
    and coverage cannot rescue it."""
    return (int(result["fidelity_breaks"]), lost, int(result["overruns"]), -float(result["score"]))


def lost_cells(results: list[dict[str, Any]]) -> list[int]:
    """For each result, how many required cells another result fills and this one leaves empty."""
    filled = [set(r.get("filled") or []) for r in results]
    return [len(set().union(*(f for j, f in enumerate(filled) if j != i)) - mine) if len(filled) > 1 else 0
            for i, mine in enumerate(filled)]
