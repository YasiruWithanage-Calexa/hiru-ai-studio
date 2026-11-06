"""adam_take hooks (plan/2026-11-05 T1). New for Adam: one call for what five stages wrote.

The answer is cleaned in code the way each stage's was, entry by entry, and nothing else (whether a moment invents
story, a take fits the clock or a cut is motivated stays with the steps): an analysis that names a block the scene
lacks is repaired as the dramaturg's is (`clean_analysis`), the moments are tidied as the moment writer's are, staging
that names a moment or a person the plan lacks is dropped as the blocker's is, and a card that shows no moment is
dropped as the designer's is. There is no fallback (plan §5.5): with no model the job fails clearly.
"""
from __future__ import annotations

from contracts.adam.plan import SceneScript, compact, norm
from contracts.adam.wire import AnalysisWire, StagingWire, TakeCardsW
from hiru_ai.agents.adam.adam_take.schema import Context, Input, Output


def context_text(c: Context) -> str:
    rows = [f"Scene: {c.heading}" if c.heading else "",
            f"Director's note: {c.note}" if c.note else "",
            f"Episode: {c.episode_title}" if c.episode_title else "",
            f"Episode synopsis: {c.synopsis}" if c.synopsis else "",
            f"The scene before: {c.before}" if c.before else "",
            f"The scene after: {c.after}" if c.after else ""]
    rows += [f"Character {p.name}: {p.summary}" if p.summary else f"Character {p.name}" for p in c.characters]
    return "\n".join(r for r in rows if r)


def user_message(inp: Input) -> str:
    head = context_text(inp.context)
    return ((f"<devices>\n{inp.devices}\n</devices>\n\n" if inp.devices else "")
            + (f"<grammar>\n{inp.grammar}\n</grammar>\n\n" if inp.grammar else "")
            + (f"<context>\n{head}\n</context>\n\n" if head else "")
            + f"<script>\n{inp.scene.listing()}\n</script>"
            + (f"\n\n<facts>\n{inp.facts}\n</facts>" if inp.facts else "")
            + (f"\n\n<given_analysis>\n{compact(inp.analysis)}\n</given_analysis>" if inp.analysis else "")
            + (f"\n\n<stance>\n{inp.stance}\n</stance>" if inp.stance else "")
            + (f"\n\n<removed>\n{chr(10).join(inp.removed)}\n</removed>" if inp.removed else "")
            + (f"\n\n<notes>\n{inp.notes}\n</notes>" if inp.notes else ""))


def clean_analysis(scene: SceneScript, out: AnalysisWire) -> tuple[AnalysisWire, list[str]]:
    """The analysis without any reference to a block the scene does not have. -> (the answer, what was dropped).
    Copied from the dramaturg (ORIGIN.md)."""
    valid = {b.index for b in scene.blocks}
    dropped: list[str] = []

    def known(blocks: list[int], where: str) -> list[int]:
        kept = [b for b in blocks if b in valid]
        if len(kept) != len(blocks):
            dropped.append(f"{where}: block {sorted(set(blocks) - valid)} is not in the scene")
        return kept

    beats = []
    for n, beat in enumerate(out.beats, start=1):
        blocks = known(beat.blocks, f"beat {n}")
        if blocks or not beat.blocks:
            beats.append(beat.model_copy(update={"blocks": blocks}))
    subtext = []
    for s in out.subtext:
        if s.block in valid:
            subtext.append(s)
        else:
            dropped.append(f"subtext: block {s.block} is not in the scene")
    knows = []
    for k in out.audience_knows:
        if k.from_block in valid:
            knows.append(k)
        else:
            dropped.append(f"audience_knows: block {k.from_block} is not in the scene")
    break_block = out.break_block
    if break_block is not None and break_block not in valid:
        dropped.append(f"break: block {break_block} is not in the scene")
        break_block = None
    key = out.key_moment
    if key.block not in valid:
        moved = break_block if break_block is not None else max(valid, default=0)
        dropped.append(f"key moment: block {key.block} is not in the scene; moved to block {moved}")
        key = key.model_copy(update={"block": moved})
    baseline = out.baseline.model_copy(update={"blocks": known(out.baseline.blocks, "baseline")})
    wants = [w for w in out.wants if w.who.strip() and w.verb.strip()]
    return out.model_copy(update={"beats": beats, "subtext": subtext, "audience_knows": knows,
                                  "break_block": break_block, "key_moment": key, "baseline": baseline,
                                  "wants": wants}), dropped


def finish(inp: Input, out: Output) -> Output:
    moments = out.moments.tidy()
    ids = {m.id for m in moments.moments}
    people = {norm(c) for c in inp.scene.cast} | {norm(w) for m in moments.moments for w in m.who}
    staging = StagingWire(marks=[m for m in out.staging.marks if m.moment in ids and norm(m.who) in people],
                          moves=[m for m in out.staging.moves if m.moment in ids and norm(m.who) in people])
    return Output(analysis=clean_analysis(inp.scene, out.analysis)[0], treatment=out.treatment, pitches=out.pitches,
                  moments=moments, staging=staging, cards=TakeCardsW(cards=[c for c in out.cards.cards if c.moments]))
