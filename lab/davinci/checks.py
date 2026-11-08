"""The code tools that judge a bin (plan/2026-11-08d §4.3). No model, no network.

    check_all(reading, bin, allowed)    [Fault]   everything below, each fault with its owner
    measures(reading, bin)              [Measure] the shape of the coverage, reported and never blocking

Four checks, named as the plan names them: `coverage` (every block has a must clip, every line a performer), `clock`
(4 / 6 / 8 s takes, handles that fit, a line kept whole; an overrun is reported, never trimmed), `feasibility` (what Veo
cannot do, the techniques the visual language allows), and a design check (a heard-only voice never in frame, nobody
speaks in a clip with no line, every clip has its design). A fault names its owner: `director` (the bin's shape),
`clip_writer` (a clip's words) or `code`. A fault with `fix == "report"` is told to the person and does not stop `finish`.
"""
from __future__ import annotations

import re
from typing import Literal, cast

from pydantic import BaseModel

from cinematic.checks import SPEAKS, heard_names, strings_of
from cinematic.pack import Reading, is_heard, is_voice_over
from contracts.david.checks import FEASIBILITY, mentions
from contracts.david.scene import SceneS, need_s

from .schema import AERIAL, NO_DIALOGUE, TECHNIQUES, TRANSITION, Clip
from .state import Bin

Owner = Literal["director", "clip_writer", "code"]
HANDLE_MAX_S = 2.0  # a handle is about a second; more than two seconds is a take spent on nothing
ACTION_MIN_S = 1.5  # the least a clip must show of an action, between its handles (the clock's one picture, 1.5 s)
BARE_MIN_S = 1.0  # an establishing, atmosphere or transition clip needs a second of picture between its handles
# Techniques Veo cannot do, refused in any text of a clip (plan §3). The post-only ones are named in editor_notes instead.
REFUSED = (
    ("a dolly zoom", r"\b(dolly[- ]zoom|vertigo (effect|shot)|zolly|contra[- ]?zoom)\b",
     "Veo cannot hold it steady. Use a slow creep or a push-in for the same pull."),
    ("a split diopter", r"\bsplit[- ]diopter\b", "Veo cannot split the focus. Use a rack focus or a foreground layer."),
    ("a post technique", r"\b(speed[- ]ramp|freeze[- ]?frame|punch[- ]in|split[- ]screen)\b",
     "It is made in the edit: shoot a clean source and name the technique in editor_notes."))
FAMILY = {"whip_out": "whip", "whip_in": "whip", "focus_out": "focus", "focus_in": "focus", "match_cut": "match",
          "object_wipe": "wipe"}
OUT_ROLE, IN_ROLE = TRANSITION
LENGTH_MARGIN = 0.5  # the person's rule (2026-11-08): the bin holds at most the given length + 50% in seconds of takes


def limit_s(reading: Reading) -> float:
    """The most seconds of takes the bin may hold: the scene's given length (`time.guide_s`) + 50%. 0: no length was given."""
    return reading.guide_s * (1 + LENGTH_MARGIN)


class Fault(BaseModel):
    code: str
    sentence: str
    clips: list[str] = []
    owner: Owner
    fix: Literal["repair", "report"] = "repair"
    key: str = ""

    def line(self) -> str:
        who = f" [{', '.join(self.clips)}]" if self.clips else ""
        return f"({self.owner}, {self.fix}) {self.code}{who}: {self.sentence}"


class Measure(BaseModel):
    label: str
    status: Literal["met", "missed", "info"]
    detail: str


def _fault(code: str, sentence: str, owner: Owner, clips: list[str] | None = None, *, fix: Literal["repair", "report"] = "repair",
           key: str = "") -> Fault:
    return Fault(code=code, sentence=sentence, clips=clips or [], owner=owner, fix=fix,
                 key=key or f"{code}:{','.join(clips or [])}:{sentence[:40]}")


def clip_text(clip: Clip) -> list[str]:
    """Everything written in words for a clip (design, sound, reason and note)."""
    sound = [clip.sound.ambience, clip.sound.effects, clip.sound.music] if clip.sound else []
    return [*strings_of(clip.ir or {}), *sound, clip.why, clip.editor_note, clip.angle, clip.lens]


def _items(scene: SceneS, clip: Clip) -> list:
    """The kernel items the clip plays: its blocks in script order, a line only if the clip carries it."""
    keep = set(clip.blocks)
    return [i for i in scene.items() if i.index in keep and (not i.is_line or i.line_id in clip.lines)]


