"""The screening panel's notes, in code (plan/2026-11-04b §5.4).

Four critics write at most four notes each. The reviser acts on the merged list, so it must be short, ordered and free
of repeats: most severe first, a lens keeps its own order inside a severity, and the list is capped. The critics' scores
are kept, apart from the notes, for a person to read: they decide nothing (Chakrabarty et al.).

`report` turns what the code steps found into lines, for the fidelity critic (who reads the report) and the reviser.
"""
from __future__ import annotations

import re
from typing import Any

from contracts.adam.screening import SEVERITIES, NoteW, note_line

MAX_TOTAL = 8  # what the reviser is asked to act on
MAX_LINES = 6  # per section of the code report
_KEY_WORDS = 7  # two notes on one card that start with the same words are one note


def merge(results: list[dict[str, Any] | None]) -> dict[str, Any]:
    """The critics' answers, one per lens (None for a critic that failed) → the notes to act on and the scores."""
    order = {s: i for i, s in enumerate(SEVERITIES)}
    rows: list[tuple[str, NoteW]] = []
    scores: dict[str, int] = {}
    failed = 0
    for answer in results:
        if not answer:
            failed += 1
            continue
        lens = str(answer.get("lens") or "critic")
        if answer.get("score") is not None:
            scores[lens] = int(answer["score"])
        rows += [(lens, NoteW.model_validate(n)) for n in answer.get("notes") or []]
    rows.sort(key=lambda r: order[r[1].severity])  # stable: lens order, then the critic's own order, within a severity
    seen: set[tuple[int, tuple[str, ...]]] = set()
    kept: list[tuple[str, NoteW]] = []
    for lens, note in rows:
        key = (note.card, tuple(re.findall(r"\w+", note.note.lower())[:_KEY_WORDS]))
        if key in seen:
            continue
        seen.add(key)
        kept.append((lens, note))
    shown = kept[:MAX_TOTAL]
    return {"notes": [note_line(lens, n) for lens, n in shown], "scores": scores, "failed": failed,
            "kept": [{"lens": lens, **n.model_dump()} for lens, n in shown], "dropped": len(kept) - len(shown)}


def _lines(rows: list[str]) -> list[str]:
    more = len(rows) - MAX_LINES
    return rows[:MAX_LINES] + ([f"  ... and {more} more"] if more > 0 else [])


def report(reports: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """The code steps' answers as text. `problems` counts what is still open (breaks, overruns, issues, flags not yet
    answered on the card)."""
    fid, fit, cont, feas, score = (reports[k] for k in ("fidelity", "fit", "continuity", "feasibility", "score"))
    out: list[str] = []
    problems = 0

    breaks = fid.get("breaks") or []
    problems += len(breaks)
    out.append("Fidelity: " + ("every script block and line appears once, in order; nothing invented."
                               if not breaks else f"{len(breaks)} break(s)"))
    out += _lines([f"  [{b['code']}] {b['where']}: {b['reason']}" for b in breaks])

    overruns = [i for i in fit.get("issues") or [] if i.get("level") == "overrun"]
    warnings = [i for i in fit.get("issues") or [] if i.get("level") != "overrun"]
    problems += len(overruns)
    runtime = fit.get("runtime_s")
    takes = len(fit.get("cards") or [])
    head = f"Veo clock: {runtime:g} s in {takes} takes; " if runtime is not None else "Veo clock: "
    out.append(head + ("no overruns." if not overruns else f"{len(overruns)} overrun(s) (a line is never trimmed)."))
    out += _lines([f"  [{i['code']}] card {i.get('card') or '-'}: {i['message']}" for i in overruns + warnings])

    issues = cont.get("issues") or []
    problems += len(issues)
    out.append("Continuity: " + ("no problems." if not issues else f"{len(issues)} problem(s)"))
    out += _lines([f"  [{i['code']}] {i['where']}: {i['message']}" for i in issues])

    open_flags = [f for f in feas.get("flags") or [] if not f.get("addressed")]
    problems += len(open_flags)
    out.append("What Veo renders badly: " + ("nothing left unanswered." if not open_flags
                                             else f"{len(open_flags)} open flag(s)"))
    out += _lines([f"  [{f['code']}] card {f['card']} ({f['risk']}): {f['why']}; fix: {f['fix']}"
                   for f in open_flags])

    if score:
        out.append(f"Craft score: {score.get('percent', 0):g}% of {score.get('max', 0):g} points.")
        missed = [f"  {s['signal']}: card {c['card'] if c['card'] is not None else '-'}: {c['why']}"
                  for s in score.get("signals") or [] if s.get("applicable") for c in s.get("checks") or []
                  if not c.get("ok")]
        out += _lines(missed)
    return {"text": "\n".join(out), "problems": problems}
