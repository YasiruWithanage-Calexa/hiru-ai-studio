"""The row kernel (plan/2026-11-13 §3.2): typed edits to a `Coverage`, applied in code. No model, no planner.

    k = Kernel(cov)
    res = k.apply(ops, by="conductor" | "person" | "code" | "author" | "repair")
    res.applied, res.rejected, res.notes     what landed, what was refused (with the reason), what code did on its own

Guarantees: shots are named by their number AT THE START of the batch and resolved to handles once, so two edits in one
batch never shift each other; a bad operation is rolled back alone; removals land all or none; a model (`author`,
`repair`) never writes a field a person locked, while the person's own words (`conductor`, `person`) may, and what they
set becomes locked (`code` writes without locking); no operation writes a line's words. For coverage: clips may
overlap, and a line follows the clip that performs it, voiced on screen when its speaker is in the clip and off screen
when not.

Operations (flat objects, unused fields null):
    set         shot, field, value      size | link | why | sees | angle | lens | movement | setting | lighting |
                                        audio | beats | subjects | first_frame (the last three: a JSON string, whole)
    retime      shot, take_s            4 | 6 | 8
    sound       shot, field, value      ambience | effects | music | silence ("true"/"false")
    sound_mode  shot, value             dialogue | voiceover | sung | ambient | music_only | silent
    role        shot, role, priority
    insert      after, role, size, take_s, first_block, last_block, who, what   a new clip ("start" = before S01)
    remove      shot
    split       shot, at_block
    merge       shot, to_shot           the second clip folds into the first
    move        shot, after
    line        line, to_shot           the clip that performs a line
    note        shot, value             the DoP note (`person_edits.dop_note`): what the shot shows that its fields
                                        cannot say, plain words, at most 600 characters ("" clears it)

Ported from `lab/zora_rows/kernel.py`; `sound_mode` and the voicing of a moved line are new (§3.7); `note` is Sable's
(plan/2026-11-13 phase 8: Sable's change cards go through this kernel).
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Any

from contracts.coverage.scene import (
    CINE,
    IR_JSON,
    IR_TEXT,
    LINKS,
    PRIORITIES,
    SIZES,
    SOUND_MODES,
    TAKES,
    VOICED,
    Clip,
    Coverage,
    lock_key,
)

Row = dict[str, Any]
OPS = ("set", "retime", "sound", "sound_mode", "role", "insert", "remove", "split", "merge", "move", "line",
       "note")
NOTE_MAX = 600  # `contracts.producer.PersonEdits.dop_note`
SET_FIELDS = ("size", "link", "why", "sees", *CINE, *IR_TEXT, *IR_JSON)
SOUND_FIELDS = ("ambience", "effects", "music", "silence")
PROSE = ("why", "sees", *IR_TEXT, *IR_JSON)  # authored text: the conductor may write it only in the person's words
PERFORMERS = ("master", "two_shot", "single", "ots", "wide")  # roles that can carry a line on the speaker
MODELS = ("author", "repair")
PEOPLE = ("conductor", "person")  # what they set is locked
WRITERS = (*MODELS, *PEOPLE, "code")


class Refused(Exception):
    pass


@dataclass
class Result:
    applied: list[Row] = field(default_factory=list)
    rejected: list[Row] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _short(v: Any, n: int = 60) -> str:
    text = " ".join(str(v if v not in (None, "") else "-").split())
    return text if len(text) <= n else text[: n - 1] + "…"


class Kernel:
    def __init__(self, cov: Coverage) -> None:
        self.cov = cov

    # ── applying a batch ─────────────────────────────────────────────────────────────────────────────────────

    def apply(self, ops: list[Row], *, by: str) -> Result:
        if by not in WRITERS:
            raise ValueError(f"unknown writer {by!r}")
        res = Result()
        start = {n: c.h for n, c in enumerate(self.cov.clips, start=1)}  # numbers as at the start of the batch
        removals = [o for o in ops if o.get("op") == "remove"]
        if len(removals) > 1:  # all or none: try them together on a copy first
            trial = Kernel(self.cov.copy())
            for o in removals:
                try:
                    trial._one(o, by, start, Result())
                except Refused as exc:
                    for r in removals:
                        res.rejected.append({"op": r, "reason": f"removals land together or not at all: {exc}"})
                    ops = [o for o in ops if o.get("op") != "remove"]
                    break
        for o in ops:
            snap = copy.deepcopy(self.cov)
            try:
                text = self._one(o, by, start, res)
                res.applied.append({"op": o, "by": by, "text": text})
            except Refused as exc:
                self.cov.__dict__.update(snap.__dict__)
                res.rejected.append({"op": o, "reason": str(exc)})
        return res

    def _clip(self, ref: Any, start: dict[int, str]) -> Clip:
        text = str(ref if ref is not None else "").strip().upper().lstrip("S")
        h = start.get(int(text)) if text.isdigit() else None
        c = self.cov.clip(h) if h else None
        if c is None:
            raise Refused(f"there is no shot {ref}")
        return c

    def _guard(self, c: Clip, op: Row, by: str) -> None:
        key = lock_key(op)
        if by in MODELS and key and key in c.locks:
            raise Refused(f"{self.cov.code(c.h)}'s {key} was set by a person (locked)")

    def _voice(self, c: Clip) -> None:
        """A clip's sound mode follows the lines it performs: voiced (on or off screen) while it performs one; a clip
        that stopped performing goes back to its ambience (it would otherwise speak a line another clip performs)."""
        mode = self.cov.voice_for(c)
        if mode:
            c.sound_mode = mode
        elif c.sound_mode in ("dialogue", "voiceover"):
            c.sound_mode = "ambient"

    def _one(self, o: Row, by: str, start: dict[int, str], res: Result) -> str:
        name = str(o.get("op") or "")
        if name not in OPS:
            raise Refused(f"unknown operation {name!r}")
        cov = self.cov
        old: Any
        if name == "insert":
            return self._insert(o, start, by)
        if name == "line":
            return self._line(o, start)
        c = self._clip(o.get("shot"), start)
        code = cov.code(c.h)
        self._guard(c, o, by)
        if name == "set":
            return self._set(c, o, by)
        if name == "note":
            note = " ".join(str(o.get("value") or "").split())
            if len(note) > NOTE_MAX:
                raise Refused(f"a DoP note is at most {NOTE_MAX} characters, not {len(note)}")
            if note == c.note:
                raise Refused(f"{code}'s DoP note is already that")
            old, c.note = c.note, note
            return f"{code} · DoP note: {_short(old)} → {_short(note)}"
        if name == "retime":
            t = int(o.get("take_s") or 0)
            if t not in TAKES:
                raise Refused(f"a take is 4, 6 or 8 s, not {o.get('take_s')}")
            if t == c.take_s:
                raise Refused(f"{code} is already {t} s")
            old, c.take_s = c.take_s, t
            if by in PEOPLE:
                c.locks.add("take_s")
            return f"{code} · take: {old} s → {t} s"
        if name == "sound":
            f, v = str(o.get("field") or ""), o.get("value")
            if f not in SOUND_FIELDS:
                raise Refused(f"{f!r} is not a sound field")
            v2: Any = str(v).strip().lower() in ("true", "yes", "1") if f == "silence" else str(v or "")
            old = c.sound.get(f)
            if old == v2:
                raise Refused(f"{code}'s {f} is already that")
            c.sound[f] = v2
            if by in PEOPLE:
                c.locks.add("sound")
            return f"{code} · {f}: {_short(old)} → {_short(v2)}"
        if name == "sound_mode":
            v = str(o.get("value") or "").strip().lower()
            if v not in SOUND_MODES:
                raise Refused(f"{v or 'nothing'} is not a sound mode ({', '.join(SOUND_MODES)})")
            perf = cov.performs(c.h)
            if perf and v not in VOICED:
                raise Refused(f"{code} performs {', '.join(ln.lid for ln in perf)}: its sound must voice it "
                              f"({cov.voice_for(c)}); move the line to another clip first")
            if v == c.sound_mode:
                raise Refused(f"{code}'s sound is already {v}")
            old = c.sound_mode
            c.sound_mode = v
            if by in PEOPLE:
                c.locks.add("sound_mode")
            return f"{code} · sound mode: {old} → {v}"
        if name == "role":
            role, pr = o.get("role"), o.get("priority")
            if role in PRIORITIES and not pr:  # a priority written in the role field
                role, pr = None, role
            if pr not in (None, "", *PRIORITIES):
                raise Refused(f"{pr} is not a priority (must, should, nice)")
            before = f"{c.priority or '-'} {c.role or '-'}"
            c.role = str(role or c.role)
            c.priority = str(pr or c.priority)
            now = f"{c.priority or '-'} {c.role or '-'}"
            if before == now:
                raise Refused(f"{code} is already {now}")
            return f"{code} · role: {before} → {now}"
        if name == "remove":
            moved = self._rehome(c, exclude={c.h})
            cov.clips.remove(c)
            for other in cov.clips:  # a clip anchored to it loses that anchor
                if c.slate and c.slate in other.anchor:
                    other.anchor = [a for a in other.anchor if a != c.slate]
            res.notes += moved
            return f"{code} removed ({c.priority or '-'} {c.role or '-'} {c.size}, " \
                   f"{', '.join(f'b{i}' for i in c.blocks) or 'no block'})"
        if name == "split":
            raw = o.get("at_block")
            at = int(raw) if raw is not None else -1
            if not c.first < at < c.last:
                raise Refused(f"{code} covers {', '.join(f'b{i}' for i in c.blocks)}: it can only split at a block "
                              "inside it (to cover a block twice, insert a clip)")
            twin = copy.deepcopy(c)
            twin.h, twin.row_id, twin.slate, twin.new = cov.new_handle(), "", "", True
            twin.first, c.last = at, at
            twin.why = twin.sees = ""
            twin.ir = {}
            twin.locks = set()
            cov.clips.insert(cov.clips.index(c) + 1, twin)
            for ln in cov.lines.values():
                if ln.by == c.h and ln.block >= at:
                    ln.by = twin.h
            twin.heard = [x for x in c.heard if x in cov.lines and cov.lines[x].block >= at]
            c.heard = [x for x in c.heard if x not in twin.heard]
            self._voice(c)
            self._voice(twin)
            return f"{code} split at b{at}: {code} keeps b{c.first}-b{at - 1}, a new clip takes b{at}-b{twin.last - 1}"
        if name == "merge":
            other = self._clip(o.get("to_shot"), start)
            if other.h == c.h:
                raise Refused("a shot cannot merge with itself")
            ocode = cov.code(other.h)
            c.first, c.last = min(c.first, other.first), max(c.last, other.last)
            c.take_s = max(c.take_s, other.take_s)
            for ln in cov.lines.values():
                if ln.by == other.h:
                    ln.by = c.h
            c.heard = sorted(set(c.heard) | set(other.heard), key=lambda x: int(x[1:]) if x[1:].isdigit() else 0)
            c.on_screen = list(dict.fromkeys(c.on_screen + other.on_screen))
            c.why = c.sees = ""
            c.ir = {}
            cov.clips.remove(other)
            self._voice(c)
            return f"{ocode} merged into {code} (now b{c.first}-b{c.last - 1}, {c.take_s} s; its picture needs writing)"
        # move
        after = o.get("after")
        cov.clips.remove(c)
        if str(after).lower() == "start":
            cov.clips.insert(0, c)
        else:
            anchor = self._clip(after, start)
            if anchor.h == c.h:
                raise Refused("a shot cannot move after itself")
            cov.clips.insert(cov.clips.index(anchor) + 1, c)
        return f"{code} moved to {cov.code(c.h)}"

    def _set(self, c: Clip, o: Row, by: str) -> str:
        code = self.cov.code(c.h)
        f, v = str(o.get("field") or ""), o.get("value")
        if f not in SET_FIELDS:
            raise Refused(f"{f!r} is not a field Zora writes")
        if v is None:
            raise Refused(f"no value for {code}'s {f}")
        old: Any
        if f == "size":
            v = str(v).upper()
            if v not in SIZES:
                raise Refused(f"{v} is not a size ({', '.join(SIZES)})")
            old, c.size = c.size, v
        elif f == "link":
            if v not in LINKS:
                raise Refused(f"{v} is not a join ({', '.join(LINKS)})")
            old, c.link = c.link, str(v)
        elif f == "why":
            old, c.why = c.why, str(v)
        elif f == "sees":
            old, c.sees = c.sees, str(v)
        elif f in CINE:
            cine = dict(c.ir.get("cinematography") or {})
            old = str(cine.get(f) or "")
            cine[f] = str(v)
            c.ir["cinematography"] = cine
        elif f in IR_TEXT:
            old, c.ir[f] = str(c.ir.get(f) or ""), str(v)
        else:  # beats, subjects, first_frame: JSON, whole
            try:
                parsed = json.loads(v) if isinstance(v, str) else v
            except ValueError as exc:
                raise Refused(f"{code}'s {f} is not valid JSON") from exc
            if f in ("beats", "subjects") and not isinstance(parsed, list):
                raise Refused(f"{code}'s {f} must be a list")
            if json.dumps(parsed, sort_keys=True) == json.dumps(c.ir.get(f), sort_keys=True):
                raise Refused(f"{code}'s {f} is already that")
            old, c.ir[f] = "(was set)" if c.ir.get(f) else "", parsed
            v = f"({len(parsed) if isinstance(parsed, list) else 1} written)"
        if str(old) == str(v):
            raise Refused(f"{code}'s {f} is already {v}")
        if by in PEOPLE:
            c.locks.add(f)  # what a person says becomes theirs
        return f"{code} · {f}: {_short(old)} → {_short(v)}"

    def _line(self, o: Row, start: dict[int, str]) -> str:
        cov = self.cov
        lid = str(o.get("line") or "").upper()
        ln = cov.lines.get(lid)
        if ln is None:
            raise Refused(f"there is no line {o.get('line')}")
        to = self._clip(o.get("to_shot"), start)
        if ln.block not in to.blocks:
            raise Refused(f"{cov.code(to.h)} does not cover b{ln.block}, where {lid} is said")
        if ln.by == to.h:
            raise Refused(f"{cov.code(to.h)} already performs {lid}")
        old = cov.clip(ln.by) if ln.by else None
        was = cov.code(ln.by) if ln.by else "no clip"
        ln.by = to.h
        if lid not in to.heard:
            to.heard.append(lid)
        self._voice(to)  # on screen → dialogue, else voiced off screen (the lab always wrote dialogue)
        if old is not None:
            self._voice(old)
        how = "on screen" if to.sound_mode == "dialogue" else "voiced off screen"
        return f"{lid} ({ln.speaker}) now performed by {cov.code(to.h)} ({how}; was {was})"

    def _insert(self, o: Row, start: dict[int, str], by: str) -> str:
        cov = self.cov
        given_size = bool(o.get("size"))
        size = str(o.get("size") or ("INSERT" if str(o.get("role") or "insert") == "insert" else "MS")).upper()
        if size not in SIZES:
            raise Refused(f"{size} is not a size ({', '.join(SIZES)})")
        take = int(o.get("take_s") or 4)
        if take not in TAKES:
            raise Refused(f"a take is 4, 6 or 8 s, not {take}")
        first = o.get("first_block")
        last = o.get("last_block")
        first = int(first) if first is not None else 0
        last = int(last) if last is not None else first
        if not 0 <= first <= last < len(cov.blocks):
            raise Refused(f"blocks b{first}-b{last} are not in the scene (b0-b{len(cov.blocks) - 1})")
        who = [str(w) for w in o.get("who") or []]
        role, priority = str(o.get("role") or "insert"), str(o.get("priority") or "should")
        if role in PRIORITIES:  # a priority written in the role field
            role, priority = "insert" if size == "INSERT" else "single", role
        locks = ({"size"} if given_size else set()) | ({"sees"} if o.get("what") else set()) if by in PEOPLE else set()
        clip = Clip(h=cov.new_handle(), row_id="", slate="", role=role, priority=priority, stage=0, anchor=[], blend="",
                    size=size, take_s=take, link="cut", sound_mode="ambient", first=first, last=last + 1, why="",
                    sees=str(o.get("what") or ""), on_screen=who, sound={}, ir={},
                    heard=[ln.lid for ln in cov.lines.values() if first <= ln.block <= last], new=True,
                    # the person's own words are locked; a default (lab run 2: MS) never is
                    locks=locks)
        after = o.get("after")
        if after is None or str(after).lower() == "start":
            cov.clips.insert(0, clip)
        else:
            anchor = self._clip(after, start)
            cov.clips.insert(cov.clips.index(anchor) + 1, clip)
        return f"new {cov.code(clip.h)}: {size} {clip.role}, b{first}-b{last}, {take} s (its picture needs writing)"

    def _rehome(self, gone: Clip, *, exclude: set[str]) -> list[str]:
        """The lines `gone` performs move to the clip that best keeps them: one that covers the line's block and has
        the speaker on screen, a master, two-shot or single before a reaction or insert, must before should. A line
        with no such clip is left unbound (the checks report it, and the risk rule asks the person)."""
        cov, notes = self.cov, []
        for ln in cov.performs(gone.h):
            fits = [c for c in cov.clips if c.h not in exclude and ln.block in c.blocks]
            seen = [c for c in fits if ln.speaker in c.on_screen]
            pick = sorted(seen, key=lambda c: (c.role not in PERFORMERS, c.priority != "must", cov.clips.index(c)))
            if pick:
                to = pick[0]
                ln.by = to.h
                if ln.lid not in to.heard:
                    to.heard.append(ln.lid)
                self._voice(to)
                notes.append(f"{ln.lid} ({ln.speaker}'s line) moves to the {to.role or 'clip'} {to.size} "
                             f"[{to.slate or 'new'}], which shows {ln.speaker}")
            else:
                ln.by = ""
                notes.append(f"{ln.lid} ({ln.speaker}'s line) has no other clip showing {ln.speaker}: it is unbound")
        return notes
