"""The code that judges a bin (plan/2026-11-08e §3.3, §3.5, phase 2). No model, no network.

    check_stage1(brief, bin, allowed)         [Fault]   coverage, length (1.5x), clock, feasibility, designs,
    consistency, and the state ledger (plan/2026-11-09: hands, handovers, posture, condition, presence, place; report)
    check_stage2(brief, bin, allowed, cap)    [Fault]   every stage 1 check on the whole bin (length: the chosen cap)
    plus
                                                        the cinematic checks of §3.5
    review_faults(bin, review)                [str]     the moment review must match the bin
    missing_blend_notes(bin, notes)           [str]     a cinematic clip no blend note names

DaVinci's checks (`lab/davinci/checks.py`), PORTED not imported (R3), with the person's changes of 2026-11-08: the
screen-text rule is out (a phone close-up is welcome), the length cap is a parameter (the person's choice, §2.1), and a
fault has two owners only: `code` (reported, nothing to do) and `raphael` (everything else).

A fault with `fix == "report"` is told and does not stop `finish`; every other fault blocks it. An overrun (a line
longer
than its take) is reported, never trimmed.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterator
from typing import Literal

from pydantic import BaseModel

from contracts import holding as hd
from contracts import stagemap as sm
from contracts.raphael.bin import Bin
from contracts.raphael.scene import (
    LONGEST_TAKE_S,
    Brief,
    SceneS,
    heard_names,
    is_heard,
    is_voice_over,
    long_actions,
    need_s,
    norm,
    parts_needed,
    plain_name,
    script_s,
)
from contracts.raphael.wire import (
    AERIAL,
    BLENDS,
    NO_DIALOGUE,
    STAGE1_CAP,
    TECHNIQUES,
    TRANSITION,
    Clip,
    ReviewRow,
)
from contracts.shotplan import Item

Owner = Literal["raphael", "code"]
HANDLE_MAX_S = 2.0  # a handle is about a second; more than two seconds is a take spent on nothing
ACTION_MIN_S = 1.5  # the least a clip must show of an action, between its handles
BARE_MIN_S = 1.0  # an establishing, atmosphere or transition clip needs a second of picture between its handles
PER_MOMENT_MAX = 3  # S3: at most 3 cinematic clips a moment (blocking)

# Someone SPEAKS: said in an action field, where only a line may be spoken. Not "answers" (answering a phone is an act).
SPEAKS = re.compile(
    r"\b(speaks?|speaking|says?|saying|asks?|replies|replying|shouts?|whispers?|talks?|tells?|murmurs?|"
    r"calls? out)\b",
    re.IGNORECASE,
)
# Techniques Veo cannot do, refused in any text of a clip. The post-only ones are named in editor_notes instead.
REFUSED = (
    (
        "a dolly zoom",
        r"\b(dolly[- ]zoom|vertigo (effect|shot)|zolly|contra[- ]?zoom)\b",
        "Veo cannot hold it steady. Use a slow creep or a push-in for the same pull.",
    ),
    ("a split diopter", r"\bsplit[- ]diopter\b", "Veo cannot split the focus. Use a rack focus or a foreground layer."),
    (
        "a post technique",
        r"\b(speed[- ]ramp|freeze[- ]?frame|punch[- ]in|split[- ]screen)\b",
        "It is made in the edit: shoot a clean source and name the technique in editor_notes.",
    ),
)
# What Veo does badly, and the known way round it (reported, not repaired). The screen-text rule is NOT here: the person
# (2026-11-08) struck it for Raphael, because a phone close-up is welcome (S6 is the other planners').
FEASIBILITY: tuple[tuple[str, str, str], ...] = (
    ("a mirror", r"\b(mirror|reflection)\b", "Veo breaks reflections: shoot the person, not the glass."),
    (
        "fast hands",
        r"\b(typing|texting|rapid(?:ly)?|dialling|dialing|shuffl\w+|juggl\w+|knitting|sewing)\b",
        "fast finger work blurs: hold on the face, or show the hands still on the object.",
    ),
    (
        "touching",
        r"\b(hug\w*|embrac\w+|kiss\w*|holds? hands|holding hands)\b",
        "bodies in contact merge: keep a hand's width apart, or cut away at the moment of contact.",
    ),
    (
        "a crowd",
        r"\b(crowd|dozens|hundreds|packed with people|mob)\b",
        "Veo invents the crowd's faces: frame a few people near, the rest soft and far.",
    ),
)
FAMILY = {
    "whip_out": "whip",
    "whip_in": "whip",
    "focus_out": "focus",
    "focus_in": "focus",
    "match_cut": "match",
    "object_wipe": "wipe",
}
OUT_ROLE, IN_ROLE = TRANSITION


class Fault(BaseModel):
    code: str
    sentence: str
    clips: list[str] = []
    owner: Owner = "raphael"
    fix: Literal["repair", "report"] = "repair"
    key: str = ""

    def line(self) -> str:
        who = f" [{', '.join(self.clips)}]" if self.clips else ""
        return f"({self.owner}, {self.fix}) {self.code}{who}: {self.sentence}"


def _fault(
    code: str,
    sentence: str,
    clips: list[str] | None = None,
    *,
    fix: Literal["repair", "report"] = "repair",
    key: str = "",
    owner: Owner = "raphael",
) -> Fault:
    return Fault(
        code=code,
        sentence=sentence,
        clips=clips or [],
        owner=owner,
        fix=fix,
        key=key or f"{code}:{','.join(clips or [])}:{sentence[:40]}",
    )


def blocking(found: list[Fault]) -> list[Fault]:
    """The faults `finish` refuses to pass: everything but a report."""
    return [f for f in found if f.fix != "report"]


def mentions(text: str, name: str) -> bool:
    """`name` appears in `text` as a whole word, ignoring case."""
    return bool(name.strip()) and re.search(rf"(?<!\w){re.escape(name.strip())}(?!\w)", text, re.IGNORECASE) is not None


def strings_of(value: object) -> list[str]:
    """Every string in a nested value (the free text of an IR)."""
    return list(_strings(value))


def _strings(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


def limit_s(brief: Brief, cap: float = STAGE1_CAP) -> float:
    """The most seconds of takes the bin may hold: the scene's given length x `cap`. 0: no length was given."""
    return brief.guide_s * cap


