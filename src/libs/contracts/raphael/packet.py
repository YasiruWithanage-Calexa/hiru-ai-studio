"""Raphael reads the scene packet (plan/2026-11-11 §7): the whole packet goes to the model, nothing is dropped.

    opening(packet)             -> (first message, SceneS, ids)   what raphael_planner is given on the packet path
    scene_from_packet(packet)   -> (SceneS, ids)                  what Raphael's CODE reads (tools, checks, length)
    render(packet, ids)         -> text                           every section of the packet, as the model reads it
    timing(scene, ids)          -> text                           the clock per block, worked out by code

Two readers, two forms. The model gets the packet whole (`<packet>`), so nothing it says is lost; Raphael's tools and
checks keep reading `SceneS` (block numbers b0..bN, line ids L<n>), now built from the packet, not from `present()`,
`objects_of()`, `mark_recorded` and the stager. `ids` maps each short id (b4, L4) to the packet's block id (E01-S08-B05)
so every clip can be traced back.

What replaces what (plan/2026-11-11 §7, "code that becomes unnecessary"):
- `cast`: the people the packet lists `on_screen` or `body` (not a name found in the text)
- heard, not seen: the packet's presence written into the line's delivery, so `is_heard` / `is_voice_over` read it
- `place.objects`: the packet's things; `opening_state` and each block's `now`: the packet's stage
- an action's time: its events in the packet (one event = one beat), not one beat for any block
No model here. Pure functions of the packet dict (`lab/two_memories/packet.py` assembles it).
"""

from __future__ import annotations

import re
from typing import Any

from contracts.breakdown.series import render_lines as render_series
from contracts.raphael.scene import BlockS, Brief, PlaceS, SceneS, action_s, line_facts

EMPTY = "empty"
_THING_ID = re.compile(r"\s*\bP\d{2,}\b")  # a block's device is "phone P08": the thing's name, then its id
# the packet's presence -> the delivery mark Raphael's code reads (contracts.shotplan.HEARD_MARKS, scene.VOICE_OVER)
DELIVERY = {
    "phone": "on the phone",
    "voice_message": "voice message",
    "recording": "recording",
    "voice_over": "voice over",
    "thought": "voice over",
}
SEEN = ("on_screen", "body")


def _v(x: Any) -> str:
    return "" if isinstance(x, dict) and EMPTY in x else str(x)


def _name(packet: dict[str, Any], pid: str) -> str:
    return str(packet.get("ids", {}).get(pid, {}).get("name") or pid)


def _state(fields: dict[str, Any]) -> str:
    return ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in fields.items() if v and k != "person")


def scene_from_packet(packet: dict[str, Any]) -> tuple[SceneS, dict[str, str]]:
    people = packet["B_people"]
    presence = {p["id"]: p["presence"] for p in people}
    speakers = {b["speaker"] for b in packet["E_blocks"] if b["kind"] == "dialogue" and b["speaker"]}
    # Seen people, and heard ones who speak: Raphael's voice-only rule (`heard_names`) looks for a speaker in `cast`
    # whose every line is heard. A heard person who never speaks is left out, so no clip can show them.
    cast = [p["name"] for p in people if p["presence"] in SEEN or p["id"] in speakers]
    stage = packet.get("stage") or {}
    changes = stage.get("changes_at", {})
    turns = set(packet["F_feeling"].get("turns", []))
    ids: dict[str, str] = {}
    blocks: list[BlockS] = []
    for i, b in enumerate(packet["E_blocks"]):
        ids[f"b{i}"] = b["id"]
        line = b["kind"] == "dialogue" and bool(b["speaker"])
        if line:
            ids[f"L{i}"] = b["id"]
        heard = DELIVERY.get(b["presence"] or presence.get(b["speaker"], ""), "")
        now = "; ".join(f"{m['person']}: {_state(m)}" for m in changes.get(b["id"], []))
        blocks.append(
            BlockS(
                index=i,
                kind="dialogue" if line else "action",
                text=b["text"],
                speaker=_name(packet, b["speaker"]) if line else "",
                line_id=f"L{i}" if line else None,
                delivery=heard,
                events=max(1, len(b.get("events") or [])),
                turn=b["id"] in turns,
                now=now,
                device=_THING_ID.sub("", b.get("device") or "").strip() if line else "",
            )
        )
    opening = "; ".join(
        f"{_name(packet, pid)}: {_state(s['in'])}" for pid, s in stage.get("people", {}).items() if s.get("in")
    )
    stated = packet["H_length"].get("stated_seconds")
    things = packet["D_things"] if isinstance(packet["D_things"], list) else []
    place = packet["C_place"]
    scene = SceneS(
        blocks=blocks,
        cast=cast,
        others=[],  # the packet shows only the scene's people (D3): nobody else is named to Raphael
        place=PlaceS(name=str(place.get("name", "")), objects=[t["name"] for t in things]),
        envelope_s=float(stated) if isinstance(stated, (int, float)) and stated > 0 else None,
        codes={p["id"]: p["name"] for p in people},  # a subject's id is the person's packet id (C01)
        opening_state=opening,
    )
    return scene, ids


