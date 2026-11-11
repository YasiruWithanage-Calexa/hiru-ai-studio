"""The scene breakdown's real pipeline on one PDF, with every intermediate step saved as JSON (plan/2026-11-11, before
phase 7). The product's own code and agents run end to end (extract text -> split -> build -> continuity -> episodes ->
checks -> repair -> stager -> today's columns -> packets -> Raphael's opening); the memories are kept in files, not in
Supabase (schema v21 is not applied).

    python lab/two_memories/live.py <pdf>                       dry: the text, the split's message, sizes, no call
    (free)
    python lab/two_memories/live.py <pdf> --yes --cap 2.50      the paid run (the person's yes first), hard money cap
    options: --out DIR (default lab/two_memories/runs/pipeline_<pdf name>), --no-stage (skip the stager calls),
             --raphael (then plan every complete packet with Shot Planner Raphael, both stages, on the packet path;
             each scene under Raphael's own meter, RAPHAEL_SCENE_CAP_USD, default $1.00; saved in 12_raphael/)

Money: every call is priced from its usage (GPT-6.1 Sol $2 in, $0.10 cached in, $10 out per 1M;
contracts/raphael/money.py).
A call is refused BEFORE it is sent when the spend so far plus its planning worst case (the lab's output caps) would
pass
--cap. The structured agents set no output cap of their own, so the worst case is a planning figure, not a hard bound on
one
answer. Costs go to the console and `ledger.json` only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src" / "libs"), str(ROOT / "src")]

from contracts.breakdown import fill, memory, packet, render, stage  # noqa: E402
from contracts.breakdown import run as brun  # noqa: E402
from contracts.breakdown.lines import Doc  # noqa: E402
from hiru_ai.core.tokens import tokens_of  # noqa: E402

PRICE = (2.00, 0.10, 10.00)  # $/1M: input, cached input, output
WORST_OUT = {"split": 16_000, "continuity": 16_000, "episode": 32_000, "repair": 10_000, "stager": 6_000}
SCENE = re.compile(r"=== (E\d\d-S\d\d)")
NL = chr(10)


class CapReached(Exception):
    pass


class Recorder:
    """Every call: its message, its answer and what it cost, saved under `calls/`; the money cap held before each
    call."""

    def __init__(self, out: Path, cap: float) -> None:
        self.out, self.cap = out, cap
        self.lock = threading.Lock()
        self.spent = 0.0
        self.reserved = 0.0
        self.n = 0
        self.rows: list[dict[str, Any]] = []
        (out / "calls").mkdir(parents=True, exist_ok=True)

    def worst(self, slot: str, message: str, system: str) -> float:
        return (tokens_of(system) + tokens_of(message)) * PRICE[0] / 1e6 + WORST_OUT[slot] * PRICE[2] / 1e6

    def call(self, slot: str, agent_id: str, message: str) -> Any:
        from hiru_ai.core import agents
        from hiru_ai.core.context import RunContext

        agent = agents.build(agent_id)
        worst = self.worst(slot, message, agent.prompt.text)
        with self.lock:
            if self.spent + self.reserved + worst > self.cap + 1e-9:
                raise CapReached(
                    f"refused {slot}: ${self.spent:.4f} spent, ${self.reserved:.4f} in flight, this call "
                    f"could cost ${worst:.4f}; the cap is ${self.cap:.2f}"
                )
            self.reserved += worst
            self.n += 1
            n = self.n
        usage: list[dict[str, Any]] = []
        started = time.monotonic()
        try:
            got = agent.run({"message": message}, RunContext(usage_sink=usage.append))
            status = "done"
        except Exception as exc:
            got, status = None, f"failed: {type(exc).__name__}: {exc}"
        took = time.monotonic() - started
        i = sum(int(u.get("input_tokens") or 0) for u in usage)
        c = sum(int(u.get("cached_input_tokens") or 0) for u in usage)
        o = sum(int(u.get("output_tokens") or 0) for u in usage)
        dollars = (i - c) * PRICE[0] / 1e6 + c * PRICE[1] / 1e6 + o * PRICE[2] / 1e6 if usage else worst
        scenes = SCENE.findall(message.split("SCENES TO BREAK DOWN", 1)[-1]) if slot in ("episode", "repair") else []
        row = {
            "n": n,
            "slot": slot,
            "agent": agent_id,
            "scenes": scenes,
            "seconds": round(took, 1),
            "input_tokens": i,
            "cached_tokens": c,
            "output_tokens": o,
            "dollars": round(dollars, 4),
            "status": status,
            "model": str((usage[0] if usage else {}).get("model") or ""),
        }
        with self.lock:
            self.reserved -= worst
            self.spent += dollars
            self.rows.append(row)
            (self.out / "ledger.json").write_text(
                json.dumps({"cap": self.cap, "spent": round(self.spent, 4), "calls": self.rows}, indent=1),
                encoding="utf-8",
            )
        tag = f"{n:02d}_{slot}" + (
            f"_{scenes[0]}" + (f"-{scenes[-1][-3:]}" if len(scenes) > 1 else "") if scenes else ""
        )
        (self.out / "calls" / f"{tag}.json").write_text(
            json.dumps(
                {**row, "message": message, "answer": got.model_dump(mode="json") if got is not None else None},
                indent=1,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        print(
            f"  call {n:02d} {slot:<10} {' '.join(scenes):<20} {took:6.1f} s  in {i:>6}  out {o:>6}  ${dollars:.4f}  "
            f"{status if status != 'done' else ''}",
            flush=True,
        )
        if got is None:
            raise RuntimeError(status)
        return got


def save(out: Path, name: str, data: Any) -> None:
    (out / name).write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"  saved {name}")


def extract(pdf: Path) -> str:
    from hiru_ai.steps.extract_text.logic import extract as _extract

    return _extract(pdf.read_bytes(), pdf.name, "application/pdf").text


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--cap", type=float, default=0.0)
    ap.add_argument("--out", default="")
    ap.add_argument("--no-stage", action="store_true")
    ap.add_argument("--raphael", action="store_true")
    ap.add_argument("--raphael-only", default="", help="a run folder: plan its saved complete packets with Raphael")
    args = ap.parse_args()
    if args.raphael_only:  # no breakdown calls: the packets the earlier run saved
        if not args.yes or not args.out:
            sys.exit("--raphael-only needs --yes and --out (a new folder)")
        src = Path(args.raphael_only)
        packets = json.loads((src / "09_packets.json").read_text(encoding="utf-8"))
        waits = json.loads((src / "09_packets_waits.json").read_text(encoding="utf-8"))
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        raphael_all(out, {sid: p for sid, p in packets.items() if not waits.get(sid)})
        return
    pdf = Path(args.pdf)
    slug = re.sub(r"[^a-z0-9]+", "_", pdf.stem.lower()).strip("_")
    out = Path(args.out) if args.out else ROOT / "lab" / "two_memories" / "runs" / f"pipeline_{slug}"
    out.mkdir(parents=True, exist_ok=True)
    print(f"output: {out}")

    text = extract(pdf)
    (out / "00_extracted.txt").write_text(text, encoding="utf-8")
    lines = memory.strip_furniture(memory.clean_lines(text))
    split_msg = brun.split_message(pdf.name, Doc(lines))
    (out / "00_split_message.txt").write_text(split_msg, encoding="utf-8")
    print(
        f"  saved 00_extracted.txt ({len(text)} chars), 00_split_message.txt ({len(lines)} lines after the page "
        "furniture)"
    )

    from hiru_ai.core import agents as _agents

    split_in = tokens_of(_agents.build("breakdown_split").prompt.text) + tokens_of(split_msg)
    print(f"split: {split_in} tokens in")
    if not args.yes:
        print("dry run: no call made. A paid run needs --yes and --cap (the person's yes first).")
        return
    if args.cap <= 0:
        sys.exit("--cap is required with --yes")

    rec = Recorder(out, args.cap)
    calls = brun.Calls(
        split=lambda m: rec.call("split", "breakdown_split", m),
        continuity=lambda m: rec.call("continuity", "breakdown_continuity", m),
        episode=lambda m: rec.call("episode", "breakdown_episode", m),
        repair=lambda m: rec.call("repair", "breakdown_repair", m),
    )
    upload = brun.Upload(document_id="local-" + slug, filename=pdf.name, text=text)
    print("creation run:")
    res = brun.create([upload], calls, production=slug, workers=4, progress=lambda t: print(f"  > {t}", flush=True))
    save(out, "01_source_memory.json", [s.model_dump(mode="json") for s in res.sources])
    save(out, "06_notes.json", {"failed": res.failed, "notes": res.notes})
    if res.memory is None:
        print(f"no memory: {res.failed}")
        return
    bd = res.memory
    save(out, "02_continuity.json", bd.continuity)
    save(out, "03_findings.json", [f.model_dump() for f in bd.findings])
    save(out, "04_creation_questions.json", bd.questions)
    save(out, "05_memory_before_stager.json", bd.model_dump(mode="json"))

    if not args.no_stage:
        print("stager (step 6), one call per scene:")
        for sc in bd.scenes:
            if sc.brief is None:
                continue
            try:
                got = rec.call("stager", "breakdown_stager", brun.stage_message(bd, sc.id))
            except (CapReached, RuntimeError) as exc:
                print(f"  {sc.id}: no map ({exc})")
                continue
            for f in stage.apply(bd, sc, got):
                bd.findings.append(f)

    save(out, "07_memory.json", bd.model_dump(mode="json"))
    save(
        out,
        "08_todays_columns.json",
        {
            "structure": fill.structure(bd),
            "canon": fill.canon_cards(bd),
            "production_memory": fill.memory_rows(bd),
            "staging": {sc.id: fill.staging(bd, sc) for sc in bd.scenes if sc.stage},
        },
    )
    packets, texts, waits = {}, [], {}
    for sc in bd.scenes:
        if sc.brief is None:
            waits[sc.id] = ["the scene has no breakdown yet"]
            continue
        p = packet.assemble(bd, sc.id)
        packets[sc.id] = p
        waits[sc.id] = packet.incomplete(bd, p)
        texts.append(render.render(p))
    save(out, "09_packets.json", packets)
    save(out, "09_packets_waits.json", waits)
    (out / "10_packets.txt").write_text("\n\n" + ("=" * 100 + "\n\n").join(texts), encoding="utf-8")
    print("  saved 10_packets.txt")
    from contracts.raphael.packet import opening

    rdir = out / "11_raphael_openings"
    rdir.mkdir(exist_ok=True)
    for sid, p in packets.items():
        if not waits[sid]:
            (rdir / f"{sid}.txt").write_text(opening(p)[0], encoding="utf-8")
    print(f"  saved 11_raphael_openings/ ({sum(not w for w in waits.values())} scenes)")
    print(
        f"\n{len(bd.scenes)} scenes, {sum(not w for w in waits.values())} packets complete; "
        f"{rec.n} calls, spent ${rec.spent:.4f} of the ${rec.cap:.2f} cap"
    )
    if args.raphael:
        raphael_all(out, {sid: p for sid, p in packets.items() if not waits[sid]})


def raphael_one(out: Path, sid: str, packet_: dict[str, Any], number: int) -> dict[str, Any]:
    """Raphael on the packet path, as `raphael_shot_planner` runs it with RAPHAEL_PACKET on: the packet is stage 1's
    opening, no stager call, no director's breakdown, then stage 2 over the locked bin. No database: the line ids are
    the packet's block ids (in the product they are the scene's `dialogue_lines` rows)."""
    from contracts.raphael.packet import opening
    from hiru_ai.core.context import RunContext
    from hiru_ai.systems.raphael.raphael_shot_planner import scene as raphael

    text, script, ids = opening(packet_)
    line_ids = {k: v for k, v in ids.items() if k.startswith("L")}
    planner = raphael.Planner(
        RunContext(), script, number=number, line_ids=line_ids, production={}, context={}, opening=text
    )
    started = time.monotonic()
    try:
        done = planner.plan(previous={}, job_id=f"local-{sid}")
        result: dict[str, Any] = done.stored.model_dump(mode="json")
        status = "done"
    except raphael.Failed as exc:
        result, status = {}, f"failed: {exc}"
    took = time.monotonic() - started
    summary = {
        "scene": sid,
        "status": status,
        "seconds": round(took, 1),
        "calls": planner.meter.calls,
        "dollars": round(planner.meter.spent, 4),
        "log": planner.log,
        "warnings": planner.warnings,
    }
    rdir = out / "12_raphael"
    (rdir / f"{sid}.json").write_text(
        json.dumps({**summary, "ids": ids, "result": result}, indent=1, ensure_ascii=False), encoding="utf-8"
    )
    (rdir / f"{sid}.txt").write_text(clip_text(sid, result, packet_, ids, status), encoding="utf-8")
    print(
        f"  raphael {sid}: {status}, {planner.meter.calls} calls, {took:.0f} s, ${planner.meter.spent:.4f}", flush=True
    )
    return summary


def clip_text(sid: str, r: dict[str, Any], packet_: dict[str, Any], ids: dict[str, str], status: str) -> str:
    """A person's reading of Raphael's result: the seconds, the intended cut, each clip with its blocks and lines."""
    if not r:
        return f"{sid}: {status}" + NL
    words = {b["id"]: b["text"] for b in packet_["E_blocks"]}
    sec = r.get("seconds") or {}
    rows = [
        f"SCENE {sid}: stage 1 {r.get('stage1')}, stage 2 "
        f"{r.get('stage2')}" + (f" ({r['stopped']})" if r.get("stopped") else ""),
        f"Seconds: target {sec.get('target_s')}, cap {sec.get('cap_s')}, takes {sec.get('take_s')} "
        f"(must {sec.get('must_s')}, cinematic {sec.get('cinematic_s')})",
        "",
    ]
    t = (r.get("edit") or {}).get("treatment") or {}
    for key in ("logline", "approach", "key_image", "geography"):
        if t.get(key):
            rows.append(f"{key.replace('_', ' ').title()}: {t[key]}")
    for beat in t.get("arc") or []:
        rows.append(f"Arc: {beat.get('beat')} (blocks {beat.get('blocks')}): {beat.get('feeling')}")
    rows.append("")
    for c in r.get("clips") or []:
        ir = c.get("ir") or {}
        cam = ir.get("cinematography") or {}
        tags = [
            f"{c['id']}",
            f"stage {c.get('stage')}",
            str(c.get("role") or ""),
            str(c.get("priority") or ""),
            f"anchor {','.join(c['anchor'])}" if c.get("anchor") else "",
        ]
        head = f"{c.get('slate', c['id'])} [{', '.join(t for t in tags if t)}]"
        rows.append(head)
        if c.get("summary"):
            rows.append(f"    SUMMARY: {c['summary']}")
        for key in ("blocks", "lines"):
            for x in c.get(key) or []:
                bid = ids.get(f"b{x}" if isinstance(x, int) else str(x), str(x))
                rows.append(f"    {key[:-1]} {x} = {bid}: {words.get(bid, '')}")
        rows.append(
            f"    {c.get('size')} · {c.get('lens')} · {c.get('technique')} · {c.get('angle')} · "
            f"take {c.get('take_s')} s"
        )
        for label, value in (
            ("why", c.get("why")),
            ("editor", c.get("editor_note")),
            ("framing", cam.get("framing")),
            ("movement", cam.get("movement")),
            ("light", ir.get("lighting")),
        ):
            if value:
                rows.append(f"    {label}: {value}")
        for s in ir.get("subjects") or []:
            rows.append(f"    {s.get('id')}: {s.get('action')}")
        rows.append("")
    for row in r.get("review") or []:
        rows.append(f"Review moment {row.get('moment')}: {'earns' if row.get('earns') else 'no'}: {row.get('why')}")
    for n in r.get("editor_notes") or []:
        rows.append(f"Editor note: {n}")
    for n in r.get("blend_notes") or []:
        rows.append(f"Blend note: {n}")
    for left in r.get("left") or []:
        rows.append(f"Left: {left.get('sentence')}")
    return NL.join(rows) + NL


def raphael_all(out: Path, packets: dict[str, dict[str, Any]]) -> None:
    import contextvars
    from concurrent.futures import ThreadPoolExecutor

    (out / "12_raphael").mkdir(exist_ok=True)
    print(f"Raphael on {len(packets)} complete packet(s), each under its own $1.00 meter:")
    jobs = [(sid, p, int(sid[-2:])) for sid, p in packets.items()]
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(contextvars.copy_context().run, raphael_one, out, *j) for j in jobs]
        done = [f.result() for f in futures]
    save(out, "12_raphael_summary.json", done)
    print(f"Raphael spent ${sum(d['dollars'] for d in done):.4f} over {sum(d['calls'] for d in done)} calls")


if __name__ == "__main__":
    main()
