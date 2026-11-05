"""What a model is asked to write at each stage of Shot Planner Adam (plan/2026-11-04b §5.2): the WIRE shapes.

`plan.py` holds the plan as the rest of the system reads it: optional fields, defaults, an alias. A model that answers
in strict JSON-schema mode cannot be held to that (every property must be required, every object closed, no free-form
mapping), so each stage has a wire shape of its own with NO defaults, and a method that turns it into the plan's
shape:

    AnalysisWire   (adam_dramaturg)       .analysis()    → SceneAnalysis
    TreatmentsWire (adam_director)        .all()         → [Treatment]        three, one per stance
    MomentsWire    (adam_moment_writer)   .moment_list() → [Moment]; .bind()  → the ids the plan names, bound
    StagingWire    (adam_blocker)         .staging()     → Staging
    CardsWire      (adam_shot_designer)   .card_list()   → [ShotCard]
    SoundWire      (adam_sound_designer)  .sound_map()   → SoundMap; .apply() → the cards with their sound

The conversions keep the model's words and decide nothing: whether a moment invents story, a take fits the clock or a
cut is motivated belongs to the steps (`adam_fidelity`, `adam_fit`, `adam_continuity`, `adam_score`). Pure standard
library + pydantic (the `contracts` rule).
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict

from contracts.adam import plan as p


class _Wire(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ── ① the analysis (adam_dramaturg) ──────────────────────────────────────────────────────────────


class ValueW(_Wire):
    start: str
    end: str


class BeatW(_Wire):
    blocks: list[int]
    action: str
    reaction: str
    turn: bool
    reactor: str


class WantW(_Wire):
    who: str
    verb: str  # a playable verb: "to enjoy", "to hide"


class SubtextW(_Wire):
    block: int
    who: str
    behaviour: str
    object: str
    sound: str


class PovW(_Wire):
    start: str
    end: str  # who has it after the handover; the same name as `start` when it never changes
    why: str


class KnowsW(_Wire):
    fact: str
    who_doesnt: str
    from_block: int


class BaselineW(_Wire):
    blocks: list[int]
    state: str


class KeyMomentW(_Wire):
    block: int
    why: str


class QuestionW(_Wire):
    question: str  # what the script leaves open that changes what is filmed
    blocks: list[int]  # the blocks it concerns


class AnalysisWire(_Wire):
    about: str
    dramatic_question: str
    value: ValueW
    tone: str
    beats: list[BeatW]
    wants: list[WantW]
    obstacles: list[str]
    subtext: list[SubtextW]
    pov_owner: PovW
    audience_knows: list[KnowsW]
    baseline: BaselineW
    break_block: int | None  # the block where the value breaks; null when the scene has no break
    aftermath: str
    key_moment: KeyMomentW
    questions: list[QuestionW]  # open questions for a person; empty when the script leaves nothing open

    def analysis(self) -> p.SceneAnalysis:
        """The plan's form. The POV handover (a moment id) is bound later, by the moment writer."""
        return p.SceneAnalysis(
            about=self.about, dramatic_question=self.dramatic_question,
            value=p.Value(start=self.value.start, end=self.value.end), tone=self.tone,
            beats=[p.Beat(blocks=b.blocks, action=b.action, reaction=b.reaction, turn=b.turn, reactor=b.reactor)
                   for b in self.beats],
            wants={w.who: w.verb for w in self.wants if w.who.strip()}, obstacles=self.obstacles,
            subtext=[p.Subtext(block=s.block, who=s.who, behaviour=s.behaviour, object=s.object, sound=s.sound)
                     for s in self.subtext],
            pov_owner=p.PovOwner(start=self.pov_owner.start, end=self.pov_owner.end, why=self.pov_owner.why),
            audience_knows=[p.Knows(fact=k.fact, who_doesnt=k.who_doesnt, from_block=k.from_block)
                            for k in self.audience_knows],
            baseline=p.Baseline(blocks=self.baseline.blocks, state=self.baseline.state),
            aftermath=p.Aftermath(state=self.aftermath),
            key_moment=p.KeyMoment(block=self.key_moment.block, why=self.key_moment.why),
            questions=[p.Question(question=q.question.strip(), blocks=q.blocks) for q in self.questions
                       if q.question.strip()],
            **{"break": p.BreakAt(block=self.break_block)})


