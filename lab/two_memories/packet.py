"""Step 7, the scene packet (plan/2026-11-11 §7): code assembles it from the breakdown memory and the continuity facts; every shot
planner reads the same one. Complete means every id resolves to its full card and every field is filled or says why it is empty.

The packet says what happens and what is true. It holds no shot sizes, lenses, moves, cuts or take lengths (§7, last block).

How a packet differs from the stored memory (the memory is never changed):
- ids stay in every structured field; inside a model's SENTENCES an id is written as the name (`Name [id]` when two cards share
  a name), and `ids` at the top of the packet maps every id in the scene to its name and kind;
- a card shows only the facts that lie in the cast or direction sections or in THIS scene's lines (a fact from another scene
  belongs to a thread), and its `summary` only when its range is tight;
- a direction rule says how it applies: `scoped`, `general`, or `conditional` (a planner decides whether the scene qualifies)."""
from __future__ import annotations

import re
from typing import Any

from .checks import _MINUTES, WPS
from .schema import Breakdown, Entity, Scene

EMPTY = "empty"
SUMMARY_MAX_LINES = 6
_ID = re.compile(r"\b[CLP]\d{2,}\b")


def _pretty(name: str) -> str:
    return " ".join(w[:1] + w[1:].lower() for w in name.split()) if name.isupper() else name


class Names:
    """id to display name; a name two cards share is shown with its id."""

    def __init__(self, bd: Breakdown) -> None:
        self.by_id = {e.id: _pretty(e.name) for e in bd.entities}
        counts: dict[str, int] = {}
        for n in self.by_id.values():
            counts[n.lower()] = counts.get(n.lower(), 0) + 1
        self.dup = {n for n, c in counts.items() if c > 1}

    def of(self, id_: str) -> str:
        name = self.by_id.get(id_)
        if name is None:
            return id_
        return f"{name} [{id_}]" if name.lower() in self.dup else name

    def text(self, s: Any) -> Any:
        return _ID.sub(lambda m: self.of(m.group(0)), s) if isinstance(s, str) else s

    def many(self, xs: list[str]) -> list[str]:
        return [self.text(x) for x in xs]


def _allowed(bd: Breakdown, sc: Scene, lines: tuple[int, int] | None) -> bool:
    """A card fact is shown when it is outside the story (the cast, the direction) or inside this scene."""
    if lines is None:
        return False
    lo = min(s.heading_line for s in bd.scenes)
    hi = max(s.last for s in bd.scenes)
    return lines[1] < lo or lines[0] > hi or (sc.heading_line <= lines[0] and lines[1] <= sc.last)


def _card(bd: Breakdown, sc: Scene, e: Entity | None, n: Names) -> dict[str, Any]:
    if e is None:
        return {}
    card: dict[str, Any] = {}
    withheld = 0
    for k, v in e.card.items():
        if k == "summary":
            if e.lines[1] - e.lines[0] + 1 <= SUMMARY_MAX_LINES:
                card[k] = {"value": v.value, "source": v.source}
            else:
                card[k] = {EMPTY: "withheld: the range it was read from is too wide"}
        elif _allowed(bd, sc, v.lines):
            card[k] = {"value": v.value, "source": v.source}
        else:
            withheld += 1
    out = {"id": e.id, "name": n.by_id[e.id], "kind": e.kind, "place_kind": e.place_kind, "card": card}
    if withheld:
        out["withheld_other_scenes"] = withheld
    return out


def _filled(value: Any, why: str) -> Any:
    return value if value not in ("", [], None, {}) else {EMPTY: why}


def _in_scope(bd: Breakdown, scene: Scene, rule: Any) -> bool:
    if rule.scope_kind == "all":
        return True
    if rule.scope_kind in ("scene", "episode"):
        return rule.scope_id == str(scene.number if rule.scope_kind == "scene" else scene.episode)
    if rule.scope_kind == "place":
        place = bd.entity(scene.brief.get("place", "")) if scene.brief else None
        return place is not None and rule.scope_id in (place.id, place.within)
    return False


def _conditional(rule: Any) -> bool:
    return rule.scope_kind == "all" and rule.about == "lens"


def _wanted(rule: Any, met: list[str] | None) -> bool:
    """When the episode call stated which conditional rules the scene meets, the others are left out."""
    return not _conditional(rule) or met is None or rule.id in met


