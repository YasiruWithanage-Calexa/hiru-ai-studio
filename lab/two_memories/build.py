"""Step 2, the build (plan/2026-11-11 §4.2): code turns a split into the breakdown memory's skeleton and a finished episode
answer into scene briefs and blocks. Ids are numbered here, text is cut here; nothing is a model's words."""
from __future__ import annotations

from typing import Any

from . import ids
from .lines import Doc, Span, sentence_spans
from .schema import Breakdown, Entity, EpisodeW, Finding, Rule, Scene, SpanW, SplitW, Value

LITERAL = ("age", "gender")  # a fact of one word stays as pointed; every other field is widened to its sentence


def _name(doc: Doc, s: SpanW) -> str:
    sp = Span(s.line, s.w_from, s.w_to)
    return doc.text([sp]).strip(" .,:;-") if doc.span_ok(sp) else ""


def build(split: SplitW, doc: Doc, document: str) -> Breakdown:
    bd = Breakdown(document=document)
    reg = ids.Registry()
    for c in split.cards:
        e = Entity(id=reg.new({"person": "C", "place": "L", "thing": "P"}[c.kind]), kind=c.kind, name=_name(doc, c.name),
                   lines=(c.lines.start, c.lines.end), place_kind=c.place_kind, seen=c.seen)
        e.card["summary"] = Value(value=doc.cut(c.lines.start, c.lines.end), lines=e.lines)
        for f in c.fields:
            sp = Span(f.span.line, f.span.w_from, f.span.w_to)
            if not doc.span_ok(sp):
                bd.findings.append(Finding(code="sources", message=f"card {e.id}: field {f.name} points outside the document: dropped"))
                continue
            spans = [sp] if f.name in LITERAL else sentence_spans(doc, sp, c.lines.start, max(c.lines.end, f.span.line))
            e.card[f.name] = Value(value=doc.text(spans), lines=(spans[0].line, spans[-1].line))
        bd.entities.append(e)
    for c, e in zip(split.cards, bd.entities, strict=True):
        if not e.name:
            bd.findings.append(Finding(code="sources", blocking=True, message=f"{e.id}: the name points outside the document"))
        if c.within >= 0:
            if c.within < len(bd.entities) and bd.entities[c.within].kind == "place":
                e.within = bd.entities[c.within].id
            else:
                bd.findings.append(Finding(code="ids", blocking=True, message=f"{e.id} is within card {c.within}, which is no place"))
    for r in split.rules:
        rid = reg.new("D")
        scope = ""
        if r.scope_kind == "place" and 0 <= r.scope_card < len(bd.entities) and bd.entities[r.scope_card].kind == "place":
            scope = bd.entities[r.scope_card].id
        elif r.scope_kind in ("episode", "scene") and r.scope_number > 0:
            scope = str(r.scope_number)
        bd.rules.append(Rule(id=rid, about=r.about, text=doc.cut(r.lines.start, r.lines.end),
                             lines=(r.lines.start, r.lines.end), scope_kind=r.scope_kind, scope_id=scope))
    for ep in split.episodes:
        ep_n = ep.number or 1
        for sc in ep.scenes:
            bd.scenes.append(Scene(id=ids.scene(ep_n, sc.number), episode=ep_n, number=sc.number,
                                   heading=doc.lines[sc.heading - 1].strip(), heading_line=sc.heading,
                                   first=sc.heading + 1, last=sc.last))
    return bd


def apply_episode(bd: Breakdown, doc: Doc, ep: EpisodeW) -> None:
    """Step 4's answer: briefs and blocks. Block ids and event ids are numbered by code; the words are cut by code."""
    for brief in ep.scenes:
        scene = bd.scene(brief.scene)
        if scene is None:
            bd.findings.append(Finding(code="ids", scene=brief.scene, blocking=True,
                                       message="episode answer names a scene that does not exist"))
            continue
        blocks: list[dict[str, Any]] = []
        for i, b in enumerate(brief.blocks, 1):
            bid = ids.block(scene.id, i)
            spans = [Span(s.line, s.w_from, s.w_to) for s in b.spans]
            d = b.model_dump(exclude={"spans", "events"})
            d.update(id=bid, spans=[[s.line, s.w_from, s.w_to] for s in spans],
                     text=doc.text(spans) if all(doc.span_ok(s) for s in spans) else "",
                     events=[{"id": ids.event(bid, j), **e.model_dump()} for j, e in enumerate(b.events, 1)])
            blocks.append(d)
        scene.blocks = blocks
        scene.brief = brief.model_dump(exclude={"blocks", "scene"})