# ── the edit plan ────────────────────────────────────────────────────────────────────────────────


def edit_plan(scene: SceneS, work: Bin) -> list[Fault]:
    plan = work.edit
    if plan is None:
        return [_fault("edit", "There is no edit plan yet: write the intended cut first (write_edit_plan).", "director",
                       key="edit:none")]
    out: list[Fault] = []
    everything = {b.index for b in scene.blocks}
    owners: dict[int, list[int]] = {}
    for m in plan.moments:
        for b in m.blocks:
            owners.setdefault(b, []).append(m.n)
    for b in sorted(everything - set(owners)):
        out.append(_fault("edit", f"Block b{b} is in no moment of the edit plan.", "director", key=f"edit:missing:{b}"))
    for b, ms in sorted(owners.items()):
        if b not in everything:
            out.append(_fault("edit", f"Moment {ms[0]} names block b{b}, which the script does not have.", "director",
                              key=f"edit:unknown:{b}"))
        elif len(ms) > 1:
            out.append(_fault("edit", f"Block b{b} is in moments {ms}: a block belongs to ONE moment.", "director",
                              key=f"edit:twice:{b}"))
    numbers = [m.n for m in plan.moments]
    if len(set(numbers)) != len(numbers):
        out.append(_fault("edit", "Two moments have the same number.", "director", key="edit:duplicate"))
    known = {s.id for s in plan.sequences}
    for m in plan.moments:
        if m.sequence not in known:
            out.append(_fault("edit", f"Moment {m.n} is in sequence \"{m.sequence}\", which does not exist.", "director",
                              key=f"edit:sequence:{m.n}"))
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
            out.append(_fault("coverage", f"{c.id} covers moment {c.moment}, which the edit plan does not have.", "director",
                              [c.id], key=f"coverage:moment:{c.id}"))
        for b in c.blocks:
            if b not in everything:
                out.append(_fault("coverage", f"{c.id} covers block b{b}, which the script does not have.", "director", [c.id],
                                  key=f"coverage:block:{c.id}:{b}"))
        for lid in c.lines:
            block = lines.get(lid)
            if block is None:
                out.append(_fault("coverage", f"{c.id} carries line {lid}, which the script does not have.", "director", [c.id],
                                  key=f"coverage:line:{c.id}:{lid}"))
            elif block.index not in c.blocks:
                out.append(_fault("coverage", f"{c.id} carries line {lid} but does not cover its block b{block.index}.",
                                  "director", [c.id], key=f"coverage:lineblock:{c.id}:{lid}"))
        if c.speaks and not c.lines:
            out.append(_fault("coverage", f"{c.id} is marked as speaking but carries no line.", "director", [c.id],
                              key=f"coverage:speaks:{c.id}"))
    for b in sorted(everything):
        if not any(b in c.blocks for c in must):
            out.append(_fault("coverage", f"Block b{b} has no must clip: the intended cut has nothing to show for it.",
                              "director", key=f"coverage:must:{b}"))
    for n in sorted(moments):
        if not any(c.moment == n for c in must):
            out.append(_fault("coverage", f"Moment {n} has no must clip.", "director", key=f"coverage:moment_must:{n}"))
    for lid, block in lines.items():
        carriers = [c for c in work.clips if lid in c.lines]
        heard = is_heard(block) or is_voice_over(block)  # heard not seen, or a thought with the lips closed
        if not any(c.priority == "must" for c in carriers):
            out.append(_fault("coverage", f"Line {lid} is carried by no must clip.", "director", key=f"coverage:carrier:{lid}"))
        elif heard and any(c.speaks for c in carriers):
            out.append(_fault("coverage", f"Line {lid} is heard and not seen (a voice over, a thought or the other end of a "
                              "call): no clip may show lips speaking it.", "director", [c.id for c in carriers if c.speaks],
                              key=f"coverage:heard:{lid}"))
        elif not heard and not any(c.speaks for c in carriers if c.priority == "must"):
            out.append(_fault("coverage", f"Line {lid} is performed by no must clip (D2: the master and the speaker's "
                              "single speak).", "director", [c.id for c in carriers], key=f"coverage:performer:{lid}"))
    outs = [c for c in work.clips if c.role == OUT_ROLE]
    ins = [c for c in work.clips if c.role == IN_ROLE]
    for fam in sorted({FAMILY.get(c.technique, "") for c in [*outs, *ins]} - {""}):
        a = [c for c in outs if FAMILY.get(c.technique) == fam]
        z = [c for c in ins if FAMILY.get(c.technique) == fam]
        if len(a) != len(z):
            out.append(_fault("coverage", f"The {fam} transition has {len(a)} out clip(s) and {len(z)} in clip(s): both "
                              "halves of a pair are planned.", "director", [c.id for c in [*a, *z]], key=f"coverage:pair:{fam}"))
    return out