def _applies(rule: Any, met: list[str] | None = None) -> str:
    """Code cannot tell whether a scene is a love scene: the episode call says (`rules_met`); without it the rule is labelled."""
    if rule.scope_kind != "all":
        return "scoped"
    if not _conditional(rule):
        return "general"
    return "the scene meets this rule's condition" if met is not None else         "conditional: apply only if the scene is of the kind the rule names"


def _continuity(bd: Breakdown, sc: Scene, cont: dict[str, Any], n: Names) -> dict[str, Any]:
    order = {t["scene"]: t["story_order"] for t in cont["timeline"]}
    mine = order.get(sc.id)
    if mine is None:
        return {"time": {EMPTY: "continuity has no timeline entry for this scene"}}
    t = next(x for x in cont["timeline"] if x["scene"] == sc.id)
    by_order = sorted((s for s in bd.scenes if s.id in order), key=lambda s: order[s.id])
    k = by_order.index(sc)

    def end_of(s: Scene) -> dict[str, Any]:
        last = next((b for b in reversed(s.blocks) if b["text"]), None)
        first = next((b for b in s.blocks if b["text"]), None)
        return {"id": s.id, "heading": s.heading, "ends_with": last["text"] if last else None,
                "opens_with": first["text"] if first else None,
                "people_at_end": [n.by_id.get(p["person"], p["person"]) for p in (s.brief or {}).get("people", [])
                                  if p["presence"] == "on_screen"]}

    def at(sid: str) -> int:
        return order.get(sid, 10**6)

    threads = []
    for th in cont["threads"]:
        beats = th["beats"]
        if any(b["scene"] == sc.id for b in beats):
            threads.append({"kind": th["kind"], "subject": n.text(th["subject"]), "summary": n.text(th["summary"]),
                            "source": th["source"],
                            "earlier": [{"scene": b["scene"], "note": n.text(b["note"])} for b in beats if at(b["scene"]) < mine],
                            "this_scene": [n.text(b["note"]) for b in beats if b["scene"] == sc.id],
                            "later": [{"scene": b["scene"], "note": n.text(b["note"])} for b in beats if at(b["scene"]) > mine]})
    people = {p["person"] for p in (sc.brief or {}).get("people", [])}
    looks = [{"person": n.by_id.get(x["person"], x["person"]), "kind": x["kind"], "note": n.text(x["note"]),
              "source": x["source"]} for x in cont["looks"]
             if x["person"] in people and at(x["from_scene"]) <= mine <= (at(x["to_scene"]) if x["to_scene"] else 10**6)]
    knowledge = [{"person": n.by_id.get(x["person"], "the audience" if x["audience_only"] else "a group"),
                  "learns": n.text(x["learns"]), "audience_only": x["audience_only"], "source": x["source"]}
                 for x in cont["knowledge"] if x["scene"] == sc.id]
    relations = [{"between": [n.by_id.get(x["a"], x["a"]), n.by_id.get(x["b"], x["b"])], "state": n.text(x["state"]),
                  "scene": x["scene"]} for x in cont["relationships"]
                 if x["a"] in people and x["b"] in people and at(x["scene"]) <= mine]  # a later change is not yet true
    return {"time": {"story_order": mine, "story_day": t["story_day"] or {EMPTY: "not stated"},
                     "relative": t["relative"] or {EMPTY: "none"}, "kind": t["kind"], "anchor": t["anchor"] or None,
                     "source": t["source"]},
            "before_in_story": end_of(by_order[k - 1]) if k else {EMPTY: "first in story order"},
            "after_in_story": end_of(by_order[k + 1]) if k + 1 < len(by_order) else {EMPTY: "last in story order"},
            "threads": threads or {EMPTY: "no thread touches this scene"},
            "irony": [x for x in knowledge if x["audience_only"]] or {EMPTY: "none stated"},
            "knowledge": [x for x in knowledge if not x["audience_only"]] or {EMPTY: "none stated"},
            "looks": looks or {EMPTY: "no lasting condition changes here"},
            "relationships": relations or {EMPTY: "none stated"}}


