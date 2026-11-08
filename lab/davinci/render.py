"""The page a person reads (plan/2026-11-08d §2): the intended cut, the shoot bin grouped by moment and role, the editor
notes, the checks, and Jonathan's cut of the same scene beside it for the phase-0 comparison. One self-contained HTML file."""
from __future__ import annotations

import json
from html import escape
from typing import Any

from . import checks
from .checks import Fault, Measure
from .schema import Clip
from .state import Bin

CSS = """
body{font:15px/1.5 system-ui,sans-serif;max-width:1100px;margin:2rem auto;padding:0 1rem;color:#1c1c1c;background:#fafafa}
h1{font-size:1.5rem}h2{margin-top:2.2rem;border-bottom:2px solid #ddd;padding-bottom:.2rem}h3{margin:1.4rem 0 .4rem}
.note{background:#fff7e0;border:1px solid #ecd9a0;padding:.6rem .9rem;border-radius:6px}
.card{background:#fff;border:1px solid #ddd;border-radius:8px;padding:.6rem .9rem;margin:.5rem 0}
.must{border-left:6px solid #c8102e}.should{border-left:6px solid #2f6fb0}.nice{border-left:6px solid #8a8a8a}
.slate{font:600 1.05rem ui-monospace,monospace}.chip{display:inline-block;font-size:.75rem;padding:0 .5rem;border-radius:99px;background:#eee;margin-left:.3rem}
.bar{display:flex;height:14px;margin:.4rem 0;border-radius:3px;overflow:hidden;background:#eee}
.bar i{display:block;height:100%}.h{background:#f4c27a}.a{background:#4c9a63}
.fault{color:#8a1c1c}.ok{color:#256b3a}table{border-collapse:collapse}td,th{border:1px solid #ddd;padding:.25rem .6rem;text-align:left}
details pre{white-space:pre-wrap;font-size:.8rem;background:#f3f3f3;padding:.5rem}
"""


def bar(clip: Clip) -> str:
    take = clip.take_s
    a = max(take - clip.handle_in_s - clip.handle_out_s, 0)
    seg = [("h", clip.handle_in_s), ("a", a), ("h", clip.handle_out_s)]
    cells = "".join(f'<i class="{k}" style="width:{100 * v / take:.1f}%"></i>' for k, v in seg)
    return f'<div class="bar" title="handle {clip.handle_in_s:g} s, action {a:g} s, handle {clip.handle_out_s:g} s">{cells}</div>'


def card(clip: Clip, words: dict[str, tuple[str, str]]) -> str:
    said = "".join(f"<div><b>{escape(lid)}</b> {escape(words[lid][0])}: {escape(words[lid][1])}</div>" for lid in clip.lines
                   if lid in words)
    perform = "performs the line" if clip.speaks else ("plays silent under the chosen audio" if clip.lines else "")
    design = (f"<details><summary>design</summary><pre>{escape(json.dumps({'ir': clip.ir, 'sound': clip.sound.model_dump() if clip.sound else None}, ensure_ascii=False, indent=1))}</pre></details>"
              if clip.ir is not None else "<i>no design yet</i>")
    return (f'<div class="card {clip.priority}"><span class="slate">{escape(clip.slate)}</span> '
            f'<span class="chip">{escape(clip.id)}</span><span class="chip">{clip.priority}</span>'
            f'<span class="chip">{escape(clip.role)}</span><span class="chip">{escape(clip.technique)}</span>'
            f'<span class="chip">{escape(clip.size)}</span><span class="chip">{clip.take_s} s</span>{bar(clip)}'
            f"<div>{escape(clip.why)}</div>"
            + (f"<div>blocks {clip.blocks}" + (f"; {perform}" if perform else "") + "</div>" if clip.blocks or clip.lines else "")
            + (f"<div>shows {escape(clip.over)} while the line is heard</div>" if clip.over else "")
            + said + (f"<div><i>{escape(clip.editor_note)}</i></div>" if clip.editor_note else "") + design + "</div>")


def jonathan_table(jon: dict[str, Any] | None, work: Bin) -> str:
    if not jon:
        return "<p>No Jonathan plan was given for this scene.</p>"
    shots = jon.get("shots") or []
    n = work.counts()
    rows = [("shots / clips", len(shots), n["clips"]),
            ("seconds of takes", sum(s.get("take_s", 0) for s in shots), n["take_s"]),
            ("seconds the edit keeps (Jonathan `use_s`) / seconds of must clips", sum(s.get("use_s", 0) for s in shots), n["must_take_s"]),
            ("alternates for the editor (clips beyond one per moment)", 0, n["should"] + n["nice"])]
    body = "".join(f"<tr><td>{escape(str(a))}</td><td>{b}</td><td>{c}</td></tr>" for a, b, c in rows)
    listing = "".join(f"<tr><td>{s.get('n')}</td><td>{escape(str(s.get('size')))}</td><td>{s.get('take_s')}/{s.get('use_s')}</td>"
                      f"<td>{escape(str(s.get('why', '')))}</td></tr>" for s in shots)
    return (f"<table><tr><th></th><th>Jonathan</th><th>DaVinci</th></tr>{body}</table>"
            f"<details><summary>Jonathan's {len(shots)} shots</summary><table><tr><th>n</th><th>size</th><th>take/use</th><th>why</th></tr>"
            f"{listing}</table></details>")