# ── length ───────────────────────────────────────────────────────────────────────────────────────


def length(reading: Reading, work: Bin) -> list[Fault]:
    """The bin is not three times the cut: its takes add up to at most the given length + 50%. Over it, the director drops
    `nice` clips first, then `should`; a `must` clip is never the one to go."""
    limit = limit_s(reading)
    total = sum(c.take_s for c in work.clips)
    if not limit or total <= limit + 1e-9:
        return []
    by = {p: sum(c.take_s for c in work.clips if c.priority == p) for p in ("must", "should", "nice")}
    return [_fault("length", f"The bin holds {total} s of takes and may hold {limit:g} s (the scene's {reading.guide_s:g} s + "
                   f"{LENGTH_MARGIN:.0%}): {by['must']} s must, {by['should']} s should, {by['nice']} s nice. Drop nice clips "
                   "first, then should; most moments need only their must clips. Do not cover every action from several angles.",
                   "director", key="length:over")]


# ── clock ────────────────────────────────────────────────────────────────────────────────────────


def _fits(c: Clip, take: int, need: float, spoken: bool) -> bool:
    """Do the clip's handles and what it shows fit a take of `take` seconds?"""
    if spoken:  # the clock's 0.5 s lead-in and 0.5 s tail are silent time: they count as part of the handles
        return c.handle_in_s + c.handle_out_s + max(need - 1.0, 0.0) <= take + 1e-9
    window = ACTION_MIN_S if c.blocks and need else BARE_MIN_S
    return take - c.handle_in_s - c.handle_out_s >= max(window, need if c.blocks else 0.0) - 1e-9


def clock(scene: SceneS, work: Bin) -> list[Fault]:
    """4 / 6 / 8 s takes (the schema holds them), handles that fit, a line kept whole. Reports an overrun, never trims."""
    out: list[Fault] = []
    for c in work.clips:
        for name, h in (("in", c.handle_in_s), ("out", c.handle_out_s)):
            if not 0 <= h <= HANDLE_MAX_S:
                out.append(_fault("clock", f"{c.id}'s handle {name} is {h:g} s: a handle is 0 to {HANDLE_MAX_S:g} s.",
                                  "director", [c.id], key=f"clock:handle:{c.id}:{name}"))
        items = _items(scene, c)
        spoken = [i for i in items if i.is_line]
        need = need_s(items) if items else 0.0
        if spoken and need > c.take_s + 1e-9:
            out.append(_fault("clock", f"{c.id} needs {need:.1f} s for what it carries and the take is {c.take_s} s: a line "
                              "is kept whole and never trimmed. Split the exchange into overlapping clips.", "director",
                              [c.id], fix="report", key=f"clock:overrun:{c.id}"))
            continue
        if not _fits(c, c.take_s, need, bool(spoken)):
            out.append(_fault("clock", f"{c.id}: its handles ({c.handle_in_s:g} s + {c.handle_out_s:g} s) and what it shows "
                              f"do not fit a {c.take_s} s take. Take a longer take or shorter handles.", "director", [c.id],
                              key=f"clock:fit:{c.id}"))
    return out


# ── feasibility ──────────────────────────────────────────────────────────────────────────────────


def feasibility(work: Bin, allowed: tuple[str, ...] = TECHNIQUES) -> list[Fault]:
    """What Veo cannot do, and the techniques the production's visual language allows (D3). Menu faults are the
    director's, faults in the designed words are the clip writer's."""
    out: list[Fault] = []
    for c in work.clips:
        if c.technique not in allowed:
            out.append(_fault("feasibility", f"{c.id} uses {c.technique}, which the visual language does not allow.",
                              "director", [c.id], key=f"feasibility:language:{c.id}"))
        if c.technique in NO_DIALOGUE and c.speaks:
            out.append(_fault("feasibility", f"{c.id} is {c.technique} and carries a spoken line: slow motion, timelapse "
                              "and hyperlapse have no dialogue.", "director", [c.id], key=f"feasibility:time:{c.id}"))
        if not c.why.strip():
            out.append(_fault("feasibility", f"{c.id} has no story reason: every technique needs one.", "director", [c.id],
                              key=f"feasibility:why:{c.id}"))
        blob = " \n ".join(clip_text(c))
        owner: Owner = "clip_writer" if c.ir is not None else "director"
        for name, pattern, fix in REFUSED:
            if re.search(pattern, blob, re.IGNORECASE):
                out.append(_fault("feasibility", f"{c.id} asks for {name}. {fix}", owner, [c.id],
                                  key=f"feasibility:refused:{c.id}:{name}"))
        for name, pattern, fix in FEASIBILITY:
            if re.search(pattern, blob, re.IGNORECASE):
                out.append(_fault("feasibility", f"{c.id} asks for {name}. {fix}", "clip_writer", [c.id], fix="report",
                                  key=f"feasibility:{c.id}:{name}"))
    return out


