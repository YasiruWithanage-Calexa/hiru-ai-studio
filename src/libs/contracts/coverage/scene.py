"""The scene as Zora sees it: clips read from the shot rows, never from a planner (plan/2026-11-13 §3.1).

    Coverage.from_rows(scene, shots, lines, characters)   the rows the ports return, in row order
    cov.copy()                   a deep copy, for trying an edit
    cov.render(only=None)        the addressable text the conductor and the author read
    cov.number_of(h) / at(n)     a clip's number now (S01 is the first row) / the clip at a number
    cov.fingerprint()            what a card was made on (Accept is refused when it changed)
    cov.row_of(clip)             the clip back as a full shot row (ids kept; fields the contract does not name carried)

Clips may overlap: several clips can show the same block (coverage). A line is PERFORMED by exactly one clip
(`dialogue_lines.shot_id`); other clips over its block play it silent or under it. A line's id for the models is
`L<block index>`, as Raphael's cards write it.

Never read here: `scenes.raphael`, `scenes.jonathan`, `scenes.david`, `scenes.adam`, `scenes.coverage` (a planner's
own JSON). Ported from `lab/zora_rows/coverage.py`.
"""
from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from contracts.timing import word_target
from contracts.veo import SoundMode

Row = dict[str, Any]
SIZES = ("WIDE", "MS", "MCU", "CU", "TWO", "OTS", "INSERT")  # the database's list (shots.framing)
TAKES = (4, 6, 8)
LINKS = ("cut", "continuous", "match")
CINE = ("angle", "lens", "movement")  # read from and written to ir.cinematography
IR_TEXT = ("setting", "lighting", "audio")  # plain text parts of the IR
IR_JSON = ("beats", "subjects", "first_frame")  # structured parts of the IR (the author writes them whole)
SOUND_MODES = ("dialogue", "voiceover", "sung", "ambient", "music_only", "silent")
VOICED = ("dialogue", "voiceover", "sung")  # a clip that performs a line carries one of these
PRIORITIES = ("must", "should", "nice")


def lock_key(op: Mapping[str, Any]) -> str:
    """The lock an operation would write: "take_s", "size", "angle" ... ("" when none applies)."""
    name = op.get("op")
    if name == "retime":
        return "take_s"
    if name == "set":
        return str(op.get("field") or "")
    if name == "sound":
        return "sound"
    if name == "sound_mode":
        return "sound_mode"
    return ""


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
    character_id: str = ""
    by: str = ""  # the handle of the clip that performs it, "" = none


@dataclass
class Clip:
    h: str  # stable handle for the turn (h1.. for loaded rows, n1.. for new clips)
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
    note: str = ""  # the DoP note (`person_edits.dop_note`): what the shot shows that its fields cannot say

    @property
    def blocks(self) -> list[int]:
        return list(range(self.first, self.last))

    def cine(self, key: str) -> str:
        c = self.ir.get("cinematography")
        return str((c or {}).get(key) or "") if isinstance(c, dict) else ""

    def content(self) -> tuple[Any, ...]:
        """Everything a save writes for this clip: two clips with the same content are the same row."""
        return (self.size, self.take_s, self.link, self.sound_mode, self.first, self.last, self.role, self.priority,
                self.why, self.sees, tuple(self.on_screen), json.dumps(self.ir, sort_keys=True, default=str),
                json.dumps(self.sound, sort_keys=True, default=str), tuple(self.heard), tuple(sorted(self.locks)),
                tuple(self.anchor), self.note)


def _obj(value: Any) -> Row:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return dict(value) if isinstance(value, dict) else {}


def _take(seconds: Any) -> int:
    """A stored length as a take Veo makes (4 / 6 / 8 s)."""
    try:
        s = int(float(seconds or 0))
    except (TypeError, ValueError):
        s = 0
    return 4 if s <= 4 else 6 if s <= 6 else 8


