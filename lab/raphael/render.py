"""The page a person reads: DaVinci's page (the intended cut, the bin by moment, the notes, the checks, Jonathan beside it),
titled for Raphael and with the length against both the target and the cap. One self-contained HTML file."""
from __future__ import annotations

from html import escape
from typing import Any

from davinci import checks, render
from davinci.checks import Fault
from davinci.state import Bin


def build(reading: Any, work: Bin, found: list[Fault], stopped: str, detail: str, source: str,
          jonathan: dict[str, Any] | None = None, turns: int = 0) -> str:
    n = work.counts()
    cap = checks.limit_s(reading)
    length = (f"{n['take_s']} s of takes ({n['must_take_s']} s must) against a target of {reading.guide_s:g} s and a cap of "
              f"{cap:g} s" if cap else f"{n['take_s']} s of takes")
    html = render.page(f"Raphael bin: {reading.title}", source, reading.words(), work, found, checks.measures(reading, work),
                       stopped, detail, jonathan)
    html = html.replace("<th>DaVinci</th>", "<th>Raphael</th>")
    extra = f"<p><b>Length:</b> {escape(length)}. <b>Turns used:</b> {turns}.</p>"
    return html.replace("</p>", "</p>" + extra, 1) if "</p>" in html else html + extra


# ── stage 2: the same page, two layers (plan/2026-11-08e §2.2, phase 0c) ─────────────────────────

LAYER_CSS = (".cinematic{border-left:6px solid #7a3fb0;margin-left:1.5rem}.chip.cin{background:#efe4f8;color:#4b1f72}"
             ".locked{color:#555;font-size:.85rem}")


def build_layers(reading: Any, work: Bin, found: list[Fault], stopped: str, detail: str, source: str,
                 jonathan: dict[str, Any] | None = None, turns: int = 0, blend_notes: list[str] | None = None,
                 changed_must: list[str] | None = None, review: list[dict[str, Any]] | None = None) -> str:
    """Stage 1's page, with the cinematic clips (stage 2) marked under their moment: a `cinematic` chip, the anchor and the
    blend on each card, a table of the layer and the blend notes. The intended cut stays the must cut."""
    import re

    from .stage2 import STAGE2_MARGIN, cap_s, extras

    html = build(reading, work, found, stopped, detail, source, jonathan, turns)
    old, new = checks.limit_s(reading), cap_s(reading)
    if old and new != old:  # stage 2's cap is the given length x 2, not stage 1's 1.5x
        html = html.replace(f"and a cap of {old:g} s", f"and a cap of {new:g} s (stage 2: the given length x {1 + STAGE2_MARGIN:g})", 1)
        took = work.counts()["take_s"]
        html = re.sub(r"<tr><td>length</td><td>\w+</td><td>[^<]*</td></tr>",
                      f"<tr><td>length</td><td>{'met' if took <= new else 'missed'}</td><td>{took} s of takes against stage 2's "
                      f"cap of {new:g} s (the given {reading.guide_s:g} s x {1 + STAGE2_MARGIN:g})</td></tr>", html, count=1)
    html = html.replace("</style>", LAYER_CSS + "</style>", 1)
    by_id = {c.id: c for c in work.clips}
    for e in extras(work):
        anchors = ", ".join(f"{a} [{by_id[a].slate}]" if a in by_id else a for a in e.anchor)
        html = html.replace(f'<div class="card {e.priority}"><span class="slate">{escape(e.slate)}</span> '
                            f'<span class="chip">{escape(e.id)}</span>',
                            f'<div class="card {e.priority} cinematic"><span class="slate">{escape(e.slate)}</span> '
                            f'<span class="chip">{escape(e.id)}</span><span class="chip cin">cinematic, optional</span>'
                            f'<span class="chip cin">{escape(e.blend)}</span><span class="chip cin">anchor {escape(anchors)}</span>', 1)
    rows = "".join(f"<tr><td>{escape(e.slate)}</td><td>{e.id}</td><td>{e.moment}</td><td>{escape(e.role)}</td>"
                   f"<td>{escape(e.technique)}</td><td>{e.take_s} s</td><td>{escape(', '.join(e.anchor))}</td>"
                   f"<td>{escape(e.blend)}</td><td>{escape(e.why)}</td></tr>" for e in extras(work))
    secs = sum(e.take_s for e in extras(work))
    unchanged = ('<p class="ok">Every must clip is exactly as stage 1 left it.</p>' if not changed_must else
                 f'<p class="fault">Must clips changed by stage 2: {escape(", ".join(changed_must))}</p>')
    layer = (f"<h2>The cinematic layer (stage 2)</h2><p>{len(extras(work))} cinematic clip(s), {secs} s, optional: post blends "
             "them in at their anchor. The intended cut above is the must cut.</p>" + unchanged
             + ("<table><tr><th>slate</th><th>id</th><th>moment</th><th>role</th><th>technique</th><th>take</th><th>anchor</th>"
                f"<th>blend</th><th>why</th></tr>{rows}</table>" if rows else "<p>No cinematic clip.</p>")
             + "<h3>Blend notes</h3>" + ("<ul>" + "".join(f"<li>{escape(n)}</li>" for n in blend_notes) + "</ul>"
                                         if blend_notes else "<p>None.</p>")
             + ("<h3>Moment review</h3><table><tr><th>moment</th><th>earns</th><th>why</th></tr>" + "".join(
                 f"<tr><td>{r.get('moment')}</td><td>{'yes' if r.get('earns') else 'no'}</td><td>{escape(str(r.get('why', '')))}</td></tr>"
                 for r in review) + "</table>" if review else ""))
    marker = "<h2>The shoot bin</h2>"
    return html.replace(marker, layer + marker, 1) if marker in html else html + layer
