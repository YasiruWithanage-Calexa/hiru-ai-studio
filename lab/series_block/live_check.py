"""plan/2026-11-12b phase 7, the live check, as a lab run that writes NOTHING to the database.

    A  the breakdown, rebuilt from the PDF with the product's agents (split, continuity, the NEW series reader, episodes,
       repair) and the stager for Scene 1, through `contracts.breakdown.run.create`; packets for every scene
    B  Shot Planner Raphael on Scene 1's packet (the packet path; house rules H-12 and H-13 on both stages)
    C  Scene 1's draft first frames: the plan turned into shot rows by the product's `raphael_write.write`, composed by
       `frame_compose` (the genre lead from the series facts this build would write), painted by the product's image
       adapter at draft quality with the canon sheets of the production as it is (read only)

Reads (never writes) the hosted database and storage for the production's canon, looks and Scene 1's ids. Every paid
call is under ONE hard total, TOTAL_CAP: the breakdown under its own worst-case cap, Raphael under what is left minus
the frames' reserve, each frame only while its worst case still fits.

    python lab/series_block/live_check.py "<pdf>" --yes
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "lab"), str(ROOT / "lab" / "two_memories"), str(ROOT / "src" / "libs"), str(ROOT / "src")]

import live  # noqa: E402  (lab/two_memories/live.py: the Recorder, the Raphael runner, the PDF text)

from contracts import safe_depiction  # noqa: E402
from contracts.breakdown import fill, packet, render, stage  # noqa: E402
from contracts.breakdown import run as brun  # noqa: E402
from contracts.memory import genre_of  # noqa: E402

TOTAL_CAP = 1.50
BREAKDOWN_CAP = 1.00  # worst-case gate; a full Ekama breakdown cost $0.29 on 2026-11-11
FRAME_WORST = 0.10  # one draft frame with up to six reference pictures, gpt-image-2 low, generously
FRAMES_RESERVE = 0.60  # 13 painted draft frames cost $0.57 on 2026-11-12
IMAGE_PRICE = (8.00, 30.00)  # $/1M tokens in, out (contracts/costs.py seed for gpt-image-2)
PRODUCTION_ID = "96c4a5b7-b00e-44e1-acb8-f3ec75241a23"  # hiru short combined 1 (Ekama Sakshiya)
SCENE_ROW_ID = "25a8708f-19a8-47c2-a0ee-193d035f4a23"  # its Scene 1 row: ids for location, episode, looks
SID = "E01-S01"


def dump(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False, default=str), encoding="utf-8")


def step_a(pdf: Path, out: Path) -> tuple[Any, float]:
    live.WORST_OUT["series"] = 8_000
    text = live.extract(pdf)
    rec = live.Recorder(out, BREAKDOWN_CAP)
    calls = brun.Calls(
        split=lambda m: rec.call("split", "breakdown_split", m),
        continuity=lambda m: rec.call("continuity", "breakdown_continuity", m),
        episode=lambda m: rec.call("episode", "breakdown_episode", m),
        repair=lambda m: rec.call("repair", "breakdown_repair", m),
        series=lambda m: rec.call("series", "breakdown_series", m),
    )
    print("A  the breakdown:")
    res = brun.create([brun.Upload(document_id="local-ekama", filename=pdf.name, text=text)], calls,
                      production="ekama", workers=4, progress=lambda t: print(f"  > {t}", flush=True))
    dump(out / "A1_notes.json", {"failed": res.failed, "notes": res.notes})
    bd = res.memory
    if bd is None:
        sys.exit(f"no breakdown: {res.failed}")
    dump(out / "A2_series.json", {"series": bd.series,
                                  "findings": [f.model_dump() for f in bd.findings if f.code == "series"]})
    sc = bd.scene(SID)
    if sc is None or sc.brief is None:
        sys.exit(f"{SID} has no brief")
    got = rec.call("stager", "breakdown_stager", brun.stage_message(bd, SID))
    bd.findings += stage.apply(bd, sc, got)
    dump(out / "A3_memory.json", bd.model_dump(mode="json"))
    rows = fill.memory_rows(bd)
    dump(out / "A4_production_memory.json", rows)
    packets = {s.id: packet.assemble(bd, s.id) for s in bd.scenes if s.brief is not None}
    dump(out / "A5_packets.json", packets)
    (out / "A5_packets.txt").write_text("\n\n".join(render.render(p) for p in packets.values()), encoding="utf-8")
    print(f"  A spent ${rec.spent:.4f} ({rec.n} calls)")
    return bd, rec.spent


def step_b(out: Path, p: dict[str, Any], cap: float) -> tuple[dict[str, Any], float]:
    os.environ["RAPHAEL_SCENE_CAP_USD"] = f"{cap:.2f}"
    from hiru_ai.core.settings import get_settings

    get_settings.cache_clear()
    print(f"B  Raphael on {SID} (meter ${get_settings().raphael_scene_cap_usd:.2f}):")
    (out / "12_raphael").mkdir(exist_ok=True)
    summary = live.raphael_one(out, SID, p, 1)
    from contracts.raphael.packet import opening

    (out / "B0_opening.txt").write_text(opening(p)[0], encoding="utf-8")
    print(f"  B {summary['status']}, ${summary['dollars']:.4f}, {summary['calls']} calls, {summary['seconds']} s")
    return summary, float(summary["dollars"])


def _local_scene(bd: Any, db_scene: dict[str, Any], canon: list[dict[str, Any]]) -> tuple[dict, list, dict]:
    """Scene 1 as the product would store it from THIS breakdown: the database row's ids, this build's blocks and
    lines (new line ids), and the stager's map. -> (scene row, line rows, block id -> line id)."""
    sc = bd.scene(SID)
    chars = {str(c["name"]).casefold(): str(c["id"]) for c in canon if c.get("kind") == "character"}
    script, lines, line_of = [], [], {}
    for b, shaped in zip(sc.blocks, fill.scene_blocks(bd, sc), strict=True):
        if shaped["kind"] == "dialogue":
            lid = str(uuid.uuid4())
            line_of[b["id"]] = lid
            lines.append({"id": lid, "production_id": PRODUCTION_ID, "scene_id": SCENE_ROW_ID, "ord": len(lines),
                          "speaker": shaped["speaker"], "character_id": chars.get(shaped["speaker"].casefold()),
                          "text": shaped["text"], "delivery": shaped["delivery"]})
            script.append({"kind": "dialogue", "text": "", "line_id": lid})
        else:
            script.append({"kind": shaped["kind"], "text": shaped["text"], "line_id": None})
    scene = {**db_scene, "script": script, "status": "split", "staging": fill.staging(bd, sc), "raphael": None}
    return scene, lines, line_of


