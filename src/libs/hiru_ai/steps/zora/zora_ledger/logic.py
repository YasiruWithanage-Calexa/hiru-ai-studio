"""Zora's ledger (plan/2026-11-06e §4.6, §4.11; Nova W2, W5): what the turn changed, read from the DIFF.

    change_lines(before, after)   plain lines by treatment / sequence / shot / staging / end state, computed by code
                                  from two plans exported WITH handles (a shot is paired with itself, never by
                                  position, so an insert does not make every later shot look changed)
    build(...)                    the turn's `contracts.zora.ledger.Ledger`

A line names the shot by its number AFTER the turn (what the person now sees), and a removed shot by its number before.
Creative text is quoted short; the reply shows the rest from the plan.
"""
from __future__ import annotations

from typing import Any

from contracts.zora.ledger import Ledger, Line
from contracts.zora.ops import IR_FIELDS, SHOT_FIELDS, SOUND_FIELDS, TREATMENT_FIELDS, code

Row = dict[str, Any]


def _q(text: Any, n: int = 80) -> str:
    s = " ".join(str(text or "").split())
    return f"“{s if len(s) <= n else s[:n] + '…'}”" if s else "(empty)"


def _span(blocks: list[int]) -> str:
    b = sorted(blocks)
    return "no script block" if not b else f"b{b[0]}" if len(b) == 1 else f"b{b[0]}–b{b[-1]}"


def _treatment(before: Row, after: Row) -> list[Line]:
    out = []
    tb, ta = before["treatment"], after["treatment"]
    for f in TREATMENT_FIELDS:
        if tb.get(f) != ta.get(f):
            out.append(Line(level="treatment", where="Treatment", text=f"{f.replace('_', ' ')} is now {_q(ta[f])}"))
    arc_b = [{k: v for k, v in a.items() if k != "_h"} for a in tb.get("arc") or []]
    arc_a = [{k: v for k, v in a.items() if k != "_h"} for a in ta.get("arc") or []]
    if arc_b != arc_a:
        if len(arc_b) != len(arc_a):
            out.append(Line(level="treatment", where="Treatment", text=f"the arc has {len(arc_a)} beats now (was "
                            f"{len(arc_b)}): " + " → ".join(a["beat"] for a in arc_a)))
        for i, (a, b) in enumerate(zip(arc_b, arc_a, strict=False), start=1):
            if a != b:
                moved = f" (now b{b['blocks']['first']}–b{b['blocks']['last']})" if a["blocks"] != b["blocks"] else ""
                out.append(Line(level="treatment", where="Treatment", text=f"arc beat {i}: {_q(b['beat'], 60)}, "
                                f"feeling {_q(b['feeling'], 50)}{moved}"))
    cb = {c["sequence"]: c for c in tb.get("colour_script") or []}
    for c in ta.get("colour_script") or []:
        old = cb.get(c["sequence"], {})
        diff = [f"{k} {_q(c[k], 50)}" for k in ("palette", "light", "grade") if old.get(k) != c.get(k)]
        if diff:
            out.append(Line(level="treatment", where=f"Sequence {c['sequence']}", text="colour: " + "; ".join(diff)))
    return out


def _sequences(before: Row, after: Row) -> list[Line]:
    out = []
    qb = {q["id"]: q for q in before.get("sequences") or []}
    qa = {q["id"]: q for q in after.get("sequences") or []}
    for sid, q in qa.items():
        old = qb.get(sid)
        if old is None:
            out.append(Line(level="sequence", where=f"Sequence {sid}", text=f"new: {_q(q['title'], 50)}, "
                            f"{code(q['shots']['first'])}–{code(q['shots']['last'])}"))
            continue
        for f in ("title", "purpose"):
            if old[f] != q[f]:
                out.append(Line(level="sequence", where=f"Sequence {sid}", text=f"{f} is now {_q(q[f], 70)}"))
    for sid in qb:
        if sid not in qa:
            out.append(Line(level="sequence", where=f"Sequence {sid}", text="removed: its shots joined the sequence "
                            "beside it"))
    hb = {s["_h"]: s.get("sequence") for s in before.get("shots") or []}
    moved: dict[str, list[int]] = {}
    for i, s in enumerate(after.get("shots") or [], start=1):
        if s["_h"] in hb and hb[s["_h"]] != s.get("sequence"):
            moved.setdefault(str(s.get("sequence")), []).append(i)
    for sid, ns in moved.items():
        out.append(Line(level="sequence", where=f"Sequence {sid}", text="now holds " + ", ".join(code(n) for n in ns)
                        + " too"))
    return out


