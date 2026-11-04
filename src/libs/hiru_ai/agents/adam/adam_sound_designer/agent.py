"""adam_sound_designer hooks (plan/2026-11-04b §5.2).

New for Adam; the nearest part is `agents/sound_designer`, which writes one shot's sound from its design. This one
writes the whole scene's sound as one map, so the turn, the silence and the way out are planned together and a card's
sound is a slice of it. The answer is cleaned in code: an entry that names a card or a moment the plan does not have is
dropped. There is no fallback (plan §5.5).
"""
from __future__ import annotations

from contracts.adam.plan import compact
from hiru_ai.agents.adam.adam_sound_designer.schema import Input, Output


def user_message(inp: Input) -> str:
    return (f"<script>\n{inp.scene.listing()}\n</script>\n\n"
            f"<treatment>\n{compact(inp.treatment)}\n</treatment>\n\n"
            f"<moments>\n{compact(list(inp.moments))}\n</moments>\n\n"
            f"<cards>\n{compact(list(inp.cards))}\n</cards>")


def finish(inp: Input, out: Output) -> Output:
    moments = {m.id for m in inp.moments}
    numbers = {c.number for c in inp.cards}
    return Output(
        sections=out.sections,
        subjective=[s for s in out.subjective if s.moment in moments],
        silences=[s for s in out.silences if s in moments],
        pre_laps=[x for x in out.pre_laps if x.card in numbers],
        music=[m for m in out.music if m.moment in moments],
        cards=[c for c in out.cards if c.number in numbers])
