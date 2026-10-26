"""The scene-plan EDIT ALGEBRA: a closed set of operations on one scene's shot list, applied in
code. Forked from PromptMotion `nova_chat/studio/ops.py` (PlanKernel, commit 1d748dc); the
document is a Hiru scene (script blocks → shots) instead of a Nova plan.

Models PROPOSE operations; this kernel applies them. The guarantees are upstream's:
  1. Addressing is stable within a batch: operations name shots by their number AT THE START of
     the batch; numbers resolve to handles once, so two splits in one batch cannot shift each
     other.
  2. Undo is exact: every operation snapshots the state first.
  3. A bad operation never corrupts the plan: each is re-fitted (contracts.shotplan) on its own
     and rolled back if the scene stops being a valid plan; the rest of the batch still lands.

Hiru's rules on top:
  * Dialogue is the approved script's, verbatim, and every shot keeps its lines bound by code.
    The words change only through `block.*` operations, which only a PERSON's own words may use
    (`by="you"`): an agent never writes, trims or "improves" a line. The turn stages a dialogue
    change for the person to accept; it is never applied unseen.
  * A length a PERSON set (`duration_locked`) is not changed by an agent; only the person's own
    words (the conductor transcribing them) may change it.
  * A reaction or insert shot with no script under it is a director's BEAT block added to the
    script (`insert`), so the kernel's rule "every block in exactly one shot" still holds.
  * A shot's own marks by a person (who is in it, which advisories to ignore, the DoP's note) are
    `person_edits`, changed by `canon.*`, `check.*` and `dop_note.set`; also person-only.
"""
from __future__ import annotations

import copy
import unicodedata
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from contracts.canon import name_key
from contracts.director import SCRIPT_OPS
from contracts.producer import CHECK_TOPICS, PersonEdits, cast_in, check_code
from contracts.production import BlockKind, Framing
from contracts.shotplan import FitResult, Item, ProposedShot, allowed_durations, fit
from contracts.veo import CameraLink, SoundMode
from director_chat.engine import refusals

MARK_OPS = ("canon.add", "canon.remove", "check.waive", "check.restore", "dop_note.set")
PERSON_ONLY = SCRIPT_OPS + MARK_OPS  # a person's own words only: `by="you"`
MODEL_OPS = ("set", "retime", "unlock_length", "split", "merge", "regroup", "set_join", "beat.set",
             "insert", "remove", "set_envelope", *PERSON_ONLY)
STRUCTURAL_OPS = ("split", "merge", "regroup", "insert", "remove")
SCRIPT_LIMITS = {"text": 2000, "speaker": 120, "delivery": 200}  # as `contracts.director.ScriptBlockEdit`
DOP_NOTE_CHARS = 600
SHOT_TEXT_FIELDS = ("title",)
BEAT_FIELDS = ("camera", "director_line", "action")
_MAX_TEXT = 300
_MAX_OPS = 30


Op = dict[str, Any]
Addr = dict[int, str]  # shot number at the start of the batch → handle


class OpError(ValueError):
    """An operation that cannot be applied, with a reason a person can read."""


@dataclass
class Change:
    kind: str  # "field" | "timing" | "structure" | "join" | "beat" | "envelope"
    handles: tuple[str, ...] = ()
    field: str = ""
    by: str = ""


OpResult = tuple[Op, list["Change"]]


@dataclass
class ApplyResult:
    applied: list[dict[str, Any]] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)
    changes: list[Change] = field(default_factory=list)
    undo: list[tuple[Any, ...]] = field(default_factory=list)

    def extend(self, other: ApplyResult) -> None:
        self.applied += other.applied
        self.rejected += other.rejected
        self.changes += other.changes
        self.undo += other.undo


def _text(value: Any, name: str) -> str:
    if value is None or isinstance(value, (list, dict)):
        raise OpError(f"say what the {name} should be")
    return " ".join(str(value).split())[:_MAX_TEXT]