@dataclass
class Coverage:
    heading: str
    target_s: int
    blocks: list[Block]
    lines: dict[str, Line]
    clips: list[Clip]
    names: dict[str, str]  # character id (and code) → name
    rows: dict[str, Row] = field(default_factory=dict)  # row id → the shot row as read (carried through on save)
    line_rows: dict[str, Row] = field(default_factory=dict)  # line row id → the dialogue line row as read
    scene_id: str = ""
    production_id: str = ""
    next_new: int = 1

    # ── loading ──────────────────────────────────────────────────────────────────────────────────────────────

    @classmethod
    def from_rows(cls, scene: Mapping[str, Any], shots: list[Row], lines: list[Row],
                  characters: list[Row] | None = None) -> Coverage:
        """The scene row (`heading`, `envelope_s`, `script`), its shot rows, its dialogue line rows and the production's
        characters (`id`, `name`, `code`), as the ports return them."""
        chars = characters or []
        names = {str(c["id"]): str(c.get("name") or "") for c in chars if c.get("id")}
        names.update({str(c["code"]): str(c.get("name") or "") for c in chars if c.get("code")})
        raw = scene.get("script")
        script = raw if isinstance(raw, list) else (json.loads(raw) if isinstance(raw, str) and raw.strip() else [])
        line_rows = sorted(lines, key=lambda r: int(r.get("ord") or 0))
        by_row = {str(r["id"]): r for r in line_rows}
        used: set[str] = set()
        blocks: list[Block] = []
        out_lines: dict[str, Line] = {}
        spoken = iter(line_rows)
        for i, b in enumerate(script):
            kind = str((b or {}).get("kind") or "action")
            if kind == "dialogue":
                row = by_row.get(str(b.get("line_id"))) if b.get("line_id") else None
                if row is None:  # bound by order to the next line not bound by id
                    row = next((r for r in spoken if str(r["id"]) not in used), None)
                if row is not None:
                    used.add(str(row["id"]))
                    lid = f"L{i}"
                    text = str(row.get("text") or "")
                    out_lines[lid] = Line(lid, str(row["id"]), i, str(row.get("speaker") or ""), text,
                                          str(row.get("delivery") or ""), int(row.get("words") or len(text.split())),
                                          str(row.get("character_id") or ""))
                    blocks.append(Block(i, kind, "", str(row.get("speaker") or ""), lid))
                    continue
            blocks.append(Block(i, kind, str((b or {}).get("text") or "")))
        clips = []
        ordered = sorted(shots, key=lambda r: int(r.get("number") or 0))
        for n, r in enumerate(ordered, start=1):
            card, intent = _obj(r.get("card")), _obj(r.get("intent"))
            edits = _obj(r.get("person_edits"))
            locks = {"take_s"} if r.get("duration_locked") else set()
            locks |= {str(k) for k in _obj(r.get("camera_overrides")) if k in CINE or k == "size"}
            locks |= {str(k) for k in edits.get("zora_locks") or []}
            size = str(r.get("framing") or "MS").upper()
            clips.append(Clip(
                h=f"h{n}", row_id=str(r["id"]), slate=str(r.get("slate") or ""), role=str(r.get("role") or ""),
                priority=str(r.get("priority") or ""), stage=int(r.get("stage") or 0),
                anchor=[str(a) for a in r.get("anchor") or []], blend=str(r.get("blend") or ""),
                size=size if size in SIZES else "MS", take_s=_take(r.get("duration_s")),
                link=str(r.get("camera_link") or "cut"), sound_mode=str(r.get("sound_mode") or "ambient"),
                first=int(r.get("block_start") or 0), last=int(r.get("block_end") or 0),
                why=str(intent.get("purpose") or ""), sees=str(intent.get("what_we_see") or ""),
                on_screen=[names.get(str(x), str(x)) for x in intent.get("on_screen") or []],
                sound=_obj(card.get("sound")), ir=_obj(r.get("ir")),
                heard=[str(x.get("line_id")) for x in card.get("lines") or []
                       if isinstance(x, dict) and x.get("line_id")], locks=locks,
                note=str(edits.get("dop_note") or "") if isinstance(edits.get("dop_note"), str) else ""))
        cov = cls(heading=str(scene.get("heading") or ""), target_s=int(float(scene.get("envelope_s") or 0)),
                  blocks=blocks, lines=out_lines, clips=clips, names=names,
                  rows={str(r["id"]): dict(r) for r in ordered}, line_rows={str(r["id"]): dict(r) for r in line_rows},
                  scene_id=str(scene.get("id") or ""), production_id=str(scene.get("production_id") or ""))
        by_row_clip = {c.row_id: c.h for c in clips}
        for ln in out_lines.values():
            ln.by = by_row_clip.get(str(by_row[ln.row_id].get("shot_id") or ""), "")
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
        text = str(ref if ref is not None else "").strip().upper().lstrip("S")
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

    def voice_for(self, c: Clip) -> str:
        """The sound mode a clip that performs lines must carry: its speaker on screen → dialogue, else voiced off
        screen (as `raphael_write.sound_mode_of`). "" when it performs none."""
        perf = self.performs(c.h)
        if not perf:
            return ""
        if c.sound_mode == "sung":
            return "sung"
        return "dialogue" if any(ln.speaker in c.on_screen for ln in perf) else "voiceover"

    def fingerprint(self) -> str:
        """A short hash of the clips and the line bindings as read: a card made on another state is refused."""
        def key(c: Clip) -> str:
            return c.row_id or c.h

        state: list[Any] = [(key(c), c.content()) for c in self.clips]
        state.append(tuple(sorted((ln.lid, key(cl) if (cl := self.clip(ln.by)) else "") for ln in self.lines.values())))
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
        if perf and c.sound_mode not in VOICED:
            does += f" (stored {c.sound_mode}: the line is not voiced)"
        heard = [x for x in c.heard if x not in {ln.lid for ln in perf}]
        under = f" · hears {', '.join(heard)} (silent or under)" if heard else ""
        cine = "anchor " + ",".join(c.anchor) + f" ({c.blend})" if c.anchor else ""
        locked = f" [locked: {', '.join(sorted(c.locks))}]" if c.locks else ""
        role = f"{c.priority or '-'} {c.role or '-'}"
        return (f"{self.code(c.h)} [{c.slate or 'new'}] {role} {c.size} {c.take_s}s {c.link} · {span}{does}{under}"
                f"{' · ' + cine if cine else ''} · on screen: {', '.join(c.on_screen) or '-'}{locked}")

    def clip_detail(self, c: Clip, drop: tuple[str, ...] = ()) -> str:
        sound = "; ".join(f"{k} {c.sound.get(k)}" for k in ("ambience", "effects", "music") if c.sound.get(k))
        if c.sound.get("silence"):
            sound += "; silence"
        out = [self.clip_head(c), f"   why: {c.why or '(empty: needs writing)'}", f"   sees: {c.sees or '(empty)'}",
               f"   camera: angle {c.cine('angle') or '-'}; lens {c.cine('lens') or c.cine('camera') or '-'}; "
               f"movement {c.cine('movement') or '-'}", f"   sound ({c.sound_mode}): {sound or '-'}"]
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
        `drop`: structured IR parts left out of the full clips. `brief`: the clips not in full show their head, reason
        and camera (a whole-scene task's view: lab run 6)."""
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
            elif brief:
                rows.append(f"{self.clip_head(c)}\n   why: {c.why or '(empty)'}\n   camera: {c.cine('angle') or '-'}; "
                            f"{c.cine('lens') or c.cine('camera') or '-'}; {c.cine('movement') or '-'}")
            else:
                rows.append(self.clip_head(c))
        return f"{head}\n\n{blocks}\n\nCLIPS (in the order of the intended cut)\n" + "\n".join(rows)

    # ── back to rows ─────────────────────────────────────────────────────────────────────────────────────────

    def row_of(self, c: Clip, *, number: int, row_id: str, planner: str = "", now: str = "") -> Row:
        """The clip as a whole shot row. A loaded clip starts from its row as read (every column carried through); a
        new one from its neighbour's row with its identity, frame and design cleared. Derived columns (word target,
        words, speaker) follow the clip."""
        ids = {name: cid for cid, name in self.names.items() if len(cid) > 8}  # name → character id
        base = dict(self.rows.get(c.row_id) or {})
        if not base:
            i = self.clips.index(c)
            near = next((self.rows[x.row_id] for x in [*self.clips[:i][::-1], *self.clips[i + 1:]]
                         if x.row_id in self.rows), {})
            base = {k: None for k in near}
            base.update({k: near[k] for k in ("frame_strategy", "video_settings", "handle_in_s", "handle_out_s")
                         if k in near})
            base.update({"production_id": self.production_id or near.get("production_id"),
                         "scene_id": self.scene_id or near.get("scene_id"), "planner": planner or near.get("planner"),
                         "status": "draft", "version": 0, "design": {}, "camera_overrides": {}, "person_edits": {},
                         "duration_locked": False, "beats": [], "stage": 0, "start_s": 0, "created_at": now or None,
                         "updated_at": now or None})
        card = _obj(base.get("card"))
        perf = self.performs(c.h)
        card.update({"size": c.size, "take_s": c.take_s, "use_s": c.take_s, "sound": c.sound,
                     "lines": [{"line_id": x, "on_speaker": any(ln.lid == x for ln in perf), "over_whom": ""}
                               for x in c.heard]})
        intent = _obj(base.get("intent"))
        intent.update({"purpose": c.why, "what_we_see": c.sees, "on_screen": [ids.get(x, x) for x in c.on_screen]})
        edits = _obj(base.get("person_edits"))
        zora_locks = sorted(k for k in c.locks if k != "take_s")
        if zora_locks:
            edits["zora_locks"] = zora_locks
        else:
            edits.pop("zora_locks", None)
        if c.note:
            edits["dop_note"] = c.note
        else:
            edits.pop("dop_note", None)
        try:
            target = word_target(SoundMode(c.sound_mode), c.take_s)
        except ValueError:
            target = 0
        speaker = next((ln.character_id for ln in perf if ln.character_id), None)
        title = str(base.get("title") or "")
        if not title or c.why != str(_obj(self.rows.get(c.row_id, {}).get("intent")).get("purpose") or ""):
            title = " ".join(c.why.split()[:8]) or f"Shot {number}"
        base.update({"id": row_id, "number": number, "framing": c.size, "duration_s": c.take_s, "camera_link": c.link,
                     "sound_mode": c.sound_mode, "block_start": c.first, "block_end": c.last, "role": c.role or "",
                     "priority": c.priority or "", "slate": c.slate or "", "anchor": list(c.anchor),
                     "blend": c.blend, "card": card, "intent": intent, "ir": c.ir, "title": title,
                     "duration_locked": "take_s" in c.locks, "person_edits": edits, "word_target": target,
                     "words": sum(ln.words for ln in perf), "speaker_id": speaker})
        return base
