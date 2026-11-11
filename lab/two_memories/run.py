"""The two-memories lab's one tool (plan/2026-11-11 phase 0).

    python lab/two_memories/run.py dry        what the split call would send (size in tokens) and the most it could cost (free)
    python lab/two_memories/run.py rehearse   the whole flow with NO model: the hand-written gold answers (free)
    python lab/two_memories/run.py split --yes --hypothesis "..."   ONE paid split call on Ekama (the person's yes first)
    python lab/two_memories/run.py continuity [--yes --hypothesis "..."]   dry, or ONE paid continuity call on the approved cards
    python lab/two_memories/run.py ledger     what has been spent of the $1.00 hard cap (free)

Every paid run waits for the person's yes (plan §10). Hard cap: $1.00 for the whole lab (paid.py). Run the free commands with
`OPENAI__API_KEY=` blank.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    _ROOT = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(_ROOT / "lab"), str(_ROOT / "src" / "libs"), str(_ROOT / "src")]

from hiru_ai.core.tokens import tokens_of
from two_memories import build, checks, packet, rehearsal

PROMPTS = Path(__file__).resolve().parent / "prompts"
NL = chr(10)
PRICE_IN, PRICE_OUT = 2.0, 10.0  # $/1M tokens, Sol (plan §9)
SPLIT_OUT_CAP = 16_000  # tokens the split's answer may take: it is pointers only


def dry() -> None:
    d = rehearsal.doc()
    system = (PROMPTS / "split.md").read_text(encoding="utf-8")
    tin = tokens_of(system) + tokens_of(d.numbered())
    print(f"split call: {len(d)} lines, {tin} tokens in, at most {SPLIT_OUT_CAP} out")
    print(f"most it could cost: ${tin * PRICE_IN / 1e6 + SPLIT_OUT_CAP * PRICE_OUT / 1e6:.4f}  (no call is made)")


def rehearse() -> None:
    d = rehearsal.doc()
    bd = build.build(rehearsal.split(d), d, "ekama-sakshiya")
    names = {k: e.id for k, e in zip(rehearsal.KEYS, bd.entities, strict=True)}
    build.apply_episode(bd, d, rehearsal.episode(d, names))
    found = checks.run_all(bd, d)
    print(f"{len(bd.entities)} entities, {len(bd.rules)} rules, {len(bd.scenes)} scenes, {len(found)} findings")
    for f in found:
        print(f"  {'BLOCK' if f.blocking else 'report'} {f.code} {f.scene}: {f.message}")
    for sc in bd.scenes:
        if sc.brief is None:
            continue
        p = packet.assemble(bd, sc.id)
        wait = packet.incomplete(bd, p)
        print(f"{sc.id}: packet {tokens_of(json.dumps(p, ensure_ascii=False))} tokens, "
              f"{'COMPLETE' if not wait else 'WAITS: ' + '; '.join(wait)}")


def split_paid() -> None:
    from contracts.doc_read import strict_schema
    from two_memories import paid
    from two_memories.schema import SplitW

    if "--yes" not in sys.argv or "--hypothesis" not in sys.argv:
        sys.exit("A paid call needs --yes and --hypothesis \"one change, one reason\" (the person's yes comes first).")
    hyp = sys.argv[sys.argv.index("--hypothesis") + 1]
    d = rehearsal.doc()
    out = paid.call("split", (PROMPTS / "split.md").read_text(encoding="utf-8"), d.numbered(), strict_schema(SplitW),
                    max_output=16_000, hypothesis=hyp)
    got = SplitW.model_validate_json(out)
    (paid.RUNS / "split_ekama.json").write_text(json.dumps(got.model_dump(), indent=1), encoding="utf-8")
    gold = rehearsal.split(d)
    bd = build.build(got, d, "ekama-sakshiya")
    print(f"cards {len(got.cards)} (gold {len(gold.cards)}), rules {len(got.rules)} (gold {len(gold.rules)}), "
          f"scenes {sum(len(e.scenes) for e in got.episodes)} (gold 9), build findings {len(bd.findings)}")
    gs = {(s.number, s.heading, s.last) for e in gold.episodes for s in e.scenes}
    ms = {(s.number, s.heading, s.last) for e in got.episodes for s in e.scenes}
    print("scene cuts equal gold:", gs == ms, "" if gs == ms else sorted(gs ^ ms))
    for f in bd.findings:
        print("  ", f.code, f.message)
    ledger()


def _approved() -> tuple[object, object]:
    """The person-approved Ekama cards (gold/split_ekama.json) built into a memory, and the document."""
    from two_memories.schema import SplitW

    d = rehearsal.doc()
    got = SplitW.model_validate_json((Path(__file__).resolve().parent / "gold" / "split_ekama.json").read_text(encoding="utf-8"))
    return build.build(got, d, "ekama-sakshiya"), d


def continuity_dry() -> None:
    from two_memories import inputs

    bd, d = _approved()
    system = (PROMPTS / "continuity.md").read_text(encoding="utf-8")
    user = inputs.continuity_user(bd, d)
    tin = tokens_of(system) + tokens_of(user)
    print(f"continuity call: {tin} tokens in, at most 16000 out, most it could cost ${tin * PRICE_IN / 1e6 + 16000 * PRICE_OUT / 1e6:.4f}")


def continuity_paid() -> None:
    from contracts.doc_read import strict_schema
    from two_memories import inputs, paid
    from two_memories.schema import ContinuityW

    if "--yes" not in sys.argv or "--hypothesis" not in sys.argv:
        sys.exit("A paid call needs --yes and --hypothesis (the person's yes comes first).")
    bd, d = _approved()
    out = paid.call("continuity", (PROMPTS / "continuity.md").read_text(encoding="utf-8"), inputs.continuity_user(bd, d),
                    strict_schema(ContinuityW), max_output=16_000, hypothesis=sys.argv[sys.argv.index("--hypothesis") + 1])
    got = ContinuityW.model_validate_json(out)
    (paid.RUNS / "continuity_ekama.json").write_text(json.dumps(got.model_dump(), indent=1, ensure_ascii=False), encoding="utf-8")
    ids_ok = {e.id for e in bd.entities} | {s.id for s in bd.scenes} | {r.id for r in bd.rules} | {""}
    print({k: len(v) for k, v in got.model_dump().items()})
    bad = [t.scene for t in got.timeline if t.scene not in ids_ok] + [a.person for a in got.arcs if a.person not in ids_ok]
    print("unknown ids:", bad)
    ledger()


def episode_cmd() -> None:
    """Step 4 on the scenes named by --scenes (default E01-S01,E01-S02,E01-S03): dry, or paid with --yes --hypothesis."""
    from contracts.doc_read import strict_schema
    from two_memories import inputs, paid
    from two_memories.schema import EpisodeW

    scenes = (sys.argv[sys.argv.index("--scenes") + 1] if "--scenes" in sys.argv else "E01-S01,E01-S02,E01-S03").split(",")
    bd, d = _approved()
    cont = json.loads((paid.RUNS / "continuity_ekama.json").read_text(encoding="utf-8"))
    system = (PROMPTS / "episode.md").read_text(encoding="utf-8")
    user = inputs.episode_user(bd, d, cont, scenes)
    tin = tokens_of(system) + tokens_of(user)
    cap = int(sys.argv[sys.argv.index("--cap") + 1]) if "--cap" in sys.argv else 24_000
    if "--yes" not in sys.argv:
        print(f"episode call {scenes}: {tin} tokens in, at most {cap} out, most it could cost ${tin * PRICE_IN / 1e6 + cap * PRICE_OUT / 1e6:.4f}")
        return
    out = paid.call("episode", system, user, strict_schema(EpisodeW), max_output=cap,
                    hypothesis=sys.argv[sys.argv.index("--hypothesis") + 1])
    got = EpisodeW.model_validate_json(out)
    (paid.RUNS / f"episode_ekama_{scenes[0][-3:]}_{scenes[-1][-3:]}.json").write_text(
        json.dumps(got.model_dump(), indent=1, ensure_ascii=False), encoding="utf-8")
    from two_memories.schema import EpisodeW as _E

    for f in sorted((Path(__file__).resolve().parent / "gold").glob("episode_ekama_*.json")):  # scenes already approved
        build.apply_episode(bd, d, _E.model_validate_json(f.read_text(encoding="utf-8")))
    build.apply_episode(bd, d, got)
    found = checks.run_all(bd, d)
    for f in found:
        print(f"  {'BLOCK' if f.blocking else 'report'} {f.code} {f.scene}: {f.message}")
    for sc in bd.scenes:
        if sc.brief:
            wait = packet.incomplete(bd, packet.assemble(bd, sc.id))
            print(sc.id, "blocks", len(sc.blocks), "packet", "COMPLETE" if not wait else "WAITS: " + "; ".join(wait))
    ledger()


def repair_cmd() -> None:
    """Step 5's repair (plan §4.4, §8): for each scene with a blocking finding, show the same model its own answer and the exact
    problems, ask for the scene again; at most two tries; a patch with more blocking problems is never kept."""
    from contracts.doc_read import strict_schema
    from two_memories import inputs, paid
    from two_memories.schema import EpisodeW

    if "--yes" not in sys.argv or "--hypothesis" not in sys.argv:
        sys.exit("A paid call needs --yes and --hypothesis (the person's yes comes first).")
    hyp = sys.argv[sys.argv.index("--hypothesis") + 1]
    bd, d = _approved()
    gold = Path(__file__).resolve().parent / "gold"
    for f in sorted(gold.glob("episode_ekama_*.json")):
        build.apply_episode(bd, d, EpisodeW.model_validate_json(f.read_text(encoding="utf-8")))
    cont = json.loads((gold / "continuity_ekama.json").read_text(encoding="utf-8"))
    system = (PROMPTS / "episode.md").read_text(encoding="utf-8") + (PROMPTS / "repair.md").read_text(encoding="utf-8")
    checks.run_all(bd, d)
    fixed: list[object] = []
    for sc in list(bd.scenes):
        probs = [f for f in bd.findings if f.blocking and f.scene == sc.id]
        for attempt in (1, 2):
            if not probs:
                break
            prev = {"scene": sc.id, **(sc.brief or {}), "blocks": [{k: v for k, v in b.items() if k not in ("id", "text")}
                                                                  | {"events": [{k: v for k, v in e.items() if k != "id"} for e in b["events"]]}
                                                                  for b in sc.blocks]}
            problems = NL.join(f"- {f.message}" for f in probs)
            user = (NL * 2).join([inputs.episode_user(bd, d, cont, [sc.id]),
                                  "YOUR PREVIOUS ANSWER FOR THIS SCENE" + NL + json.dumps(prev, ensure_ascii=False),
                                  "PROBLEMS" + NL + problems])
            out = paid.call(f"repair {sc.id} #{attempt}", system, user, strict_schema(EpisodeW), max_output=10_000, hypothesis=hyp)
            got = EpisodeW.model_validate_json(out)
            keep = (sc.brief, sc.blocks)
            build.apply_episode(bd, d, got)
            checks.run_all(bd, d)
            now = [f for f in bd.findings if f.blocking and f.scene == sc.id]
            if len(now) >= len(probs):  # a worse (or no better) patch is not kept
                sc.brief, sc.blocks = keep
                checks.run_all(bd, d)
                print(f"{sc.id} try {attempt}: {len(now)} problems (was {len(probs)}): not kept")
            else:
                print(f"{sc.id} try {attempt}: {len(now)} problems (was {len(probs)}): kept")
                fixed.append(got.scenes[0])
                probs = now
    if fixed:
        (gold / "episode_ekama_s99_repairs.json").write_text(
            json.dumps({"scenes": [s.model_dump() for s in fixed]}, indent=1, ensure_ascii=False), encoding="utf-8")
    for sc in bd.scenes:
        wait = packet.incomplete(bd, packet.assemble(bd, sc.id, cont))
        print(sc.id, "COMPLETE" if not wait else "WAITS: " + "; ".join(wait))
    ledger()


def ledger() -> None:
    from two_memories import paid

    print(f"spent ${paid.spent():.4f} of the ${paid.LAB_CAP_USD:.2f} hard cap")


if __name__ == "__main__":
    {"dry": dry, "rehearse": rehearse, "split": split_paid, "continuity": lambda: (continuity_paid if "--yes" in sys.argv else continuity_dry)(),
     "stage": lambda: __import__("two_memories.stage_run", fromlist=["main"]).main(sys.argv),
     "episode": episode_cmd, "repair": repair_cmd, "ledger": ledger}.get(sys.argv[1] if len(sys.argv) > 1 else "", lambda: print(__doc__))()