def render(packet: dict[str, Any], ids: dict[str, str]) -> str:
    """Every section of the packet as text. Blocks carry both ids (`b4 = E01-S08-B05`)."""
    short = {v: k for k, v in ids.items() if k.startswith("b")}
    a = packet["A_scene"]
    series = render_series(packet.get("J_series"))  # plan/2026-11-12b: what the drama is, read before the scene
    out = [
        *([*series, ""] if series else []),
        f"SCENE {a['id']}: {a['heading']}",
        f"Title: {a['title']}",
        f"Summary: {a['summary']}",
        f"Purpose ({a.get('purpose_source', 'inferred')}): {a['purpose']}",
    ]
    t = a.get("time")
    if isinstance(t, dict) and "story_order" in t:
        out.append(
            f"Story time: order {t['story_order']}, {t['kind']}"
            + (f", {t['relative']}" if _v(t["relative"]) else "")
            + (f" (measured from {t['anchor']})" if t.get("anchor") else "")
        )
    for key, label, field, verb in (
        ("before_in_story", "The scene before it in the story", "ends_with", "ends with"),
        ("after_in_story", "The scene after it in the story", "opens_with", "opens with"),
    ):
        n = a.get(key)
        if isinstance(n, dict) and "id" in n:
            out.append(f"{label}: {n['id']} {n['heading']}" + (f". It {verb}: {n[field]}" if n.get(field) else ""))
    for key, label in (("before_on_page", "On the page, before it"), ("after_on_page", "On the page, after it")):
        n = a.get(key)
        if isinstance(n, dict) and "id" in n:
            out.append(f"{label}: {n['id']} {n['heading']}")
    for key in ("threads", "irony", "knowledge", "looks", "relationships"):
        items = a.get(key)
        if not isinstance(items, list):
            continue
        for x in items:
            if key == "threads":
                earlier = "; ".join(f"{b['scene']}: {b['note']}" for b in x["earlier"])
                later = "; ".join(f"{b['scene']}: {b['note']}" for b in x["later"])
                out.append(
                    f"Thread ({x['kind']}, {x['subject']}): {x['summary']}"
                    + (f" Here: {' '.join(x['this_scene'])}" if x["this_scene"] else "")
                    + (f" Earlier: {earlier}." if earlier else "")
                    + (f" Later: {later}." if later else "")
                )
            elif key == "relationships":
                out.append(f"Relationship ({' and '.join(x['between'])}, as of {x['scene']}): {x['state']}")
            else:
                out.append(
                    f"{key.title()}: "
                    + "; ".join(f"{k} {v}" for k, v in x.items() if v not in ("", None) and k != "source")
                )
    out += ["", "PEOPLE (only these are in the scene; ids are what `subjects[].id` uses)"]
    for p in packet["B_people"]:
        card = "; ".join(f"{k}: {v['value']}" for k, v in p["card"].items() if isinstance(v, dict) and "value" in v)
        out.append(
            f"- {p['id']} {p['name']} [{p['presence']}]"
            + (f" {card}" if card else "")
            + f" | wants: {_v(p['wants']) or '-'}"
            + f" | feels: {_v(p['feeling_start']) or '-'} -> {_v(p['feeling_end']) or '-'}"
            + f" ({p.get('source', 'script')})"
        )
    c = packet["C_place"]
    stage = packet.get("stage") or {}
    out += [
        "",
        f"PLACE: {c.get('name', '')} ({c.get('place_kind') or ''})"
        + (f"; zones: {', '.join(stage['zones'])}" if stage.get("zones") else "")
        + "".join(f"; {k}: {v['value']}" for k, v in c.get("card", {}).items() if isinstance(v, dict) and "value" in v),
    ]
    things = packet["D_things"] if isinstance(packet["D_things"], list) else []
    if things:
        out.append("THINGS")
        for t in things:
            card = "; ".join(
                f"{k}: {v['value']}" for k, v in t.get("card", {}).items() if isinstance(v, dict) and "value" in v
            )
            out.append(
                f"- {t['id']} {t['name']} [{t['role']}] held at the start by: {t['holder_start'] or '-'}; at the end: "
                f"{t['holder_end'] or '-'} ({t['source']})" + (f". Card: {card}" if card else "")
            )
    for pid, s in stage.get("people", {}).items():
        out.append(
            f"STATE {_name(packet, pid)}: in: {_state(s.get('in', {})) or '-'}; out: {_state(s.get('out', {})) or '-'}"
        )
    for who, why in stage.get("not_placed", {}).items():
        out.append(f"NOT PLACED {who}: {why} (the script does not say)")
    for prop in stage.get("props", []):
        out.append(
            f"PROP from b{prop['block']}: {prop['prop']}, {prop['where']}"
            + (f", {prop['state']}" if prop.get("state") else "")
        )
    out += ["", "BLOCKS (the exact words; b = the id the tools use)"]
    changes = stage.get("changes_at", {})
    for b in packet["E_blocks"]:
        who = ""
        if b["speaker"]:
            heard = ", ".join(_name(packet, h) for h in b.get("heard_by", []))
            who = (
                f" {_name(packet, b['speaker'])} [{b['presence']}{', ' + b['device'] if b['device'] else ''}]"
                + (f" to {_name(packet, b['addressee'])}" if b.get("addressee") else "")
                + (f", heard by {heard}" if heard else "")
            )
        out.append(f"{short.get(b['id'], '?')} = {b['id']} {b['kind']}{who}: {b['text']}")
        if b.get("intent"):
            out.append(f"    intent ({b.get('intent_source', 'script')}): {b['intent']}")
        if b.get("delivery_hint"):
            out.append(f"    delivery hint: {b['delivery_hint']}")
        for e in b.get("events", []):
            who = ", ".join(_name(packet, x) for x in e.get("actors", []))
            what = ", ".join(_name(packet, x) for x in e.get("things", []))
            where = _name(packet, e["spot"]) if e.get("spot") else ""
            out.append(
                f"    event {e['id']} ({e['function']}{'' if e['visible'] else ', not visible'}"
                + (f"; who: {who}" if who else "")
                + (f"; things: {what}" if what else "")
                + (f"; at: {where} [{e['spot']}]" if where else "")
                + f"): {e['change'] or '-'}"
            )
        for m in changes.get(b["id"], []):
            out.append(f"    state from here: {m['person']}: {_state(m)}")
    f = packet["F_feeling"]
    mood = f["mood"] if isinstance(f["mood"], list) else []
    out += [
        "",
        f"FEELING: {', '.join(mood)}; the scene turns at {', '.join(short.get(x, x) for x in f.get('turns', []))}",
        "DIRECTION IN SCOPE",
    ]
    for r in packet["G_direction"]:
        out.append(
            f"- {r['id']} [{r['applies']}] {' '.join(r['text'].split())}"
            + (f" (here: {r['moment_here']})" if r.get("moment_here") else "")
        )
    h = packet["H_length"]
    out += ["", f"LENGTH: stated {_v(h['stated_seconds']) or '-'} s; spoken {h['spoken_seconds']} s"]
    opn = packet["I_open"]
    if isinstance(opn, list) and opn:
        out += ["OPEN"] + [f"- {o}" for o in opn]
    return "\n".join(out)


