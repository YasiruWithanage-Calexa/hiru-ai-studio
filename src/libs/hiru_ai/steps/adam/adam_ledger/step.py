"""adam_ledger: every moment the writer made ends in exactly one bucket (plan/2026-11-04c §4 F1).

Double-entry reconciliation, the way a data pipeline reconciles its row counts per stage: what came in must equal what
went out plus what is accounted for, or the books do not close.

    {"created": [moment id], "final": [moment id],
     "dropped_fidelity": [{"id", "reason"}],            removed by `adam_fidelity` because it invented story
     "removed_by_person": [id],                         taken out by a person (never added back)
     "removed_by_operation": [{"id", "op", "note_id"}]}  taken out by a revision, for a note
        → {"ok", "buckets": {"kept", "dropped_fidelity", "removed_by_person", "removed_by_operation"},
           "unaccounted": [id], "doubled": [id], "added": [id], "problems": [line]}

An id in no bucket, in two, or removed by an operation that names no note is a problem, and a problem fails the job
with the line a person can read: "moment m8 left the plan without a record". `added` lists the moments in the final
plan the writer did not make (a revision added them): they are not part of the ledger, but they are shown. Pure code.
"""
from __future__ import annotations

from typing import Any

BUCKETS: tuple[str, ...] = ("kept", "dropped_fidelity", "removed_by_person", "removed_by_operation")


def run(payload: dict[str, Any]) -> dict[str, Any]:
    created = [str(i) for i in payload.get("created") or []]
    final = {str(i) for i in payload.get("final") or []}
    fidelity = {str(r["id"]): r for r in payload.get("dropped_fidelity") or []}
    person = {str(i) for i in payload.get("removed_by_person") or []}
    by_op = {str(r["id"]): r for r in payload.get("removed_by_operation") or []}
    buckets: dict[str, list[str]] = {b: [] for b in BUCKETS}
    unaccounted: list[str] = []
    doubled: list[str] = []
    problems: list[str] = []
    for ident in created:
        homes = [name for name, there in (("kept", ident in final), ("dropped_fidelity", ident in fidelity),
                                          ("removed_by_person", ident in person),
                                          ("removed_by_operation", ident in by_op)) if there]
        if len(homes) > 1:
            doubled.append(ident)
            problems.append(f"moment {ident} is recorded as {' and '.join(homes)}: it can end only one way")
        elif not homes:
            unaccounted.append(ident)
            problems.append(f"moment {ident} left the plan without a record")
        elif homes == ["removed_by_operation"] and not str(by_op[ident].get("note_id") or ""):
            unaccounted.append(ident)
            problems.append(f"moment {ident} was removed by operation {by_op[ident].get('op', '?')}, "
                            "which answers no note")
        if homes:
            buckets[homes[0]].append(ident)
    added = sorted(final - set(created))
    return {"ok": not problems, "buckets": buckets, "unaccounted": unaccounted, "doubled": doubled, "added": added,
            "problems": problems, "created": len(created), "kept": len(buckets["kept"])}
