"""What the screening panel's critics and the reviser read and write (plan/2026-11-04b §5.4).

Four critics, each with one lens, read the same plan and answer with at most four notes and a score from 1 to 5 on their
own lens. A note names a card (0 = the scene as a whole), a severity and a KIND (add, remove, change, risk; an `add`
also names the coverage cell or the moment kind it would fill). They never choose: the notes go to ONE reviser, which
answers with OPERATIONS on the plan (replace a card, insert one, remove one, add or remove a moment), not a fresh plan,
and DISPOSITIONS, one for every note: the operations that answered it, or why it was declined (plan/2026-11-04c F5, the
way a production keeps a notes log). CODE (`adam_score`) keeps the better version.

    ScreenInput    what every critic and the reviser are given
    CriticWire     a critic's answer (strict wire shape: no defaults)
    RevisionWire   the reviser's answer; `.apply(moments, cards)` → `Revised`
    Noted          a merged note with its id (n1, n2 ...); `check_revision` holds the reviser to its dispositions
    drop_moments   remove moments and every card left with none (also what a fidelity "drop" does)
    remap_sound    the sound map after cards were renumbered and moments removed

The conversions keep the model's words and decide nothing about the story: whether an added moment invents anything is
`adam_fidelity`'s decision, made after the operations are applied. Pure standard library + pydantic (the `contracts`
rule).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from contracts.adam import wire as w
from contracts.adam.plan import (
    Moment,
    SceneAnalysis,
    SceneScript,
    ShotCard,
    SoundMap,
    Staging,
    Treatment,
    compact,
)

Severity = Literal["high", "medium", "low"]
SEVERITIES: tuple[str, ...] = ("high", "medium", "low")
NoteKind = Literal["add", "remove", "change", "risk"]
NOTE_KINDS: tuple[str, ...] = ("add", "remove", "change", "risk")
MAX_NOTES = 4  # per critic (plan §5.4)
LENSES: tuple[str, ...] = ("audience", "editor", "opportunity", "fidelity")


class ScreenInput(BaseModel):
    """What a critic (and the reviser) is given: the plan so far. `report` is the code's findings as text, for the
    fidelity critic and the reviser only; the other lenses judge the picture without it."""

    scene: SceneScript
    analysis: SceneAnalysis
    treatment: Treatment
    moments: list[Moment]
    staging: Staging = Staging()
    cards: list[ShotCard]
    sound_map: SoundMap = SoundMap()
    report: str = ""


def screen_message(inp: ScreenInput) -> str:
    """The plan as a critic reads it: the script, the intent, then the moments and the cards. Data last, in tags."""
    return (f"<script>\n{inp.scene.listing()}\n</script>\n\n"
            f"<analysis>\n{compact(inp.analysis)}\n</analysis>\n\n"
            f"<treatment>\n{compact(inp.treatment)}\n</treatment>\n\n"
            f"<moments>\n{compact(list(inp.moments))}\n</moments>\n\n"
            f"<cards>\n{compact(list(inp.cards))}\n</cards>\n\n"
            f"<sound>\n{compact(inp.sound_map)}\n</sound>"
            + (f"\n\n<report>\n{inp.report}\n</report>" if inp.report else ""))


class _Wire(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ── a critic's answer ────────────────────────────────────────────────────────────────────────────


class NoteW(_Wire):
    card: int  # the card's number; 0 = the scene as a whole
    severity: Severity
    kind: NoteKind  # add a picture, remove one, change one, or a risk to watch
    cell: str  # an `add` note: the coverage cell it fills (turn:2, stake:dasun:before) or a moment kind; else ""
    note: str  # what is wrong or missing, in one or two sentences, and what would make it better


class CriticWire(_Wire):
    notes: list[NoteW]  # at most four, the ones that matter most
    score: Literal[1, 2, 3, 4, 5]  # on this critic's own lens; stored for a person, it decides nothing

    def clean(self, card_numbers: set[int]) -> CriticWire:
        """At most `MAX_NOTES`, most severe first; a note on a card the plan does not have is dropped; no empty note."""
        order = {s: i for i, s in enumerate(SEVERITIES)}
        kept = [n for n in self.notes if n.note.strip() and (n.card == 0 or n.card in card_numbers)]
        kept.sort(key=lambda n: order[n.severity])  # stable: the critic's order holds within a severity
        return CriticWire(notes=kept[:MAX_NOTES], score=self.score)


# ── the reviser's answer ─────────────────────────────────────────────────────────────────────────

OpName = Literal["replace_card", "insert_card", "remove_card", "add_moment", "remove_moment"]


class OpW(_Wire):
    op: OpName
    why: str  # the note this answers, in a few words
    number: int  # replace_card, remove_card: the card's number. insert_card: the card to insert AFTER (0 = first)
    after: str  # add_moment: the id of the moment to insert after ("" = first)
    id: str  # remove_moment: the moment's id
    card: w.CardW | None  # replace_card, insert_card: the whole card as it should be
    moment: w.MomentW | None  # add_moment


class DispositionW(_Wire):
    """What became of one note: the operations that answered it (their numbers in `operations`, from 1), or the reason
    it was declined. Exactly one of the two is filled."""

    note_id: str
    done: list[int]
    declined: str


class RevisionWire(_Wire):
    operations: list[OpW]
    dispositions: list[DispositionW]  # one for every note; a high note must have one

    def apply(self, moments: list[Moment], cards: list[ShotCard]) -> Revised:
        """The plan after the operations. Numbers always mean the cards as the critics saw them, whatever the earlier
        operations did; an operation that cannot apply is skipped and says why. Cards are numbered again at the end."""
        out_moments = list(moments)
        entries: list[list[Any]] = [[c.number, c] for c in cards]  # [original number | None, card | None (removed)]
        skipped: list[str] = []
        removed: set[str] = set()
        applied = [True] * len(self.operations)
        removals: dict[str, int] = {}  # a moment a `remove_moment` took out → the number of that operation

        def at(number: int) -> int | None:
            return next((i for i, e in enumerate(entries) if e[0] == number), None)

        for n, op in enumerate(self.operations, start=1):
            before = len(skipped)
            tag = f"operation {n} ({op.op})"
            if op.op == "replace_card":
                i = at(op.number)
                if op.card is None or i is None:
                    skipped.append(f"{tag}: needs a card and a card number the plan has")
                else:
                    entries[i][1] = op.card.card(1)
            elif op.op == "insert_card":
                i = -1 if op.number == 0 else at(op.number)
                if op.card is None or i is None:
                    skipped.append(f"{tag}: needs a card and 0 or a card number the plan has")
                else:
                    entries.insert(i + 1, [None, op.card.card(1)])
            elif op.op == "remove_card":
                i = at(op.number)
                if i is None:
                    skipped.append(f"{tag}: the plan has no card {op.number}")
                else:
                    entries[i][1] = None
            elif op.op == "add_moment":
                here = {m.id for m in out_moments}
                spot = 0 if not op.after else next((i + 1 for i, m in enumerate(out_moments) if m.id == op.after), None)
                if op.moment is None or spot is None or op.moment.id in here or not op.moment.id.strip():
                    skipped.append(f"{tag}: needs a new moment with an id of its own, after a moment the plan has")
                else:
                    out_moments.insert(spot, _moment(op.moment))
            else:  # remove_moment
                found = next((m for m in out_moments if m.id == op.id), None)
                if found is None:
                    skipped.append(f"{tag}: the plan has no moment {op.id!r}")
                elif found.tier == "script":
                    skipped.append(f"{tag}: {op.id} is a script moment; the script is never removed")
                else:
                    out_moments.remove(found)
                    removed.add(op.id)
                    removals[op.id] = n
            applied[n - 1] = len(skipped) == before

        kept: list[tuple[int | None, ShotCard]] = [(e[0], e[1]) for e in entries if isinstance(e[1], ShotCard)]
        shown_moments, survivors = _drop(out_moments, kept, removed)
        numbered = [c.model_copy(update={"number": i}) for i, (_, c) in enumerate(survivors, start=1)]
        renumbered = {old: i for i, (old, _) in enumerate(survivors, start=1) if isinstance(old, int)}
        gone = {c.number for c in cards} - set(renumbered)
        return Revised(moments=shown_moments, cards=numbered, renumbered=renumbered, skipped=skipped, applied=applied,
                       removals=removals, gone=gone)


def _moment(m: w.MomentW) -> Moment:
    return Moment(id=m.id.strip(), tier=m.tier, kind=m.kind, serves=m.serves, who=m.who, seen=m.seen, heard=m.heard,
                  feeling=m.feeling, seconds_need=max(0.0, m.seconds_need), lines=m.lines, objects=m.objects)


@dataclass
class Revised:
    moments: list[Moment]
    cards: list[ShotCard]
    renumbered: dict[int, int] = field(default_factory=dict)  # a card's old number → its number now
    skipped: list[str] = field(default_factory=list)  # operations that could not apply, and why
    applied: list[bool] = field(default_factory=list)  # for each operation, did it apply
    removals: dict[str, int] = field(default_factory=dict)  # a moment removed → the operation that removed it
    gone: set[int] = field(default_factory=set)  # the old numbers of the cards that no longer exist


def _drop[K](moments: list[Moment], cards: list[tuple[K, ShotCard]],
            ids: set[str]) -> tuple[list[Moment], list[tuple[K, ShotCard]]]:
    """The moments without `ids`, and the keyed cards without them: a card left with no moment goes."""
    survivors = []
    for key, card in cards:
        left = [m for m in card.moments if m not in ids]
        if left:
            survivors.append((key, card.model_copy(update={"moments": left})))
    return [m for m in moments if m.id not in ids], survivors


def drop_moments(moments: list[Moment], cards: list[ShotCard],
                 ids: set[str]) -> tuple[list[Moment], list[ShotCard], dict[int, int]]:
    """The plan without these moments: they leave every card that showed them, and a card left with none goes. Cards are
    numbered again from 1 in order. -> (moments, cards, old number → new number)."""
    kept_moments, survivors = _drop(moments, [(c.number, c) for c in cards], ids)
    numbered = [c.model_copy(update={"number": i}) for i, (_, c) in enumerate(survivors, start=1)]
    return kept_moments, numbered, {old: i for i, (old, _) in enumerate(survivors, start=1)}


def remap_sound(sound: SoundMap, renumbered: dict[int, int], moment_ids: set[str]) -> SoundMap:
    """The sound map after a revision: entries about a moment that is gone are dropped, a pre-lap follows its card to
    its new number and goes with it if the card went."""
    return sound.model_copy(update={
        "subjective": [s for s in sound.subjective if s.moment in moment_ids],
        "silences": [s for s in sound.silences if s in moment_ids],
        "music": [m for m in sound.music if m.moment in moment_ids],
        "pre_laps": [x.model_copy(update={"card": renumbered[x.card]}) for x in sound.pre_laps
                     if x.card in renumbered]})


def note_line(lens: str, note: NoteW, ident: str = "") -> str:
    """A note as one line the reviser (and a person) reads: its id first, so a disposition can name it."""
    where = f"card {note.card}" if note.card else "the scene"
    aim = f" -> {note.cell}" if note.kind == "add" and note.cell.strip() else ""
    return f"{ident + ' ' if ident else ''}[{lens}, {note.severity}, {note.kind}{aim}] {where}: {note.note.strip()}"


@dataclass
class Noted:
    """A note after merging: the critic's words with an id, so the reviser answers it by id."""

    id: str
    lens: str
    severity: str
    kind: str
    card: int
    cell: str
    note: str

    @classmethod
    def of(cls, row: dict[str, Any]) -> Noted:
        return cls(id=str(row["id"]), lens=str(row["lens"]), severity=str(row["severity"]), kind=str(row["kind"]),
                   card=int(row["card"]), cell=str(row.get("cell") or ""), note=str(row["note"]))


