"""The fidelity rule (plan/2026-11-04b §4, §6.1): Adam may elaborate the PICTURE, never invent STORY.

Every check is deterministic and names what broke, why, and what to do about it:

* a moment that invents (a new person who acts or speaks, a new line, an object that does not fit the place, a kind
  not on the allowed list, a moment that serves nothing) is `drop`ped, and the plan goes on without it;
* a plan that leaves out or repeats a script block or a line, or puts the script out of order, is `send_back`.

The words of a line are not in a moment or a card at all, only its id, so a model cannot change them; what code can
still catch is a NEW line (an id the scene does not have, a line on an added moment, a quoted sentence the script
never says).
"""
from __future__ import annotations

import itertools
import re
from dataclasses import asdict, dataclass
from typing import Any

from contracts.adam.plan import Moment, SceneScript, ShotCard, block_of, norm
from contracts.adam.tiers import (
    ALLOWED_TIERS,
    ELABORATION,
    ELABORATION_KINDS,
    INVENTION,
    NEEDS_OBJECTS,
    NEEDS_WHO,
    SCRIPT,
)

QUOTED = re.compile(r"[“\"]([^”\"]{3,})[”\"]")
MIN_QUOTED_WORDS = 2  # a quoted word or two is a label ("the 'Dad' look"); a sentence is speech


@dataclass(frozen=True)
class Break:
    code: str
    where: str  # "moment m7", "block 3", "card 4", "line L2"
    reason: str
    fix: str  # "drop" (leave this moment out) | "send_back" (the plan must be made again)
    moment: str = ""


