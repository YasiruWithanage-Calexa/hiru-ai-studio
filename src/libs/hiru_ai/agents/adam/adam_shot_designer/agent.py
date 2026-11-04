"""adam_shot_designer hooks (plan/2026-11-04b §5.2).

New for Adam. The designer is told, moment by moment, how long the Veo clock says each one takes (the seconds the
picture asks for or the time its lines take to say, whichever is longer, plus the half second before a first word), so
it can group moments into 4, 6 or 8 second takes. What does not fit is REPORTED by `adam_fit` after this agent and
never trimmed; a line is named by its id and its words are the script's. The answer is cleaned in code: a card that
shows no moment is dropped. There is no fallback (plan §5.5).
"""
from __future__ import annotations

from contracts.adam.plan import Moment, SceneScript, compact
from contracts.shotplan import LEAD_IN_S, TAIL_S
from contracts.timing import speech_seconds, words_in
from hiru_ai.agents.adam.adam_shot_designer.schema import Input, Output


def clock_text(scene: SceneScript, moments: list[Moment]) -> str:
    """The clock the designer groups moments on: one row a line, one a moment."""
    facts = {b.line_id: (words_in(b.text), b.delivery) for b in scene.lines if b.line_id}
    rows = [f"line {ident}: {words} words, {speech_seconds(words, delivery):.1f} s to say"
            for ident, (words, delivery) in facts.items()]
    for m in moments:
        said = sum(speech_seconds(*facts[ln]) for ln in m.lines if ln in facts)
        lead = LEAD_IN_S if any(ln in facts for ln in m.lines) else 0.0
        rows.append(f"{m.id}: {max(m.seconds_need, said) + lead:.1f} s on the clock")
    return "\n".join([*rows, f"A take with speech also needs {TAIL_S:g} s after the last word."])


def moments_text(moments: list[Moment]) -> str:
    return compact(list(moments))


def user_message(inp: Input) -> str:
    return ((f"<devices>\n{inp.devices}\n</devices>\n\n" if inp.devices else "")
            + f"<script>\n{inp.scene.listing()}\n</script>\n\n"
            + f"<analysis>\n{compact(inp.analysis)}\n</analysis>\n\n"
            + f"<treatment>\n{compact(inp.treatment)}\n</treatment>\n\n"
            + f"<moments>\n{moments_text(inp.moments)}\n</moments>\n\n"
            + f"<staging>\n{compact(inp.staging)}\n</staging>\n\n"
            + f"<clock>\n{clock_text(inp.scene, inp.moments)}\n</clock>")


def finish(inp: Input, out: Output) -> Output:
    return Output(cards=[c for c in out.cards if c.moments])
