"""The scene as Zora sees it: clips read from the shot rows, never from a planner (plan/2026-11-12d §3.1).

    Coverage.load(path)          the exported scene (`export.py`): blocks, lines, clips in row order
    cov.copy()                   a deep copy, for trying an edit
    cov.render(only=None)        the addressable text the conductor and the author read
    cov.number_of(h) / at(n)     a clip's number now (S01 is the first row) / the clip at a number
    cov.fingerprint()            what a card was made on (Accept is refused when it changed)
    cov.to_rows()                the clips back as shot rows (ids kept), for the result files

Clips may overlap: several clips can show the same block (coverage). A line is PERFORMED by exactly one clip
(`dialogue_lines.shot_id`); other clips over its block play it silent or under it.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

Row = dict[str, Any]
SIZES = ("WIDE", "MS", "MCU", "CU", "TWO", "OTS", "INSERT")  # the database's list (shots.framing)
TAKES = (4, 6, 8)
LINKS = ("cut", "continuous", "match")
CINE = ("angle", "lens", "movement")  # read from and written to ir.cinematography
IR_TEXT = ("setting", "lighting", "audio")  # plain text parts of the IR
IR_JSON = ("beats", "subjects", "first_frame")  # structured parts of the IR (the author writes them whole)


@dataclass
class Block:
    index: int
    kind: str
    text: str
    speaker: str = ""
    line: str = ""  # "L2" for a dialogue block


@dataclass
class Line:
    lid: str  # "L2": the block it sits in
    row_id: str
    block: int
    speaker: str
    text: str  # verbatim, read-only
    delivery: str
    words: int
    by: str = ""  # the handle of the clip that performs it, "" = none


@dataclass
class Clip:
    h: str  # stable handle for the whole thread (h1.. for loaded rows, n1.. for new clips)
    row_id: str
    slate: str
    role: str
    priority: str
    stage: int
    anchor: list[str]
    blend: str
    size: str
    take_s: int
    link: str
    sound_mode: str
    first: int  # blocks [first, last)
    last: int
    why: str  # intent.purpose
    sees: str  # intent.what_we_see
    on_screen: list[str]  # names
    sound: Row  # ambience, effects, music, silence
    ir: Row
    heard: list[str]  # line ids heard on this clip (card.lines), performed or not
    locks: set[str] = field(default_factory=set)  # "take_s", "size", "angle" ...
    new: bool = False

    @property
    def blocks(self) -> list[int]:
        return list(range(self.first, self.last))

    def cine(self, key: str) -> str:
        c = self.ir.get("cinematography")
        return str((c or {}).get(key) or "") if isinstance(c, dict) else ""


@dataclass
class Coverage:
    heading: str
    target_s: int
    blocks: list[Block]
    lines: dict[str, Line]
    clips: list[Clip]
    names: dict[str, str]  # character id → name
    source: Row  # the exported file, for writing rows back
    next_new: int = 1

    # ── loading ──────────────────────────────────────────────────────────────────────────────────────────────

    @classmethod
    def load(cls, path: Path) -> Coverage:
        return cls.from_data(json.loads(path.read_text(encoding="utf-8")))

    @classmethod
    def from_data(cls, data: Row) -> Coverage:
        """`{"production", "scene", "shots", "lines", "characters"}` (the export's shape) → the scene as clips."""
        scene = data["scene"]
        names = {str(c["id"]): str(c["name"]) for c in data["characters"]}
        names.update({str(c["code"]): str(c["name"]) for c in data["characters"] if c.get("code")})
        script = scene["script"] if isinstance(scene["script"], list) else json.loads(scene["script"])
        line_rows = sorted(data["lines"], key=lambda r: int(r["ord"]))
        by_row = {str(r["id"]): r for r in line_rows}
        blocks: list[Block] = []
        lines: dict[str, Line] = {}
        spoken = iter(line_rows)
        for i, b in enumerate(script):
            kind = str(b.get("kind") or "action")
            if kind == "dialogue":
                row = by_row.get(str(b.get("line_id"))) if b.get("line_id") else None
                row = row or next(spoken)
                lid = f"L{i}"
                lines[lid] = Line(lid, str(row["id"]), i, str(row["speaker"]), str(row["text"]),
                                  str(row.get("delivery") or ""), int(row.get("words") or len(str(row["text"]).split())))
                blocks.append(Block(i, kind, "", str(row["speaker"]), lid))
            else:
                blocks.append(Block(i, kind, str(b.get("text") or "")))
        clips = []
        for n, r in enumerate(data["shots"], start=1):
            card, intent = r.get("card") or {}, r.get("intent") or {}
            locks = {"take_s"} if r.get("duration_locked") else set()
            locks |= {k for k in (r.get("camera_overrides") or {})}
            clips.append(Clip(
                h=f"h{n}", row_id=str(r["id"]), slate=str(r.get("slate") or ""), role=str(r.get("role") or ""),
                priority=str(r.get("priority") or ""), stage=int(r.get("stage") or 0), anchor=list(r.get("anchor") or []),
                blend=str(r.get("blend") or ""), size=str(r["framing"]), take_s=int(r["duration_s"]),
                link=str(r.get("camera_link") or "cut"), sound_mode=str(r.get("sound_mode") or "ambient"),
                first=int(r["block_start"]), last=int(r["block_end"]), why=str(intent.get("purpose") or ""),
                sees=str(intent.get("what_we_see") or ""),
                on_screen=[names.get(str(x), str(x)) for x in intent.get("on_screen") or []],
                sound=dict(card.get("sound") or {}), ir=dict(r.get("ir") or {}),
                heard=[str(x.get("line_id")) for x in card.get("lines") or [] if x.get("line_id")], locks=locks))
        cov = cls(heading=str(scene["heading"]), target_s=int(scene.get("envelope_s") or 0), blocks=blocks, lines=lines,
                  clips=clips, names=names, source=data)
        by_row_clip = {c.row_id: c.h for c in clips}
        for ln in lines.values():
            row = by_row[ln.row_id]
            ln.by = by_row_clip.get(str(row.get("shot_id")), "")
        return cov

    # ── addressing ───────────────────────────────────────────────────────────────────────────────────────────

    def copy(self) -> Coverage:
        return copy.deepcopy(self)

    def clip(self, h: str) -> Clip | None:
        return next((c for c in self.clips if c.h == h), None)

    def number_of(self, h: str) -> int | None:
        return next((i for i, c in enumerate(self.clips, start=1) if c.h == h), None)

    def code(self, h: str) -> str:
        n = self.number_of(h)
        return f"S{n:02d}" if n else h

    def at(self, ref: Any) -> Clip | None:
        """A clip by its number now: 5, "5", "S05", "s5"."""
        text = str(ref or "").strip().upper().lstrip("S")
        if not text.isdigit():
            return None
        n = int(text)
        return self.clips[n - 1] if 1 <= n <= len(self.clips) else None

    def performs(self, h: str) -> list[Line]:
        return [ln for ln in self.lines.values() if ln.by == h]

    def new_handle(self) -> str:
        h = f"n{self.next_new}"
        self.next_new += 1
        return h

    def fingerprint(self) -> str:
        state = [(c.h, c.size, c.take_s, c.link, c.first, c.last, c.role, c.priority, c.why, c.sees,
                  json.dumps(c.ir, sort_keys=True), json.dumps(c.sound, sort_keys=True)) for c in self.clips]
        state.append(tuple(sorted((ln.lid, ln.by) for ln in self.lines.values())))
        return hashlib.sha256(json.dumps(state, default=str).encode()).hexdigest()[:16]

    def total_s(self) -> int:
        return sum(c.take_s for c in self.clips)

    # ── what the models read ─────────────────────────────────────────────────────────────────────────────────

    def block_text(self, b: Block) -> str:
        if b.line:
            ln = self.lines[b.line]
            delivery = f" ({ln.delivery})" if ln.delivery else ""
            return f"b{b.index} line {ln.lid}, {ln.speaker}{delivery}: “{ln.text}” ({ln.words} words)"
        return f"b{b.index} {b.kind}: {b.text}"

    def clip_head(self, c: Clip) -> str:
        span = ",".join(f"b{i}" for i in c.blocks) or "no block"
        perf = self.performs(c.h)
        does = f" · performs {', '.join(f'{ln.lid} ({ln.speaker})' for ln in perf)}" if perf else ""
        heard = [x for x in c.heard if x not in {ln.lid for ln in perf}]
        under = f" · hears {', '.join(heard)} (silent or under)" if heard else ""
        cine = "anchor " + ",".join(c.anchor) + f" ({c.blend})" if c.anchor else ""
        locked = f" [locked: {', '.join(sorted(c.locks))}]" if c.locks else ""
        role = f"{c.priority or '-'} {c.role or '-'}"
        slate = f"[{c.slate}] " if c.slate else ("[new] " if c.new else "")  # a classic shot has no slate
        return (f"{self.code(c.h)} {slate}{role} {c.size} {c.take_s}s {c.link} · {span}{does}{under}"
                f"{' · ' + cine if cine else ''} · on screen: {', '.join(c.on_screen) or '-'}{locked}")

    def clip_detail(self, c: Clip, drop: tuple[str, ...] = ()) -> str:
        sound = "; ".join(f"{k} {c.sound.get(k)}" for k in ("ambience", "effects", "music") if c.sound.get(k))
        if c.sound.get("silence"):
            sound += "; silence"
        out = [self.clip_head(c), f"   why: {c.why or '(empty: needs writing)'}", f"   sees: {c.sees or '(empty)'}",
               f"   camera: angle {c.cine('angle') or '-'}; lens {c.cine('lens') or c.cine('camera') or '-'}; "
               f"movement {c.cine('movement') or '-'}", f"   sound: {sound or '-'}"]
        for k in IR_TEXT:
            if c.ir.get(k):
                out.append(f"   {k}: {c.ir[k]}")
        for k in IR_JSON:
            if c.ir.get(k) and k not in drop:
                out.append(f"   {k}: {json.dumps(c.ir[k], ensure_ascii=False)}")
        return "\n".join(out)

    def render(self, only: set[str] | None = None, *, detail: bool = True, drop: tuple[str, ...] = (),
               brief: bool = False) -> str:
        """The scene for a model. `only`: the handles shown in full (the rest one line each); None = all in full.
        `drop`: structured IR parts left out of the full clips (run 4: a whole-scene task without subjects and first
        frames costs a third of the tokens)."""
        musts = sum(c.take_s for c in self.clips if c.priority == "must")
        head = (f"SCENE: {self.heading}\nTARGET LENGTH: {self.target_s} s of screen time. TAKES: {self.total_s()} s in "
                f"{len(self.clips)} clips ({musts} s in must clips).\nThis is COVERAGE: clips overlap, several clips "
                "may show the same block (a master, singles, reactions, inserts); the editor cuts between them. Each "
                "line is performed by exactly one clip; other clips over its block play silent or under it.")
        blocks = "BLOCKS (the script, read-only)\n" + "\n".join(self.block_text(b) for b in self.blocks)
        rows = []
        for c in self.clips:
            full = detail and (only is None or c.h in only)
            if full:
                rows.append(self.clip_detail(c, drop))
            elif brief:  # run 6: the head, the reason and the camera, without the IR (a whole-scene task's view)
                rows.append(f"{self.clip_head(c)}\n   why: {c.why or '(empty)'}\n   camera: {c.cine('angle') or '-'}; "
                            f"{c.cine('lens') or c.cine('camera') or '-'}; {c.cine('movement') or '-'}")
            else:
                rows.append(self.clip_head(c))
        return f"{head}\n\n{blocks}\n\nCLIPS (in the order of the intended cut)\n" + "\n".join(rows)

    # ── back to rows ─────────────────────────────────────────────────────────────────────────────────────────

    def to_rows(self) -> list[Row]:
        old = {str(r["id"]): r for r in self.source["shots"]}
        ids = {v: k for k, v in self.names.items() if len(k) > 8}  # name → character id
        out = []
        for n, c in enumerate(self.clips, start=1):
            base = dict(old.get(c.row_id) or {})
            card = dict(base.get("card") or {})
            card.update({"size": c.size, "take_s": c.take_s, "use_s": c.take_s, "sound": c.sound,
                         "lines": [{"line_id": x, "on_speaker": any(ln.lid == x for ln in self.performs(c.h)),
                                    "over_whom": ""} for x in c.heard]})
            intent = dict(base.get("intent") or {})
            intent.update({"purpose": c.why, "what_we_see": c.sees, "on_screen": [ids.get(x, x) for x in c.on_screen]})
            base.update({"id": c.row_id or f"new:{c.h}", "number": n, "framing": c.size, "duration_s": c.take_s,
                         "camera_link": c.link, "sound_mode": c.sound_mode, "block_start": c.first, "block_end": c.last,
                         "role": c.role, "priority": c.priority, "slate": c.slate, "anchor": c.anchor, "blend": c.blend,
                         "card": card, "intent": intent, "ir": c.ir, "title": " ".join(c.why.split()[:8])})
            out.append(base)
        return out
