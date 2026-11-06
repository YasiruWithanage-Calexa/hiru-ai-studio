"""What the person reads (plan/2026-11-06 §6). No model, no network.

    plan_html(...)            a self-contained page laid out like a shot list: the treatment card, the colour script, the
                              sequences with their time windows, one card per shot, the staging, the problems and measures
    plain_list(...)           the plan as a plain list (sequence, size, what, purpose) for the blind read
    side_by_side(entries)     the plans as plain lists under shuffled letters, nothing naming whose they are, and the key

Every string a model wrote is escaped; nothing here executes it.
"""
from __future__ import annotations

import colorsys
import html
import random
import re
from typing import Any

from contracts.david.plan import Problem

from .checks import Measure
from .pack import Reading, is_heard
from .schema import CinemaShotW, CinemaWire

e = html.escape

CSS = """
:root{--bg:#fafaf8;--ink:#1c1b19;--mute:#6b6a66;--card:#fff;--line:#e3e1db;--warn:#a4381f;--ok:#2d6b3c;--info:#55606e}
@media (prefers-color-scheme:dark){:root{--bg:#161614;--ink:#ece9e2;--mute:#9b988f;--card:#1f1e1b;--line:#33312c;--warn:#e58b72;--ok:#7cc48b;--info:#9aa6b5}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,sans-serif}
main{max-width:980px;margin:0 auto;padding:24px 16px 64px}h1{font-size:1.5rem;margin:0 0 4px}h2{font-size:1.1rem;margin:32px 0 8px}
.mute{color:var(--mute)}.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:10px 0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px}.strip{display:flex;gap:4px;margin:8px 0}
.sw{flex:1;min-height:76px;border-radius:8px;padding:8px;font-size:.78rem;color:#fff;text-shadow:0 1px 2px rgba(0,0,0,.6)}
.shot{display:grid;grid-template-columns:64px 1fr;gap:12px}.n{font-size:1.4rem;font-weight:650}.tag{display:inline-block;border:1px solid var(--line);
border-radius:99px;padding:0 8px;font-size:.78rem;margin-right:4px}.bad{color:var(--warn)}.good{color:var(--ok)}.infoc{color:var(--info)}
ul{margin:4px 0;padding-left:20px}.line{border-left:3px solid var(--line);padding-left:10px;margin:6px 0}.beats{font-size:.88rem;color:var(--mute)}
table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid var(--line);padding:4px 6px;text-align:left;vertical-align:top}
pre{white-space:pre-wrap;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px}
@media (max-width:560px){.shot{grid-template-columns:1fr}}
"""


def page(title: str, body: str) -> str:
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,'
            f'initial-scale=1"><title>{e(title)}</title><style>{CSS}</style></head><body><main>{body}</main></body></html>')


def swatch(text: str) -> str:
    """A colour that suggests a grade written in words (cool, warm, desaturated ...): a reading aid, not a grade."""
    low = text.lower()
    hue = 28 if any(w in low for w in ("warm", "gold", "amber", "sun")) else 205
    if any(w in low for w in ("cool", "teal", "blue", "grey", "gray", "cold")) and not any(w in low for w in ("warm", "gold")):
        hue = 200
    sat = 0.15 if any(w in low for w in ("desaturat", "drain", "flat", "muted")) else 0.42
    r, g, b = colorsys.hls_to_rgb(hue / 360, 0.36, sat)
    return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"


def _first_action(shot: CinemaShotW) -> str:
    for beat in shot.ir.get("beats") or []:
        if isinstance(beat, dict) and str(beat.get("action") or "").strip():
            return str(beat["action"]).strip()
    return shot.why


def windows(plan: CinemaWire) -> dict[str, tuple[int, int]]:
    """Each sequence's time window in the cut, from the seconds the edit keeps."""
    out, clock = {}, 0
    for q in plan.sequences:
        used = sum(s.use_s for s in plan.shots if s.sequence == q.id)
        out[q.id] = (clock, clock + used)
        clock += used
    return out


def _line_html(reading: Reading, shot: CinemaShotW) -> str:
    said = reading.words()
    rows = []
    for ln in shot.lines:
        if ln in said:
            speaker, words = said[ln]
            block = reading.scene.line_block(ln)
            heard = " (heard, not seen)" if block is not None and is_heard(block) else ""
            rows.append(f'<div class="line"><b>{e(speaker)}</b>{e(heard)}: “{e(words)}”</div>')
    if shot.over:
        rows.append(f'<div class="mute">The picture stays on {e(shot.over)} while the line is heard.</div>')
    return "".join(rows)