def step_c(out: Path, bd: Any, result: dict[str, Any], budget: float) -> tuple[list[dict[str, Any]], float]:
    from contracts.raphael.stored import StoredRaphael
    from hiru_ai.adapters import images as painter
    from hiru_ai.adapters.supabase_rest import build_ports
    from hiru_ai.core import parts
    from hiru_ai.core.settings import get_settings

    settings = get_settings()
    ports = build_ports(settings)  # read only below: canon, looks, a scene row, the reference sheets
    canon = ports.scenes.canon(uuid.UUID(PRODUCTION_ID))
    production = ports.scenes.production(uuid.UUID(PRODUCTION_ID))
    db_scene = ports.frames.scene(SCENE_ROW_ID)
    all_looks = ports.frames.looks(uuid.UUID(PRODUCTION_ID))
    episode = ports.frames.episode_number(str(db_scene["episode_id"])) if db_scene.get("episode_id") else None
    compose = parts.step("frame_compose", "step").run
    looks = compose({"op": "looks", "all_looks": all_looks, "scene_looks": ports.frames.scene_looks(SCENE_ROW_ID),
                     "episode": episode})["looks"] if all_looks else {}
    scene, lines, line_of = _local_scene(bd, db_scene, canon)
    stored = StoredRaphael.model_validate(result)
    # D7: the packet's mood words ride on the plan, as the Raphael graph sets them (`moods` in raphael_shot_planner)
    mood = [m for m in packet.assemble(bd, SID)["F_feeling"].get("mood") or [] if isinstance(m, str)]
    stored = stored.model_copy(update={"line_ids": {k: line_of.get(v, v) for k, v in stored.line_ids.items()},
                                       "mood": stored.mood or mood})
    shots, line_rows, fields = parts.step("raphael_write", "logic").write(scene, lines, stored, canon, production)
    scene = {**scene, **{k: fields[k] for k in ("raphael", "coverage")}}
    rows = [{**r, "status": "draft", "source": "reader"} for rs in fill.memory_rows(bd).values() for r in rs]
    genre = genre_of(rows)
    world = {"production": production, "canon": canon, "scene": scene, "lines": line_rows, "looks": looks,
             "shots": shots, "accepted": {}, "genre": genre}
    aspect = parts.step("frame_compose", "logic").production_aspect(production)
    paint = painter.build(settings, sink=None)
    print(f"C  {len(shots)} draft frames, genre phrase {genre!r}, budget ${budget:.2f}:")
    fdir = out / "C_frames"
    fdir.mkdir(exist_ok=True)
    spent, made = 0.0, []
    from hiru_ai.core.ports import Reference

    for shot in shots:
        tag = f"S{int(shot['number']):02d}"
        if compose({"op": "plate", **world, "shot": shot})["plate"]:  # the renderer's rule: made by code, free
            from contracts.frame_brief import BLACK_PLATE

            (fdir / f"{tag}.png").write_bytes(parts.step("frame_compose", "logic").black_png(aspect))
            (fdir / f"{tag}.prompt.txt").write_text(BLACK_PLATE, encoding="utf-8")
            made.append({"shot": tag, "slate": shot.get("slate"), "status": "black plate (code)", "dollars": 0.0})
            print(f"  {tag} black plate, made by code")
            continue
        if spent + FRAME_WORST > budget + 1e-9:
            made.append({"shot": tag, "status": "not painted: the cap"})
            print(f"  {tag} not painted: ${spent:.4f} spent, the next could pass the cap")
            continue
        pictures = []
        for want in compose({"op": "references", **world, "shot": shot})["references"]:
            for choice in want["choices"]:
                try:
                    data = bytes(ports.files.download(str(choice.get("bucket") or "references"), choice["path"]))
                    pictures.append(Reference(label=choice["label"], data=data))
                    break
                except Exception as exc:  # one that cannot be read is left out, as the renderer does
                    print(f"  {tag} {choice['label']} not read: {type(exc).__name__}")
        prompt = compose({"op": "compose", **world, "shot": shot, "labels": [p.label for p in pictures]})["prompt"]
        (fdir / f"{tag}.prompt.txt").write_text(prompt, encoding="utf-8")
        row = {"shot": tag, "slate": shot.get("slate"), "framing": shot.get("framing"), "title": shot.get("title"),
               "references": [p.label for p in pictures]}
        found = safe_depiction.blocking(prompt)
        if found:
            made.append({**row, "status": "refused by the gate", "words": [f.word for f in found]})
            print(f"  {tag} refused by the safe-depiction gate: {[f.word for f in found]}")
            continue
        try:
            pic = paint(prompt, aspect, pictures, draft=True)
        except Exception as exc:
            spent += FRAME_WORST  # a failed call is counted at its worst case
            cause = exc.__cause__
            why = f"{type(cause).__name__}: {str(cause)[:300]}" if cause is not None else str(exc)
            made.append({**row, "status": f"failed: {type(exc).__name__}: {exc}", "cause": why})
            print(f"  {tag} failed: {exc} ({why})")
            continue
        cost = pic.input_tokens * IMAGE_PRICE[0] / 1e6 + pic.output_tokens * IMAGE_PRICE[1] / 1e6
        spent += cost
        (fdir / f"{tag}.png").write_bytes(pic.data)
        made.append({**row, "status": "done", "dollars": round(cost, 4), "input_tokens": pic.input_tokens,
                     "output_tokens": pic.output_tokens})
        print(f"  {tag} done ${cost:.4f} ({len(pictures)} refs)")
    dump(out / "C_frames.json", {"genre": genre, "frames": made, "spent": round(spent, 4)})
    dump(out / "C_shots.json", shots)
    return made, spent


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--reuse", default="", help="an earlier run folder: its breakdown (A3_memory.json), no step A")
    ap.add_argument("--cap", type=float, default=TOTAL_CAP)
    args = ap.parse_args()
    if not args.yes:
        sys.exit("a paid run: --yes (the person's yes first)")
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    out = Path(__file__).resolve().parent / "runs" / time.strftime("live_%Y%m%d_%H%M%S")
    out.mkdir(parents=True)
    cap = min(args.cap, TOTAL_CAP)
    print(f"output: {out}; hard total ${cap:.2f}")
    if args.reuse:
        from contracts.breakdown.schema import Breakdown

        bd = Breakdown.model_validate_json((Path(args.reuse) / "A3_memory.json").read_text(encoding="utf-8"))
        a = 0.0
        print(f"A  reused {args.reuse}: $0")
    else:
        bd, a = step_a(Path(args.pdf), out)
    left = cap - a
    raphael_cap = min(0.50, left - FRAMES_RESERVE - 0.10)  # 0.10: a meter stops AFTER the call that crosses it
    if raphael_cap < 0.20:
        sys.exit(f"stopped before Raphael: ${a:.4f} spent leaves too little")
    _, b = step_b(out, packet.assemble(bd, SID), raphael_cap)
    result = json.loads((out / "12_raphael" / f"{SID}.json").read_text(encoding="utf-8"))["result"]
    c = 0.0
    if result.get("clips"):
        _, c = step_c(out, bd, result, cap - a - b)
    total = a + b + c
    dump(out / "ledger_total.json", {"breakdown": round(a, 4), "raphael": round(b, 4), "frames": round(c, 4),
                                     "total": round(total, 4), "cap": cap})
    print(f"\ntotal ${total:.4f} of ${cap:.2f}: breakdown ${a:.4f}, Raphael ${b:.4f}, frames ${c:.4f}")


if __name__ == "__main__":
    main()