def clip_text(clip: Clip) -> list[str]:
    """Everything written in words for a clip (design, sound, reason and note)."""
    sound = [clip.sound.ambience, clip.sound.effects, clip.sound.music] if clip.sound else []
    return [*strings_of(clip.ir or {}), *sound, clip.why, clip.editor_note, clip.angle, clip.lens]


def _items(scene: SceneS, clip: Clip) -> list[Item]:
    """The kernel items the clip plays: its blocks in script order, a line only if the clip carries it."""
    keep = set(clip.blocks)
    return [i for i in scene.items() if i.index in keep and (not i.is_line or i.line_id in clip.lines)]


# ── the edit plan ────────────────────────────────────────────────────────────────────────────────


def edit_plan(scene: SceneS, work: Bin) -> list[Fault]:
    plan = work.edit
    if plan is None:
        return [
            _fault(
                "edit", "There is no edit plan yet: write the intended cut first (write_edit_plan).", key="edit:none"
            )
        ]
    out: list[Fault] = []
    everything = {b.index for b in scene.blocks}
    owners: dict[int, list[int]] = {}
    for m in plan.moments:
        for b in m.blocks:
            owners.setdefault(b, []).append(m.n)
    for b in sorted(everything - set(owners)):
        out.append(_fault("edit", f"Block b{b} is in no moment of the edit plan.", key=f"edit:missing:{b}"))
    for b, ms in sorted(owners.items()):
        if b not in everything:
            out.append(
                _fault(
                    "edit", f"Moment {ms[0]} names block b{b}, which the script does not have.", key=f"edit:unknown:{b}"
                )
            )
        elif len(ms) > 1:
            out.append(
                _fault("edit", f"Block b{b} is in moments {ms}: a block belongs to ONE moment.", key=f"edit:twice:{b}")
            )
    numbers = [m.n for m in plan.moments]
    if len(set(numbers)) != len(numbers):
        out.append(_fault("edit", "Two moments have the same number.", key="edit:duplicate"))
    known = {s.id for s in plan.sequences}
    for m in plan.moments:
        if m.sequence not in known:
            out.append(
                _fault(
                    "edit",
                    f'Moment {m.n} is in sequence "{m.sequence}", which does not exist.',
                    key=f"edit:sequence:{m.n}",
                )
            )
    return out


# ── coverage ─────────────────────────────────────────────────────────────────────────────────────


def coverage(scene: SceneS, work: Bin) -> list[Fault]:
    out: list[Fault] = []
    everything = {b.index for b in scene.blocks}
    moments = {m.n for m in work.edit.moments} if work.edit else set()
    lines = {b.line_id: b for b in scene.lines if b.line_id}
    must = [c for c in work.clips if c.priority == "must"]
    for c in work.clips:
        if moments and c.moment not in moments:
            out.append(
                _fault(
                    "coverage",
                    f"{c.id} covers moment {c.moment}, which the edit plan does not have.",
                    [c.id],
                    key=f"coverage:moment:{c.id}",
                )
            )
        for b in c.blocks:
            if b not in everything:
                out.append(
                    _fault(
                        "coverage",
                        f"{c.id} covers block b{b}, which the script does not have.",
                        [c.id],
                        key=f"coverage:block:{c.id}:{b}",
                    )
                )
        for lid in c.lines:
            block = lines.get(lid)
            if block is None:
                out.append(
                    _fault(
                        "coverage",
                        f"{c.id} carries line {lid}, which the script does not have.",
                        [c.id],
                        key=f"coverage:line:{c.id}:{lid}",
                    )
                )
            elif block.index not in c.blocks:
                out.append(
                    _fault(
                        "coverage",
                        f"{c.id} carries line {lid} but does not cover its block b{block.index}.",
                        [c.id],
                        key=f"coverage:lineblock:{c.id}:{lid}",
                    )
                )
        if c.speaks and not c.lines:
            out.append(
                _fault(
                    "coverage",
                    f"{c.id} is marked as speaking but carries no line.",
                    [c.id],
                    key=f"coverage:speaks:{c.id}",
                )
            )
    for b in sorted(everything):
        if not any(b in c.blocks for c in must):
            out.append(
                _fault(
                    "coverage",
                    f"Block b{b} has no must clip: the intended cut has nothing to show for it.",
                    key=f"coverage:must:{b}",
                )
            )
    for n in sorted(moments):
        if not any(c.moment == n for c in must):
            out.append(_fault("coverage", f"Moment {n} has no must clip.", key=f"coverage:moment_must:{n}"))
    for lid, block in lines.items():
        carriers = [c for c in work.clips if lid in c.lines]
        heard = is_heard(block) or is_voice_over(block)  # heard not seen, or a thought with the lips closed
        if not any(c.priority == "must" for c in carriers):
            out.append(_fault("coverage", f"Line {lid} is carried by no must clip.", key=f"coverage:carrier:{lid}"))
        elif heard and any(c.speaks for c in carriers):
            out.append(
                _fault(
                    "coverage",
                    f"Line {lid} is heard and not seen (a voice over, a thought or the other end of a "
                    "call): no clip may show lips speaking it.",
                    [c.id for c in carriers if c.speaks],
                    key=f"coverage:heard:{lid}",
                )
            )
        elif not heard and not any(c.speaks for c in carriers if c.priority == "must"):
            out.append(
                _fault(
                    "coverage",
                    f"Line {lid} is performed by no must clip (D2: the master and the speaker's single speak).",
                    [c.id for c in carriers],
                    key=f"coverage:performer:{lid}",
                )
            )
    outs = [c for c in work.clips if c.role == OUT_ROLE]
    ins = [c for c in work.clips if c.role == IN_ROLE]
    for fam in sorted({FAMILY.get(c.technique, "") for c in [*outs, *ins]} - {""}):
        a = [c for c in outs if FAMILY.get(c.technique) == fam]
        z = [c for c in ins if FAMILY.get(c.technique) == fam]
        if len(a) != len(z):
            out.append(
                _fault(
                    "coverage",
                    f"The {fam} transition has {len(a)} out clip(s) and {len(z)} in clip(s): both "
                    "halves of a pair are planned.",
                    [c.id for c in [*a, *z]],
                    key=f"coverage:pair:{fam}",
                )
            )
    return out