def _shot_html(reading: Reading, plan: CinemaWire, s: CinemaShotW) -> str:
    cin = s.ir.get("cinematography") or {}
    added = [a for a in plan.added if a.shot == s.n]
    sound = ", ".join(x for x in (s.sound.ambience, s.sound.effects, s.sound.music) if x)
    beats = "".join(f"<li>{e(str(b.get('time')))}: {e(str(b.get('action')))} <i>({e(str(b.get('performance')))})</i></li>"
                    for b in s.ir.get("beats") or [] if isinstance(b, dict))
    tags = [s.size, s.angle, s.lens, str(cin.get("movement") or "")]
    return (f'<div class="card shot"><div class="n">S{s.n:02d}</div><div>'
            + "".join(f'<span class="tag">{e(t)}</span>' for t in tags if t)
            + f'<span class="tag">take {s.take_s} s</span><span class="tag">keeps {s.use_s} s</span>'
            + "".join(f'<span class="tag">added: {e(a.kind)}</span>' for a in added)
            + f'<p>{e(s.why)}</p>' + _line_html(reading, s)
            + f'<div class="mute">Sound: {e("silence" if s.sound.silence and not sound else sound or "—")}'
              + (" (silent: no speech)" if s.sound.silence and sound else "") + "</div>"
            + f'<ul class="beats">{beats}</ul></div></div>')


def plan_html(reading: Reading, plan: CinemaWire, *, found: list[Problem], measures: list[Measure],
              mended: list[str], title: str = "") -> str:
    t = plan.treatment
    win = windows(plan)
    arc = "".join(f"<tr><td>{e(a.beat)}</td><td>b{a.blocks.first}–b{a.blocks.last}</td><td>{e(a.feeling)}</td></tr>"
                  for a in t.arc)
    strip = "".join(f'<div class="sw" style="background:{swatch(c.grade + " " + c.palette)}"><b>{e(c.sequence)}</b><br>'
                    f'{e(c.grade)}</div>' for c in t.colour_script)
    colours = "".join(f"<tr><td>{e(c.sequence)}</td><td>{e(c.palette)}</td><td>{e(c.light)}</td><td>{e(c.grade)}</td></tr>"
                      for c in t.colour_script)
    seqs = ""
    for q in plan.sequences:
        a, b = win[q.id]
        seqs += (f"<h2>{e(q.id)} · {e(q.title)} <span class=\"mute\">({a}–{b} s)</span></h2><p class=\"mute\">"
                 f"{e(q.purpose)}</p>" + "".join(_shot_html(reading, plan, s) for s in plan.shots if s.sequence == q.id))
    staging = "".join(f"<li>from b{m.block}: {e(m.who)} in the {e(m.zone)}"
                      + (f", facing {e(m.facing)}" if m.facing else "") + (f", {e(m.frame_side)} of frame" if m.frame_side else "")
                      + (f", holding {e(m.holding)}" if m.holding else "") + "</li>" for m in plan.staging.marks)
    problems = "".join(f'<li class="bad">[{e(p.code)}] {e(p.sentence)}</li>' for p in found) or '<li class="good">none</li>'
    marks = "".join(f'<tr><td class="{ {"met": "good", "missed": "bad"}.get(m.status, "infoc") }">{e(m.status)}</td>'
                    f'<td>{e(m.label)}</td><td>{e(m.detail)}</td></tr>' for m in measures)
    fixed = "".join(f"<li>{e(x)}</li>" for x in mended)
    body = (f'<h1>{e(title or reading.title)}</h1><div class="mute">{len(plan.shots)} shots · '
            f'{sum(s.take_s for s in plan.shots)} s of takes · {sum(s.use_s for s in plan.shots)} s kept'
            + (f' · guide {reading.guide_s:g} s' if reading.guide_s else "") + '</div>'
            f'<h2>Treatment</h2><div class="card"><p><b>{e(t.logline)}</b></p><p>{e(t.approach)}</p>'
            f'<p><b>Key image.</b> {e(t.key_image)}</p><p><b>Geography.</b> {e(t.geography)}</p>'
            f'<table><tr><th>Beat</th><th>Blocks</th><th>Feeling</th></tr>{arc}</table>'
            + ('<p><b>Director\'s advice</b> (shown, never applied)</p><ul>' + "".join(f"<li>{e(x)}</li>" for x in t.advice)
               + "</ul>" if t.advice else "") + '</div>'
            f'<h2>Colour script</h2><div class="strip">{strip}</div><div class="card"><table><tr><th>Seq</th><th>Palette</th>'
            f'<th>Light</th><th>Grade</th></tr>{colours}</table></div>'
            f'{seqs}<h2>Staging</h2><div class="card"><p class="mute">Spots: {e(", ".join(plan.staging.zones))}</p>'
            f'<ul>{staging}</ul></div>'
            f'<h2>Hard problems left</h2><div class="card"><ul>{problems}</ul></div>'
            + (f'<h2>What code mended</h2><div class="card"><ul>{fixed}</ul></div>' if mended else "")
            + f'<h2>Craft measures <span class="mute">(reported, never blocking)</span></h2><div class="card">'
              f'<table>{marks}</table></div>')
    return page(f"{title or reading.title}: shot list", body)


