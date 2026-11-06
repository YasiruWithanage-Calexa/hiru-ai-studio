"""Zora's two renderings of the document (plan/2026-11-06e §4.1; Nova W1 "the brief is an address space", W2).

    addressable(doc, only=…)   the conductor and the author: every node printed with the address its operation uses,
                               under a header that names every field and the op that writes it, and says there is no
                               other. Numbers start at 1 everywhere. Shots in `only` are printed in full, the rest one
                               line each (compression, never omission).
    consumer(doc, only=…)      the reply: plain words, the turn's shots in full, everything else one line each.

The script's lines are printed with their ids and words, and never as a writable field. Pure standard library.
"""
from __future__ import annotations

import json
from typing import Any

from contracts.zora.doc import ZoraDoc
from contracts.zora.ops import code

HEADER = """THE PLAN, ADDRESSABLE. Every part is printed with its address; numbers start at 1. These are the ONLY
fields, and each is written by the operation named beside it; there is no other field and no other operation.
  Treatment            treatment.set {field: logline|approach|geography|key_image, value}
  arc 1..              arc.set {n, beat?, feeling?, first?, last?} · arc.add {after, beat, feeling, first, last} ·
                       arc.remove {n}            (first/last are script blocks)
  colour A..           colour.set {sequence, field: palette|light|grade, value}
  Sequence A..         sequence.set {id, field: title|purpose, value} · sequence.bounds {id, first, last} (shots) ·
                       sequence.add {title, purpose, first, last} · sequence.remove {id}
  S01..                set {shot, field: size|angle|lens|link|why|over, value} · retime {shot, take_s: 4|6|8} ·
                       use {shot, use_s} · sound.set {shot, field: ambience|effects|music|silence, value} ·
                       ir.set {shot, path: setting|cinematography[.x]|lighting|subjects|beats|audio|first_frame,
                       value} ·
                       split {shot, at_block} · merge {shots: [a, b]} · regroup {shot, sequence} ·
                       insert {after, kind, what, who: [...], object} · remove {shot} · move {shot, after}
                       (remove and move only for shots that show no script block: script shots play in script order)
  mark [b, who]        mark.set {block, who, field: zone|facing|frame_side|holding, value} · mark.add {...} ·
                       mark.remove {block, who} · zone.add {zone}
  end.<person>, end    end.set {who?, field: where|facing|holding|look|time|light, value}
  line L4              READ-ONLY. The script's words are never an operation's value.
A field marked [locked] was set by the person: leave it."""


def _lock(doc: ZoraDoc, path: str) -> str:
    return " [locked]" if doc.person.is_locked(path) else ""


def _span(blocks: list[int]) -> str:
    if not blocks:
        return "no script block"
    b = sorted(blocks)
    return f"b{b[0]}" if len(b) == 1 else f"b{b[0]}–b{b[-1]}"


def _compact(value: Any, limit: int = 400) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + "…"


def _treatment(doc: ZoraDoc, *, addresses: bool) -> list[str]:
    t = doc.plan["treatment"]
    out = ["TREATMENT" if addresses else "Treatment"]
    for f in ("logline", "approach", "geography", "key_image"):
        label = f"treatment.{f}" if addresses else f.replace("_", " ")
        out.append(f"  {label}{_lock(doc, f'treatment.{f}')}: {t[f]}")
    for i, a in enumerate(t["arc"], start=1):
        out.append(f"  arc {i} ({_span(list(range(a['blocks']['first'], a['blocks']['last'] + 1)))}): "
                   f"{a['beat']} — feeling: {a['feeling']}")
    for c in t["colour_script"]:
        out.append(f"  colour {c['sequence']}: palette {c['palette']} · light {c['light']} · grade {c['grade']}"
                   + _lock(doc, f"colour.{c['sequence']}"))
    if t.get("advice"):
        out.append("  advice (shown to the person, never applied): " + " | ".join(t["advice"]))
    return out