# ── the designs ──────────────────────────────────────────────────────────────────────────────────


def designs(scene: SceneS, work: Bin) -> list[Fault]:
    out: list[Fault] = []
    heard = heard_names(scene)
    for c in work.clips:
        if c.ir is None or c.sound is None:
            out.append(_fault("design", f"{c.id} has no design yet (write_clips).", "clip_writer", [c.id],
                              key=f"design:none:{c.id}"))
            continue
        seen = [*strings_of(c.ir.get("subjects")), *strings_of(c.ir.get("first_frame"))]
        for who in heard:
            if any(mentions(t, who) for t in seen):
                out.append(_fault("design", f"{c.id}: {who} is only heard (a voice on the phone) and is in its subjects or "
                                  "first frame: take them out of the picture.", "clip_writer", [c.id],
                                  key=f"design:heard:{c.id}:{who}"))
        if not c.speaks:
            beats = [str(b.get("action") or "") for b in c.ir.get("beats") or [] if isinstance(b, dict)]
            subs = [str(s.get("action") or "") for s in c.ir.get("subjects") or [] if isinstance(s, dict)]
            said = next((m.group(0) for t in [*beats, *subs] if (m := SPEAKS.search(t))), "")
            if said:
                out.append(_fault("design", f"{c.id} does not perform a line, but a beat says someone \"{said}\": nobody "
                                  "speaks in a clip that does not perform a line (Veo invents the speech). Say what they DO.",
                                  "clip_writer", [c.id], key=f"design:speaks:{c.id}"))
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
    """Risk 1 of the plan: every angle of one moment must describe the place, the light and each person word for word the
    same, or the editor cannot cut between them. Aerial, establishing and atmosphere clips show another view and are left out.
    The fault names the clips that differ from the commonest wording, so a repair re-sends only those."""
    out: list[Fault] = []
    for n in sorted({c.moment for c in work.clips}):
        group = [c for c in work.clips if c.moment == n and c.ir is not None and c.role not in ("establishing", "atmosphere")
                 and c.technique not in AERIAL]
        if len(group) < 2:
            continue
        for field_name in ("setting", "lighting"):
            values = {c.id: " ".join(str((c.ir or {}).get(field_name) or "").split()) for c in group}
            if len(set(values.values())) > 1:
                out.append(_fault("consistency", f"The clips of moment {n} do not describe the {field_name} word for word the "
                                  "same: copy one sentence into every clip.", "clip_writer", _odd_ones(values),
                                  key=f"consistency:{n}:{field_name}"))
        looks: dict[str, dict[str, str]] = {}
        for c in group:
            for s in (c.ir or {}).get("subjects") or []:
                if isinstance(s, dict) and s.get("id"):
                    looks.setdefault(str(s["id"]), {})[c.id] = " ".join(str(s.get("description") or "").split())
        for who, by_clip in sorted(looks.items()):
            if len(set(by_clip.values())) > 1:
                out.append(_fault("consistency", f"In moment {n}, {who} is described in {len(set(by_clip.values()))} different "
                                  "ways: the clothes and look are word for word the same in every angle.", "clip_writer",
                                  _odd_ones(by_clip), key=f"consistency:{n}:{who}"))
    return out