# ── the blind read ───────────────────────────────────────────────────────────────────────────────


def shot_card(shot: dict[str, Any], said: dict[str, tuple[str, str]], keeps: int | None = None) -> str:
    """One shot as a professional shot-list entry, from a plan's shot as a dict: the same fields for every contestant, so a
    blind read compares the plans and not how much detail a page chose to print."""
    ir = shot.get("ir") or {}
    cin = ir.get("cinematography") or {}
    sound = shot.get("sound") or {}
    angle = shot.get("angle") or cin.get("angle") or ""
    lens = shot.get("lens") or cin.get("camera") or ""
    head = f"SHOT {int(shot['n']):02d} — {shot['size']}, {shot['take_s']} s" + (f" (keeps {keeps} s)" if keeps else "")
    rows = [head, "  Camera: " + " · ".join(x for x in (angle, lens, cin.get("movement") or "") if x)]
    if cin.get("framing"):
        rows.append(f"  Framing: {cin['framing']}")
    for beat in ir.get("beats") or []:
        if isinstance(beat, dict) and str(beat.get("action") or "").strip():
            note = "; ".join(str(beat[k]).strip() for k in ("camera", "performance") if str(beat.get(k) or "").strip())
            rows.append(f"  Visual {beat.get('time', '')}: {str(beat['action']).strip()}" + (f" ({note})" if note else ""))
    if not ir.get("beats"):
        rows.append(f"  Visual: {shot.get('why', '')}")
    rows.append(f"  Purpose: {shot.get('why', '')}")
    if shot.get("over"):
        rows.append(f"  (the picture stays on {shot['over']} while the line is heard)")
    lines = [f'{said[ln][0]}: "{said[ln][1]}"' for ln in shot.get("lines") or [] if ln in said]
    if lines:
        rows.append("  Says: " + " / ".join(lines))
    heard = ", ".join(x for x in (sound.get("ambience"), sound.get("effects"), sound.get("music")) if x)
    rows.append("  Audio: silence" if sound.get("silence") else (f"  Audio: {heard}" if heard else ""))
    return "\n".join(r for r in rows if r)


def plain_list(reading: Reading, plan: CinemaWire) -> str:
    """The plan as a shot list: a sequence heading, then one full shot card each (see `shot_card`)."""
    said = reading.words()
    out = []
    for q in plan.sequences:
        out.append(f"{q.id}. {q.title.upper()}: {q.purpose}")
        for s in (x for x in plan.shots if x.sequence == q.id):
            out.append(shot_card(s.model_dump(), said, s.use_s))
        out.append("")
    return "\n".join(out).strip()


def side_by_side(entries: dict[str, str], seed: int = 0) -> tuple[str, dict[str, str]]:
    """-> (the page, the key). Each plan is one plain list under a letter; the order is shuffled and nothing names whose
    it is. The key says which letter is which."""
    names = [n for n, text in entries.items() if text.strip()]
    letters = ["X", "Y", "Z", "W"][:len(names)]
    order = list(names)
    random.Random(seed).shuffle(order)  # noqa: S311 (a shuffle of letters, not a secret)
    key = dict(zip(letters, order, strict=True))
    cols = "".join(f'<div class="card"><h2>Plan {x}</h2><pre>{e(entries[key[x]])}</pre></div>' for x in letters)
    rubric = ("<p class=\"mute\">Score each plan with rubric.md: geography, coverage per beat, reactions, inserts, camera "
              "language, colour arc, sequence endings, would I shoot this.</p>")
    return page("Blind read", f'<h1>Blind read</h1>{rubric}<div class="grid">{cols}</div>'), key


def comments_stripped(text: str) -> str:
    """A pasted file without its html comments (the lab's own instructions in `input/chatgpt.md`)."""
    return re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL).strip()


def david_today(stored: list[dict[str, Any]]) -> str:
    """David's stored plans as the same shot cards the lab's plan gets (`shot_card`), one scene after the other."""
    out = []
    for item in stored:
        said = {b["line_id"]: (b.get("speaker", ""), b["text"]) for b in item["scene"]["blocks"] if b.get("line_id")}
        out.extend(shot_card(s, said) for s in item["stored"]["plan"]["shots"])
    return "\n\n".join(out)
