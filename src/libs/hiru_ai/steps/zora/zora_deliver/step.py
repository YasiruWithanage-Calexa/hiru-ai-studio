"""zora_deliver: `{"before", "after", "tasks", "locked"?}` → `{"missing", "retask", "report"}` (plan/2026-11-06e §4.6
step 5).

Deterministic, no model. `before` and `after` are the plan exported WITH handles (`_h` on every shot), `tasks` the
turn's tasks with their scope as handles, `locked` the kernel's locked paths. The rules are `logic`.
"""
from __future__ import annotations

from typing import Any

from contracts.zora.tasks import Task
from hiru_ai.steps.zora.zora_deliver.logic import report, retask, undelivered


def run(payload: dict[str, Any]) -> dict[str, Any]:
    tasks = [Task(writes=tuple(t.get("writes") or ()), may=tuple(t.get("may") or ()), scope=tuple(t.get("scope") or ()),
                  instruction=str(t.get("instruction") or ""), origin=str(t.get("origin") or "deps"))
             for t in payload.get("tasks") or []]
    after = payload["after"]
    handles = [str(s["_h"]) for s in after.get("shots") or []]
    locked = list(payload.get("locked") or [])
    missing = undelivered(tasks, payload["before"], after)
    return {"missing": missing, "retask": [t.data() for t in retask(missing, tasks, locked=locked, handles=handles)],
            "report": report(missing, tasks, locked=locked, handles=handles)}
