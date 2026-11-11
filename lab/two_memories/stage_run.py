"""`run.py stage`: step 6 on the scenes named by --scenes (default E01-S08). Dry without --yes; paid with --yes --hypothesis."""
from __future__ import annotations

import json
from pathlib import Path

from hiru_ai.agents.stager.schema import Output
from hiru_ai.core.tokens import tokens_of
from two_memories import build, checks, packet, paid, rehearsal, stage
from two_memories.schema import EpisodeW, SplitW

LAB = Path(__file__).resolve().parent
GOLD = LAB / "gold"
CAP = 6_000


def load():
    d = rehearsal.doc()
    bd = build.build(SplitW.model_validate_json((GOLD / "split_ekama.json").read_text(encoding="utf-8")), d, "ekama-sakshiya")
    for f in sorted(GOLD.glob("episode_ekama_*.json")):
        build.apply_episode(bd, d, EpisodeW.model_validate_json(f.read_text(encoding="utf-8")))
    cont = json.loads((GOLD / "continuity_ekama.json").read_text(encoding="utf-8"))
    for f in sorted(GOLD.glob("stage_ekama_*.json")):  # scenes already staged
        sid = f.stem.removeprefix("stage_ekama_")
        stage.apply(bd, bd.scene(sid), Output.model_validate_json(f.read_text(encoding="utf-8")))
    return bd, d, cont


def main(argv: list[str]) -> None:
    from contracts.doc_read import strict_schema

    scenes = (argv[argv.index("--scenes") + 1] if "--scenes" in argv else "E01-S08").split(",")
    bd, _d, _cont = load()
    system = (LAB / "prompts" / "stager.md").read_text(encoding="utf-8")
    total = 0.0
    for sid in scenes:
        sc = bd.scene(sid)
        user = stage.user_message(bd, sc)
        tin = tokens_of(system) + tokens_of(user)
        worst = paid.worst_case(tin, CAP)
        total += worst
        print(f"{sid}: {tin} tokens in, at most {CAP} out, most it could cost ${worst:.4f}")
        if "--yes" not in argv:
            continue
        hyp = argv[argv.index("--hypothesis") + 1]
        out = Output.model_validate_json(paid.call(f"stage {sid}", system, user, strict_schema(Output), max_output=CAP, hypothesis=hyp))
        (GOLD / f"stage_ekama_{sid}.json").write_text(json.dumps(out.model_dump(), indent=1, ensure_ascii=False), encoding="utf-8")
        for f in stage.apply(bd, sc, out):
            print("   ", f.code, f.message)
    if "--yes" not in argv:
        print(f"most the {len(scenes)} call(s) could cost: ${total:.4f}  (no call is made)")
        print("--- the first scene's message ---")
        print(stage.user_message(bd, bd.scene(scenes[0])))
    else:
        for sid in scenes:
            p = packet.assemble(bd, sid)
            print(sid, "packet", "COMPLETE" if not packet.incomplete(bd, p) else "WAITS", json.dumps(p.get("stage", {}), ensure_ascii=False)[:600])
        print(f"spent ${paid.spent():.4f} of the ${paid.LAB_CAP_USD:.2f} hard cap")
    _ = checks