def looks(work: Bin) -> list[Fault]:
    """Staged path (plan B §2.1): the look sheet has one entry per moment of the edit plan, and none for a moment that is not in
    it. Nothing is checked when no sheet was asked for (the orchestrator has none)."""
    if not work.looks:
        return []
    out: list[Fault] = []
    moments = {m.n for m in work.edit.moments} if work.edit else set()
    seen = [m.moment for m in work.looks]
    for n in sorted(moments - set(seen)):
        out.append(_fault("looks", f"Moment {n} has no entry in the look sheet: give it a setting, a lighting and the people it "
                          "shows.", "director", key=f"looks:missing:{n}"))
    for n in sorted({m for m in seen if m not in moments}):
        out.append(_fault("looks", f"The look sheet has an entry for moment {n}, which the edit plan does not have.", "director",
                          key=f"looks:unknown:{n}"))
    for n in sorted({m for m in seen if seen.count(m) > 1}):
        out.append(_fault("looks", f"The look sheet has {seen.count(n)} entries for moment {n}: one only.", "director",
                          key=f"looks:twice:{n}"))
    for entry in work.looks:
        if not entry.setting.strip() or not entry.lighting.strip():
            out.append(_fault("looks", f"The look sheet entry for moment {entry.moment} has an empty setting or lighting.",
                              "director", key=f"looks:empty:{entry.moment}"))
    return out


def plan_checks(reading: Reading, work: Bin, allowed: tuple[str, ...] = TECHNIQUES) -> list[Fault]:
    """What can be judged before any design exists (plan B §2.2): the edit plan, the look sheet, the coverage, the clock, what
    Veo can do and the length. Every fault is the director's."""
    scene = reading.scene
    return [*edit_plan(scene, work), *looks(work), *coverage(scene, work), *clock(scene, work), *feasibility(work, allowed),
            *length(reading, work)]


def design_checks(reading: Reading, work: Bin, allowed: tuple[str, ...] = TECHNIQUES) -> list[Fault]:
    """What can be judged once the clips are designed (plan B §2.4): the designs, the match between angles, and the words of a
    design that Veo cannot do. The faults whose owner is the clip writer are the ones a re-design can cure."""
    words = [f for f in feasibility(work, allowed) if f.owner == "clip_writer"]
    return [*designs(reading.scene, work), *consistency(work), *words]


def better(new: list[Fault], old: list[Fault]) -> bool:
    """A repair is kept only when it leaves fewer blocking faults (plan B §2.3). Equal is not better."""
    return len(blocking(new)) < len(blocking(old))


def check_all(reading: Reading, work: Bin, allowed: tuple[str, ...] = TECHNIQUES) -> list[Fault]:
    scene = reading.scene
    return [*edit_plan(scene, work), *looks(work), *coverage(scene, work), *clock(scene, work), *feasibility(work, allowed),
            *designs(scene, work), *consistency(work), *length(reading, work)]


def blocking(found: list[Fault]) -> list[Fault]:
    """The faults `finish` refuses to pass: everything but a report."""
    return [f for f in found if f.fix != "report"]


# ── measures ─────────────────────────────────────────────────────────────────────────────────────


def measures(reading: Reading, work: Bin) -> list[Measure]:
    """The shape of the coverage in numbers, for the page and for the person. A prompt for the eye, never a verdict."""
    out: list[Measure] = []
    n = work.counts()
    limit = limit_s(reading)
    if limit:
        out.append(Measure(label="length", status="met" if n["take_s"] <= limit else "missed",
                           detail=f"{n['take_s']} s of takes against a limit of {limit:g} s (the given {reading.guide_s:g} s + "
                                  f"{LENGTH_MARGIN:.0%}); the must clips alone are {n['must_take_s']} s"))
    out.append(Measure(label="bin", status="info", detail=f"{n['clips']} clips: {n['must']} must, {n['should']} should, "
                       f"{n['nice']} nice; {n['take_s']} s of takes, {n['must_take_s']} s of them must"))
    spoken = [b for b in reading.scene.lines if b.line_id and not (is_heard(b) or is_voice_over(b))]
    thin = []
    for b in spoken:
        sizes = {c.size for c in work.clips if b.index in c.blocks}
        if len(sizes) < 3:
            thin.append(f"b{b.index}")
    out.append(Measure(label="angles on spoken moments", status="missed" if thin else "met",
                       detail=("fewer than 3 sizes on " + ", ".join(thin)) if thin else "3 or more sizes on every spoken line"))
    reactions = [c for c in work.clips if c.role == "reaction"]
    out.append(Measure(label="reactions", status="met" if reactions else "missed", detail=f"{len(reactions)} reaction clip(s)"))
    cover = [c for c in work.clips if c.role in ("establishing", "atmosphere", "cutaway", "insert")]
    out.append(Measure(label="inserts and B-roll", status="met" if cover else "missed",
                       detail=f"{len(cover)} establishing / atmosphere / cutaway / insert clip(s)"))
    aerial = [c for c in work.clips if c.technique.startswith("drone") or c.technique in ("top_down", "orbit")]
    out.append(Measure(label="aerial", status="info", detail=f"{len(aerial)} aerial clip(s)"))
    handled = [c for c in work.clips if c.handle_in_s >= 0.5 and c.handle_out_s >= 0.5]
    out.append(Measure(label="handles", status="met" if len(handled) == len(work.clips) else "missed",
                       detail=f"{len(handled)} of {len(work.clips)} clips have a handle of at least half a second each side"))
    techs = sorted({c.technique for c in work.clips if c.technique != "locked_off"})
    out.append(Measure(label="techniques used", status="info", detail=", ".join(techs) or "none"))
    return out


