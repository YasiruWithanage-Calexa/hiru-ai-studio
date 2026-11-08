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

from dataclasses import dataclass
from itertools import pairwise

from pydantic import BaseModel, ConfigDict, Field

from contracts.shotplan import HEARD_MARKS, LEAD_IN_S, TAIL_S, Item, shot_clock
from contracts.timing import speech_seconds, words_in
from contracts.veo import VEO_DURATIONS

VOICE_OVER = ("v.o", "vo)", "voice over", "voice-over", "voiceover", "narrat")
LONGEST_TAKE_S = max(VEO_DURATIONS)  # 8 s: no single Veo take is longer
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
        )

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

    def items(self) -> list[Item]:
        return [b.item() for b in sorted(self.blocks, key=lambda b: b.index)]

    def block(self, index: int) -> BlockS | None:
        return next((b for b in self.blocks if b.index == index), None)

    @property
    def lines(self) -> list[BlockS]:
        return [b for b in self.blocks if b.kind == "dialogue" and b.line_id]

    def line_block(self, line_id: str) -> BlockS | None:
        return next((b for b in self.lines if b.line_id == line_id), None)


@dataclass(frozen=True)
class Brief:
    """What the checks read about a scene: the scene and the length the script gives (0: none was given)."""

    scene: SceneS
    guide_s: float = 0.0


# ── the clock ────────────────────────────────────────────────────────────────────────────────────


def need_s(items: list[Item]) -> float:
    """Seconds a clip must run to show these blocks and say these lines, with breathing room (the Veo clock)."""
    return shot_clock(items)[1]


def shortest_take(need: float) -> int | None:
    """The shortest Veo take that holds `need` seconds, None when even the longest does not."""
    return next((t for t in sorted(VEO_DURATIONS) if t >= need - 1e-9), None)


def action_s(scene: SceneS) -> dict[int, float]:
    """Block index -> seconds each action block takes on screen (its picture and its hold), by the Veo clock."""
    return {i.index: need_s([i]) for i in scene.items() if i.kind == "action"}


def long_actions(scene: SceneS) -> dict[int, float]:
    """The action blocks longer than any take (plan/2026-11-08f §1): no one clip can show them, so consecutive clips
    each show the next part (`checks.long_action`). Block index -> seconds."""
    return {b: s for b, s in action_s(scene).items() if s > LONGEST_TAKE_S + 1e-9}


def script_s(scene: SceneS) -> float:
    """What the script itself times at: every block on one clock, pictures, lines and their gaps (no coverage)."""
    items = scene.items()
    return need_s(items) if items else 0.0


def parts_needed(seconds: float) -> int:
    """How many consecutive 8 s clips with the usual 1 s handles (6 s of action each) it takes to show `seconds`."""
    per = int((LONGEST_TAKE_S - 2 * USUAL_HANDLE_S) * 10)
    return max(1, -(-round(seconds * 10) // per))


def line_facts(scene: SceneS) -> list[tuple[BlockS, int, float, int | None]]:
    """For each line: (block, words, seconds to say, the shortest take that holds it alone). Worked out in code so the
    model does not do the clock in its reasoning."""
    out = []
    for b in scene.lines:
        words = words_in(b.text)
        said = speech_seconds(words, b.delivery)
        out.append((b, words, said, shortest_take(said + LEAD_IN_S + TAIL_S)))
    return out


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
    seconds = action_s(scene)
    head = [
        f"Present: {', '.join(scene.cast)}" if scene.cast else "",
        f"Place: {scene.place.name}" + (f" (objects: {', '.join(scene.place.objects)})" if scene.place.objects else "")
        if scene.place.name
        else "",
    ]
    rows = []
    for b in sorted(scene.blocks, key=lambda x: x.index):
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
            rows.append(
                f"b{b.index} line [{b.line_id}] {b.speaker}{how}{heard} ({words} words, {said:.1f} s, {held}): "
                f'"{b.text}"'
            )
        elif b.kind == "action" and b.index in seconds:
            # The action's own time, worked out by code (plan/2026-11-08f §2): the model never guesses the clock.
            mark = " [move]" if b.screen == "move" else ""
            took = seconds[b.index]
            when = (
                f"{took:.1f} s on screen, longer than any take: show it over {parts_needed(took)} consecutive "
                "clips, each the next part"
                if took > LONGEST_TAKE_S + 1e-9
                else f"{took:.1f} s on screen"
            )
            rows.append(f"b{b.index} action{mark} ({when}): {b.text}")
        else:
            rows.append(f"b{b.index} {b.kind}: {b.text}")
    return "\n".join([r for r in head if r] + rows)
