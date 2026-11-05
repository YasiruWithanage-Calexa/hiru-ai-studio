"""Mutants of a gold master (plan/2026-11-04c §4 F3): a plan broken on purpose, to see whether the score notices.

Mutation testing asks of a test suite what this asks of the craft score: delete every assertion and coverage is
unchanged, so coverage alone says little; inject a small fault and see whether the suite fails. A mutant the score
does NOT mark down is a blind spot, and the test that says so carries the mutant's name.

    mutants(name)       → {mutant name: plan payload} for the ones that apply to the gold scene `name`
    killed(name)        → {mutant name: (master percent, mutant percent)}

A mutant that cannot be built for a scene (it has no second person to remove, no spoken line to misplace) is left out
for that scene, never counted as killed. A merge that stays on one face and one beat is no fault by the plan's own rule
("one card, one main job: a change of the face we are on, or of the beat, starts a new card"), so it is an EQUIVALENT
mutant: `equivalent_merges` lists them, and the test prints how many there are. `BLIND_SPOTS` names what the score
still cannot see, by scene and mutant, with the reason; the test fails if one of them starts being caught, so the list
stays true.
"""
from __future__ import annotations

import copy
from typing import Any

from tests.adam import gold

from contracts.adam.plan import AdamPlan, norm
from hiru_ai.core import parts

Plan = dict[str, Any]

BLIND_SPOTS: dict[tuple[str, str], str] = {
    ("silent_morning", "bare"): "a one-person scene with no break, no irony and no plant has nothing the score "
                                "requires, so stripping its atmosphere and details scores like the master; only a "
                                "person sees it",
}


