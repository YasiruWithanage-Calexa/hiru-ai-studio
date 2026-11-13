"""Repair Raphael shots written silent over a line they say (once; the cause is fixed in `raphael_write`).

Before the fix, a clip bound to a line whose speaker is not seen in it ("Aruni's voice message plays." then a bare line)
was stored `silent` / `ambient` / `music_only`, so its prompt said "nobody speaks" over a spoken line and the handoff
check failed ("The prompt does not say nobody speaks"). Such a shot is now voiced off screen: `voiceover`, with the
word target of its length. A shot whose speaker is seen was always `dialogue`, so the pattern is unambiguous.

    python scripts/repair_heard_shots.py                 # list what would change; writes nothing
    python scripts/repair_heard_shots.py --apply         # write it
    python scripts/repair_heard_shots.py --shot <id>...  # only these shots

Only planner `raphael`; an approved scene is never touched. Prompts are not rewritten: press Regenerate on each shot
listed (its next prompt is written from the repaired row). Reads SUPABASE__URL / SUPABASE__SERVICE_ROLE_KEY from .env.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common

_common.load_env()

from contracts.timing import shot_word_target  # noqa: E402

UNSPOKEN = ("silent", "ambient", "music_only")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--apply", action="store_true", help="write the repair (default: list only)")
    ap.add_argument("--shot", nargs="*", default=[], help="only these shot ids")
    args = ap.parse_args()
    rest = _common.Rest()

    params = {"select": "id,scene_id,number,sound_mode,duration_s,word_target",
              "planner": "eq.raphael", "sound_mode": f"in.({','.join(UNSPOKEN)})"}
    if args.shot:
        params["id"] = f"in.({','.join(args.shot)})"
    shots = rest.get("shots", **params)
    if not shots:
        print("No Raphael shot is stored without words.")
        return 0
    ids = [str(s["id"]) for s in shots]
    said: dict[str, list[str]] = {}
    for i in range(0, len(ids), 100):
        for ln in rest.get("dialogue_lines", select="shot_id,speaker", shot_id=f"in.({','.join(ids[i:i + 100])})"):
            said.setdefault(str(ln["shot_id"]), []).append(str(ln.get("speaker") or "?"))
    broken = [s for s in shots if str(s["id"]) in said]
    scene_ids = sorted({str(s["scene_id"]) for s in broken})
    scenes = {str(r["id"]): r for r in (rest.get("scenes", select="id,number,status",
                                                 id=f"in.({','.join(scene_ids)})") if scene_ids else [])}

    changed = 0
    for s in sorted(broken, key=lambda r: (int(scenes.get(str(r["scene_id"]), {}).get("number") or 0), r["number"])):
        scene = scenes.get(str(s["scene_id"]), {})
        label = f"Scene {scene.get('number', '?')} · S{int(s['number']):02d} · {s['id']}"
        target = shot_word_target(int(s["duration_s"]))
        if scene.get("status") == "approved":
            print(f"SKIP  {label}: the scene is approved (unapprove it to repair)")
            continue
        print(f"{'FIX ' if args.apply else 'WOULD'} {label}: {s['sound_mode']} -> voiceover, word target "
              f"{s.get('word_target')} -> {target} (says: {', '.join(said[str(s['id'])])})")
        if args.apply:
            r = rest.c.patch(f"{rest.rest}/shots", headers=rest.h, params={"id": f"eq.{s['id']}"},
                             json={"sound_mode": "voiceover", "word_target": target})
            r.raise_for_status()
            changed += 1
    print(f"\n{len(broken)} shot(s) found; {changed} repaired." if args.apply else
          f"\n{len(broken)} shot(s) found. Run again with --apply to repair, then Regenerate each prompt.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
