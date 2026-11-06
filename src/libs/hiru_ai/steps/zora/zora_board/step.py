"""zora_board: `{"doc", "ops", "tasks", "seat"?}` → `{"kept", "refused", "noops"}` (plan/2026-11-06e §4.6 step 1).

Deterministic, no model. `ops` are the author's answer, numbered as the plan in `doc` stands; `tasks` are the turn's
tasks with their scope as shot numbers of that plan. Kept ops go to the kernel; every refusal is a sentence for the
ledger. The rules are `logic.settle`; the gate (the planner's checks by id) is `gate`, used by the system.
"""
from __future__ import annotations

from typing import Any

from contracts.zora.doc import ZoraDoc
from contracts.zora.tasks import Task
from hiru_ai.steps.zora.zora_board.logic import settle


def run(payload: dict[str, Any]) -> dict[str, Any]:
    doc = ZoraDoc.model_validate(payload["doc"])
    handles = [f"h{i}" for i in range(1, len(doc.shots) + 1)]
    locked = []
    for path in doc.person.locked:  # S03.lens → #h3.lens, as the kernel holds them
        head, dot, rest = path.partition(".")
        n = int(head[1:]) if head[:1] == "S" and head[1:].isdigit() else 0
        locked.append(f"#h{n}{dot}{rest}" if 1 <= n <= len(handles) else path)
    tasks = [Task(writes=tuple(t.get("writes") or ()), may=tuple(t.get("may") or ()),
                  scope=tuple(f"h{n}" for n in t.get("scope") or [] if 1 <= int(n) <= len(handles)),
                  instruction=str(t.get("instruction") or "")) for t in payload.get("tasks") or []]
    out = settle(list(payload.get("ops") or []), tasks, doc.plan, handles=handles, locked=locked,
                 seat=str(payload.get("seat") or "the director"))
    return {"kept": out.kept, "refused": out.refused, "noops": out.noops}