def check_revision(notes: list[Noted], wire: RevisionWire, revised: Revised, *, filled: set[str],
                   known: set[str], first_kinds: set[str], now_kinds: set[str]) -> list[str]:
    """Why a revision does not stand, or [] when it does (plan/2026-11-04c F5).

    Every note gets a disposition (a high one must have it), a disposition says either which operations answered the
    note or why it was declined, an `add` marked done must fill the cell it named, a `remove` marked done must remove
    the card it named, and a removed moment must be named by an operation that answers a note: a moment never leaves
    the plan without a record of which note asked for it.

    `filled` is the cells the revised plan fills, `known` every cell the scene has; `first_kinds` and `now_kinds` are
    the kinds of added moment before and after (an `add` note may name a kind instead of a cell)."""
    by_id = {n.id: n for n in notes}
    out: list[str] = []
    seen: set[str] = set()
    answered: set[int] = set()
    for d in wire.dispositions:
        note = by_id.get(d.note_id)
        if note is None:
            out.append(f"a disposition names {d.note_id!r}, which is not one of the notes")
            continue
        if d.note_id in seen:
            out.append(f"{note.id} has two dispositions")
        seen.add(d.note_id)
        if bool(d.done) == bool(d.declined.strip()):
            out.append(f"{note.id} must be either done (the operations that answered it) or declined (with a reason)")
            continue
        if d.declined.strip():
            continue
        bad = [i for i in d.done if not 1 <= i <= len(wire.operations) or not revised.applied[i - 1]]
        if bad:
            out.append(f"{note.id} is marked done by operation(s) {bad}, which do not exist or did not apply")
            continue
        answered.update(d.done)
        if note.kind == "add" and note.cell:
            fills = note.cell in filled if note.cell in known else note.cell in now_kinds - first_kinds
            if not fills:
                out.append(f"{note.id} is marked done but nothing fills {note.cell}")
        if note.kind == "remove" and note.card and note.card not in revised.gone:
            out.append(f"{note.id} is marked done but card {note.card} is still in the plan")
    out += [f"{n.id} is a high note and has no disposition" for n in notes
            if n.severity == "high" and n.id not in seen]
    out += [f"operation {n} removes {ident} and answers no note" for ident, n in sorted(revised.removals.items())
            if revised.applied[n - 1] and n not in answered]
    return out