# ── length ───────────────────────────────────────────────────────────────────────────────────────


def length(brief: Brief, work: Bin, cap: float = STAGE1_CAP, *, key: str = "length:over") -> list[Fault]:
    """The bin's takes add up to at most the given length x `cap`. Over it, `nice` clips go first, then `should`; a
    `must`
    clip is never the one to go."""
    limit = limit_s(brief, cap)
    total = sum(c.take_s for c in work.clips)
    if not limit or total <= limit + 1e-9:
        return []
    by = {p: sum(c.take_s for c in work.clips if c.priority == p) for p in ("must", "should", "nice")}
    return [
        _fault(
            "length",
            f"The bin holds {total} s of takes and may hold {limit:g} s (the scene's {brief.guide_s:g} s x "
            f"{cap:g}): {by['must']} s must, {by['should']} s should, {by['nice']} s nice. Drop nice clips first, "
            "then should; the must clips are never the ones to go.",
            [c.id for c in work.extras()],
            key=key,
        )
    ]


# ── clock ────────────────────────────────────────────────────────────────────────────────────────


def _fits(c: Clip, take: int, need: float, spoken: bool) -> bool:
    """Do the clip's handles and what it shows fit a take of `take` seconds?"""
    if spoken:  # the clock's 0.5 s lead-in and 0.5 s tail are silent time: they count as part of the handles
        return c.handle_in_s + c.handle_out_s + max(need - 1.0, 0.0) <= take + 1e-9
    window = ACTION_MIN_S if c.blocks and need else BARE_MIN_S
    return take - c.handle_in_s - c.handle_out_s >= max(window, need if c.blocks else 0.0) - 1e-9


def _split(scene: SceneS, c: Clip, long: dict[int, float]) -> tuple[list[Item], list[int]]:
    """The clip's items that must play WHOLE in it, and the long actions (longer than any take) it shows a PART of."""
    items = _items(scene, c)
    return [i for i in items if i.index not in long], [i.index for i in items if i.index in long]


def part_s(scene: SceneS, c: Clip, long: dict[int, float]) -> float:
    """Seconds of its long action(s) a clip shows: the room between its handles once what plays whole in it is
    played."""
    whole, parts = _split(scene, c, long)
    if not parts:
        return 0.0
    rest = need_s(whole) if whole else 0.0
    return max(c.take_s - c.handle_in_s - c.handle_out_s - rest, 0.0) / len(parts)


def clock(scene: SceneS, work: Bin) -> list[Fault]:
    """4 / 6 / 8 s takes (the schema holds them), handles that fit, a line kept whole. Reports an overrun, never
    trims.

    An action longer than any take (plan/2026-11-08f §1) cannot play whole in one clip: a clip over it shows a PART,
    at least `ACTION_MIN_S` of it, and `long_action` checks that the must clips over it add up to the whole."""
    out: list[Fault] = []
    long = long_actions(scene)
    for c in work.clips:
        for name, h in (("in", c.handle_in_s), ("out", c.handle_out_s)):
            if not 0 <= h <= HANDLE_MAX_S:
                out.append(
                    _fault(
                        "clock",
                        f"{c.id}'s handle {name} is {h:g} s: a handle is 0 to {HANDLE_MAX_S:g} s.",
                        [c.id],
                        key=f"clock:handle:{c.id}:{name}",
                    )
                )
        items, parts = _split(scene, c, long)
        spoken = [i for i in items if i.is_line]
        need = need_s(items) if items else 0.0
        if parts:
            # The part of the long action(s) is the least this clip shows of each; the rest plays whole as before.
            need += ACTION_MIN_S * len(parts)
            room = c.take_s - c.handle_in_s - c.handle_out_s
            if room + 1e-9 < need:
                names = ", ".join(f"b{b}" for b in parts)
                out.append(
                    _fault(
                        "clock",
                        f"{c.id}: between its handles ({c.handle_in_s:g} s + {c.handle_out_s:g} s) a {c.take_s} s "
                        f"take has {room:g} s, and it needs {need:.1f} s: what plays whole in it plus at least "
                        f"{ACTION_MIN_S:g} s of {names}. Take a longer take, shorter handles or fewer blocks.",
                        [c.id],
                        key=f"clock:fit:{c.id}",
                    )
                )
            continue
        if spoken and need > c.take_s + 1e-9:
            out.append(
                _fault(
                    "clock",
                    f"{c.id} needs {need:.1f} s for what it carries and the take is {c.take_s} s: a line "
                    "is kept whole and never trimmed. Split the exchange into overlapping clips.",
                    [c.id],
                    fix="report",
                    key=f"clock:overrun:{c.id}",
                )
            )
            continue
        if not _fits(c, c.take_s, need, bool(spoken)):
            out.append(
                _fault(
                    "clock",
                    f"{c.id}: its handles ({c.handle_in_s:g} s + {c.handle_out_s:g} s) and what it shows "
                    f"({need:.1f} s) do not fit a {c.take_s} s take. Take a longer take or shorter handles.",
                    [c.id],
                    key=f"clock:fit:{c.id}",
                )
            )
    return out


