"""A director's choice: apply the chosen edit (a side of a disagreement, or an option) to the scene.

The API has already checked who is choosing (Permission.DIRECT, and Permission.EDIT_SCRIPT for a
change to the script's words) and taken the operations from the stored message, not from the
browser. Here the scene is read fresh, each operation finds its shot or block by id (numbers
may have moved since the board spoke; a block someone changed meanwhile is refused), the kernel
applies them as the person's own choice, and the plan is saved and audited like a turn's edit. A
choice that changes nothing says why, and saves nothing. A script change is checked against the
shots around it, and the summary says what was looked at.

The summary is the card's recorded OUTCOME, and later turns answer "did you apply it?" from it, so it states the
effect (what actually changed, and that the words did not when they did not) and, when the option promised a
goal, whether the saved scene reaches it. It never repeats the label's promise.
"""
from __future__ import annotations

import copy

from contracts import director_capabilities as caps
from contracts.director import SCRIPT_OPS, ChoicePayload, ChoiceResult
from contracts.production import ProductionSettings
from director_chat.engine import ripple
from director_chat.engine.turn import (
    SCRIPT_CONFLICT,
    ScriptConflict,
    StoreLike,
    describe_op,
    kernel_for,
    persist,
    unpin,
)

GONE = "That part of the scene has changed since the board spoke. Ask the directors again."
NO_SCRIPT = "Your role can change shots but not the script's words; a writer or producer can."


NOTE_FIELDS = ("camera", "director_line", "action")


def effect(applied: list[dict]) -> str:
    """What the applied operations did, in words that cannot be read as more: how many lines' words
    changed, or that only a shot's notes did and the dialogue words are untouched. "" when neither applies
    (a framing or a length says itself in the list of changes)."""
    words = {o.get("line_id") or o.get("block") for o in applied if o.get("op") in SCRIPT_OPS
             and (o.get("kind") == "dialogue" or o.get("field") == "text")}
    notes = {o.get("shot_id") or o.get("shot") for o in applied
             if o.get("op") == "beat.set" and o.get("field") in NOTE_FIELDS}
    if words:
        return f"Changed dialogue on {len(words)} line{'s' if len(words) != 1 else ''}."
    if notes:
        return f"Changed director notes on {len(notes)} shot{'s' if len(notes) != 1 else ''}. Dialogue words unchanged."
    return ""


def apply_choice(req: ChoicePayload, store: StoreLike) -> ChoiceResult:
    production = store.production(req.production_id)
    scene = store.scene(req.production_id, req.scene_id)
    if production is None or scene is None:
        return ChoiceResult(summary="This scene is no longer available.")
    if scene["status"] == "approved":
        return ChoiceResult(summary="This scene is approved and locked. Unlock it before changing it.")
    if any(op.get("op") in SCRIPT_OPS for op in req.ops) and not req.can_edit_script:
        return ChoiceResult(summary=NO_SCRIPT)
    settings = ProductionSettings.model_validate(production.get("settings") or {})
    lines = store.lines(req.scene_id)
    shot_rows = store.shots(req.scene_id)
    kernel = kernel_for(scene, lines, shot_rows, settings.fixed_shot_seconds, store.canon(req.production_id))

    handles = kernel.handles()
    ops = [unpin(op, handles, kernel.items) for op in req.ops]
    if any(op is None for op in ops):
        return ChoiceResult(summary=GONE)
    original = copy.deepcopy(kernel)
    # A person's choice is their own words: it may pass the length locks they set.
    result = kernel.apply([op for op in ops if op is not None], by="you", respect_locks=False)
    if not result.applied:
        reasons = "; ".join(r["reason"] for r in result.rejected) or "nothing to change"
        return ChoiceResult(summary=f"Not applied: {reasons}.")
    try:
        persist(store, kernel, scene, shot_rows, lines, production_id=req.production_id,
                actor_user_id=req.actor_user_id, action="scene.director_choice", applied=result.applied)
    except ScriptConflict:
        return ChoiceResult(summary=SCRIPT_CONFLICT)
    review = ripple.review(original, kernel, result.applied, result.changes)
    summary = "Applied: " + "; ".join(describe_op(o) for o in result.applied) + "."
    if review.scripted:
        summary += " " + ripple.checked(review) + "".join(f" {n.text}" for n in review.notes if n.check)
    if said := effect(result.applied):
        summary += " " + said
    if (goal := caps.intent_by_id(req.intent)) is not None:
        # A translation card ("translate S02 to Tamil") is judged on the lines it translated, as `turn._stage` judged
        # it before showing it; any other card on the whole scene.
        translated = [kernel.items[int(o["block"])] for o in result.applied if o.get("translated_to")]
        says = goal.says.replace("every spoken line", "every translated line") if translated else goal.says
        reached, state = caps.met(goal.id, items=translated or kernel.items, ops=result.applied)
        summary += f" Goal reached: {says}." if reached else f" Goal NOT reached ({says}): {state}"
    return ChoiceResult(applied=result.applied, summary=summary)