# ── ② the treatments (adam_director) ─────────────────────────────────────────────────────────────

Stance = Literal["restrained", "intimate", "heightened"]
STANCES: tuple[str, ...] = ("restrained", "intimate", "heightened")


class SectionW(_Wire):
    beats: list[int]  # indexes into the analysis's beats
    camera_behaviour: str
    size_band: list[p.Size]  # [smallest, largest]
    sound_state: str


class PlantW(_Wire):
    object: str
    plant_when: str  # in words: "the opening two-shot"; the moment writer binds it to a moment
    payoff_when: str
    payoff_scene: str  # a LATER scene, named, when the payoff is not in this one; else empty


class BreakW(_Wire):
    when: str  # in words; the moment writer binds it to a moment
    kind: Literal["silence", "long_hold", "sudden_cut"]


class TreatmentW(_Wire):
    stance: Stance
    name: str
    concept: str  # "we make the viewer feel X by Y"
    pov: str
    sound_concept: str
    sections: list[SectionW]
    size_arc: list[p.Size]
    motif: str
    plant: PlantW | None
    rhythm: list[str]
    rhythm_break: BreakW | None
    entry: str
    exit: str
    ending_image: str
    transition_in: str
    transition_out: str
    off_speaker: bool  # the treatment asks for at least one line to play over a listener's face

    def treatment(self) -> p.Treatment:
        """The plan's form. Every moment id is empty: the moment writer binds them (`MomentsWire.bind`)."""
        plant = (p.Plant(object=self.plant.object, plant_moment="", payoff_moment="",
                         payoff_scene=self.plant.payoff_scene, plant_when=self.plant.plant_when,
                         payoff_when=self.plant.payoff_when) if self.plant else None)
        brk = p.RhythmBreak(moment="", kind=self.rhythm_break.kind, when=self.rhythm_break.when) \
            if self.rhythm_break else None
        return p.Treatment(
            name=self.name, stance=self.stance, concept=self.concept, pov=self.pov, sound_concept=self.sound_concept,
            sections=[p.Section(beats=s.beats, camera_behaviour=s.camera_behaviour, size_band=s.size_band,
                                sound_state=s.sound_state) for s in self.sections],
            size_arc=self.size_arc, motif=self.motif, plant=plant, rhythm=self.rhythm, rhythm_break=brk,
            entry=self.entry, exit=self.exit, ending_image=self.ending_image, ending_moment="",
            transition_in=self.transition_in, transition_out=self.transition_out, off_speaker=self.off_speaker)


class TreatmentsWire(_Wire):
    treatments: list[TreatmentW]

    def all(self) -> list[p.Treatment]:
        return [t.treatment() for t in self.treatments]


# ── ③ the moments (adam_moment_writer) ───────────────────────────────────────────────────────────


class MomentW(_Wire):
    id: str  # "m1", "m2" ... in the order they play
    tier: Literal["script", "implied", "elaboration"]
    # an elaboration's kind (or an implied moment's), from the closed list in `tiers.ELABORATION_KINDS`; empty for a
    # script moment. An enum, not free text: a live model otherwise writes "baseline Anudi" and fidelity drops it.
    kind: Literal["", "baseline", "reaction", "listener", "insert_detail", "hands", "pov", "atmosphere", "hold",
                  "plant", "transition", "empty_frame", "implied_action", "move"]
    serves: list[str]
    who: list[str]
    seen: str
    heard: str
    feeling: str
    seconds_need: float
    lines: list[str]
    objects: list[str]


class BindingsW(_Wire):
    """Which moment each thing the director described in words has become. Empty when there is no such moment."""

    plant: str
    payoff: str
    rhythm_break: str
    ending: str
    handover: str  # the moment that hands the point of view over, when it changes hands