def _shot_fields(old: Row, new: Row) -> list[str]:
    out = []
    for f in SHOT_FIELDS:
        if old.get(f) != new.get(f):
            if f == "why":
                out.append(f"reason {_q(new['why'], 70)}")
            else:
                out.append(f"{f} {old.get(f) or '—'} → {new.get(f) or '—'}")
    if old.get("take_s") != new.get("take_s"):
        out.append(f"take {old.get('take_s')} s → {new.get('take_s')} s")
    if old.get("use_s") != new.get("use_s"):
        out.append(f"keeps {old.get('use_s')} s → {new.get('use_s')} s")
    if sorted(old.get("blocks") or []) != sorted(new.get("blocks") or []):
        out.append(f"now shows {_span(new.get('blocks') or [])}")
    sb, sa = old.get("sound") or {}, new.get("sound") or {}
    snd = [f for f in SOUND_FIELDS if sb.get(f) != sa.get(f)]
    if snd:
        out.append("sound: " + ", ".join(f"{f} {_q(sa[f], 40)}" if f != "silence" else
                                         ("silent" if sa[f] else "not silent") for f in snd))
    ir = [f.replace("_", " ") for f in IR_FIELDS if (old.get("ir") or {}).get(f) != (new.get("ir") or {}).get(f)]
    if ir:
        out.append("camera design: " + ", ".join(ir))
    return out


def _shots(before: Row, after: Row) -> list[Line]:
    out = []
    old = {s["_h"]: (i, s) for i, s in enumerate(before.get("shots") or [], start=1)}
    new_added = {a["shot"]: a for a in after.get("added") or []}
    seen = set()
    for i, s in enumerate(after.get("shots") or [], start=1):
        h = s["_h"]
        seen.add(h)
        if h not in old:
            a = new_added.get(i)
            what = f" ({a['kind']}: {_q(a['what'], 60)})" if a else f" (shows {_span(s.get('blocks') or [])})"
            out.append(Line(level="shot", where=code(i), text="new shot" + what))
            continue
        n0, prev = old[h]
        diff = _shot_fields(prev, s)
        if diff:
            out.append(Line(level="shot", where=code(i), text=("" if n0 == i else f"(was {code(n0)}) ")
                            + "; ".join(diff)))
    for h, (n0, s) in old.items():
        if h not in seen:
            out.append(Line(level="shot", where=code(n0), text=f"removed (it was {_q(s.get('why'), 60)})"))
    return out


def _staging(before: Row, after: Row) -> list[Line]:
    mb = {(m["block"], m["who"]): m for m in before["staging"]["marks"]}
    ma = {(m["block"], m["who"]): m for m in after["staging"]["marks"]}
    out = []
    for k, m in ma.items():
        if mb.get(k) != m:
            out.append(Line(level="staging", where="Staging", text=f"{m['who']} from b{m['block']}: {m['zone']}"
                            + (f", facing {m['facing']}" if m["facing"] else "")
                            + (f", frame {m['frame_side']}" if m["frame_side"] else "")))
    for k in mb:
        if k not in ma:
            out.append(Line(level="staging", where="Staging", text=f"{k[1]}'s mark at b{k[0]} removed"))
    if before["staging"]["zones"] != after["staging"]["zones"]:
        out.append(Line(level="staging", where="Staging", text="zones: " + ", ".join(after["staging"]["zones"])))
    return out


def _end(before: Row, after: Row) -> list[Line]:
    eb, ea = before["end_state"], after["end_state"]
    out = []
    pb = {p["who"]: p for p in eb.get("people") or []}
    for p in ea.get("people") or []:
        old = pb.get(p["who"], {})
        diff = [f"{k} {_q(p[k], 40)}" for k in ("where", "facing", "holding", "look") if old.get(k) != p.get(k)]
        if diff:
            out.append(Line(level="end", where="End state", text=f"{p['who']}: " + "; ".join(diff)))
    for k in ("time", "light"):
        if eb.get(k) != ea.get(k):
            out.append(Line(level="end", where="End state", text=f"{k} {_q(ea[k], 50)}"))
    return out


def change_lines(before: Row, after: Row) -> list[Line]:
    """Everything that differs, as lines a person reads (both plans exported with handles)."""
    return [*_treatment(before, after), *_sequences(before, after), *_shots(before, after), *_staging(before, after),
            *_end(before, after)]


def build(before: Row, after: Row, *, refused: list[str] | None = None, team_refused: list[str] | None = None,
          undelivered: list[str] | None = None, attempted: bool = False, staged: list[str] | None = None,
          mended: list[str] | None = None, problems: list[str] | None = None, overruns: list[str] | None = None,
          seams: list[str] | None = None, stale: list[str] | None = None, offer: str = "", undone: bool = False,
          locks: list[str] | None = None, already: list[str] | None = None) -> Ledger:
    lines = [] if undone else change_lines(before, after)
    lines += [Line(level="lock", where="Locks", text=t) for t in locks or []]

    def once(xs: list[str] | None) -> list[str]:  # ten ops refused for one reason are one reason
        return list(dict.fromkeys(xs or []))

    return Ledger(changes=lines, refused=once(refused), team_refused=once(team_refused),
                  undelivered=once(undelivered), attempted=attempted, staged=once(staged),
                  mended=once(mended), problems=once(problems), overruns=once(overruns),
                  seams=once(seams), stale=once(stale), offer=offer, undone=undone, already=once(already))
