"""views_writer hooks (plan/2026-11-24; plan/2026-11-24c, lab/place_views r2).

The person's method: ONE picture of a place in six named views keeps the place the same in every board panel and first
frame. The sheet is made at CANON time, so it covers the place's main POSSIBLE views: this agent answers three questions
about the place (sides, moves, size), which pick one of four fixed templates (`contracts.canon.VIEW_TEMPLATES`), and
writes each slot. `contracts.canon.view_findings` checks the answer in code; `views_sheet_prompt` paints it. A person
may edit the views before painting, and then this agent is not called. No fallback: without a model nothing is painted.

The message is the lab's `user_message`, word for word, with these additions (plan §2.2): the storyboards' geography,
the fixed places that stand in it, the vehicles that come and go, a person's answers, and the re-ask's findings.
"""
from __future__ import annotations

from hiru_ai.agents.views_writer.schema import Input


def user_message(inp: Input) -> str:
    kind = "a vehicle card" if inp.vehicle else "a place card"
    parts = [f"The place: {inp.place.name} ({kind}).", f"Its look (the canon card): {inp.place.look}"]
    if inp.spots:
        parts.append("Its parts: " + "; ".join(f"{s.name}: {s.look}" for s in inp.spots))
    parts.append("Its picture is attached: keep its look and where its things stand." if inp.picture else
                 "It has no picture yet: the sheet will be painted from your words only.")
    if inp.within:
        parts.append("Other places that stand in it in these scenes (fixed, part of it): "
                     + "; ".join(f"{p.name}: {p.look}" for p in inp.within))
    if inp.comes_and_goes:
        parts.append("Things that come and go here (vehicles with sheets of their own; keep where they stand empty): "
                     + "; ".join(f"{p.name}: {p.look}" for p in inp.comes_and_goes))
    if inp.geographies:
        parts.append("How the storyboards of these scenes laid the place out:\n" + "\n".join(inp.geographies))
    if inp.scenes:
        parts.append("Scenes set there or using it:\n" + "\n".join(inp.scenes))
    if inp.answers:
        a = inp.answers
        parts.append(f"The person's answers (use them): sides {a.sides}; moves {'yes' if a.moves else 'no'}; "
                     f"size {a.size}.")
    if inp.findings:
        parts.append("Your first answer had these faults. Write the whole answer again without them:\n"
                     + "\n".join(f"- {f}" for f in inp.findings))
    return "\n\n".join(parts)


def images(inp: Input) -> list[tuple[str, str]]:
    return [(inp.picture.mime, inp.picture.b64)] if inp.picture else []