def long_action(scene: SceneS, work: Bin) -> list[Fault]:
    """An action longer than any take is shown whole by its must clips together (plan/2026-11-08f §1): each must clip
    over it shows the next part, so their parts add up to the action's seconds. Before this check, every clip over such
    a block failed the clock however it was set, and a scene could never finish."""
    out: list[Fault] = []
    long = long_actions(scene)
    for b, seconds in sorted(long.items()):
        over = [c for c in work.clips if c.priority == "must" and b in c.blocks]
        if not over:
            continue  # `coverage` already says the block has no must clip
        shown = sum(part_s(scene, c, long) for c in over)
        if shown + 1e-9 >= seconds:
            continue
        out.append(
            _fault(
                "clock",
                f"b{b} is a {seconds:.1f} s action, longer than any take ({LONGEST_TAKE_S} s): its must clips show "
                f"the next part each, in order (say in each clip's beats which part). Together they show "
                f"{shown:.1f} s of it now; it needs {seconds - shown:.1f} s more (in all about "
                f"{parts_needed(seconds)} clips of 8 s with 1 s handles).",
                [c.id for c in over],
                key=f"clock:long:{b}",
            )
        )
    return out


SHORT_SHARE = 0.8  # plan/2026-11-08f §3: a must bin under 80 % of the scene's given length cannot finish


def short(brief: Brief, work: Bin) -> list[Fault]:
    """A must bin far under the scene's length (plan/2026-11-08f §3). The script's blocks alone rarely time at the
    given length; the rest is coverage of the same moments, and a bin with too little of it is a scene the editor
    cannot cut to length. Blocking below `SHORT_SHARE` of the target; nothing above it."""
    if not brief.guide_s:
        return []
    total = sum(c.take_s for c in work.clips)
    floor = brief.guide_s * SHORT_SHARE
    if total + 1e-9 >= floor:
        return []
    return [
        _fault(
            "length",
            f"The bin holds {total} s of takes; the target is {brief.guide_s:g} s and `finish` needs at least "
            f"{floor:g} s. The script itself times at {script_s(brief.scene):.0f} s: the rest is coverage of the same "
            "moments. Add must angles where the intended cut needs them: the master, each speaker's single, the "
            "listener's reaction where a line lands, and long actions shown over consecutive clips.",
            key="length:short",
        )
    ]


# ── feasibility ──────────────────────────────────────────────────────────────────────────────────


def feasibility(work: Bin, allowed: tuple[str, ...] = TECHNIQUES) -> list[Fault]:
    """What Veo cannot do, and the techniques the production's visual language allows."""
    out: list[Fault] = []
    for c in work.clips:
        if c.technique not in allowed:
            out.append(
                _fault(
                    "feasibility",
                    f"{c.id} uses {c.technique}, which the visual language does not allow.",
                    [c.id],
                    key=f"feasibility:language:{c.id}",
                )
            )
        if c.technique in NO_DIALOGUE and c.speaks:
            out.append(
                _fault(
                    "feasibility",
                    f"{c.id} is {c.technique} and carries a spoken line: slow motion, timelapse "
                    "and hyperlapse have no dialogue.",
                    [c.id],
                    key=f"feasibility:time:{c.id}",
                )
            )
        if not c.why.strip():
            out.append(
                _fault(
                    "feasibility",
                    f"{c.id} has no story reason: every technique needs one.",
                    [c.id],
                    key=f"feasibility:why:{c.id}",
                )
            )
        blob = " \n ".join(clip_text(c))
        for name, pattern, fix in REFUSED:
            if re.search(pattern, blob, re.IGNORECASE):
                out.append(
                    _fault(
                        "feasibility",
                        f"{c.id} asks for {name}. {fix}",
                        [c.id],
                        key=f"feasibility:refused:{c.id}:{name}",
                    )
                )
        for name, pattern, fix in FEASIBILITY:
            if re.search(pattern, blob, re.IGNORECASE):
                out.append(
                    _fault(
                        "feasibility",
                        f"{c.id} asks for {name}. {fix}",
                        [c.id],
                        fix="report",
                        key=f"feasibility:{c.id}:{name}",
                    )
                )
    return out


# ── the designs ──────────────────────────────────────────────────────────────────────────────────


def designs(scene: SceneS, work: Bin) -> list[Fault]:
    out: list[Fault] = []
    heard = heard_names(scene)
    for c in work.clips:
        if c.ir is None or c.sound is None:
            out.append(
                _fault(
                    "design",
                    f"{c.id} has no design yet (send it with its ir and sound).",
                    [c.id],
                    key=f"design:none:{c.id}",
                )
            )
            continue
        seen = [*strings_of(c.ir.get("subjects")), *strings_of(c.ir.get("first_frame"))]
        for who in heard:
            if any(mentions(t, who) for t in seen):
                out.append(
                    _fault(
                        "design",
                        f"{c.id}: {who} is only heard (a voice on the phone) and is in its subjects or "
                        "first frame: take them out of the picture.",
                        [c.id],
                        key=f"design:heard:{c.id}:{who}",
                    )
                )
        if not c.speaks:
            beats = [str(b.get("action") or "") for b in c.ir.get("beats") or [] if isinstance(b, dict)]
            subs = [str(s.get("action") or "") for s in c.ir.get("subjects") or [] if isinstance(s, dict)]
            said = next((m.group(0) for t in [*beats, *subs] if (m := SPEAKS.search(t))), "")
            if said:
                out.append(
                    _fault(
                        "design",
                        f'{c.id} does not perform a line, but a beat says someone "{said}": nobody '
                        "speaks in a clip that does not perform a line (Veo invents the speech). Say what they DO.",
                        [c.id],
                        key=f"design:speaks:{c.id}",
                    )
                )
    return out


