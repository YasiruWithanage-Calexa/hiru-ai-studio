"""The scene as Jonathan is given it (plan/2026-11-05e §5), and the Veo clock over a Jonathan shot.

`SceneS` is the scene's numbered blocks (with the picture and hold time `contracts.sceneplan.scene_items` already
worked out), who is present, the place and what it has. Each of Jonathan's steps takes it as JSON and turns it back into
the kernel's `Item`s, so the Veo clock is the repo's one clock (`contracts.shotplan.shot_clock`), not a second copy.

A dialogue block's line is named `L<block index>` (the line at block 4 is L4: the id says where the line is); the map to
the dialogue line's real id is the caller's (`scene.script_of` in the system).
"""
from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field

from contracts.jonathan.plan import norm
from contracts.jonathan.wire import JonathanWire, ShotW, renumber
from contracts.shotplan import HEARD_MARKS, LEAD_IN_S, TAIL_S, Item, shot_clock
from contracts.stagemap import people_in
from contracts.timing import speech_seconds, words_in
from contracts.veo import VEO_DURATIONS

# Sinhala the model echoed into free text (the DoP's `strip_spoken` uses the same pattern)
SINHALA_RUN = re.compile(r"[඀-෿‌‍]+(?:[\s,.!?'\"“”‘’]*[඀-෿‌‍]+)*")


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BlockS(_Model):
    index: int = Field(ge=0)
    kind: str = "action"
    text: str = ""
    speaker: str = ""
    line_id: str | None = None  # the short id (L4) of a dialogue block
    delivery: str = ""
    screen: str = "act"  # actions: a contracts.timing.SCREEN_SECONDS key
    events: int = 1
    hold_s: float = 0.0  # the reading's breath after the block
    hold_kind: str = ""
    hold_who: str = ""
    turn: bool = False

    @classmethod
    def of(cls, item: Item) -> BlockS:
        return cls(index=item.index, kind=item.kind, text=item.text, speaker=item.speaker, delivery=item.delivery,
                   line_id=item.line_id if item.is_line else None, screen=item.screen, events=item.events,
                   hold_s=item.hold_s, hold_kind=item.hold_kind, hold_who=item.hold_who, turn=item.turn)

    def item(self) -> Item:
        return Item(self.index, self.kind, self.text, self.speaker, None, self.delivery, self.line_id,
                    screen=self.screen, events=self.events, hold_s=self.hold_s, hold_kind=self.hold_kind,
                    hold_who=self.hold_who, turn=self.turn)


class PlaceS(_Model):
    name: str = ""
    objects: list[str] = []  # what the place card has: an insert may show these


class SceneS(_Model):
    blocks: list[BlockS]
    cast: list[str] = []  # the people PRESENT
    others: list[str] = []  # names (and nicknames) of the production's other people: free text must not name them
    place: PlaceS = PlaceS()
    envelope_s: float | None = Field(None, gt=0)

    def items(self) -> list[Item]:
        return [b.item() for b in sorted(self.blocks, key=lambda b: b.index)]

    def block(self, index: int) -> BlockS | None:
        return next((b for b in self.blocks if b.index == index), None)

    @property
    def lines(self) -> list[BlockS]:
        return [b for b in self.blocks if b.kind == "dialogue" and b.line_id]

    def line_block(self, line_id: str) -> BlockS | None:
        return next((b for b in self.lines if b.line_id == line_id), None)

    def fits(self, thing: str) -> bool:
        """An object fits the place when the script names it or the place card has it (either may be the longer
        phrase)."""
        want = norm(thing)
        hay = [norm(b.text) for b in self.blocks] + [norm(o) for o in self.place.objects]
        return bool(want) and any(want in h or (h and h in want) for h in hay)


# ── the clock over a Jonathan shot ──────────────────────────────────────────────────────────────────


def items_of(scene: SceneS, shot: ShotW) -> list[Item]:
    """The kernel items a shot plays: the blocks it shows, in script order."""
    wanted = set(shot.blocks)
    return [i for i in scene.items() if i.index in wanted]


def need_s(items: list[Item]) -> float:
    """Seconds a shot must run to show these blocks and say these lines, with breathing room (the Veo clock)."""
    return shot_clock(items)[1]


def shortest_take(need: float) -> int | None:
    """The shortest Veo take that holds `need` seconds, None when even the longest does not."""
    return next((t for t in sorted(VEO_DURATIONS) if t >= need - 1e-9), None)


def line_facts(scene: SceneS) -> list[tuple[BlockS, int, float, int | None]]:
    """For each line: (block, words, seconds to say, the shortest take that holds it alone). Computed in code so the
    model does not work the clock out in its reasoning (plan §5, context pack)."""
    out = []
    for b in scene.lines:
        words = words_in(b.text)
        said = speech_seconds(words, b.delivery)
        out.append((b, words, said, shortest_take(said + LEAD_IN_S + TAIL_S)))
    return out


def split_items(items: list[Item], longest: int) -> list[list[Item]]:
    """Groups of consecutive items that each fit `longest` seconds, cut at a block boundary and never inside a line
    (the rule of `contracts.shotplan.split_to_fit`: an action that plays under the line after it stays with that
    line). One group when nothing can be cut."""
    groups: list[list[Item]] = []
    group: list[Item] = []
    for item in items:
        timed = any(g.is_line or g.picture_s > 0 for g in group)
        if timed and need_s([*group, item]) > longest:
            last = group[-1]
            if item.is_line and last.kind == "action" and last.screen == "with_line" and len(group) > 1:
                groups.append(group[:-1])
                group = [last]
            else:
                groups.append(group)
                group = []
        group.append(item)
    if group:
        groups.append(group)
    return groups


