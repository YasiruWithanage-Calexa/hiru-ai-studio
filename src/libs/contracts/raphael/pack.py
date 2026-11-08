"""The first message of each stage (plan/2026-11-08e §3.1, §3.5): what the agent is given, built by code. No model.

    opening_stage1(...)   <production>, <scene>, <script>, <voice_only>, <length>, then "Plan this scene."
    opening_stage2(...)   the same, then <intended_cut>, <must_bin>, <looks>, <room>

The lab's messages (`lab/cinematic/pack.py`, `lab/raphael/agent.py`, `lab/raphael/stage2.py`), ported. Everything the
agent
needs is in this one message; it never asks another model for anything.
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from contracts.raphael.bin import Bin
from contracts.raphael.checks import PER_MOMENT_MAX, SHORT_SHARE, limit_s
from contracts.raphael.scene import Brief, SceneS, heard_names, listing, long_actions, script_s
from contracts.raphael.wire import STAGE1_CAP


def _words(text: Any) -> str:
    return " ".join(str(text).split())


def person_line(p: dict[str, Any]) -> str:
    """One person: their look, their voice and WHO THEY ARE (the essence the coverage is planned from)."""
    bits = [
        f"look: {p['look']}" if p.get("look") else "",
        f"voice: {p['voice']}" if p.get("voice") else "",
        f"who they are: {p['essence']}" if p.get("essence") else "",
    ]
    said = "; ".join(_words(b).rstrip(".") for b in bits if b)
    return f"- {p['name']} ({p.get('code') or '-'})" + (f": {said}" if said else "")


def production_part(production: dict[str, Any]) -> str:
    people = [person_line(p) for p in production.get("people") or []]
    rules = [f"- {r}" for r in production.get("rules") or []]
    rows = [
        f"Style guide: {_words(production['style_note'])}" if production.get("style_note") else "",
        "Production rules:\n" + "\n".join(rules) if rules else "",
        "People in this episode:\n" + "\n".join(people) if people else "",
    ]
    return "\n".join(r for r in rows if r)


def scene_part(context: dict[str, Any]) -> str:
    rows = [
        f"Scene: {context['heading']}" if context.get("heading") else "",
        f"Episode: {context['episode_title']}" if context.get("episode_title") else "",
        f"Episode synopsis: {context['synopsis']}" if context.get("synopsis") else "",
        f"The scene before: {context['before']}" if context.get("before") else "",
        f"The scene after: {context['after']}" if context.get("after") else "",
        f"The place card: {context['place']}" if context.get("place") else "",
        f"Director's note: {_words(context['note'])}" if context.get("note") else "",
    ]
    return "\n".join(r for r in rows if r)


def message(production: dict[str, Any], context: dict[str, Any], scene: SceneS, extra: str = "") -> str:
    """The user message, tagged: <production>, <scene>, <script> (the script last: what is the same for the whole job
    comes
    first, so it caches)."""
    script = listing(scene) + (("\n\n" + extra) if extra else "")
    parts = [("production", production_part(production)), ("scene", scene_part(context)), ("script", script)]
    return "\n\n".join(f"<{tag}>\n{text}\n</{tag}>" for tag, text in parts if text)


def voice_only(scene: SceneS) -> str:
    """The people who are only heard, listed by code from the script, so the rule cannot be missed."""
    names = heard_names(scene)
    if not names:
        return ""
    return (
        "<voice_only>\n"
        + ", ".join(names)
        + ": heard and never seen. Never in subjects or first_frame, and never named in any clip's picture text, not "
        "even "
        "as the person someone listens to.\n</voice_only>"
    )


def length_block(brief: Brief) -> str:
    """The length rule in seconds (never money): the target is the given length, stage 1's cap is 1.5x and is hard,
    and (plan/2026-11-08f §3) a bin under 80 % of the target cannot finish. The script's own time is worked out by code
    and given here, so the coverage the target asks for is planned from the first turn."""
    cap = limit_s(brief, STAGE1_CAP)
    if not cap:
        return ""
    floor = brief.guide_s * SHORT_SHARE
    own = script_s(brief.scene)
    cover = max(brief.guide_s - own, 0.0)
    gap = (
        f"The script itself times at {own:.0f} s (its actions and lines on one clock); the other {cover:.0f} s of the "
        "target is COVERAGE of the same moments: the master, each speaker's single, the listener's reaction where a "
        "line lands. "
        if cover >= 1
        else f"The script itself times at {own:.0f} s. "
    )
    long = long_actions(brief.scene)
    spread = (
        "Long actions ("
        + ", ".join(f"b{b} {s:.1f} s" for b, s in sorted(long.items()))
        + ") are longer than any take: show each over consecutive clips, each the next part. "
        if long
        else ""
    )
    return (
        f"<length>\nThe scene is {brief.guide_s:g} s long. TARGET: a bin of about {brief.guide_s:g} s of takes. "
        f"{gap}{spread}"
        f"CAP: {cap:g} s of takes (the given length x {STAGE1_CAP:g}); `finish` refuses a bin over it, and a bin "
        f"under {floor:g} s. The room between the target and the cap is allowed, not expected.\n</length>"
    )


def opening_stage1(production: dict[str, Any], context: dict[str, Any], brief: Brief, extra: str = "") -> str:
    return "\n\n".join(
        p
        for p in (
            message(production, context, brief.scene, extra),
            voice_only(brief.scene),
            length_block(brief),
            "Plan this scene. Start with the intended cut.",
        )
        if p
    )


# ── stage 2 ──────────────────────────────────────────────────────────────────────────────────────


def _common(values: list[str]) -> str:
    values = [" ".join(v.split()) for v in values if v and v.strip()]
    return Counter(values).most_common(1)[0][0] if values else ""


def looks(work: Bin) -> dict[int, dict[str, Any]]:
    """Per moment, the words the must clips use for the place, the light and each person (the commonest), so a cinematic
    clip can copy them word for word and pass the consistency check."""
    out: dict[int, dict[str, Any]] = {}
    for n in sorted({c.moment for c in work.clips}):
        mine = [c for c in work.musts() if c.moment == n and c.ir]
        people: dict[str, list[str]] = {}
        for c in mine:
            for s in (c.ir or {}).get("subjects") or []:
                if isinstance(s, dict) and s.get("id"):
                    people.setdefault(str(s["id"]), []).append(str(s.get("description") or ""))
        out[n] = {
            "setting": _common([str((c.ir or {}).get("setting") or "") for c in mine]),
            "lighting": _common([str((c.ir or {}).get("lighting") or "") for c in mine]),
            "people": {k: _common(v) for k, v in sorted(people.items())},
        }
    return out


def _first_line(clip: Any) -> str:
    cam = (clip.ir or {}).get("cinematography") or {}
    return " ".join(str(cam.get("framing") or "").split())[:160] if isinstance(cam, dict) else ""


def must_table(work: Bin) -> str:
    rows = ["id | slate | moment | role | technique | size | take | covers | first line of its design"]
    for c in work.musts():
        covers = (f"b{','.join(str(b) for b in c.blocks)}" if c.blocks else "-") + (
            f" lines {','.join(c.lines)}{' (speaks)' if c.speaks else ''}" if c.lines else ""
        )
        rows.append(
            f"{c.id} | {c.slate} | {c.moment} | {c.role} | {c.technique} | {c.size} | {c.take_s} s | {covers} | "
            f"{_first_line(c)}"
        )
    return "\n".join(rows)


def cut_block(work: Bin) -> str:
    plan = work.edit
    assert plan is not None
    t = plan.treatment
    seq = "\n".join(f"- {s.id}: {json.dumps(s.model_dump(), ensure_ascii=False)}" for s in plan.sequences)
    moments = "\n".join(
        f"- moment {m.n} (sequence {m.sequence}, blocks {m.blocks}): {m.what} Feeling: {m.feeling} The cut uses: "
        f"{m.cut_uses}"
        for m in plan.moments
    )
    return (
        f"<intended_cut>\nLogline: {t.logline}\nApproach: {t.approach}\nKey image: {t.key_image}\nGeography: "
        f"{t.geography}\n"
        f"Sequences:\n{seq}\nMoments:\n{moments}\n</intended_cut>"
    )


def looks_block(work: Bin) -> str:
    lines = []
    for n, look in looks(work).items():
        people = "; ".join(f"{k}: {v}" for k, v in look["people"].items())
        lines.append(
            f"moment {n}\n  setting: {look['setting']}\n  lighting: {look['lighting']}\n  people: {people or '-'}"
        )
    return (
        "<looks>\nThe words the must clips of each moment use. A cinematic clip of that moment copies them WORD FOR "
        "WORD "
        "(setting, lighting, each person's description): code checks it.\n" + "\n".join(lines) + "\n</looks>"
    )


def room_block(brief: Brief, work: Bin, cap: float) -> str:
    total = limit_s(brief, cap)
    held = work.counts()["take_s"]
    room = (
        f"The scene is {brief.guide_s:g} s long. The must bin holds {held} s of takes. CAP: {total:g} s of takes for "
        f"the "
        f"WHOLE bin (the given length x {cap:g}): {max(total - held, 0):g} s left for cinematic clips. "
        if total
        else f"The must bin holds {held} s of takes. "
    )
    return (
        f"<room>\n{room}Use it on the moments that earn it, the turning moments first; never on repeats of a must "
        f"angle. At most {PER_MOMENT_MAX} cinematic clips in any moment. `finish` asks for a review of EVERY "
        f"moment.\n</room>"
    )


def opening_stage2(
    production: dict[str, Any], context: dict[str, Any], brief: Brief, work: Bin, cap: float, extra: str = ""
) -> str:
    return "\n\n".join(
        p
        for p in (
            message(production, context, brief.scene, extra),
            voice_only(brief.scene),
            cut_block(work),
            "<must_bin>\nStage 1's finished bin: the must clips, LOCKED (you cannot change or remove them).\n"
            + must_table(work)
            + "\n</must_bin>",
            looks_block(work),
            room_block(brief, work, cap),
            "Review every moment: which earn cinematic clips and what kind (the turning moments first), then write "
            "them.",
        )
        if p
    )