def _odd_ones(values: dict[str, str]) -> list[str]:
    """The clips whose value differs from the commonest one (the earliest clip wins a tie): the ones to rewrite."""
    tally: dict[str, int] = {}
    for v in values.values():
        tally[v] = tally.get(v, 0) + 1
    top = max(tally.values())
    keep = next(v for v in values.values() if tally[v] == top)
    return [i for i, v in values.items() if v != keep]


def consistency(work: Bin) -> list[Fault]:
    """Every angle of one moment describes the place, the light and each person word for word the same, or the editor
    cannot cut between them. Aerial, establishing and atmosphere clips show another view and are left out. The fault
    names
    the clips that differ from the commonest wording, so a repair re-sends only those."""
    out: list[Fault] = []
    for n in sorted({c.moment for c in work.clips}):
        group = [
            c
            for c in work.clips
            if c.moment == n
            and c.ir is not None
            and c.role not in ("establishing", "atmosphere")
            and c.technique not in AERIAL
        ]
        if len(group) < 2:
            continue
        for field_name in ("setting", "lighting"):
            values = {c.id: " ".join(str((c.ir or {}).get(field_name) or "").split()) for c in group}
            if len(set(values.values())) > 1:
                out.append(
                    _fault(
                        "consistency",
                        f"The clips of moment {n} do not describe the {field_name} word for word the "
                        "same: copy one sentence into every clip.",
                        _odd_ones(values),
                        key=f"consistency:{n}:{field_name}",
                    )
                )
        looks: dict[str, dict[str, str]] = {}
        for c in group:
            for s in (c.ir or {}).get("subjects") or []:
                if isinstance(s, dict) and s.get("id"):
                    looks.setdefault(str(s["id"]), {})[c.id] = " ".join(str(s.get("description") or "").split())
        for who, by_clip in sorted(looks.items()):
            if len(set(by_clip.values())) > 1:
                out.append(
                    _fault(
                        "consistency",
                        f"In moment {n}, {who} is described in {len(set(by_clip.values()))} different "
                        "ways: the clothes and look are word for word the same in every angle.",
                        _odd_ones(by_clip),
                        key=f"consistency:{n}:{who}",
                    )
                )
    return out


# ── stage 1 ──────────────────────────────────────────────────────────────────────────────────────


def check_stage1(brief: Brief, work: Bin, allowed: tuple[str, ...] = TECHNIQUES) -> list[Fault]:
    scene = brief.scene
    return [
        *edit_plan(scene, work),
        *coverage(scene, work),
        *clock(scene, work),
        *long_action(scene, work),
        *feasibility(work, allowed),
        *designs(scene, work),
        *consistency(work),
        *length(brief, work, STAGE1_CAP),
        *short(brief, work),
        *state(scene, work),  # plan/2026-11-09: the state ledger, report only (D2)
    ]


# ── stage 2: the cinematic pass (§3.5) ───────────────────────────────────────────────────────────


def extra_checks(brief: Brief, work: Bin, cap: float) -> list[Fault]:
    """Anchored, silent, different from the anchor, at most 3 per moment, the whole bin within the chosen cap
    (blocking)."""
    out: list[Fault] = []
    must = {c.id: c for c in work.musts()}
    extras = work.extras()
    for e in extras:
        if e.priority == "must":
            out.append(
                _fault(
                    "cinematic",
                    f"{e.id} is a cinematic clip marked must: must clips are stage 1's. Use should or nice.",
                    [e.id],
                    key=f"cinematic:must:{e.id}",
                )
            )
        if e.blend not in BLENDS:
            out.append(
                _fault(
                    "cinematic",
                    f'{e.id}\'s blend "{e.blend}" is not one of {", ".join(BLENDS)}.',
                    [e.id],
                    key=f"cinematic:blend:{e.id}",
                )
            )
        if e.speaks:
            out.append(
                _fault(
                    "cinematic",
                    f"{e.id} is a cinematic clip and performs a line: a cinematic clip is silent "
                    "(speaks false); the dialogue stays on the must clips and post lays it under.",
                    [e.id],
                    key=f"cinematic:speaks:{e.id}",
                )
            )
        if not e.anchor:
            out.append(
                _fault(
                    "cinematic",
                    f"{e.id} names no anchor: give the must clip it sits with.",
                    [e.id],
                    key=f"cinematic:anchor:none:{e.id}",
                )
            )
        near = {e.moment - 1, e.moment, e.moment + 1} if e.blend == "transition" else {e.moment}
        for a in e.anchor:
            anchor = must.get(a)
            if anchor is None:
                out.append(
                    _fault(
                        "cinematic",
                        f"{e.id}'s anchor {a} is not a must clip of the bin (the anchors are stage 1's "
                        "clips; read_bin lists them).",
                        [e.id],
                        key=f"cinematic:anchor:unknown:{e.id}:{a}",
                    )
                )
            elif anchor.moment not in near:
                where = "the same or a neighbouring moment" if e.blend == "transition" else f"moment {e.moment}"
                out.append(
                    _fault(
                        "cinematic",
                        f"{e.id} is in moment {e.moment} and its anchor {a} is in moment "
                        f"{anchor.moment}: an anchor is in {where}.",
                        [e.id],
                        key=f"cinematic:anchor:moment:{e.id}:{a}",
                    )
                )
            elif (anchor.role, anchor.technique) == (e.role, e.technique):
                out.append(
                    _fault(
                        "cinematic",
                        f"{e.id} is a {e.role} {e.technique} like its anchor {a}: that is an alternate, "
                        "not a cinematic shot. Change its role or its technique.",
                        [e.id],
                        key=f"cinematic:same:{e.id}:{a}",
                    )
                )
    per = Counter(e.moment for e in extras)
    for n, k in sorted(per.items()):
        if k > PER_MOMENT_MAX:
            ids = [e.id for e in extras if e.moment == n]
            out.append(
                _fault(
                    "cinematic",
                    f"Moment {n} has {k} cinematic clips; at most {PER_MOMENT_MAX}: keep the strongest, "
                    "remove the rest or move one to a moment that earns it.",
                    ids,
                    key=f"cinematic:crowded:{n}",
                )
            )
    return out