def _step(step_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return dict(parts.module("step", step_id, "step").run(payload))


def percent(scene: dict[str, Any], plan: Plan) -> float:
    return float(_step("adam_score", {"scene": scene, "plan": plan})["percent"])


def without_moments(plan: Plan, ids: set[str]) -> Plan:
    """The plan with these moments out of every card; a card left with none goes. Pointers at them stay, as a revision
    that deleted them would leave them."""
    out = copy.deepcopy(plan)
    out["moments"] = [m for m in out["moments"] if m["id"] not in ids]
    cards = []
    for card in out["cards"]:
        card["moments"] = [m for m in card["moments"] if m not in ids]
        if card["moments"]:
            cards.append(card)
    out["cards"] = [{**c, "number": i} for i, c in enumerate(cards, start=1)]
    return out


def _added(plan: Plan) -> list[dict[str, Any]]:
    return [m for m in plan["moments"] if m.get("tier") != "script"]


# ── the mutants ──────────────────────────────────────────────────────────────────────────────────


def other_side_removed(scene: dict[str, Any], plan: Plan) -> Plan | None:
    """Every added moment of the people who do not own the point of view: run 3's lost side."""
    pov = norm(plan["analysis"]["pov_owner"]["start"])
    gone = {m["id"] for m in _added(plan) if m.get("who") and all(norm(w) != pov for w in m["who"])}
    return without_moments(plan, gone) if gone else None


def bare(scene: dict[str, Any], plan: Plan) -> Plan | None:
    """Every added moment gone except the plant, the break and the ending: the bare plan that scored 100 % before."""
    t = plan["treatment"]
    keep = {(t.get("plant") or {}).get("plant_moment"), (t.get("rhythm_break") or {}).get("moment"),
            t.get("ending_moment")}
    gone = {m["id"] for m in _added(plan) if m["id"] not in keep}
    return without_moments(plan, gone) if gone else None


def break_moved(scene: dict[str, Any], plan: Plan) -> Plan | None:
    """The rhythm break falls on another card than the key moment's."""
    rb = plan["treatment"].get("rhythm_break")
    if not rb:
        return None
    out = copy.deepcopy(plan)
    key = out["analysis"]["key_moment"]["block"]
    by_id = {m["id"]: m for m in out["moments"]}
    for card in out["cards"]:
        on_key = any(f"b{key}" in by_id[m]["serves"] for m in card["moments"] if m in by_id)
        if not on_key and card["size"] != "INSERT":
            for other in out["cards"]:
                other["rhythm_break"] = False
            card["rhythm_break"] = True
            out["treatment"]["rhythm_break"]["moment"] = card["moments"][0]
            return out
    return None


def flat_arc(scene: dict[str, Any], plan: Plan) -> Plan | None:
    """Every card the same size."""
    if len(plan["cards"]) < 2:
        return None
    out = copy.deepcopy(plan)
    for card in out["cards"]:
        card["size"] = "MS"
    return out


def own_line_over_hands(scene: dict[str, Any], plan: Plan) -> Plan | None:
    """A speaker's own line plays over an insert of her hands: the "I'll come" card."""
    cast = {norm(c) for c in scene["cast"]}
    speaker = {b["line_id"]: norm(b["speaker"]) for b in scene["blocks"] if b.get("line_id")}
    out = copy.deepcopy(plan)
    for card in out["cards"]:
        for cl in card.get("lines", []):
            if cl.get("on_speaker", True) and speaker.get(cl["line_id"]) in cast:
                card["size"], cl["on_speaker"], cl["over_whom"] = "INSERT", False, ""
                return out
    return None


def irony_face_cut(scene: dict[str, Any], plan: Plan) -> Plan | None:
    """Every card that shows the person who does not know, from the block the audience knows, is on someone else."""
    knows = plan["analysis"].get("audience_knows") or []
    if not knows:
        return None
    who, start = norm(knows[0]["who_doesnt"]), knows[0]["from_block"]
    pov = plan["analysis"]["pov_owner"]["start"]
    by_id = {m["id"]: m for m in plan["moments"]}
    out, cut = copy.deepcopy(plan), False
    for card in out["cards"]:
        blocks = [b for m in card["moments"] if m in by_id for b in _blocks(by_id[m])]
        if blocks and max(blocks) >= start and norm(card.get("subject") or "") == who:
            card["subject"], cut = pov, True
        if blocks and max(blocks) >= start and card.get("arrangement") in ("two", "group"):
            card["arrangement"], card["subject"], cut = "single", pov, True
    return out if cut else None


def _blocks(moment: dict[str, Any]) -> list[int]:
    return [int(s[1:]) for s in moment.get("serves", []) if s[:1] == "b" and s[1:].isdigit()]


def _crosses(plan: Plan, a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Do two adjacent cards change the face we are on, or the beat?"""
    by_id = {m["id"]: m for m in plan["moments"]}
    beat_of = {blk: i for i, beat in enumerate(plan["analysis"]["beats"]) for blk in beat["blocks"]}
    held = [by_id[m] for m in [*a["moments"], *b["moments"]] if m in by_id]
    beats = {beat_of[blk] for m in held if m.get("kind") != "plant" for blk in _blocks(m) if blk in beat_of}
    on = norm(a.get("subject") or (by_id[a["moments"][0]].get("who") or [""])[0])
    away = any(m.get("who") and on and on not in {norm(w) for w in m["who"]} for m in held)
    return len(beats) > 1 or away


def merged_pairs(scene: dict[str, Any], plan: Plan, *, equivalent: bool = False) -> dict[str, Plan]:
    """Each pair of adjacent cards whose takes fit one 8 s take, merged into one (the first's camera): compression. Only
    a merge that changes the face or the beat is a fault; `equivalent=True` gives the others instead."""
    out: dict[str, Plan] = {}
    for i in range(len(plan["cards"]) - 1):
        a, b = copy.deepcopy(plan["cards"][i]), plan["cards"][i + 1]
        if _crosses(plan, a, b) == equivalent:
            continue
        a["moments"] += b["moments"]
        a["lines"] = [*a.get("lines", []), *b.get("lines", [])]
        a["rhythm_break"] = bool(a.get("rhythm_break") or b.get("rhythm_break"))
        a["take_s"] = 8
        mutant = copy.deepcopy(plan)
        mutant["cards"][i:i + 2] = [a]
        mutant["cards"] = [{**c, "number": n} for n, c in enumerate(mutant["cards"], start=1)]
        need = next((r["need_s"] for r in _step("adam_fit", {"scene": scene, "plan": mutant})["cards"]
                     if r["number"] == i + 1), 99)
        take = next((t for t in (4, 6, 8) if t >= need), None)
        if take is None:
            continue
        mutant["cards"][i]["take_s"] = take
        out[f"merge_cards_{i + 1}_{i + 2}"] = mutant
    return out


def mutants(name: str) -> dict[str, Plan]:
    scene, plan = gold.scene(name), gold.master(name)
    single = {"other_side_removed": other_side_removed, "bare": bare, "break_moved": break_moved,
              "flat_arc": flat_arc, "own_line_over_hands": own_line_over_hands, "irony_face_cut": irony_face_cut}
    found: dict[str, Plan] = {}
    for label, make in single.items():
        mutant = make(scene, plan)
        if mutant is not None:
            AdamPlan.model_validate(mutant)
            found[label] = mutant
    found.update(merged_pairs(scene, plan))
    return found


def equivalent_merges(name: str) -> list[str]:
    """The merges of the master's adjacent cards that stay on one face and one beat: not faults, so not mutants."""
    return sorted(merged_pairs(gold.scene(name), gold.master(name), equivalent=True))


def killed(name: str) -> dict[str, tuple[float, float]]:
    scene, plan = gold.scene(name), gold.master(name)
    base = percent(scene, plan)
    return {label: (base, percent(scene, mutant)) for label, mutant in mutants(name).items()}