def speech_in(text: str, lines: list[BlockS]) -> bool:
    """Free text that holds Sinhala, or the words of a line (two words or more)."""
    if SINHALA_RUN.search(text):
        return True
    flat = norm(text)
    return any(len(norm(b.text).split()) >= 2 and norm(b.text) in flat for b in lines)


def strip_speech(text: str, lines: list[BlockS]) -> str:
    """The text without Sinhala and without a line's words (quotes left empty by it go too)."""
    out = SINHALA_RUN.sub(" ", text)
    for b in lines:
        if len(norm(b.text).split()) >= 2:
            out = re.sub(re.escape(b.text.strip()), " ", out, flags=re.IGNORECASE)
    out = re.sub(r"[\"“”']\s*[\"“”']", " ", out)
    return " ".join(out.split())


def heard_only(scene: SceneS) -> list[str]:
    """People who are heard and never seen: every line of theirs is marked (on the phone, off screen, voice over) and
    no action block names them (`stagemap.people_in`)."""
    items = scene.items()
    seen = set(people_in([i for i in items if not i.is_line], scene.cast, holds=False))
    voices: dict[str, list[bool]] = {}
    for b in scene.lines:
        marked = any(m in f"{b.delivery} {b.speaker}".lower() for m in HEARD_MARKS)
        voices.setdefault(plain_name(b.speaker), []).append(marked)
    return [who for who, marks in voices.items() if marks and all(marks) and who.casefold() not in seen]


def plain_name(speaker: str) -> str:
    """A speaker as the script writes the cue ("Father (on the phone)") → the name alone ("Father")."""
    return " ".join(re.sub(r"\(.*?\)", " ", speaker).split())



def clean(scene: SceneS, plan: JonathanWire) -> JonathanWire:
    """A model's plan with every reference the scene lacks taken out, entry by entry, and nothing else judged: a shot
    loses a block or a line the scene does not have, an addition for a shot that is not there goes, a staging mark for a
    person not present, a spot the map lacks or a block the scene lacks is dropped. Both of Jonathan's agents finish
    their answer with it."""
    blocks = {b.index for b in scene.blocks}
    lines = {b.line_id for b in scene.lines}
    cast = {norm(c) for c in scene.cast}
    shots = [s.model_copy(update={"blocks": [b for b in s.blocks if b in blocks],
                                  "lines": [ln for ln in s.lines if ln in lines]}) for s in plan.shots]
    numbered = renumber(shots, plan.added)
    zones = {z.strip().casefold() for z in plan.staging.zones}
    marks = [m for m in plan.staging.marks if norm(m.who) in cast and m.block in blocks
             and (m.zone.strip().casefold() in zones or m.zone.strip().casefold() == "off")]
    staging = plan.staging.model_copy(update={"marks": marks})
    return plan.model_copy(update={**numbered, "staging": staging}).respanned()


def is_heard(block: BlockS) -> bool:
    """A line that is heard and not seen: a voice over, a narrator, the other end of a phone."""
    return any(m in f"{block.delivery} {block.speaker}".lower() for m in HEARD_MARKS)


VOICE_OVER = ("v.o", "vo)", "voice over", "voice-over", "voiceover", "narrat")


def is_voice_over(block: BlockS) -> bool:
    """A thought or a narrator: heard over the picture, said to nobody in it."""
    return any(m in f"{block.delivery} {block.speaker}".lower() for m in VOICE_OVER)


def is_thought(block: BlockS, scene: SceneS) -> bool:
    """A voice over said by a person who is on screen: they are seen, lips closed."""
    return is_voice_over(block) and block.speaker in scene.cast


def heard_names(scene: SceneS) -> list[str]:
    """People in the cast who are only a voice: they have lines, and every one is heard and not seen (a phone call).
    Unlike `heard_only`, a script that names them in an action ("It is her father") does not put them in the picture."""
    out = []
    for who in scene.cast:
        mine = [b for b in scene.lines if norm(plain_name(b.speaker)) == norm(who)]
        if mine and all(is_heard(b) for b in mine):
            out.append(who)
    return out


def listing(scene: SceneS) -> str:
    """The scene as the author reads it (the cinematic lab's listing): who is present, the place, then one numbered
    row per block. A line carries its id (`[L4]`), its speaker, how it is said, whether it is a THOUGHT (the person is
    seen, lips closed) or HEARD NOT SEEN (a phone, a narrator), its word count and the shortest take that holds it,
    worked out by code. An action that moves a person is marked `[move]`: the only blocks across which a person may
    change place (the staging check's rule)."""
    facts = {b.index: (w, s, t) for b, w, s, t in line_facts(scene)}
    head = [f"Present: {', '.join(scene.cast)}" if scene.cast else "",
            f"Place: {scene.place.name}" + (f" (objects: {', '.join(scene.place.objects)})" if scene.place.objects
                                           else "") if scene.place.name else ""]
    rows = []
    for b in sorted(scene.blocks, key=lambda x: x.index):
        if b.kind == "dialogue" and b.line_id:
            words, said, take = facts[b.index]
            how = f", {b.delivery}" if b.delivery else ""
            heard = (", a thought (he or she is seen, lips closed)" if is_thought(b, scene)
                     else ", heard not seen" if is_heard(b) else "")
            held = f"shortest take {take} s" if take else "longer than any take: reported, never trimmed"
            rows.append(f'b{b.index} line [{b.line_id}] {b.speaker}{how}{heard} ({words} words, {said:.1f} s, {held}): '
                        f'"{b.text}"')
        else:
            mark = " [move]" if b.kind == "action" and b.screen == "move" else ""
            rows.append(f"b{b.index} {b.kind}{mark}: {b.text}")
    return "\n".join([r for r in head if r] + rows)
