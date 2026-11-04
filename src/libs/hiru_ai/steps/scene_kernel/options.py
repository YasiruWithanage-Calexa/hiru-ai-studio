"""Options: when the person asks for choices (the conductor's `options` lane), the lead director
proposes 2-4 distinct ways to go, each with the OPERATIONS that would make it.

Nothing is applied here. Every option is tried on a COPY of the scene first: operations the
kernel refuses are dropped, an option left with no edit and no message to send is dropped, and
what survives is described (the change, and what it does to the scene's timing). The operations
are stored pinned to shot ids (`turn.pin`), so a choice made later still finds its shots; the
person applies one with `engine/choice.py`, as with a disagreement.

An option that is not a shot-list change (a question of tone, wardrobe, a line reading) carries
`prompt` instead: choosing it sends that message to the board as the next turn.
"""
from __future__ import annotations

import copy
import logging
from collections.abc import Callable
from typing import Any

from contracts import director_capabilities as caps
from hiru_ai.steps.scene_kernel.conductor import clean_op
from hiru_ai.steps.scene_kernel.logic import PERSON_ONLY, ScenePlanKernel
from hiru_ai.steps.scene_kernel.turn_logic import describe_op, pin

_logger = logging.getLogger(__name__)
Ask = Callable[[dict[str, Any]], dict[str, Any]]  # the options_writer agent's input -> its answer
MAX_OPTIONS = 4
MAX_OPS_PER_OPTION = 6

def propose(ask: Ask, *, kernel: ScenePlanKernel, message: str, history: str, lead_charter: str,
            memory: list[str], at_least: int = 2) -> dict[str, Any] | None:
    """→ an options block (`contracts.director.OptionsBlock`), or None when there is nothing
    worth offering (the model failed, or fewer than `at_least` options survived their dry run).
    A follow-up to the director's own advice asks for one."""
    try:
        answer = ask({"lead_charter": lead_charter, "memory": memory, "history": history,
                      "shot_list": kernel.describe(), "message": message})
    except Exception:
        _logger.warning("options failed", exc_info=True)
        return None
    handles = kernel.handles()
    before = kernel.fit()
    options: list[dict[str, Any]] = []
    for raw in list(answer.get("options") or [])[:MAX_OPTIONS]:
        label = str(raw.get("label") or "").strip()[:80]
        prompt = str(raw.get("prompt") or "").strip()[:500]
        if not label:
            continue
        # An option is a shot-list idea: the script, a shot's cast, checks and note are a person's to change.
        asked = [clean_op(o) for o in raw.get("ops") or []]
        ops = [o for o in asked if o.get("op") not in PERSON_ONLY][:MAX_OPS_PER_OPTION]
        # What the label promises: the goal the model named, else the one its wording claims.
        named = str(raw.get("intent") or "")
        intent = named if caps.intent_by_id(named) else caps.claimed_intent(label)
        option: dict[str, Any] = {"label": label, "detail": str(raw.get("detail") or "").strip()[:300],
                                  "change": "", "impact": "", "ops": [], "prompt": "", "intent": ""}
        cut = len(ops) < len(asked)  # operations the option's idea needs were not allowed
        if ops:
            trial = copy.deepcopy(kernel)
            seen = len(trial.notes)
            result = trial.apply(ops, by="you", respect_locks=False)
            refused = {id(r["op"]) for r in result.rejected}
            cut = cut or bool(refused)
            pinned = [pin(o, handles) for o in ops if id(o) not in refused]
            if result.applied and all(pinned):
                option["ops"] = pinned
                option["change"] = "; ".join(describe_op(o) for o in result.applied)
                option["impact"] = impact(before, trial, trial.notes[seen:])
                if intent:
                    reached, state = caps.met(intent, items=trial.items, ops=result.applied)
                    if not reached:  # the label promises what the edit does not do
                        _logger.info("option %r dropped: %s", label, state)
                        continue
                    option["intent"] = intent
                elif cut:  # some of the idea was taken away: say what is left, not what was asked
                    option["label"] = option["change"][:80]
                    option["detail"] = ""
        if not option["ops"]:
            if not prompt or intent:  # a goal that only an edit can reach cannot be promised by a message
                continue  # neither an edit that works nor a message to send
            option["prompt"] = prompt
        options.append(option)
    if len(options) < at_least:
        return None
    return {"kind": "options", "question": str(answer.get("question") or "").strip()[:200], "options": options}


def impact(before: Any, trial: ScenePlanKernel, notes: list[str] | None = None) -> str:
    """What an option does to the scene as a whole, in a few words. `notes` are the shots the edit
    would have crowded ("S05 would need 10.9 s ..."): a merge that cannot fit one shot says so."""
    after = trial.fit()
    parts = list(notes or [])[:1]
    if after.total_s != before.total_s:
        parts.append(f"Scene {before.total_s} s → {after.total_s} s")
    if len(after.shots) != len(before.shots):
        parts.append(f"{len(before.shots)} → {len(after.shots)} shots")
    old = {i.message for i in before.issues}
    fresh = [i.message for i in after.issues if i.message not in old]
    if fresh:
        parts.append(fresh[0])
    return " · ".join(parts)