class MomentsWire(_Wire):
    moments: list[MomentW]
    bindings: BindingsW

    def tidy(self) -> MomentsWire:
        """Ids without spaces, unique and present; seconds never negative. An id that cannot be kept renumbers the
        list `m1 ..` by position and clears the bindings (which named the old ids) rather than guess."""
        ids = [re.sub(r"\s+", "", m.id) for m in self.moments]
        keep = all(ids) and len(set(ids)) == len(ids)
        if not keep:
            ids = [f"m{n}" for n in range(1, len(self.moments) + 1)]
        moments = [m.model_copy(update={"id": ident, "seconds_need": max(0.0, m.seconds_need),
                                        "serves": [s.strip() for s in m.serves if s.strip()],
                                        "lines": [s.strip() for s in m.lines if s.strip()]})
                   for m, ident in zip(self.moments, ids, strict=True)]
        bindings = self.bindings if keep else BindingsW(plant="", payoff="", rhythm_break="", ending="", handover="")
        return MomentsWire(moments=moments, bindings=bindings)

    def moment_list(self) -> list[p.Moment]:
        return [p.Moment(id=m.id, tier=m.tier, kind=m.kind, serves=m.serves, who=m.who, seen=m.seen, heard=m.heard,
                         feeling=m.feeling, seconds_need=m.seconds_need, lines=m.lines, objects=m.objects)
                for m in self.tidy().moments]

    def bind(self, analysis: p.SceneAnalysis, treatment: p.Treatment) -> tuple[p.SceneAnalysis, p.Treatment]:
        """The analysis and the treatment with the moment ids the writer named. An id the list does not have is left
        empty: `adam_score` then reports the thing as missing instead of the plan pointing at nothing."""
        tidy = self.tidy()
        have = {m.id for m in tidy.moments}
        b = tidy.bindings

        def known(ident: str) -> str:
            return ident if ident in have else ""

        plant = (treatment.plant.model_copy(update={"plant_moment": known(b.plant),
                                                    "payoff_moment": known(b.payoff)}) if treatment.plant else None)
        brk = (treatment.rhythm_break.model_copy(update={"moment": known(b.rhythm_break)})
               if treatment.rhythm_break else None)
        bound = treatment.model_copy(update={"plant": plant, "rhythm_break": brk, "ending_moment": known(b.ending)})
        pov = analysis.pov_owner.model_copy(update={"handover": known(b.handover)})
        return analysis.model_copy(update={"pov_owner": pov}), bound


# ── ④ the staging (adam_blocker) ─────────────────────────────────────────────────────────────────

WhyMove = Literal["power", "avoidance", "approach", "need", "enter", "exit", ""]


class MarkW(_Wire):
    moment: str
    who: str
    zone: str
    facing: str
    holding: list[str]


class MoveW(_Wire):
    moment: str
    who: str
    from_zone: str
    to_zone: str
    why: WhyMove


class StagingWire(_Wire):
    marks: list[MarkW]
    moves: list[MoveW]

    def staging(self) -> p.Staging:
        return p.Staging(
            marks=[p.Mark(moment=m.moment, who=m.who, zone=m.zone, facing=m.facing, holding=m.holding)
                   for m in self.marks],
            moves=[p.Move(moment=m.moment, who=m.who, from_zone=m.from_zone, to_zone=m.to_zone, why=m.why)
                   for m in self.moves])


# ── ⑤ the cards (adam_shot_designer) and the sound (adam_sound_designer) ─────────────────────────


class FocusW(_Wire):
    kind: Literal["deep", "shallow", "rack"]
    rack_from: str  # who or what is sharp first, for a rack; else empty
    rack_to: str


class CompositionW(_Wire):
    foreground: str
    negative_space: str
    frame_side: p.FrameSide


class CardBeatW(_Wire):
    window: list[float]  # [from_s, to_s] inside the take
    action: str
    performance: str  # visible micro-action, never a feeling word
    camera: str


class CardLineW(_Wire):
    line_id: str  # the line's id, never its words
    on_speaker: bool
    over_whom: str  # when off the speaker: whose face the line plays over


class CardSoundW(_Wire):
    ambience: str
    effects: str
    music: str
    silence: bool
    pre_lap: str
    carries_over: str

    def card_sound(self) -> p.CardSound:
        return p.CardSound(ambience=self.ambience, effects=self.effects, music=self.music, silence=self.silence,
                           pre_lap=self.pre_lap, carries_over=self.carries_over)


