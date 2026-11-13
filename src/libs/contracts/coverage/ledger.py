"""What changed between two coverages, read by code (plan/2026-11-13 §3.6): the lines the panel shows under a reply
("What changed") and the facts the reply is written from. Ported from `lab/zora_rows/turn.py`.

    changes(before, after) -> ["S01 · size: MS → WIDE", "S08 [3A-4] removed (must master MS)", ...]
    plain(line)                "S01's size went from MS to WIDE"
    label(cov, h)              a clip as a person finds it after a renumbering: "S08 [3C-3] single MCU"
"""
from __future__ import annotations

import json
import re
from typing import Any

from contracts.coverage.scene import CINE, IR_JSON, IR_TEXT, Coverage


def _same(a: Any, b: Any) -> bool:
    return json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)


def short(v: Any, n: int = 70) -> str:
    text = " ".join(str(v if v not in (None, "") else "-").split())
    return text if len(text) <= n else text[: n - 1] + "…"


def label(cov: Coverage, h: str) -> str:
    c = cov.clip(h) if h else None
    return f"{cov.code(h)} [{c.slate or 'new'}] {c.role or '-'} {c.size}" if c else "no clip"


def changes(before: Coverage, after: Coverage) -> list[str]:
    old = {c.h: c for c in before.clips}
    out: list[str] = []
    kept_before = [x.h for x in before.clips if after.clip(x.h)]
    kept_after = [x.h for x in after.clips if before.clip(x.h)]
    for c in after.clips:
        code = after.code(c.h)
        o = old.get(c.h)
        if o is None:
            word = "new" if c.new else "restored"
            out.append(f"{word} {code}: {c.priority or '-'} {c.role or '-'} {c.size} {c.take_s} s over "
                       f"{', '.join(f'b{i}' for i in c.blocks)}" + (f" — {short(c.why)}" if c.why else ""))
            continue
        pairs: list[tuple[str, Any, Any]] = [
            ("size", o.size, c.size), ("take", f"{o.take_s} s", f"{c.take_s} s"), ("join", o.link, c.link),
            ("sound mode", o.sound_mode, c.sound_mode),
            ("role", f"{o.priority or '-'} {o.role or '-'}", f"{c.priority or '-'} {c.role or '-'}"),
            ("blocks", f"b{o.first}-b{o.last - 1}", f"b{c.first}-b{c.last - 1}"),
            ("why", o.why, c.why), ("what we see", o.sees, c.sees), ("DoP note", o.note, c.note)]
        pairs += [(k, o.cine(k), c.cine(k)) for k in CINE]
        pairs += [(k, o.ir.get(k), c.ir.get(k)) for k in (*IR_TEXT, *IR_JSON)]
        pairs += [(f"sound {k}", o.sound.get(k), c.sound.get(k)) for k in ("ambience", "effects", "music", "silence")]
        for name, a, b in pairs:
            if not _same(a, b):
                out.append(f"{code} · {name} rewritten" if name in IR_JSON
                           else f"{code} · {name}: {short(a)} → {short(b)}")
        bn = before.number_of(c.h)
        if bn != after.number_of(c.h) and kept_before.index(c.h) != kept_after.index(c.h):
            out.append(f"S{bn:02d} moved to {code}")
    for h, o in old.items():
        if after.clip(h) is None:
            out.append(f"S{before.number_of(h) or 0:02d} [{o.slate or 'new'}] removed ({o.priority or '-'} "
                       f"{o.role or '-'} {o.size})")
    for lid, ln in after.lines.items():
        was = before.lines[lid].by if lid in before.lines else ""
        if ln.by != was:
            out.append(f"{lid} ({ln.speaker}) now performed by {label(after, ln.by)} (was {label(before, was)})")
    return out


CHANGE = re.compile(r"^(S\d+) · (.+?): (.*) → (.*)$")
REWRITTEN = re.compile(r"^(S\d+) · (.+) rewritten$")


def plain(line: str) -> str:
    """A ledger line as a sentence a person would say ("S01's size went from MS to WIDE")."""
    m = CHANGE.match(line)
    if m:
        shot, what, a, b = m.groups()
        return f"{shot}'s {what} went from {a} to {b}" if a != "-" else f"{shot}'s {what} is now {b}"
    m = REWRITTEN.match(line)
    if m:
        return f"{m.group(1)}'s {m.group(2).replace('_', ' ')} were rewritten"
    return line


def where(line: str) -> str:
    """The shot a ledger line is about ("S03"), or "Scene" (a line moved, a takes total)."""
    m = re.match(r"(?:new |restored )?(S\d+)", line)
    return m.group(1) if m else "Scene"