def assemble(bd: Breakdown, scene_id: str, cont: dict[str, Any] | None = None) -> dict[str, Any]:
    sc = bd.scene(scene_id)
    if sc is None or sc.brief is None:
        raise KeyError(f"{scene_id} has no brief")
    n = Names(bd)
    order = bd.scenes
    i = order.index(sc)
    brief = sc.brief
    place = bd.entity(brief.get("place", ""))
    m = _MINUTES.search(sc.heading)
    spoken = sum(len(b["text"].split()) for b in sc.blocks if b["kind"] == "dialogue") / WPS
    people = []
    for p in brief["people"]:  # D3: full cards for the scene's people; nobody else is shown
        people.append({**_card(bd, sc, bd.entity(p["person"]), n), "presence": p["presence"],
                       "wants": _filled(n.text(p["wants"]), "script does not say"),
                       "feeling_start": _filled(n.text(p["feeling_start"]), "script does not say"),
                       "feeling_end": _filled(n.text(p["feeling_end"]), "script does not say"), "source": p["source"]})
    used = {p["person"] for p in brief["people"]} | {t["thing"] for t in brief["things"]} | {brief.get("place", "")}
    for b in sc.blocks:
        used |= {b["speaker"], b["addressee"], *b["heard_by"]}
        for e in b["events"]:
            used |= {*e["actors"], *e["things"], e["spot"]}
    ids = {x: {"name": n.by_id[x], "kind": bd.entity(x).kind} for x in sorted(used) if x in n.by_id}  # type: ignore[union-attr]
    packet: dict[str, Any] = {
        "ids": ids,
        "A_scene": {"id": sc.id, "heading": sc.heading, "title": brief["title"], "summary": n.text(brief["summary"]),
                    "purpose": n.text(brief["purpose"]), "purpose_source": brief.get("source", "inferred"),
                    "before_on_page": {"id": order[i - 1].id, "heading": order[i - 1].heading} if i else {EMPTY: "first scene"},
                    "after_on_page": {"id": order[i + 1].id, "heading": order[i + 1].heading} if i + 1 < len(order)
                    else {EMPTY: "last scene"}},
        "B_people": people,
        "C_place": _card(bd, sc, place, n) or {EMPTY: "no set recorded"},
        "D_things": [{**_card(bd, sc, bd.entity(t["thing"]), n), "role": t["role"],
                      "holder_start": n.text(t["holder_start"]), "holder_end": n.text(t["holder_end"]), "source": t["source"]}
                     for t in brief["things"]] or {EMPTY: "no things in the scene"},
        "E_blocks": [{**{k: b[k] for k in ("id", "kind", "text", "speaker", "presence", "device", "addressee", "heard_by")},
                      "intent": n.text(b["intent"]), "delivery_hint": n.text(b["delivery_hint"]),
                      "intent_source": b.get("source", "script"),
                      "events": [{**e, "change": n.text(e["change"])} for e in b["events"]]} for b in sc.blocks],
        "F_feeling": {"mood": _filled(n.many(brief["mood"]), "not read"),
                      "turns": [sc.blocks[x - 1]["id"] for x in brief["turns"] if 0 < x <= len(sc.blocks)]},
        "G_direction": [{"id": r.id, "about": r.about, "applies": _applies(r, brief.get("rules_met")), "text": r.text}
                        for r in bd.rules if _in_scope(bd, sc, r) and _wanted(r, brief.get("rules_met"))],
        "H_length": {"stated_seconds": float(m.group(1)) * 60 if m else {EMPTY: "heading states none"},
                     "spoken_seconds": round(spoken, 1)},
        "I_open": [f.message for f in bd.findings if f.scene == sc.id] or {EMPTY: "no open question"},
    }
    if getattr(sc, "stage", None):
        from .stage import packet_part

        packet["stage"] = packet_part(bd, sc)
    if cont is not None:
        c = _continuity(bd, sc, cont, n)
        packet["A_scene"].update(c)
        for s in cont["scopes"]:  # a named moment ("the key falling") joins its rule, in its own scene
            if s["moment_scene"] == sc.id and s["moment_note"]:
                for r in packet["G_direction"]:
                    if r["id"] == s["rule"]:
                        r["moment_here"] = n.text(s["moment_note"])
    return packet


def incomplete(bd: Breakdown, packet: dict[str, Any]) -> list[str]:
    """§7: if this lists anything, planning that scene waits."""
    out: list[str] = [f"blocking finding: {f.message}" for f in bd.findings
                      if f.blocking and f.scene in ("", packet["A_scene"]["id"])]
    for k in ("A_scene", "C_place", "E_blocks"):
        if not packet[k]:
            out.append(f"{k} is empty")
    if EMPTY in packet["C_place"]:
        out.append("C_place: " + packet["C_place"][EMPTY])
    for p in packet["B_people"]:
        if not p.get("id"):
            out.append("B_people: a person does not resolve to a card")
    for t in packet["D_things"] if isinstance(packet["D_things"], list) else []:
        if not t.get("id"):
            out.append("D_things: a thing does not resolve to a card")
    for b in packet["E_blocks"]:
        if not b["text"]:
            out.append(f"{b['id']}: no words")
    return out