def stage_table(stages: list[dict[str, Any]] | None) -> str:
    """Staged runs (plan B): when each stage started and ended, how many model calls it made and what they cost."""
    if not stages:
        return ""
    rows = "".join(f"<tr><td>{escape(str(s['stage']))}</td><td>{escape(str(s['start']))}</td><td>{escape(str(s['end']))}</td>"
                   f"<td>{s['seconds']:g}</td><td>{s['calls']}</td><td>${s['dollars']:.2f}</td><td>{escape(str(s.get('detail', '')))}</td></tr>"
                   for s in stages)
    total = (f"<tr><td><b>total</b></td><td></td><td></td><td>{sum(s['seconds'] for s in stages):g}</td>"
             f"<td>{sum(s['calls'] for s in stages)}</td><td>${sum(s['dollars'] for s in stages):.2f}</td><td></td></tr>")
    return ("<h2>Stages</h2><table><tr><th>stage</th><th>start</th><th>end</th><th>seconds</th><th>calls</th><th>dollars</th>"
            f"<th>what happened</th></tr>{rows}{total}</table>")


def page(title: str, source: str, words: dict[str, tuple[str, str]], work: Bin, found: list[Fault], measured: list[Measure],
         stopped: str, detail: str, jonathan: dict[str, Any] | None = None, stages: list[dict[str, Any]] | None = None) -> str:
    plan = work.edit
    out = [f"<!doctype html><meta charset=utf-8><title>{escape(title)}</title><style>{CSS}</style><h1>{escape(title)}</h1>",
           f'<p class="note">{escape(source)}</p>',
           f"<p>The run ended: <b>{escape(stopped)}</b>. {escape(detail)}</p>", stage_table(stages)]
    if plan is not None:
        t = plan.treatment
        out.append("<h2>The intended cut</h2><p>A reference for the editor, not a binding edit.</p>"
                   f"<p><b>{escape(t.logline)}</b></p><p>{escape(t.approach)}</p><p><i>Key image:</i> {escape(t.key_image)}</p>"
                   f"<p><i>Geography:</i> {escape(t.geography)}</p><table><tr><th>moment</th><th>sequence</th><th>blocks</th>"
                   "<th>what</th><th>feeling</th><th>the cut uses</th></tr>"
                   + "".join(f"<tr><td>{m.n}</td><td>{escape(m.sequence)}</td><td>{m.blocks}</td><td>{escape(m.what)}</td>"
                             f"<td>{escape(m.feeling)}</td><td>{escape(m.cut_uses)}</td></tr>" for m in plan.moments) + "</table>")
        out.append("<h2>The shoot bin</h2>")
        for m in plan.moments:
            mine = [c for c in work.clips if c.moment == m.n]
            out.append(f"<h3>Moment {m.n}: {escape(m.what)} <small>({len(mine)} clips)</small></h3>")
            out += [card(c, words) for c in sorted(mine, key=lambda c: (c.priority != "must", c.priority != "should", c.id))]
        stray = [c for c in work.clips if c.moment not in {m.n for m in plan.moments}]
        if stray:
            out.append("<h3>In no moment of the plan</h3>" + "".join(card(c, words) for c in stray))
    else:
        out.append("<h2>The shoot bin</h2><p>No edit plan was written.</p>" + "".join(card(c, words) for c in work.clips))
    notes = plan.editor_notes if plan else []
    out.append("<h2>Editor notes</h2>" + ("<ul>" + "".join(f"<li>{escape(n)}</li>" for n in notes) + "</ul>" if notes else "<p>None.</p>"))
    out.append("<h2>Checks</h2>" + ("<ul class=fault>" + "".join(f"<li>{escape(f.line())}</li>" for f in found) + "</ul>"
                                    if found else '<p class="ok">No faults.</p>'))
    out.append("<h2>Coverage measures</h2><table>" + "".join(
        f"<tr><td>{escape(m.label)}</td><td>{m.status}</td><td>{escape(m.detail)}</td></tr>" for m in measured) + "</table>")
    out.append("<h2>Jonathan's cut of the same scene</h2>" + jonathan_table(jonathan, work))
    return "".join(out)


def build(reading: Any, work: Bin, found: list[Fault], stopped: str, detail: str, source: str,
          jonathan: dict[str, Any] | None = None, stages: list[dict[str, Any]] | None = None) -> str:
    return page(f"DaVinci bin: {reading.title}", source, reading.words(), work, found, checks.measures(reading, work), stopped,
                detail, jonathan, stages)