def _shot_full(doc: ZoraDoc, s: dict[str, Any], *, addresses: bool) -> list[str]:
    c = code(int(s["n"]))
    words = {k: v.get("text", "") for k, v in doc.lines.items()}
    lines = ", ".join(f"{ln} \"{words.get(ln, '')}\"" for ln in s["lines"]) or "no line"
    added = [a for a in doc.plan.get("added") or [] if a["shot"] == s["n"]]
    out = [f"{c}  sequence {s['sequence']} · {_span(s['blocks'])} · {lines}" + (f" · seen: {s['over']}" if s["over"]
                                                                                else ""),
           f"    size {s['size']}{_lock(doc, f'{c}.size')} · angle {s['angle']}{_lock(doc, f'{c}.angle')} · "
           f"lens {s['lens']}{_lock(doc, f'{c}.lens')} · take {s['take_s']} s{_lock(doc, f'{c}.take_s')} · keeps "
           f"{s['use_s']} s · link {s['link']}",
           f"    why{_lock(doc, f'{c}.why')}: {s['why'] or '(empty: to write)'}"]
    snd = s["sound"]
    out.append(f"    sound: ambience {snd['ambience'] or '—'} · effects {snd['effects'] or '—'} · music "
               f"{snd['music'] or '—'}" + (" · SILENCE" if snd["silence"] else ""))
    if addresses:
        for k, v in (s.get("ir") or {}).items():
            out.append(f"    ir.{k}{_lock(doc, f'{c}.ir.{k}')}: {_compact(v)}")
    for a in added:
        out.append(f"    added ({a['kind']}): {a['what']}" + (f" · who {', '.join(a['who'])}" if a["who"] else "")
                   + (f" · object {a['object']}" if a["object"] else ""))
    return out


def _shot_line(s: dict[str, Any]) -> str:
    return (f"{code(int(s['n']))}  {s['sequence']} · {_span(s['blocks'])} · {s['size']} · {s['lens'] or 'lens —'} · "
            f"{s['take_s']} s · {(s['why'] or '(no why)')[:90]}")


def _script(doc: ZoraDoc) -> list[str]:
    out = ["SCRIPT (read-only: blocks b0.., lines L<block>)"]
    for b in doc.blocks:
        if b.get("kind") == "dialogue" and b.get("line_id"):
            how = f", {b['delivery']}" if b.get("delivery") else ""
            out.append(f"  b{b['index']} line [{b['line_id']}] {b.get('speaker', '')}{how}: \"{b.get('text', '')}\"")
        else:
            out.append(f"  b{b['index']} {b.get('kind', 'action')}: {b.get('text', '')}")
    return out


def _staging(doc: ZoraDoc) -> list[str]:
    st = doc.plan["staging"]
    out = [f"STAGING zones: {', '.join(st['zones'])}"]
    for m in st["marks"]:
        out.append(f"  mark [b{m['block']}, {m['who']}]: zone {m['zone']} · facing {m['facing'] or '—'} · frame "
                   f"{m['frame_side'] or '—'}" + (f" · holding {m['holding']}" if m["holding"] else ""))
    return out


def _end(doc: ZoraDoc, *, addresses: bool) -> list[str]:
    end = doc.plan["end_state"]
    out = [f"END STATE (what the next scene starts from): time {end['time']} · light {end['light']}"]
    for p in end["people"]:
        label = f"end.{p['who']}" if addresses else p["who"]
        out.append(f"  {label}{_lock(doc, f'end.{p['who']}')}: at {p['where']} · facing {p['facing'] or '—'} · "
                   f"holding {p['holding'] or 'nothing'} · look {p['look'] or '—'}")
    if end.get("props"):
        out.append("  props: " + "; ".join(f"{p['what']} at {p['where']}" for p in end["props"]))
    return out


def addressable(doc: ZoraDoc, only: set[int] | None = None, *, script: bool = True) -> str:
    """The plan as the conductor and the author read it. `only`: shot numbers printed in full (None = all)."""
    out = [HEADER, "", *_treatment(doc, addresses=True), "", "SEQUENCES"]
    for q in doc.sequences:
        out.append(f"  Sequence {q['id']} ({code(q['shots']['first'])}–{code(q['shots']['last'])}): "
                   f"{q['title']}{_lock(doc, f'sequence.{q['id']}.title')} — {q['purpose']}")
    out += ["", f"SHOTS ({doc.shot_range()})"]
    for s in doc.shots:
        out += _shot_full(doc, s, addresses=True) if only is None or s["n"] in only else [_shot_line(s)]
    out += ["", *_staging(doc), "", *_end(doc, addresses=True)]
    if script:
        out += ["", *_script(doc)]
    if doc.person.settled:
        out += ["", "SETTLED (the person handed these over: never ask about them): " + ", ".join(doc.person.settled)]
    return "\n".join(out)


def consumer(doc: ZoraDoc, only: set[int] | None = None) -> str:
    """The plan in plain words for the reply: the turn's shots in full, the rest one line each."""
    out = [*_treatment(doc, addresses=False), "", "Sequences"]
    for q in doc.sequences:
        out.append(f"  {q['id']} ({code(q['shots']['first'])}–{code(q['shots']['last'])}): {q['title']} — "
                   f"{q['purpose']}")
    out += ["", f"Shots ({doc.shot_range()})"]
    for s in doc.shots:
        out += _shot_full(doc, s, addresses=False) if only and s["n"] in only else [_shot_line(s)]
    out += ["", *_end(doc, addresses=False)]
    return "\n".join(out)
