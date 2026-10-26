"""A director's choice: apply the chosen edit (a side of a disagreement, or an option) to the scene.

The API has already checked who is choosing (Permission.DIRECT, and Permission.EDIT_SCRIPT for a
change to the script's words) and taken the operations from the stored message, not from the
browser. Here the scene is read fresh, each operation finds its shot or block by id (numbers
may have moved since the board spoke; a block someone changed meanwhile is refused), the kernel
applies them as the person's own choice, and the plan is saved and audited like a turn's edit. A
choice that changes nothing says why, and saves nothing. A script change is checked against the
shots around it, and the summary says what was looked at.
"""
from __future__ import annotations

import copy

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
    return ChoiceResult(applied=result.applied, summary=summary)
