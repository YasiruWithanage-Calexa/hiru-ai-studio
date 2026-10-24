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
  * Dialogue is the approved script's, verbatim. There is no operation that writes a line;
    `line.*` is refused with the reason, and every shot keeps its lines bound by code.
  * A length a PERSON set (`duration_locked`) is not changed by an agent; only the person's own
    words (the conductor transcribing them) may change it.
  * A reaction or insert shot with no script under it is a director's BEAT block added to the
    script (`insert`), so the kernel's rule "every block in exactly one shot" still holds.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from contracts.production import Framing
from contracts.shotplan import FitResult, Item, ProposedShot, allowed_durations, fit
from contracts.veo import CameraLink, SoundMode

MODEL_OPS = ("set", "retime", "unlock_length", "split", "merge", "regroup", "set_join", "beat.set",
             "insert", "remove", "set_envelope")
STRUCTURAL_OPS = ("split", "merge", "regroup", "insert", "remove")
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
        raise OpError(f"{name} takes text")
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


def _int(value: Any, name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        raise OpError(f"{name} must be a whole number, got {value!r}") from None


class ScenePlanKernel:
    """One scene's plan: its blocks (script + director beats) and its shots as block ranges."""

    def __init__(self, items: list[dict[str, Any]], shots: list[dict[str, Any]], *, envelope_s: int,
                 fixed_seconds: int | None = None) -> None:
        self.items = copy.deepcopy(items)  # {kind, text, line_id, speaker, speaker_id, delivery}
        self.shots: list[dict[str, Any]] = []
        for s in shots:
            shot = copy.deepcopy(s)
            shot.setdefault("_h", str(shot.get("id") or f"n{len(self.shots) + 1}"))
            shot.setdefault("beat_notes", [])
            shot.setdefault("duration_locked", False)
            self.shots.append(shot)
        self.envelope_s = envelope_s
        self.fixed = fixed_seconds
        self._new = 0
        self._absorb(self.fit())

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
                        "camera_link": f.camera_link.value, "beat_notes": []}
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
            for b in self.items[f.start:f.end]:
                if b["kind"] == "dialogue":
                    blocks.append(f"{b.get('speaker', '')}: \"{b.get('text', '')}\"")
                else:
                    blocks.append(f"{b['kind'].upper()}: {b.get('text', '')}")
            lock = " (length set by a person)" if s.get("duration_locked") else ""
            rows.append(f"S{f.number:02d} {f.framing} {f.duration_s}s{lock} {f.sound_mode.value} "
                        f"{f.camera_link.value} \"{s.get('title', '')}\" blocks {f.start}-{f.end - 1}\n    "
                        + "\n    ".join(blocks))
        return "\n".join(rows)

    # ── applying ─────────────────────────────────────────────────────────────────────────

    def apply(self, ops: list[Any], *, by: str = "conductor", respect_locks: bool = True,
              allowed_ops: tuple[str, ...] | None = None) -> ApplyResult:
        result = ApplyResult()
        addr = {i: s["_h"] for i, s in enumerate(self.shots, start=1)}
        for raw in list(ops or [])[:_MAX_OPS]:
            try:
                op = self._normalize(raw)
                if allowed_ops is not None and op["op"] not in allowed_ops:
                    raise OpError(f"{by} may not use {op['op']}")
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
                result.rejected.append({"op": raw, "reason": str(exc), "by": by})
        return result

    def undo(self, result: ApplyResult) -> None:
        if result.undo:
            self._restore(result.undo[0])

    def _snapshot(self) -> tuple[Any, ...]:
        return (copy.deepcopy(self.items), copy.deepcopy(self.shots), self.envelope_s)

    def _restore(self, snap: tuple[Any, ...]) -> None:
        self.items, self.shots, self.envelope_s = copy.deepcopy(snap[0]), copy.deepcopy(snap[1]), snap[2]

    @staticmethod
    def _normalize(raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise OpError("an operation must be an object")
        name = str(raw.get("op") or "").strip().lower()
        if name.startswith("line"):
            raise OpError("dialogue comes from the approved script; change it in the script editor")
        if name not in MODEL_OPS:
            raise OpError(f"unknown operation {name!r}")
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
               "duration": None, "duration_locked": False, "camera_link": CameraLink.CUT.value, "beat_notes": []}
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
