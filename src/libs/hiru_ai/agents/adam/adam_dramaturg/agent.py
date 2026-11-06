"""adam_dramaturg hooks (plan/2026-11-04b §5.2).

New for Adam (no `script_split` part to port; the nearest is `scene_reader`, whose reading it replaces with a fuller
analysis). The answer is checked in code, entry by entry: a block that is not in the scene is dropped, never repaired.
The one exception is the key moment, which every later stage needs: a key moment on a block that does not exist moves to
the break, or failing that to the last block. There is no fallback: Adam has no rules-only answer worth having, so with
no model the job fails clearly and the production's classic planner is the way out (plan §5.5).
"""
from __future__ import annotations

from contracts.adam.plan import SceneScript
from hiru_ai.agents.adam.adam_dramaturg.schema import Context, Input, Output


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
    return ((f"<grammar>\n{inp.grammar}\n</grammar>\n\n" if inp.grammar else "")
            + (f"<context>\n{head}\n</context>\n\n" if head else "")
            + f"<script>\n{inp.scene.listing()}\n</script>")


def memory_scope(inp: Input) -> dict[str, object]:
    """What this call is about, so the production memory is narrowed to it (plan/2026-11-05d M6)."""
    return {"place": inp.scene.place.name, "people": list(inp.scene.cast), "episode": inp.context.episode}


def clean(scene: SceneScript, out: Output) -> tuple[Output, list[str]]:
    """The answer without any reference to a block the scene does not have. -> (the answer, what was dropped)."""
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
    return clean(inp.scene, out)[0]
