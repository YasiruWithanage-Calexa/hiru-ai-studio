"""The reading and the user message (plan/2026-11-06 §4.1, §4.5).

`load()` reads an input yaml (`input/reading.yaml`, `input/second_scene.yaml`) into the scene as David is given it.
`message()` builds the user message: the same parts as `david_pack` (production, scene, script, tags and all), plus each
person's essence, the style guide, the time policy as a sentence, and a marker on every line that is heard and not seen
(`b3 line [L3] Kasun, voice over, to himself, heard not seen …`). Nothing here calls a model.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from contracts import sceneplan
from contracts.david.scene import BlockS, PlaceS, SceneS, line_facts
from contracts.shotplan import HEARD_MARKS, Item
from hiru_ai.steps.david.david_pack.logic import scene_part

LAB = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Reading:
    """An input file: the raw yaml (for the page and the measures) and the scene David is given."""

    raw: dict[str, Any]
    scene: SceneS

    @property
    def title(self) -> str:
        return str(self.raw.get("title") or self.raw.get("id") or "")

    @property
    def guide_s(self) -> float:
        return float((self.raw.get("time") or {}).get("guide_s") or 0)

    @property
    def people(self) -> list[dict[str, Any]]:
        return list(self.raw.get("people") or [])

    @property
    def story_objects(self) -> list[str]:
        return [str(o) for o in self.raw.get("story_objects") or []]

    def words(self) -> dict[str, tuple[str, str]]:
        """line id -> (speaker, the line's words): the page shows them, the author never writes them."""
        return {b.line_id: (b.speaker, b.text) for b in self.scene.lines if b.line_id}


def load(path: Path) -> Reading:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    sc = raw["scene"]
    items = [Item(b["index"], b["kind"], b["text"], b.get("speaker", ""), None, b.get("delivery", ""), b.get("line_id"))
             for b in sc["blocks"]]
    items = sceneplan._read_unread(items)
    scene = SceneS(blocks=[BlockS.of(i) for i in items], cast=list(sc["cast"]), others=list(sc.get("others") or []),
                   place=PlaceS(name=sc["place"]["name"], objects=list(sc["place"]["objects"])), envelope_s=None)
    return Reading(raw=raw, scene=scene)


def is_heard(block: BlockS) -> bool:
    """A line that is heard and not seen: a voice over, a narrator, the other end of a phone."""
    return any(m in f"{block.delivery} {block.speaker}".lower() for m in HEARD_MARKS)


def is_voice_over(block: BlockS) -> bool:
    """A thought or a narrator: heard over the picture, said to nobody in it."""
    return any(m in f"{block.delivery} {block.speaker}".lower() for m in ("v.o", "vo)", "voice over", "voice-over",
                                                                         "voiceover", "narrat"))


def listing(scene: SceneS) -> str:
    """The scene as the author reads it, as `contracts.david.scene.listing` writes it, with heard lines marked."""
    facts = {b.index: (w, s, t) for b, w, s, t in line_facts(scene)}
    head = [f"Present: {', '.join(scene.cast)}" if scene.cast else "",
            f"Place: {scene.place.name}" + (f" (objects: {', '.join(scene.place.objects)})" if scene.place.objects
                                           else "") if scene.place.name else ""]
    rows = []
    for b in sorted(scene.blocks, key=lambda x: x.index):
        if b.kind == "dialogue" and b.line_id:
            words, said, take = facts[b.index]
            how = f", {b.delivery}" if b.delivery else ""
            thought = is_voice_over(b) and b.speaker in scene.cast  # a person on screen, thinking aloud: seen, lips closed
            heard = ", a thought (he or she is seen, lips closed)" if thought else ", heard not seen" if is_heard(b) else ""
            held = f"shortest take {take} s" if take else "longer than any take: reported, never trimmed"
            rows.append(f'b{b.index} line [{b.line_id}] {b.speaker}{how}{heard} ({words} words, {said:.1f} s, {held}): '
                        f'"{b.text}"')
        else:
            mark = " [move]" if b.kind == "action" and b.screen == "move" else ""  # the only blocks that may move a person
            rows.append(f"b{b.index} {b.kind}{mark}: {b.text}")
    return "\n".join([r for r in head if r] + rows)


def production_part(reading: Reading) -> str:
    rows = []
    for p in reading.people:
        bits = [f"look: {p['look']}" if p.get("look") else "", f"voice: {p['voice']}" if p.get("voice") else "",
                f"who they are: {p['essence']}" if p.get("essence") else ""]
        said = "; ".join(b.rstrip(".") for b in bits if b)
        rows.append(f"- {p['name']} ({p.get('code') or '-'})" + (f": {said}" if said else ""))
    style = str(reading.raw.get("style") or "").strip()
    out = [f"Style guide: {style}" if style else "", "People in this episode:\n" + "\n".join(rows) if rows else ""]
    return "\n".join(o for o in out if o)


def scene_context(reading: Reading) -> str:
    raw = reading.raw
    note = " ".join(str((raw.get("time") or {}).get("policy") or "").split())
    return scene_part({"heading": raw.get("heading"), "episode_title": raw.get("episode_title"),
                       "synopsis": " ".join(str(raw.get("synopsis") or "").split()), "note": note or None})


def message(reading: Reading) -> str:
    """The user message, tagged as David's is: <production>, <scene>, <script>."""
    parts = [("production", production_part(reading)), ("scene", scene_context(reading)),
             ("script", listing(reading.scene))]
    return "\n\n".join(f"<{tag}>\n{text}\n</{tag}>" for tag, text in parts if text)
