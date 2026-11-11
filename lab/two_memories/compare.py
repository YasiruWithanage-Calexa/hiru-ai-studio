"""What Shot Planner Raphael is sent today for an Ekama scene, built with the PRODUCT's own code (the rules parser,
`script_of`'s helpers, `contracts.raphael.pack`), no model: the baseline of the plan's stop rule (plan/2026-11-11 §10).

Best case for today: the people carry their cast-table line as `who they are`, the direction table is given as the
production's rules, and the place is named. The director's breakdown (`raphael_breakdown`, a model call each run) is not
included: it would add the objective, the direction and the shot cards."""
from __future__ import annotations

import sys
from pathlib import Path

from contracts import screenplay
from contracts.raphael import pack
from contracts.raphael.scene import BlockS, Brief, PlaceS, SceneS, mark_recorded
from hiru_ai.systems.raphael.raphael_shot_planner.scene import objects_of, others_of, present
from two_memories import rehearsal

PEOPLE = {"Dinu": "30, Colombo cash-transport driver. Quiet, experienced, violent only when cornered.",
          "Aruni": "27, Mahawewa community nurse. Strong, intelligent and emotionally controlled.",
          "Nimal": "34, Aruni's elder brother and Dinu's closest friend.",
          "Mudalali": "52, businessman laundering illegal money through village development projects.",
          "Suren": "38, Mudalali's brutal right-hand man.",
          "Inspector Ruwan": "45, corrupt police officer protecting the money trail."}


def today(number: int) -> str:
    d = rehearsal.doc()
    doc = screenplay.parse_document("\n".join(d.lines), "ekama.txt", set(PEOPLE))
    scenes = doc.episodes[0].scenes
    sc = scenes[number - 1]
    blocks = []
    for i, b in enumerate(sc.blocks):
        blocks.append(BlockS(index=i, kind=b.kind, text=b.text, speaker=b.speaker.title(), delivery=b.delivery,
                             line_id=f"L{i}" if b.kind == "dialogue" else None))
    blocks = mark_recorded(blocks)
    characters = [{"name": n} for n in PEOPLE]
    cast = present(characters, blocks)
    props = [{"name": n} for n in ("key", "photo", "red thread", "metal box", "medical bag", "phone", "gun", "chain", "cash bags")]
    scene = SceneS(blocks=blocks, cast=cast, others=others_of(characters, cast),
                   place=PlaceS(name=sc.heading.location.title(), objects=objects_of(props, None, blocks)),
                   envelope_s=float(sc.heading.stated_seconds or 0) or None)
    production = {"style_note": "", "rules": [r for r in TABLE], "people": [
        {"name": n, "code": n[:3].upper(), "essence": PEOPLE[n]} for n in PEOPLE if n in cast]}
    nxt = scenes[number].heading.raw if number < len(scenes) else ""
    prev = scenes[number - 2].heading.raw if number > 1 else ""
    context = {"heading": sc.heading.raw, "before": prev, "after": nxt, "place": ""}
    brief = Brief(scene=scene, guide_s=float(scene.envelope_s or 0))
    return pack.scene_opening(production, context, brief)


TABLE = ["Colombo palette: Cold blue, green and sodium orange. Handheld camera, tight frames and crowded backgrounds.",
         "Village palette: Warm amber and earthy red. Locked-off frames, natural light and longer silences.",
         "Love scenes: 50mm and 85mm lenses, shallow focus and minimal camera movement.",
         "Action lenses: 24mm for geography, 35mm for movement and 50mm for emotional impact.",
         "Lighting: Vehicle headlights, sodium lamps, practical bulbs and lightning flashes.",
         "Editing: Fast cuts only on impact. Let important punches and reactions stay on screen.",
         "Sound: Rain, breathing, metal impacts and footsteps first. Music enters only for hero elevation moments.",
         "Slow motion: Use only twice: Nimal's key falling and Dinu removing the gun."]

if __name__ == "__main__":
    print(today(int(sys.argv[1])))
    _ = Path