ATMOSPHERE_MAX = (
    2  # D-V: at most 2 atmosphere clips a scene, and 4 s each (a report, not blocking, until 0e says otherwise)
)


def variety(work: Bin) -> list[Fault]:
    """Pass 5's gap (5 of 8 clips were rain-texture atmosphere, two of them 8 s): the room goes to different ideas.
    Reported,
    never blocking (D-V)."""
    out: list[Fault] = []
    atmosphere = [e for e in work.extras() if e.role == "atmosphere"]
    if len(atmosphere) > ATMOSPHERE_MAX:
        out.append(
            _fault(
                "variety",
                f"{len(atmosphere)} atmosphere clips in a scene; at most {ATMOSPHERE_MAX}: spend the room on a held "
                f"reaction "
                "where a line lands, an insert of the story object, a drone or a transition instead.",
                [e.id for e in atmosphere],
                fix="report",
                key="variety:atmosphere",
            )
        )
    long = [e.id for e in atmosphere if e.take_s > 4]
    if long:
        out.append(
            _fault(
                "variety",
                f"Atmosphere clips are 4 s ({', '.join(long)} take longer): a texture needs no more.",
                long,
                fix="report",
                key="variety:atmosphere_take",
            )
        )
    return out


def check_stage2(brief: Brief, work: Bin, allowed: tuple[str, ...] = TECHNIQUES, cap: float = 2) -> list[Fault]:
    """Stage 1's checks on the whole bin (the 1.5x length fault replaced by the chosen cap) plus the cinematic
    checks."""
    # The must clips are locked in stage 2, so stage 1's length rules (over 1.5x, under 80 %) are not its to meet.
    kept = [f for f in check_stage1(brief, work, allowed) if f.key not in ("length:over", "length:short")]
    return [*kept, *length(brief, work, cap, key="length:stage2"), *extra_checks(brief, work, cap), *variety(work)]


def review_faults(work: Bin, review: list[ReviewRow]) -> list[str]:
    """Every moment of the intended cut once, each with a reason; `earns` true exactly where cinematic clips are."""
    if work.edit is None:
        return ["there is no intended cut"]
    moments = [m.n for m in work.edit.moments]
    has = {e.moment for e in work.extras()}
    seen = [r.moment for r in review]
    out = [f"moment {n} is not reviewed" for n in moments if n not in seen]
    out += [f"moment {n} is reviewed {seen.count(n)} times" for n in sorted(set(seen)) if seen.count(n) > 1]
    out += [f"moment {n} is not in the intended cut" for n in sorted(set(seen) - set(moments))]
    for r in review:
        if not r.why.strip():
            out.append(f"moment {r.moment} has no reason")
        if r.moment in moments and r.earns != (r.moment in has):
            out.append(
                f"moment {r.moment} says earns {str(r.earns).lower()} but has "
                f"{'cinematic clips' if r.moment in has else 'none'}"
            )
    return out


def missing_blend_notes(work: Bin, notes: list[str]) -> list[str]:
    """The cinematic clips no blend note starts with or names."""
    return [
        e.id for e in work.extras() if not any(n.startswith(e.id) or f"{e.id} " in n or f"{e.id}:" in n for n in notes)
    ]


# ── the state ledger (plan/2026-11-09 phase 6): report only until the lab decides (D2) ───────────────────────────