def timing(scene: SceneS, ids: dict[str, str]) -> str:
    """The clock, worked out by code (the model never does it): each line's words, seconds and shortest take; each
    action's seconds on screen."""
    facts = {b.index: (w, s, t) for b, w, s, t in line_facts(scene)}
    acts = action_s(scene)
    rows = []
    for b in sorted(scene.blocks, key=lambda x: x.index):
        if b.index in facts:
            w, s, t = facts[b.index]
            heard = ", heard not seen" if b.delivery in DELIVERY.values() and b.speaker not in scene.cast else ""
            rows.append(
                f"b{b.index} line [{b.line_id}] {b.speaker}{heard}: {w} words, {s:.1f} s, "
                + (f"shortest take {t} s" if t else "longer than any take: reported, never trimmed")
            )
        elif b.index in acts:
            rows.append(f"b{b.index} action: {acts[b.index]:.1f} s on screen")
    return "\n".join(rows)


def opening(packet: dict[str, Any], length_block: str = "") -> tuple[str, SceneS, dict[str, str]]:
    """The first message on the packet path: <packet> first (the same for every turn: it caches), then the clock, the
    voice-only rule and the length, then the instruction. `length_block` is `pack.length_block(Brief(...))`."""
    from contracts.raphael.pack import length_block as _length
    from contracts.raphael.pack import voice_only

    scene, ids = scene_from_packet(packet)
    length = length_block or _length(Brief(scene, float(scene.envelope_s or 0)))
    parts = [
        f"<packet>\n{render(packet, ids)}\n</packet>",
        f"<timing>\n{timing(scene, ids)}\n</timing>",
        voice_only(scene),
        length,
        "Plan this scene. Start with the intended cut.",
    ]
    return "\n\n".join(p for p in parts if p), scene, ids
