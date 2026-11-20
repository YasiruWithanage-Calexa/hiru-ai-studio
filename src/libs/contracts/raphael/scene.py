"""The scene as Raphael is given it (plan/2026-11-08e §3.1, phase 1), and the facts about its voices.

A port of the scene shapes the other planners keep (`SceneS`: the numbered blocks with the picture and hold time
`contracts.sceneplan.scene_items` already worked out, who is present, the place and what it has), cut down to what a
bin needs: the Veo clock over a clip's blocks, who is only heard, the listing the agent reads. It is Raphael's OWN copy,
so removing or changing another planner never touches it (`tests/raphael/test_isolation.py`). The Veo clock is the
repo's
one clock (`contracts.shotplan.shot_clock`), not a second copy.

A dialogue block's line is named `L<block index>` (the line at block 4 is L4: the id says where the line is); the map to
the dialogue line's real id is the caller's (the system's `script_of`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from contracts.sentences import sentence_breaks
from contracts.shotplan import HEARD_MARKS, LEAD_IN_S, TAIL_S, Item, shot_clock
from contracts.stagemap import SceneStaging
from contracts.take_lengths import SOFT_CAP_S
from contracts.timing import SENTENCE_PAUSE_S, speech_seconds, words_in
from contracts.veo import VEO_DURATIONS

VOICE_OVER = ("v.o", "vo)", "voice over", "voice-over", "voiceover", "narrat")
LONGEST_TAKE_S = max(VEO_DURATIONS)  # 8 s: the longest take of a production made before plan/2026-11-19
LEGACY_TAKES: list[int] = list(VEO_DURATIONS)  # 4/6/8; a newer production's are `SceneS.takes`
USUAL_HANDLE_S = 1.0  # the prompt's "about 1 s" each side


def norm(name: str) -> str:
    """A name or an object compared the way a person reads it: case and spacing do not matter."""
    return " ".join(str(name).lower().split())


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
    now: str = ""  # plan/2026-11-09: what the state ledger says changes at this block ("Anudi: phone in left hand")
    device: str = ""  # plan/2026-11-12: the thing a heard line comes out of ("phone"), from the packet
    # plan/2026-11-20 D7: a part of a long line (`contracts.sceneplan.in_parts`): k of n, the line's whole words
    part: int = 0
    parts: int = 0
    whole: str = ""

    @classmethod
    def of(cls, item: Item) -> BlockS:
        return cls(
            index=item.index,
            kind=item.kind,
            text=item.text,
            speaker=item.speaker,
            delivery=item.delivery,
            line_id=item.line_id if item.is_line else None,
            screen=item.screen,
            events=item.events,
            hold_s=item.hold_s,
            hold_kind=item.hold_kind,
            hold_who=item.hold_who,
            turn=item.turn,
            part=item.part,
            parts=item.parts,
            whole=item.whole,
        )

    @property
    def is_part(self) -> bool:
        return self.parts > 1

    def item(self) -> Item:
        return Item(
            self.index,
            self.kind,
            self.text,
            self.speaker,
            None,
            self.delivery,
            self.line_id,
            screen=self.screen,
            events=self.events,
            hold_s=self.hold_s,
            hold_kind=self.hold_kind,
            hold_who=self.hold_who,
            turn=self.turn,
            part=self.part,
            parts=self.parts,
            whole=self.whole,
        )


class PlaceS(_Model):
    name: str = ""
    objects: list[str] = []  # what the place card has: an insert may show these


class SceneS(_Model):
    blocks: list[BlockS]
    cast: list[str] = []  # the people PRESENT
    others: list[str] = []  # names (and nicknames) of the production's other people
    place: PlaceS = PlaceS()
    envelope_s: float | None = Field(None, gt=0)  # the length the script gives: the TARGET (§2.1)
    # plan/2026-11-09: the state ledger, pinned to these blocks by code (`contracts.raphael.state.attach`)
    staging: SceneStaging | None = None
    codes: dict[str, str] = {}  # a person's code in <production> -> their name (the clips' subjects use the code)
    opening_state: str = ""  # everyone and every prop at the first block
    # plan/2026-11-19: the lengths the production's takes may have (`ProductionSettings.takes`), shortest first
    takes: list[int] = Field(default_factory=lambda: list(LEGACY_TAKES), min_length=1)

    @property
    def longest(self) -> int:
        """The longest take this scene may use."""
        return max(self.takes)

    @property
    def legacy(self) -> bool:
        """True for 4/6/8: the openings and checks read as they did before plan/2026-11-19."""
        return list(self.takes) == LEGACY_TAKES

    def items(self) -> list[Item]:
        return [b.item() for b in sorted(self.blocks, key=lambda b: b.index)]

    def block(self, index: int) -> BlockS | None:
        return next((b for b in self.blocks if b.index == index), None)

    @property
    def lines(self) -> list[BlockS]:
        return [b for b in self.blocks if b.kind == "dialogue" and b.line_id]

    def line_block(self, line_id: str) -> BlockS | None:
        return next((b for b in self.lines if b.line_id == line_id), None)

    def name_of(self, ident: str) -> str:
        """A subject's id (a code from <production>, or a name) -> the person's name, "" when it is no one known."""
        if ident in self.codes:
            return self.codes[ident]
        return next((c for c in self.cast if norm(c) == norm(ident)), "")


LEDGER_FIELDS = ("staging", "codes", "opening_state")


def scene_dump(scene: SceneS) -> dict[str, Any]:
    """The scene as data for a hash: a scene with no ledger dumps exactly as it did before the ledger was added (its
    stored result is still current), a scene with one dumps its map too (a changed map plans again)."""
    data = scene.model_dump(mode="json")
    for key in LEDGER_FIELDS:
        if not data.get(key):
            data.pop(key, None)
    if data.get("takes") == LEGACY_TAKES:  # plan/2026-11-19: 4/6/8 dumps as before, other lengths plan again
        data.pop("takes", None)
    for block in data["blocks"]:
        if not block.get("now"):
            block.pop("now", None)
        for key in ("part", "parts", "whole"):  # plan/2026-11-20: a scene with no line in parts hashes as before
            if not block.get(key):
                block.pop(key, None)
    return data


@dataclass(frozen=True)
class Brief:
    """What the checks read about a scene: the scene and the length the script gives (0: none was given)."""

    scene: SceneS
    guide_s: float = 0.0


# ── the clock ────────────────────────────────────────────────────────────────────────────────────


def need_s(items: list[Item]) -> float:
    """Seconds a clip must run to show these blocks and say these lines, with breathing room (the Veo clock)."""
    return shot_clock(items)[1]


def shortest_take(need: float, takes: Any = VEO_DURATIONS) -> int | None:
    """The shortest take of `takes` (a scene's lengths) that holds `need` seconds, None when even the longest does
    not."""
    return next((t for t in sorted(takes) if t >= need - 1e-9), None)


def action_s(scene: SceneS) -> dict[int, float]:
    """Block index -> seconds each action block takes on screen (its picture and its hold), by the Veo clock."""
    return {i.index: need_s([i]) for i in scene.items() if i.kind == "action"}


def long_actions(scene: SceneS) -> dict[int, float]:
    """The action blocks longer than any take (plan/2026-11-08f §1): no one clip can show them, so consecutive clips
    each show the next part (`checks.long_action`). Block index -> seconds."""
    return {b: s for b, s in action_s(scene).items() if s > scene.longest + 1e-9}


def script_s(scene: SceneS) -> float:
    """What the script itself times at: every block on one clock, pictures, lines and their gaps (no coverage)."""
    items = scene.items()
    return need_s(items) if items else 0.0


def parts_needed(seconds: float, longest: int = LONGEST_TAKE_S) -> int:
    """How many consecutive clips of the longest take with the usual 1 s handles (8 s: 6 s of action each) it takes
    to show `seconds`."""
    per = int((longest - 2 * USUAL_HANDLE_S) * 10)
    return max(1, -(-round(seconds * 10) // per))


def line_facts(scene: SceneS) -> list[tuple[BlockS, int, float, int | None]]:
    """For each line (or part of one): (block, words, seconds to say, the shortest take that holds it alone). Worked out
    in code so the model does not do the clock in its reasoning. A part's seconds INCLUDE what comes before it on the
    clock (plan/2026-11-20 D12): the lead-in for the first part, the sentence pause for a later one."""
    out = []
    for b in scene.lines:
        words = words_in(b.text)
        said = speech_seconds(words, b.delivery, sentence_breaks(b.text))  # plan/2026-11-20 D1: its pauses
        if b.is_part:  # alone in a clip a part opens on the lead-in, whichever part it is
            before = LEAD_IN_S if b.part == 1 else SENTENCE_PAUSE_S
            out.append((b, words, said + before, shortest_take(said + LEAD_IN_S + TAIL_S, scene.takes)))
            continue
        out.append((b, words, said, shortest_take(said + LEAD_IN_S + TAIL_S, scene.takes)))
    return out


@dataclass
class PartGroup:
    """One line in parts (plan/2026-11-20 D7): its parts' short ids in order, what the WHOLE line needs on the clock,
    and whether it must be spread over clips (past `SOFT_CAP_S`, too long for one take)."""

    lids: list[str] = field(default_factory=list)
    blocks: list[int] = field(default_factory=list)
    need_s: float = 0.0
    must: bool = False


def part_groups(scene: SceneS) -> list[PartGroup]:
    """Every line the scene has in parts, in script order."""
    out: list[PartGroup] = []
    run: list[BlockS] = []
    for b in sorted(scene.lines, key=lambda x: x.index):
        if not b.is_part:
            continue
        if b.part == 1:
            run = []
        run.append(b)
        if b.part == b.parts:
            need = shot_clock([x.item() for x in run])[1]
            out.append(PartGroup([str(x.line_id) for x in run], [x.index for x in run], round(need, 2),
                                 need > SOFT_CAP_S + 1e-9))
    return out


def part_note(b: BlockS, groups: list[PartGroup]) -> str:
    """How the listing marks a part: "Part 2 of 3 of ONE line (L13 to L15, 9.5 s; too long for one take: ...)"."""
    group = next((g for g in groups if b.index in g.blocks), None)
    if group is None:
        return ""
    span = f"{group.lids[0]} to {group.lids[-1]}" if len(group.lids) > 2 else " and ".join(group.lids)
    must = (" Too long for one take: its parts go in at least two different must clips." if group.must else "")
    return (f"Part {b.part} of {b.parts} of ONE line ({span}, {group.need_s:.1f} s as one take; cut at a sentence "
            f"end, the words are the script's).{must}")


# ── voices ───────────────────────────────────────────────────────────────────────────────────────


def plain_name(speaker: str) -> str:
    """A speaker as the script writes the cue ("Father (on the phone)") → the name alone ("Father")."""
    import re

    return " ".join(re.sub(r"\(.*?\)", " ", speaker).split())


# A recording played in the scene (plan/2026-11-08f, scene 2 of the lab: "Aruni's voice message plays."): heard, never
# performed. Raphael's own marks, beside the shared ones.
RECORDED = ("voice message", "voice note", "voicemail", "voice mail", "recorded message", "recording")


def is_heard(block: BlockS) -> bool:
    """A line that is heard and not seen: a voice over, a narrator, the other end of a phone, a recording."""
    said = f"{block.delivery} {block.speaker}".lower()
    return any(m in said for m in (*HEARD_MARKS, *RECORDED))


def mark_recorded(blocks: list[BlockS]) -> list[BlockS]:
    """A line whose action just before says it is the speaker's recording ("Aruni's voice message plays.") is heard,
    not performed: its delivery says so. The script often leaves the line itself unmarked (no V.O.), and then the
    coverage check asked for lips on a person who is not there, and the scene could never finish."""
    out = list(blocks)
    ordered = sorted(range(len(out)), key=lambda i: out[i].index)
    for before, at in pairwise(ordered):
        prev, line = out[before], out[at]
        if line.kind != "dialogue" or not line.line_id or is_heard(line) or prev.kind != "action":
            continue
        text, name = prev.text.lower(), norm(plain_name(line.speaker))
        if name and name in norm(text) and any(m in text for m in RECORDED):
            out[at] = line.model_copy(update={"delivery": " ".join(p for p in (line.delivery, "voice message") if p)})
    return out


def is_voice_over(block: BlockS) -> bool:
    """A thought or a narrator: heard over the picture, said to nobody in it."""
    return any(m in f"{block.delivery} {block.speaker}".lower() for m in VOICE_OVER)


def is_thought(block: BlockS, scene: SceneS) -> bool:
    """A voice over said by a person who is on screen: they are seen, lips closed."""
    return is_voice_over(block) and block.speaker in scene.cast


def heard_names(scene: SceneS) -> list[str]:
    """People in the cast who are only a voice: they have lines, and every one is heard and not seen (a phone call)."""
    out = []
    for who in scene.cast:
        mine = [b for b in scene.lines if norm(plain_name(b.speaker)) == norm(who)]
        if mine and all(is_heard(b) for b in mine):
            out.append(who)
    return out


def listing(scene: SceneS) -> str:
    """The scene as the agent reads it: who is present, the place, then one numbered row per block. A line carries its
    id
    (`[L4]`), its speaker, how it is said, whether it is a THOUGHT (the person is seen, lips closed) or HEARD NOT SEEN
    (a
    phone, a narrator), its word count and the shortest take that holds it, worked out by code. An action that moves a
    person is marked `[move]`."""
    facts = {b.index: (w, s, t) for b, w, s, t in line_facts(scene)}
    groups = part_groups(scene)
    seconds = action_s(scene)
    head = [
        f"Present: {', '.join(scene.cast)}" if scene.cast else "",
        f"At the start: {scene.opening_state}" if scene.opening_state else "",
        f"Place: {scene.place.name}" + (f" (objects: {', '.join(scene.place.objects)})" if scene.place.objects else "")
        if scene.place.name
        else "",
    ]
    rows: list[str] = []
    for b in sorted(scene.blocks, key=lambda x: x.index):
        before = len(rows)
        if b.kind == "dialogue" and b.line_id:
            words, said, take = facts[b.index]
            how = f", {b.delivery}" if b.delivery else ""
            heard = (
                ", a thought (he or she is seen, lips closed)"
                if is_thought(b, scene)
                else ", heard not seen"
                if is_heard(b)
                else ""
            )
            held = f"shortest take {take} s" if take else "longer than any take: reported, never trimmed"
            part = f" {part_note(b, groups)}" if b.is_part else ""
            rows.append(
                f"b{b.index} line [{b.line_id}] {b.speaker}{how}{heard} ({words} words, {said:.1f} s, {held}):"
                f'{part} "{b.text}"'
            )
        elif b.kind == "action" and b.index in seconds:
            # The action's own time, worked out by code (plan/2026-11-08f §2): the model never guesses the clock.
            mark = " [move]" if b.screen == "move" else ""
            took = seconds[b.index]
            when = (
                f"{took:.1f} s on screen, longer than any take: show it over {parts_needed(took, scene.longest)} "
                "consecutive clips, each the next part"
                if took > scene.longest + 1e-9
                else f"{took:.1f} s on screen"
            )
            rows.append(f"b{b.index} action{mark} ({when}): {b.text}")
        else:
            rows.append(f"b{b.index} {b.kind}: {b.text}")
        if b.now and len(rows) > before:  # plan/2026-11-09: the state ledger's change at this block
            rows[-1] += f" | now: {b.now}"
    return "\n".join([r for r in head if r] + rows)