class CutInW(_Wire):
    link: p.CutLink
    motive: p.Motive


class CardW(_Wire):
    moments: list[str]
    title: str
    size: p.Size
    arrangement: p.Arrangement
    subject: str
    angle: p.Angle
    height: str
    lens_feel: p.LensFeel
    movement: p.Movement
    focus: FocusW
    composition: CompositionW
    eyeline: p.Eyeline
    axis: p.Axis
    blocking_in_shot: str
    beats: list[CardBeatW]
    lines: list[CardLineW]
    sound: CardSoundW
    cut_in: CutInW
    purpose: str
    emotional_beat: str
    rhythm_break: bool
    veo_notes: str
    take_s: Literal[4, 6, 8]

    def card(self, number: int) -> p.ShotCard:
        return p.ShotCard(
            number=number, moments=self.moments, title=self.title, size=self.size, arrangement=self.arrangement,
            subject=self.subject, angle=self.angle, height=self.height, lens_feel=self.lens_feel,
            movement=self.movement,
            focus=p.Focus.model_validate({"kind": self.focus.kind, "from": self.focus.rack_from,
                                          "to": self.focus.rack_to}),
            composition=p.Composition(foreground=self.composition.foreground,
                                      negative_space=self.composition.negative_space,
                                      frame_side=self.composition.frame_side),
            eyeline=self.eyeline, axis=self.axis, blocking_in_shot=self.blocking_in_shot,
            beats=[p.CardBeat(window=b.window, action=b.action, performance=b.performance, camera=b.camera)
                   for b in self.beats],
            lines=[p.CardLine(line_id=ln.line_id, on_speaker=ln.on_speaker, over_whom=ln.over_whom)
                   for ln in self.lines],
            sound=self.sound.card_sound(), cut_in=p.CutIn(link=self.cut_in.link, motive=self.cut_in.motive),
            purpose=self.purpose, emotional_beat=self.emotional_beat, rhythm_break=self.rhythm_break,
            veo_notes=self.veo_notes, take_s=self.take_s, use_s=None, in_s=0.0)


class CardsWire(_Wire):
    cards: list[CardW]

    def card_list(self) -> list[p.ShotCard]:
        """The cards, numbered by their place in the list (the designer does not number them)."""
        return [c.card(n) for n, c in enumerate(self.cards, start=1)]


class SoundSectionW(_Wire):
    blocks: list[int]
    ambience: str
    music: str
    state: str  # a word for how the world sounds here ("warm", "narrowed to breath")


class SubjectiveW(_Wire):
    moment: str
    kind: str  # narrowing, drop, ringing, heartbeat ...
    description: str


class PreLapW(_Wire):
    card: int
    into: str


class MusicCueW(_Wire):
    moment: str
    action: Literal["in", "out"]


class CardSoundForW(_Wire):
    number: int  # the card's number
    sound: CardSoundW


class SoundWire(_Wire):
    sections: list[SoundSectionW]
    subjective: list[SubjectiveW]
    silences: list[str]  # moment ids
    pre_laps: list[PreLapW]
    music: list[MusicCueW]
    cards: list[CardSoundForW]

    def sound_map(self) -> p.SoundMap:
        return p.SoundMap(
            sections=[p.SoundSection(blocks=s.blocks, ambience=s.ambience, music=s.music, state=s.state)
                      for s in self.sections],
            subjective=[p.SubjectiveSound(moment=s.moment, kind=s.kind, description=s.description)
                        for s in self.subjective],
            silences=self.silences, pre_laps=[p.PreLap(card=x.card, into=x.into) for x in self.pre_laps],
            music=[p.MusicCue(moment=m.moment, action=m.action) for m in self.music])

    def apply(self, cards: list[p.ShotCard]) -> list[p.ShotCard]:
        """The cards with the sound written for them. A number that is not a card is ignored; a card the designer did
        not write for keeps the sound it had."""
        by_number = {c.number: c.sound.card_sound() for c in self.cards}
        return [c.model_copy(update={"sound": by_number[c.number]}) if c.number in by_number else c for c in cards]