# ── mend and the look sheet (plan B §2.2, §2.4): code fixes only what needs no judgement ─────────


def mend(reading: Reading, work: Bin) -> list[str]:
    """Fix in code what needs no judgement, and say what was fixed. Never deletes a clip, never trims a line, never changes
    a picture. Three things:
      1. a handle outside 0 to 2 s is clamped into it;
      2. a line that no must clip carries, whose block one or more must clips cover, gets its id on the first of them (run 2's
         L16 and L22: the clip covered the block and listed no id; a clip that already carries the line is not touched);
      3. a take whose handles do not fit is rounded up to the next of 4 / 6 / 8 s that holds them, when the bin stays within
         its length limit. A line that overruns its take is reported, never mended.
    """
    scene, notes = reading.scene, []
    for c in work.clips:
        for name in ("handle_in_s", "handle_out_s"):
            h = getattr(c, name)
            clamped = min(max(h, 0.0), HANDLE_MAX_S)
            if clamped != h:
                setattr(c, name, clamped)
                notes.append(f"{c.id}: {name} {h:g} s was outside 0 to {HANDLE_MAX_S:g} s, set to {clamped:g} s")
    for block in scene.lines:
        lid = block.line_id
        if not lid or any(lid in c.lines for c in work.clips if c.priority == "must"):
            continue
        covering = [c for c in work.clips if c.priority == "must" and block.index in c.blocks]
        if covering:
            covering[0].lines = [*covering[0].lines, lid]
            notes.append(f"{covering[0].id}: line {lid} added (it covers block b{block.index} and no must clip carried the line)")
    limit = limit_s(reading)
    for c in work.clips:
        items = _items(scene, c)
        spoken = any(i.is_line for i in items)
        need = need_s(items) if items else 0.0
        if _fits(c, c.take_s, need, spoken) or (spoken and need > c.take_s + 1e-9):
            continue  # it fits already, or it is a line overrun (reported, never mended)
        total = sum(x.take_s for x in work.clips)
        for take in (4, 6, 8):
            if take > c.take_s and _fits(c, take, need, spoken) and (not limit or total - c.take_s + take <= limit + 1e-9):
                notes.append(f"{c.id}: take {c.take_s} s rounded up to {take} s to hold its handles")
                c.take_s = cast("Literal[4, 6, 8]", take)  # one of 4 / 6 / 8, as the schema holds it
                break
    return notes


def apply_looks(work: Bin) -> int:
    """Write the look sheet into every designed clip, overwriting what the writer wrote, and return how many fields changed.
    A moment's setting and lighting go into `setting`, `lighting`, `first_frame.setting` and `first_frame.lighting`, and each
    person's description into the subject with their id. Aerial, establishing and atmosphere clips show another view of the
    place, so their setting and lighting stay the writer's own; their people are still copied."""
    sheet = {m.moment: m for m in work.looks}
    changed = 0
    for c in work.clips:
        look = sheet.get(c.moment)
        if c.ir is None or look is None:
            continue
        frame = c.ir.get("first_frame")
        if not (c.role in ("establishing", "atmosphere") or c.technique in AERIAL):
            for key, value in (("setting", look.setting), ("lighting", look.lighting)):
                if c.ir.get(key) != value:
                    c.ir[key] = value
                    changed += 1
                if isinstance(frame, dict) and key in frame and frame[key] != value:
                    frame[key] = value
                    changed += 1
        people = {p.id: p.description for p in look.people}
        for s in c.ir.get("subjects") or []:
            if isinstance(s, dict) and s.get("id") in people and s.get("description") != people[str(s["id"])]:
                s["description"] = people[str(s["id"])]
                changed += 1
    return changed
