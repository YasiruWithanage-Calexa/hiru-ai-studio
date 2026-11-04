"""scene_reader hooks. Ported from `script_split/engine/reading.py` (`SceneContext.text`, `_user`).

The studio's craft rules are in the system prompt, word for word from `knowledge_bases/craft` (a test checks they have
not drifted). The answer is validated in code (`contracts.reading.validate`); the free rules read the scene when this
agent has no usable answer, so there is no fallback here. A person's reading is never replaced.
"""
from __future__ import annotations

from hiru_ai.agents.scene_reader.schema import Context, Input
from hiru_ai.steps.scene_listing.logic import scene_listing


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
    return (f"<context>\n{head}\n</context>\n\n" if head else "") + \
        f"Blocks 0 to {len(inp.items) - 1}:\n<script>\n{scene_listing(list(inp.items), inp.speaker_names)}\n</script>"