# A thing in a hand, said in a clause that names it: "phone in right hand", "phone now in left", "holds the phone"
HAND_SIDE = re.compile(r"\bin (?:her|his|their|the|one)?\s*(left|right)\b", re.IGNORECASE)
HELD = re.compile(
    r"\b(holds?|holding|grips?|gripping|clutch\w*|raises?|raised|raising|lifts?|lifted|lifting|offers?|offered|"
    r"offering|to (?:her|his|their) ear|at (?:her|his|their) ear|in (?:her|his|their|one) hand)\b",
    re.IGNORECASE,
)
CLAUSES = re.compile(r"[,;]|\bthen\b|\band\b|\bwhile\b|\bas\b", re.IGNORECASE)
# What a posture rules out (the plan's two: a lying person on their feet, a sitting person running)
NOT_WITH: dict[str, re.Pattern[str]] = {
    "lying": re.compile(
        r"\b(stands?|standing|walks?|walking|runs?|running|sits?|sitting|steps?|stepping|gets up|rises)\b",
        re.IGNORECASE,
    ),
    "sitting": re.compile(r"\b(runs?|running|walks?|walking|strides?|striding)\b", re.IGNORECASE),
}
STILL = ("dead", "unconscious")  # a condition in which a person does nothing on their own
ALIVE = re.compile(
    r"\b(breath\w*|chest (?:rises|rising|heaves|heaving)|blinks?|blinking|speaks?|speaking|talks?|talking|stirs?|"
    r"stirring|moves? (?:his|her|their)|opens (?:his|her|their) eyes|sits up|stands up|gets up|looks up|"
    r"turns (?:his|her|their) head|groans?|moans?)\b",
    re.IGNORECASE,
)
NEGATED = re.compile(r"\b(no|not|never|without|n't|nor|cannot)\W+(?:\w+\W+){0,2}$", re.IGNORECASE)
ZONE_GENERIC = frozenset(
    {
        "the",
        "a",
        "an",
        "of",
        "by",
        "near",
        "side",
        "edge",
        "area",
        "place",
        "spot",
        "road",
        "street",
        "frame",
        "left",
        "right",
        "centre",
        "center",
        "front",
        "back",
        "corner",
        "one",
    }
)


def _subjects(clip: Clip) -> list[dict[str, object]]:
    return [s for s in (clip.ir or {}).get("subjects") or [] if isinstance(s, dict)]


def _who(scene: SceneS, subject: dict[str, object]) -> str:
    return scene.name_of(str(subject.get("id") or ""))


def _subject_text(subject: dict[str, object]) -> str:
    return " , ".join(str(subject.get(k) or "") for k in ("action", "position"))


def _picture_text(clip: Clip, *, beats: bool = True) -> str:
    """What a clip SHOWS in words (never the look: a description is the clothes, not the moment)."""
    ir = clip.ir or {}
    rows = [_subject_text(s) for s in _subjects(clip)]
    if beats:
        rows += [
            str(b.get(k) or "") for b in ir.get("beats") or [] if isinstance(b, dict) for k in ("action", "performance")
        ]
    frame = ir.get("first_frame")
    if isinstance(frame, dict):
        rows += [str(frame.get("composition") or ""), *strings_of(frame.get("subjects"))]
    return " \n ".join(r for r in rows if r)


def _names(text: str, scene: SceneS, who: str) -> bool:
    """`text` names this person, by name or by the code the clips use."""
    codes = [c for c, n in scene.codes.items() if n == who]
    return any(mentions(text, n) for n in (who, *codes))


def _thing_in(text: str, key: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(key)}s?(?!\w)", text, re.IGNORECASE) is not None


def _window_states(scene: SceneS, blocks: list[int]) -> list[sm.SceneState]:
    """The state as the clip opens, then after each of its blocks."""
    staging, items = scene.staging, scene.items()
    opens, _ = sm.clip_state(staging, items, blocks)
    return [opens, *(sm.state_at(staging, items, b) for b in blocks)]