_FRAMING_WORDS = {
    "WIDE": "WIDE", "WIDE SHOT": "WIDE", "WS": "WIDE", "LONG SHOT": "WIDE", "LS": "WIDE", "ESTABLISHING": "WIDE",
    "MS": "MS", "MEDIUM": "MS", "MEDIUM SHOT": "MS", "MID SHOT": "MS",
    "MCU": "MCU", "MEDIUM CLOSE UP": "MCU", "MEDIUM CLOSEUP": "MCU",
    "CU": "CU", "CLOSE UP": "CU", "CLOSEUP": "CU", "CLOSE": "CU", "ECU": "CU", "EXTREME CLOSE UP": "CU",
    "TWO": "TWO", "TWO SHOT": "TWO", "2 SHOT": "TWO",
    "OTS": "OTS", "OVER THE SHOULDER": "OTS", "OVER SHOULDER": "OTS",
    "INSERT": "INSERT", "INSERT SHOT": "INSERT", "CUTAWAY": "INSERT",
}
_SOUND_WORDS = {
    "dialogue": "dialogue", "voiceover": "voiceover", "voice over": "voiceover", "vo": "voiceover",
    "sung": "sung", "song": "sung", "ambient": "ambient", "ambience": "ambient", "natural sound": "ambient",
    "music_only": "music_only", "music only": "music_only", "music": "music_only", "score": "music_only",
    "silent": "silent", "silence": "silent", "no sound": "silent",
}


def _framing(value: Any) -> str:
    """A model writes "Close-up" or "CU " as often as "CU"; the kernel takes the common names."""
    key = " ".join(str(value or "").upper().replace("-", " ").replace("_", " ").split())
    if key not in _FRAMING_WORDS:
        raise OpError(f"framing must be one of {', '.join(f.value for f in Framing)}")
    return _FRAMING_WORDS[key]


def _sound(value: Any) -> str:
    key = " ".join(str(value or "").lower().replace("-", " ").split())
    found = _SOUND_WORDS.get(key) or _SOUND_WORDS.get(key.replace(" ", "_"))
    if found is None:
        raise OpError(f"sound_mode must be one of {', '.join(m.value for m in SoundMode)}")
    return found


def _script_text(value: Any, name: str) -> str:
    """A script field as a person wrote it: NFC, outer whitespace trimmed. ZWJ and ZWNJ are kept
    (Sinhala conjuncts need them) and the words are never otherwise touched."""
    if value is None or isinstance(value, (list, dict)):
        raise OpError(f"say what the {name} should be")
    text = unicodedata.normalize("NFC", str(value)).strip()
    if len(text) > SCRIPT_LIMITS[name]:
        raise OpError(f"{name} can be at most {SCRIPT_LIMITS[name]} characters")
    return text