def _words(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


def _spoken_in_script(scene: SceneScript) -> str:
    return " ".join(_words(" ".join(b.text for b in scene.blocks)))


def _in_script_or_place(scene: SceneScript, thing: str) -> bool:
    """An object fits when the script names it or the location card has it (either may be the longer phrase)."""
    want = norm(thing)
    haystacks = [norm(b.text) for b in scene.blocks] + [norm(o) for o in scene.place.objects]
    return any(want in h or (h and h in want) for h in haystacks)


def check_moments(scene: SceneScript, moments: list[Moment]) -> list[Break]:
    out: list[Break] = []
    ids = [m.id for m in moments]
    cast = {norm(c) for c in scene.cast}
    block_ids = {b.index for b in scene.blocks}
    line_ids = {b.line_id: b.index for b in scene.lines}
    script_text = _spoken_in_script(scene)
    for ident in sorted({i for i in ids if ids.count(i) > 1}):
        out.append(Break("duplicate_id", f"moment {ident}", f"two moments are called {ident!r}", "send_back", ident))
    for m in moments:
        where = f"moment {m.id}"
        if m.tier == INVENTION:
            out.append(Break("invention", where, "it is labelled invention: new story (a person, a line, an event, a "
                                                 "fact) is never allowed", "drop", m.id))
            continue
        if m.tier not in ALLOWED_TIERS:
            out.append(Break("bad_tier", where, f"tier {m.tier!r} is not script, implied or elaboration", "drop", m.id))
            continue
        refs = [(r, block_of(r)) for r in m.serves]
        unknown = [r for r, b in refs if (b is not None and b not in block_ids)
                   or (b is None and r not in ids)]
        if m.tier == SCRIPT:
            out += _script_moment(scene, m, where, line_ids, unknown)
            continue
        if not m.serves:
            out.append(Break("serves_nothing", where, "it serves no script block or moment: a moment that serves "
                                                      "nothing is decoration", "drop", m.id))
        elif unknown:
            out.append(Break("unknown_serves", where, f"it serves {', '.join(unknown)}, which the plan does not have",
                             "drop", m.id))
        if m.lines:
            out.append(Break("has_line", where, "only a script moment carries a line: an added moment may not speak "
                                                "(a line over a listener is the SCRIPT moment's, placed on the card)",
                             "drop", m.id))
        for name in m.who:
            if norm(name) not in cast:
                out.append(Break("new_person", where, f"{name!r} is not in the scene: an added moment may use only "
                                                      f"the people present ({', '.join(scene.cast) or 'none given'})",
                                 "drop", m.id))
        for thing in m.objects:
            if not _in_script_or_place(scene, thing):
                out.append(Break("new_object", where, f"{thing!r} is neither in the script nor on the location "
                                                      "card: an object must fit the place", "drop", m.id))
        if m.tier == ELABORATION:
            out += _elaboration(m, where)
        out += _quoted_speech(m, where, script_text)
    return out


def _script_moment(scene: SceneScript, m: Moment, where: str, line_ids: dict[str | None, int],
                   unknown: list[str]) -> list[Break]:
    out: list[Break] = []
    blocks = m.blocks
    if not blocks:
        out.append(Break("serves_nothing", where, "a script moment names the script blocks it presents "
                                                  "(serves: [b0, b1 ...])", "send_back", m.id))
    if unknown:
        out.append(Break("unknown_serves", where, f"it presents {', '.join(unknown)}, which the script does not have",
                         "send_back", m.id))
    for line in m.lines:
        if line not in line_ids:
            out.append(Break("unknown_line", where, f"line {line!r} is not in the script: a new line is never allowed",
                             "send_back", m.id))
        elif line_ids[line] not in blocks:
            out.append(Break("line_misplaced", where, f"line {line!r} belongs to block {line_ids[line]}, which this "
                                                      "moment does not present", "send_back", m.id))
    return out


def _elaboration(m: Moment, where: str) -> list[Break]:
    if not m.kind:
        return [Break("no_kind", where, f"an elaboration names its kind ({', '.join(ELABORATION_KINDS)})", "drop",
                      m.id)]
    if m.kind not in ELABORATION_KINDS:
        return [Break("bad_kind", where,
                      f"kind {m.kind!r} is not an allowed elaboration ({', '.join(ELABORATION_KINDS)})",
                      "drop", m.id)]
    out = []
    if m.kind in NEEDS_WHO and not m.who:
        out.append(Break("no_person", where, f"a {m.kind} is a person's: say who (one of the people present)",
                         "drop", m.id))
    if m.kind in NEEDS_OBJECTS and not m.objects:
        out.append(Break("no_object", where, f"a {m.kind} shows an object: say which", "drop", m.id))
    return out


def _quoted_speech(m: Moment, where: str, script_text: str) -> list[Break]:
    """A sentence in quotation marks that the script never says, on a moment that may not speak: a new line in
    disguise."""
    for text in (m.seen, m.heard):
        for quoted in QUOTED.findall(text):
            words = _words(quoted)
            if len(words) >= MIN_QUOTED_WORDS and " ".join(words) not in script_text:
                return [Break("invented_line", where, f"it quotes {quoted!r}, which the script never says: a new line "
                                                      "is never allowed", "drop", m.id)]
    return []


def check_script(scene: SceneScript, moments: list[Moment]) -> list[Break]:
    """Every block and every line appears once, in order, in a SCRIPT moment."""
    out: list[Break] = []
    script = [m for m in moments if m.tier == SCRIPT]
    seen: dict[int, str] = {}
    flat: list[int] = []
    for m in script:
        for b in m.blocks:
            if b in seen:
                out.append(Break("script_repeated", f"block {b}", f"moments {seen[b]} and {m.id} both present it",
                                 "send_back", m.id))
            seen.setdefault(b, m.id)
            flat.append(b)
    for blk in scene.blocks:
        if blk.index not in seen:
            out.append(Break("script_missing", f"block {blk.index}", f"no script moment presents: {blk.text[:60]!r}",
                             "send_back"))
    if any(x >= y for x, y in itertools.pairwise(flat)) and not any(b.code == "script_repeated" for b in out):
        out.append(Break("script_order", "the script moments", "they present the blocks out of script order",
                         "send_back"))
    spoken: list[str] = [ln for m in script for ln in m.lines]
    want = [b.line_id for b in scene.lines if b.line_id]
    for line in want:
        if spoken.count(line) == 0:
            out.append(Break("line_missing", f"line {line}", "no script moment carries it", "send_back"))
        elif spoken.count(line) > 1:
            out.append(Break("line_repeated", f"line {line}", "more than one script moment carries it", "send_back"))
    known = [ln for ln in spoken if ln in want]
    if len(set(known)) == len(known) == len(want) and known != want:
        out.append(Break("line_order", "the lines", "the script moments carry the lines out of script order",
                         "send_back"))
    return out


def check_cards(scene: SceneScript, moments: list[Moment], cards: list[ShotCard]) -> list[Break]:
    """The cards use every SCRIPT moment once, in order, and bind each line to the card that shows its moment."""
    out: list[Break] = []
    order = {m.id: i for i, m in enumerate(moments)}
    by_id = {m.id: m for m in moments}
    placed: dict[str, int] = {}
    flat: list[int] = []
    for card in cards:
        for ident in card.moments:
            where = f"card {card.number}"
            if ident not in by_id:
                out.append(Break("unknown_moment", where, f"it uses moment {ident!r}, which the plan does not have",
                                 "send_back", ident))
                continue
            if ident in placed:
                out.append(Break("moment_repeated", where, f"moment {ident} is already in card {placed[ident]}",
                                 "send_back", ident))
                continue
            placed[ident] = card.number
            flat.append(order[ident])
    for m in moments:
        if m.tier == SCRIPT and m.id not in placed:
            out.append(Break("moment_missing", f"moment {m.id}", "a script moment is in no card", "send_back", m.id))
    if any(x >= y for x, y in itertools.pairwise(flat)):
        out.append(Break("moment_order", "the cards", "they put the moments in a different order from the plan",
                         "send_back"))
    line_card: dict[str, int] = {}
    bound: list[str] = []
    for card in cards:
        for cl in card.lines:
            where = f"card {card.number}"
            if cl.line_id not in {b.line_id for b in scene.lines}:
                out.append(Break("unknown_line", where, f"line {cl.line_id!r} is not in the script: a new line is "
                                                        "never allowed", "send_back"))
                continue
            if cl.line_id in line_card:
                out.append(Break("line_repeated", where,
                                 f"line {cl.line_id} is also in card {line_card[cl.line_id]}: a "
                                                         "line never spans two takes", "send_back"))
                continue
            line_card[cl.line_id] = card.number
            bound.append(cl.line_id)
            carrier = next((m for m in moments if m.tier == SCRIPT and cl.line_id in m.lines), None)
            if carrier is not None and carrier.id not in card.moments:
                out.append(Break("line_misplaced", where, f"line {cl.line_id} belongs to moment {carrier.id}, which "
                                                          "this card does not show", "send_back", carrier.id))
    for b in scene.lines:
        if b.line_id not in line_card:
            out.append(Break("line_missing", f"line {b.line_id}", "no card binds it", "send_back"))
    want = [b.line_id for b in scene.lines]
    if len(bound) == len(want) and set(bound) == set(want) and bound != want:
        out.append(Break("line_order", "the cards", "they bind the lines out of script order", "send_back"))
    return out


def check(scene: SceneScript, moments: list[Moment], cards: list[ShotCard] | None = None) -> dict[str, Any]:
    breaks = check_moments(scene, moments) + check_script(scene, moments)
    if cards is not None:
        breaks += check_cards(scene, moments, cards)
    dropped = sorted({b.moment for b in breaks if b.fix == "drop" and b.moment})
    send_back = [b for b in breaks if b.fix == "send_back"]
    return {
        "ok": not breaks,
        "breaks": [asdict(b) for b in breaks],
        "dropped": dropped,
        "kept": [m.model_dump(mode="json") for m in moments if m.id not in dropped],
        "send_back": bool(send_back),
        "counts": {"moments": len(moments), "script": sum(m.tier == SCRIPT for m in moments),
                   "implied": sum(m.tier == "implied" for m in moments),
                   "elaboration": sum(m.tier == ELABORATION for m in moments),
                   "dropped": len(dropped), "breaks": len(breaks)},
    }