def _zone_words(zone: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9][a-z0-9'’-]*", zone.lower()) if w not in ZONE_GENERIC and len(w) >= 3]


def _names_zone(text: str, zone: str) -> bool:
    return any(mentions(text, w) for w in _zone_words(zone))


def _hand_named(text: str, key: str, side: str) -> bool:
    """The text says which hand holds the thing: "phone in her left hand", "the phone now in left", "left hand"."""
    if re.search(rf"\b{side}[- ]hand\b", text, re.IGNORECASE):
        return True
    for clause in CLAUSES.split(text):
        m = HAND_SIDE.search(clause)
        if m and m.group(1).lower() == side and _thing_in(clause, key):
            return True
    return False


def _alive_word(text: str) -> str:
    for m in ALIVE.finditer(text):
        if not NEGATED.search(text[: m.start()]):
            return m.group(0)
    return ""


def state(scene: SceneS, work: Bin) -> list[Fault]:
    """Each clip against the scene's state ledger (`scene.staging`, pinned by `contracts.raphael.state.attach`):
    hands, handovers, posture, condition, presence and place, and the props someone carries that no clip shows.
    REPORT only (D2): a wrong ledger must not trap Raphael. No ledger, no check."""
    staging = scene.staging
    if staging is None or not staging.marks:
        return []
    items = scene.items()
    ledger = sm.ledger_of(staging, items)
    out: list[Fault] = []
    zones = staging.zones
    for c in work.clips:
        if c.ir is None or not c.blocks:
            continue
        blocks = sorted(set(c.blocks))
        states = _window_states(scene, blocks)
        first = blocks[0]
        for s in _subjects(c):
            who = _who(scene, s)
            if not who:
                continue
            mine = [st.person(who) for st in states]
            text = _subject_text(s)
            # hands: a thing in this person's hand that the ledger gives to someone else at these blocks
            for clause in CLAUSES.split(text):
                for key, thing in sorted(ledger.things.items()):
                    if not _thing_in(clause, key) or thing.worn:
                        continue
                    side_m = HAND_SIDE.search(clause)
                    if side_m is None and not HELD.search(clause):
                        continue
                    holders = {
                        st.props[key].holder.casefold() for st in states if key in st.props and st.props[key].holder
                    }
                    if not holders:
                        continue
                    if who.casefold() not in holders:
                        holder = next(st.props[key] for st in states if key in st.props and st.props[key].holder)
                        hand = f" ({holder.hand} hand)" if holder.hand else ""
                        out.append(
                            _fault(
                                "state",
                                f"{c.id} (b{first}): {who} holds the {thing.text} here, and the state map gives "
                                f"it to {holder.holder}{hand} at these blocks: follow the map, or show it pass.",
                                [c.id],
                                fix="report",
                                key=f"state:hand:{c.id}:{key}:{who}",
                            )
                        )
                        continue
                    sides = {p.hand_of(key) for p in mine if p is not None and key in p.keys()} - {""}
                    said = side_m.group(1).lower() if side_m else ""
                    if said and sides and said not in sides:
                        out.append(
                            _fault(
                                "state",
                                f"{c.id} (b{first}): the {thing.text} is in {who}'s {'/'.join(sorted(sides))} "
                                f"hand by the state map; '{clause.strip()}' puts it in the {said}.",
                                [c.id],
                                fix="report",
                                key=f"state:hand:{c.id}:{key}:{who}:side",
                            )
                        )
            # posture, held through the whole clip
            postures = {p.posture for p in mine if p is not None}
            if len(postures) == 1 and (posture := postures.pop()) in NOT_WITH:
                m = NOT_WITH[posture].search(text)
                if m:
                    out.append(
                        _fault(
                            "state",
                            f"{c.id}: {who} is {posture} at b{first} by the state map; '{m.group(0)}' contradicts it.",
                            [c.id],
                            fix="report",
                            key=f"state:posture:{c.id}:{who}",
                        )
                    )
            # condition: a dead or unconscious person does nothing on their own
            conditions = {p.condition.casefold() for p in mine if p is not None}
            still = next((x for x in STILL for cond in conditions if x in cond), "")
            if still and len(conditions) == 1:
                alone = len(_subjects(c)) == 1
                word = _alive_word(text + (" \n " + _picture_text(c) if alone else ""))
                speaks = c.speaks and any(
                    (b := scene.line_block(ln)) is not None and norm(plain_name(b.speaker)) == norm(who)
                    for ln in c.lines
                )
                if word or speaks:
                    said = f"'{word}'" if word else "a spoken line"
                    out.append(
                        _fault(
                            "state",
                            f"{c.id}: {who} is {still} by the state map; {said} contradicts it.",
                            [c.id],
                            fix="report",
                            key=f"state:condition:{c.id}:{who}",
                        )
                    )
            # presence: off for every block of the clip
            during = [sm.state_at(staging, items, b).person(who) for b in blocks]
            if during and all(p is not None and p.zone == sm.OFF for p in during):
                out.append(
                    _fault(
                        "state",
                        f"{c.id}: {who} is off (not in the place) at b{first}-b{blocks[-1]} by the state map: "
                        "take them out of the picture, or put the clip where they are.",
                        [c.id],
                        fix="report",
                        key=f"state:off:{c.id}:{who}",
                    )
                )
            # place: the position names another of the map's spots
            here = {p.zone for p in mine if p is not None and p.zone and p.zone != sm.OFF}
            position = str(s.get("position") or "")
            if here and not any(_names_zone(position, z) for z in here):
                other = next((z for z in zones if z not in here and _names_zone(position, z)), "")
                if other:
                    now = sorted(here)[0]
                    out.append(
                        _fault(
                            "state",
                            f"{c.id} (b{first}): {who} is at the {now} by the state map; '{position}' is the "
                            f"{other}: show them go there, or keep them at the {now}.",
                            [c.id],
                            fix="report",
                            key=f"state:zone:{c.id}:{who}",
                        )
                    )
        # handovers inside the clip: show who gives it and which hand takes it
        start, end = blocks[0], blocks[-1] + 1
        shown = _picture_text(c)
        for change in ledger.during(start, end):
            if not (change.giver and change.taker) or change.block not in blocks:
                continue
            thing = ledger.things[change.key]
            if not _thing_in(shown, change.key):
                continue
            side = ledger.side(change.taker, change.key, change.block)
            subjects = {_who(scene, s) for s in _subjects(c)}
            both = all(p in subjects or _names(shown, scene, p) for p in (change.giver, change.taker))
            named_hand = not side or _hand_named(shown, change.key, side)
            if not (both and named_hand):
                taking = f"{change.taker}'s {side} hand" if side else f"{change.taker}'s hand"
                out.append(
                    _fault(
                        "state",
                        f"{c.id}: the {thing.text} passes from {change.giver} to {change.taker} at "
                        f"b{change.block}: show {change.giver}'s hand giving it and {taking} taking it.",
                        [c.id],
                        fix="report",
                        key=f"state:handover:{c.id}:{change.key}:{change.block}",
                    )
                )
    out += unplaced(scene, work, ledger)
    return out


def unplaced(scene: SceneS, work: Bin, ledger: hd.Ledger) -> list[Fault]:
    """A prop someone holds (a handbag) that no clip shows where its holder is seen: once a scene, not once a clip."""
    staging, items = scene.staging, scene.items()
    out: list[Fault] = []
    for key, thing in sorted(ledger.things.items()):
        taken = next((ch for ch in ledger.changes if ch.key == key and ch.taker), None)
        if taken is None:
            continue
        seen_with: list[Clip] = []
        for c in work.clips:
            if c.ir is None:
                continue
            for b in sorted(set(c.blocks)):
                held = sm.state_at(staging, items, b).props.get(key)
                if (
                    held is not None
                    and held.holder
                    and any(norm(_who(scene, s)) == norm(held.holder) for s in _subjects(c))
                ):
                    seen_with.append(c)
                    break
        if not seen_with:
            continue
        first = (taken.block, taken.taker)
        if not any(_thing_in(_picture_text(c), key) for c in seen_with):
            out.append(
                _fault(
                    "state",
                    f"The {thing.text} {first[1]} carries (from b{first[0]}) is in no clip's picture where "
                    f"{first[1]} is seen, only perhaps in a description: place it (a hand, a shoulder) in at "
                    "least one.",
                    fix="report",
                    key=f"state:unplaced:{key}",
                )
            )
    return out