def _int(value: Any, name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        raise OpError(f"give the {name} as a whole number") from None


class ScenePlanKernel:
    """One scene's plan: its blocks (script + director beats) and its shots as block ranges."""

    def __init__(self, items: list[dict[str, Any]], shots: list[dict[str, Any]], *, envelope_s: int,
                 fixed_seconds: int | None = None, canon: list[dict[str, Any]] | None = None,
                 location_id: str | None = None) -> None:
        self.items = copy.deepcopy(items)  # {kind, text, line_id, speaker, speaker_id, delivery}
        self.original_items = copy.deepcopy(items)  # what was stored: `script_changed` compares to it
        self.shots: list[dict[str, Any]] = []
        for s in shots:
            shot = copy.deepcopy(s)
            shot.setdefault("_h", str(shot.get("id") or f"n{len(self.shots) + 1}"))
            shot.setdefault("beat_notes", [])
            shot.setdefault("duration_locked", False)
            shot.setdefault("person_edits", {})
            self.shots.append(shot)
        self.envelope_s = envelope_s
        self.fixed = fixed_seconds
        self.canon = list(canon or [])  # {id, kind, code, name, aliases}: to name people, places and props
        self.location_id = location_id  # the scene's place: pinned to every shot unless taken out
        self._new = 0
        # Blocks are named by their number at the START of a batch, like shots: `_tokens[i]` is the
        # start-of-batch number of the block now at i (None for one made in this batch).
        self._tokens: list[int | None] = list(range(len(self.items)))
        self._batch_len = len(self.items)
        self._absorb(self.fit())

    @property
    def script_changed(self) -> bool:
        return self.items != self.original_items

    def _absorb(self, r: FitResult) -> None:
        """Make the kernel's shots the FITTED ones. A shot whose speech cannot fit the longest
        rung is split by `contracts.shotplan` into a continuous follow-on; taking that split in
        here keeps the numbers a model reads (S03) the numbers its operations address."""
        if not self.shots or len(r.shots) == len(self.shots):
            return  # no plan yet (Re-split makes one), or nothing was split
        by_start = {s["start"]: s for s in self.shots}
        out: list[dict[str, Any]] = []
        for f in r.shots:
            shot = by_start.get(f.start)
            if shot is None:
                shot = {"_h": self._new_handle(), "id": None, "start": f.start, "end": f.end, "framing": f.framing,
                        "title": f.title, "sound_mode": None, "duration": None, "duration_locked": False,
                        "camera_link": f.camera_link.value, "beat_notes": [], "person_edits": {}}
            shot["end"] = f.end
            out.append(shot)
        self.shots = out

    # ── reading ──────────────────────────────────────────────────────────────────────────

    def kernel_items(self) -> list[Item]:
        return [Item(i, b["kind"], b.get("text", ""), b.get("speaker", ""), b.get("speaker_id"),
                     b.get("delivery", ""), b.get("line_id")) for i, b in enumerate(self.items)]

    def proposal(self) -> list[ProposedShot]:
        return [ProposedShot(s["start"], s["end"], s.get("framing", "MS"), s.get("title", ""),
                             s.get("sound_mode"), s.get("duration"), bool(s.get("duration_locked")),
                             s.get("camera_link", "cut")) for s in self.shots]

    def fit(self) -> FitResult:
        return fit(self.kernel_items(), self.proposal(), envelope_s=self.envelope_s, fixed_seconds=self.fixed)

    def handles(self) -> list[str]:
        return [s["_h"] for s in self.shots]

    def index_of(self, handle: str) -> int:
        for i, s in enumerate(self.shots):
            if s["_h"] == handle:
                return i
        raise OpError("that shot no longer exists")

    def number_of(self, handle: str) -> int | None:
        try:
            return self.index_of(handle) + 1
        except OpError:
            return None

    def describe(self) -> str:
        """The plan as a model reads it: numbered shots, their blocks, lengths and words."""
        r = self.fit()
        by_start = {s["start"]: s for s in self.shots}
        rows = []
        for f in r.shots:
            s = by_start.get(f.start, {})
            blocks = []
            for n, b in enumerate(self.items[f.start:f.end], start=f.start):
                if b["kind"] == "dialogue":
                    delivery = f" ({b['delivery']})" if b.get("delivery") else ""
                    blocks.append(f"[{n}] {b.get('speaker', '')}{delivery}: \"{b.get('text', '')}\"")
                else:
                    blocks.append(f"[{n}] {b['kind'].upper()}: {b.get('text', '')}")
            lock = " (length set by a person)" if s.get("duration_locked") else ""
            rows.append(f"S{f.number:02d} {f.framing} {f.duration_s}s{lock} {f.sound_mode.value} "
                        f"{f.camera_link.value} \"{s.get('title', '')}\" blocks {f.start}-{f.end - 1}"
                        f"{self._marks(s)}\n    " + "\n    ".join(blocks))
        return "\n".join(rows)

    def _marks(self, shot: dict[str, Any]) -> str:
        """Who is in the shot, and what a person set on it, for the model's reading."""
        present = self._present(shot)
        names = [c["name"] for c in self.canon if str(c["id"]) in present]
        edits = PersonEdits.of(shot)
        bits = [f"in shot: {', '.join(names)}" if names else "",
                f"ignored checks: {', '.join(edits.waived_checks)}" if edits.waived_checks else "",
                f"DoP note: {edits.dop_note}" if edits.dop_note else ""]
        text = "; ".join(b for b in bits if b)
        return f" [{text}]" if text else ""

    # ── applying ─────────────────────────────────────────────────────────────────────────

    def apply(self, ops: list[Any], *, by: str = "conductor", respect_locks: bool = True,
              allowed_ops: tuple[str, ...] | None = None) -> ApplyResult:
        result = ApplyResult()
        addr = {i: s["_h"] for i, s in enumerate(self.shots, start=1)}
        self._tokens, self._batch_len = list(range(len(self.items))), len(self.items)
        for raw in list(ops or [])[:_MAX_OPS]:
            try:
                op = self._normalize(raw)
                if allowed_ops is not None and op["op"] not in allowed_ops:
                    raise OpError(f"{by} may not use {op['op']}")
                if op["op"] in PERSON_ONLY and by != "you":
                    raise OpError("only a person's own words can change the script, a shot's cast, checks or note")
                snap = self._snapshot()
                normalized, changes = self._dispatch(op, addr, by, respect_locks)
                check = self.fit()
                if any(i.code == "repaired" for i in check.issues):
                    self._restore(snap)
                    raise OpError("the result would not cover the script exactly once")
                self._absorb(check)
                for c in changes:
                    c.by = by
                result.undo.append(snap)
                result.changes += changes
                result.applied.append({**normalized, "by": by})
            except OpError as exc:
                result.rejected.append({"op": raw, "reason": refusals.for_person(str(exc)), "by": by})
        return result

    def undo(self, result: ApplyResult) -> None:
        if result.undo:
            self._restore(result.undo[0])

    def _snapshot(self) -> tuple[Any, ...]:
        return (copy.deepcopy(self.items), copy.deepcopy(self.shots), self.envelope_s, list(self._tokens))

    def _restore(self, snap: tuple[Any, ...]) -> None:
        self.items, self.shots, self.envelope_s = copy.deepcopy(snap[0]), copy.deepcopy(snap[1]), snap[2]
        self._tokens = list(snap[3])

    @staticmethod
    def _normalize(raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise OpError("that change was not written in a form I can apply")
        name = str(raw.get("op") or "").strip().lower()
        if name.startswith("line"):
            raise OpError("to change a line, name the line and say what it should say")
        if name not in MODEL_OPS:
            raise OpError("the chat cannot make that kind of change yet")
        return {**raw, "op": name}

    def _resolve(self, addr: dict[int, str], value: Any) -> str:
        number = _int(value, "shot")
        handle = addr.get(number)
        if handle is None:
            raise OpError(f"there is no shot {number}")
        self.index_of(handle)
        return handle

    def _new_handle(self) -> str:
        self._new += 1
        return f"new{self._new}"

    def _dispatch(self, op: dict[str, Any], addr: dict[int, str], by: str,
                  locks: bool) -> tuple[dict[str, Any], list[Change]]:
        handler = {
            "set": self._op_set, "retime": self._op_retime, "unlock_length": self._op_unlock,
            "split": self._op_split, "merge": self._op_merge, "regroup": self._op_regroup,
            "set_join": self._op_set_join, "beat.set": self._op_beat_set, "insert": self._op_insert,
            "remove": self._op_remove, "set_envelope": self._op_envelope,
            "block.set": self._op_block_set, "block.insert": self._op_block_insert,
            "block.remove": self._op_block_remove,
            "canon.add": lambda o, a, lk: self._op_canon(o, a, add=True),
            "canon.remove": lambda o, a, lk: self._op_canon(o, a, add=False),
            "check.waive": lambda o, a, lk: self._op_check(o, a, waive=True),
            "check.restore": lambda o, a, lk: self._op_check(o, a, waive=False),
            "dop_note.set": lambda o, a, lk: self._op_dop_note(o, a),
        }[op["op"]]
        return handler(op, addr, locks)

    # ── operations ───────────────────────────────────────────────────────────────────────

    def _op_set(self, op: Op, addr: Addr, locks: bool) -> OpResult:
        handle = self._resolve(addr, op.get("shot"))
        shot = self.shots[self.index_of(handle)]
        key = str(op.get("field") or "")
        if key == "framing":
            value = _framing(op.get("value"))
        elif key == "sound_mode":
            value = _sound(op.get("value"))
        elif key in SHOT_TEXT_FIELDS:
            value = _text(op.get("value"), key)
        elif key in ("duration_s", "duration"):
            raise OpError("a shot's length is changed with retime")
        else:
            raise OpError(f"shots have no settable field {key!r}")
        shot[key] = value
        return ({"op": "set", "shot": self.number_of(handle), "field": key, "value": value},
                [Change("field", (handle,), key)])

    def _op_retime(self, op: Op, addr: Addr, locks: bool) -> OpResult:
        handle = self._resolve(addr, op.get("shot"))
        shot = self.shots[self.index_of(handle)]
        seconds = _int(op.get("seconds"), "seconds")
        allowed = allowed_durations(self.fixed)
        if seconds not in allowed:
            raise OpError(f"Veo renders {', '.join(map(str, allowed))} second shots")
        if locks and shot.get("duration_locked") and shot.get("duration") != seconds:
            raise OpError("a person set this shot's length; ask them before changing it")
        shot["duration"] = seconds
        shot["duration_locked"] = True
        return ({"op": "retime", "shot": self.number_of(handle), "seconds": seconds},
                [Change("timing", (handle,), "duration")])

    def _op_unlock(self, op: Op, addr: Addr, locks: bool) -> OpResult:
        handle = self._resolve(addr, op.get("shot"))
        if locks:
            raise OpError("only the person who set a length can release it")
        shot = self.shots[self.index_of(handle)]
        shot["duration_locked"] = False
        shot["duration"] = None
        return ({"op": "unlock_length", "shot": self.number_of(handle)}, [Change("timing", (handle,), "duration")])

    def _op_split(self, op: Op, addr: Addr, locks: bool) -> OpResult:
        handle = self._resolve(addr, op.get("shot"))
        i = self.index_of(handle)
        shot = self.shots[i]
        at = _int(op.get("at_block"), "at_block")
        if not shot["start"] < at < shot["end"]:
            raise OpError(f"shot {i + 1} covers blocks {shot['start']}-{shot['end'] - 1}; split inside it")
        second = {**copy.deepcopy(shot), "_h": self._new_handle(), "id": None, "start": at,
                  "duration": None, "duration_locked": False, "beat_notes": [],
                  "person_edits": PersonEdits(cast=PersonEdits.of(shot).cast).dump(),
                  "title": _text(op.get("title"), "title") if op.get("title") else shot.get("title", "")}
        if op.get("framing"):
            second["framing"] = _framing(op["framing"])
        shot["end"] = at
        shot["duration"] = None if not shot.get("duration_locked") else shot.get("duration")
        self.shots.insert(i + 1, second)
        return ({"op": "split", "shot": i + 1, "at_block": at},
                [Change("structure", (handle, second["_h"]), "split")])

    def _op_merge(self, op: Op, addr: Addr, locks: bool) -> OpResult:
        handle = self._resolve(addr, op.get("shot"))
        i = self.index_of(handle)
        if i + 1 >= len(self.shots):
            raise OpError(f"shot {i + 1} is the last shot; there is nothing after it to merge")
        nxt = self.shots.pop(i + 1)
        shot = self.shots[i]
        shot["end"] = nxt["end"]
        shot["duration"] = None
        shot["duration_locked"] = False
        return ({"op": "merge", "shot": i + 1}, [Change("structure", (handle, nxt["_h"]), "merge")])

    def _op_regroup(self, op: Op, addr: Addr, locks: bool) -> OpResult:
        """Move the cut between a shot and the next to before `end_block`."""
        handle = self._resolve(addr, op.get("shot"))
        i = self.index_of(handle)
        if i + 1 >= len(self.shots):
            raise OpError("the last shot always runs to the end of the scene")
        end = _int(op.get("end_block"), "end_block")
        shot, nxt = self.shots[i], self.shots[i + 1]
        if not shot["start"] < end < nxt["end"]:
            raise OpError(f"the cut must fall between blocks {shot['start'] + 1} and {nxt['end'] - 1}")
        shot["end"] = nxt["start"] = end
        return ({"op": "regroup", "shot": i + 1, "end_block": end},
                [Change("structure", (handle, nxt["_h"]), "regroup")])

    def _op_set_join(self, op: Op, addr: Addr, locks: bool) -> OpResult:
        handle = self._resolve(addr, op.get("shot"))
        i = self.index_of(handle)
        link = str(op.get("link") or "").lower()
        if link not in {c.value for c in CameraLink}:
            raise OpError(f"link must be one of {', '.join(c.value for c in CameraLink)}")
        if i == 0 and link == CameraLink.CONTINUOUS:
            raise OpError("the first shot has nothing before it to continue")
        self.shots[i]["camera_link"] = link
        return ({"op": "set_join", "shot": i + 1, "link": link}, [Change("join", (handle,), "camera_link")])

    def _op_beat_set(self, op: Op, addr: Addr, locks: bool) -> OpResult:
        handle = self._resolve(addr, op.get("shot"))
        shot = self.shots[self.index_of(handle)]
        beat = _int(op.get("beat"), "beat")
        key = str(op.get("field") or "")
        if key not in BEAT_FIELDS:
            raise OpError(f"a beat has {', '.join(BEAT_FIELDS)}")
        if not 0 <= beat < 3:
            raise OpError("a shot has at most three beats (0, 1, 2)")
        notes = list(shot.get("beat_notes") or [])
        while len(notes) <= beat:
            notes.append({})
        notes[beat] = {**notes[beat], key: _text(op.get("value"), key)}
        shot["beat_notes"] = notes
        return ({"op": "beat.set", "shot": self.number_of(handle), "beat": beat, "field": key,
                 "value": notes[beat][key]}, [Change("beat", (handle,), key)])

    def _op_insert(self, op: Op, addr: Addr, locks: bool) -> OpResult:
        """A reaction or insert shot after `after_shot`: a director's beat block plus its shot."""
        after = _int(op.get("after_shot"), "after_shot")
        description = _text(op.get("description"), "description")
        if not description:
            raise OpError("say what the new shot shows")
        if after == 0:
            pos, i = 0, 0
        else:
            handle = self._resolve(addr, after)
            i = self.index_of(handle) + 1
            pos = self.shots[i - 1]["end"]
        self.items.insert(pos, {"kind": "beat", "text": description, "line_id": None})
        for s in self.shots:  # `pos` is a cut, so no shot straddles it
            if s["start"] >= pos:
                s["start"] += 1
            if s["end"] > pos:
                s["end"] += 1
        framing = _framing(op.get("framing") or Framing.CU.value)
        new: dict[str, Any] = {"_h": self._new_handle(), "id": None, "start": pos, "end": pos + 1, "framing": framing,
               "title": _text(op.get("title") or description[:40], "title"), "sound_mode": None,
               "duration": None, "duration_locked": False, "camera_link": CameraLink.CUT.value, "beat_notes": [],
               "person_edits": {}}
        self.shots.insert(i, new)
        return ({"op": "insert", "after_shot": after, "description": description, "framing": framing},
                [Change("structure", (str(new["_h"]),), "insert")])

    def _op_remove(self, op: Op, addr: Addr, locks: bool) -> OpResult:
        """Remove a shot. Script under it joins the shot before (or after); a director's beat
        block that only it carried is removed with it. Script is never removed."""
        handle = self._resolve(addr, op.get("shot"))
        i = self.index_of(handle)
        if len(self.shots) == 1:
            raise OpError("a scene needs at least one shot")
        shot = self.shots[i]
        own = list(range(shot["start"], shot["end"]))
        if all(self.items[b]["kind"] == "beat" for b in own):
            for b in reversed(own):
                del self.items[b]
            self.shots.pop(i)
            for s in self.shots:
                if s["start"] >= shot["end"]:
                    s["start"] -= len(own)
                if s["end"] >= shot["end"]:
                    s["end"] -= len(own)
        else:
            self.shots.pop(i)
            if i > 0:
                self.shots[i - 1]["end"] = shot["end"]
                self.shots[i - 1]["duration"] = None if not self.shots[i - 1].get("duration_locked") \
                    else self.shots[i - 1]["duration"]
            else:
                self.shots[0]["start"] = shot["start"]
        return ({"op": "remove", "shot": i + 1}, [Change("structure", (handle,), "remove")])

    def _op_envelope(self, op: Op, addr: Addr, locks: bool) -> OpResult:
        seconds = _int(op.get("seconds"), "seconds")
        if not 4 <= seconds <= 1800:
            raise OpError("a scene envelope is between 4 and 1800 seconds")
        self.envelope_s = seconds
        return ({"op": "set_envelope", "seconds": seconds}, [Change("envelope", (), "envelope_s")])

    # ── a person's changes to the script ─────────────────────────────────────────────────

    def _block(self, value: Any) -> int:
        """Where the block a person named (its number at the start of the batch) is now."""
        b = _int(value, "block")
        if not 0 <= b < self._batch_len:
            raise OpError(f"there is no block {b}; the script has blocks 0-{self._batch_len - 1}")
        if b not in self._tokens:
            raise OpError(f"block {b} was removed earlier in this change")
        return self._tokens.index(b)

    def _shot_of_block(self, b: int) -> int:
        for i, shot in enumerate(self.shots):
            if shot["start"] <= b < shot["end"]:
                return i
        raise OpError(f"block {b} is in no shot")

    def character_id(self, speaker: str) -> str | None:
        """The canon character a speaker's name (or alias) is, when there is one."""
        key = name_key(speaker)
        for c in self.canon:
            if c.get("kind") == "character" and key in {name_key(n) for n in [c["name"], *(c.get("aliases") or [])]}:
                return str(c["id"])
        return None

    def touches_dialogue(self, op: dict[str, Any]) -> bool:
        """Does this operation write a spoken line? Those are staged for the person to accept."""
        name = op.get("op")
        if name == "block.insert":
            return str(op.get("kind") or "action").lower() == BlockKind.DIALOGUE.value
        if name in ("block.set", "block.remove"):
            try:
                return bool(self.items[int(op["block"])]["kind"] == BlockKind.DIALOGUE.value)
            except (KeyError, TypeError, ValueError, IndexError):
                return False
        return False

    def _op_block_set(self, op: Op, addr: Addr, locks: bool) -> OpResult:
        want = _int(op.get("block"), "block")
        b = self._block(want)
        item = self.items[b]
        key = str(op.get("field") or "text").lower()
        if item["kind"] == BlockKind.DIALOGUE.value:
            if key not in SCRIPT_LIMITS:
                raise OpError("a line has text, speaker and delivery")
        elif key != "text":
            raise OpError("only a line has a speaker or a delivery")
        value = _script_text(op.get("value"), key)
        if not value and key != "delivery":
            raise OpError(f"say what the {key} should be; to delete a block, remove it instead")
        was = str(item.get(key) or "")
        if value == was:
            raise OpError(f"block {b} already says that")
        item[key] = value
        if key == "speaker":
            item["speaker_id"] = self.character_id(value)
        i = self._shot_of_block(b)
        who = {"speaker": item.get("speaker", "")} if item["kind"] == BlockKind.DIALOGUE.value else {}
        return ({"op": "block.set", "block": want, "shot": i + 1, "kind": item["kind"], "field": key, "value": value,
                 "was": was, **who}, [Change("script", (self.shots[i]["_h"],), key)])

    def _op_block_insert(self, op: Op, addr: Addr, locks: bool) -> OpResult:
        want = _int(op.get("block"), "block")
        if not 0 <= want <= self._batch_len:
            raise OpError(f"a new block goes at 0-{self._batch_len}")
        pos = len(self.items) if want == self._batch_len else self._block(want)
        kind = str(op.get("kind") or BlockKind.ACTION.value).lower()
        if kind not in {k.value for k in BlockKind}:
            raise OpError(f"a block is one of {', '.join(k.value for k in BlockKind)}")
        text = _script_text(op.get("value"), "text")
        if not text:
            raise OpError("say what the new block says")
        item: dict[str, Any] = {"kind": kind, "text": text, "line_id": None}
        if kind == BlockKind.DIALOGUE.value:
            speaker = _script_text(op.get("speaker"), "speaker")
            if not speaker:
                raise OpError("a line needs a speaker")
            item |= {"line_id": str(uuid4()), "speaker": speaker, "speaker_id": self.character_id(speaker),
                     "delivery": _script_text(op.get("delivery") or "", "delivery")}
        elif op.get("speaker"):
            raise OpError("only a line has a speaker")
        # The block joins the shot before it (the first shot when it opens the scene).
        i = self._shot_of_block(pos - 1) if pos > 0 else 0
        self.items.insert(pos, item)
        self._tokens.insert(pos, None)
        self.shots[i]["end"] += 1
        for later in self.shots[i + 1:]:
            later["start"] += 1
            later["end"] += 1
        said = {"speaker": item["speaker"], "delivery": item["delivery"]} if kind == BlockKind.DIALOGUE.value else {}
        return ({"op": "block.insert", "block": want, "shot": i + 1, "kind": kind, "value": text, **said},
                [Change("script", (self.shots[i]["_h"],), "insert")])

    def _op_block_remove(self, op: Op, addr: Addr, locks: bool) -> OpResult:
        want = _int(op.get("block"), "block")
        b = self._block(want)
        if len(self.items) == 1:
            raise OpError("a scene needs at least one block")
        i = self._shot_of_block(b)
        shot = self.shots[i]
        handle, removed = shot["_h"], self.items.pop(b)
        self._tokens.pop(b)
        shot["end"] -= 1
        for later in self.shots[i + 1:]:
            later["start"] -= 1
            later["end"] -= 1
        if shot["start"] == shot["end"]:  # it was the shot's only block: the shot goes with it
            self.shots.pop(i)
        return ({"op": "block.remove", "block": want, "shot": i + 1, "kind": removed["kind"],
                 "was": str(removed.get("text") or ""), **({"speaker": removed.get("speaker", "")}
                                                            if removed["kind"] == "dialogue" else {})},
                [Change("script", (handle,), "remove")])

    # ── a person's marks on a shot ───────────────────────────────────────────────────────

    def _entity(self, value: Any) -> dict[str, Any]:
        """A canon entry by its code ("C02"), name or alias."""
        key = name_key(str(value or ""))
        for c in self.canon:
            if key and key in {name_key(n) for n in [c["name"], c["code"], *(c.get("aliases") or [])]}:
                return c
        raise OpError(f"there is no canon entry called {str(value or '').strip()!r}")

    def _natural(self, shot: dict[str, Any]) -> set[str]:
        """Who and what the script puts in a shot: its speakers, who its action names, the place."""
        items = [i for i in self.kernel_items() if shot["start"] <= i.index < shot["end"]]
        ids = set(cast_in(items, [c for c in self.canon if c.get("kind") == "character"]))
        return ids | ({self.location_id} if self.location_id else set())

    def _present(self, shot: dict[str, Any]) -> set[str]:
        edits = PersonEdits.of(shot)
        return (self._natural(shot) | set(edits.cast.add)) - set(edits.cast.remove)

    def _op_canon(self, op: Op, addr: Addr, *, add: bool) -> OpResult:
        handle = self._resolve(addr, op.get("shot"))
        shot = self.shots[self.index_of(handle)]
        number = self.number_of(handle) or 0
        entity = self._entity(op.get("value"))
        eid = str(entity["id"])
        edits, natural = PersonEdits.of(shot), self._natural(shot)
        if add == (eid in self._present(shot)):
            raise OpError(f"{entity['name']} is {'already' if add else 'not'} in S{number:02d}")
        cast = edits.cast
        if add:
            if eid in cast.remove:
                cast.remove.remove(eid)
            if eid not in natural:
                cast.add.append(eid)
        else:
            if eid in cast.add:
                cast.add.remove(eid)
            if eid in natural:
                cast.remove.append(eid)
        shot["person_edits"] = edits.dump()
        return ({"op": "canon.add" if add else "canon.remove", "shot": number, "value": str(entity["name"])},
                [Change("cast", (handle,), "canon")])

    def _op_check(self, op: Op, addr: Addr, *, waive: bool) -> OpResult:
        handle = self._resolve(addr, op.get("shot"))
        shot = self.shots[self.index_of(handle)]
        number = self.number_of(handle) or 0
        edits = PersonEdits.of(shot)
        said = str(op.get("value") or "").strip().lower()
        if not waive and said in ("all", "everything"):
            edits.waived_checks = []
        else:
            code = check_code(said)
            if code is None:
                raise OpError("a check is named by its topic: " + ", ".join(t.replace("_", " ") for t in CHECK_TOPICS))
            if waive == (code in edits.waived_checks):
                raise OpError(f"the {code.replace('_', ' ')} check is {'already' if waive else 'not'} ignored in "
                              f"S{number:02d}")
            edits.waived_checks = ([*edits.waived_checks, code] if waive
                                   else [c for c in edits.waived_checks if c != code])
        shot["person_edits"] = edits.dump()
        return ({"op": "check.waive" if waive else "check.restore", "shot": number, "value": said},
                [Change("mark", (handle,), "checks")])

    def _op_dop_note(self, op: Op, addr: Addr) -> OpResult:
        handle = self._resolve(addr, op.get("shot"))
        shot = self.shots[self.index_of(handle)]
        number = self.number_of(handle) or 0
        edits = PersonEdits.of(shot)
        note = " ".join(str(op.get("value") or "").split())[:DOP_NOTE_CHARS]
        if note == edits.dop_note:
            raise OpError(f"S{number:02d} already has that DoP note" if note
                          else f"S{number:02d} has no DoP note to clear")
        edits.dop_note = note
        shot["person_edits"] = edits.dump()
        return ({"op": "dop_note.set", "shot": number, "value": note}, [Change("mark", (handle,), "dop_note")])
