"""Coverage lab (2026-11-18): does shooting a small accident "the way TV dramas do" fix what five Omni Flash takes of
the phone-drop shot got wrong? Api Denna v2, episode 1, scene 3 (E01-S03), from the saved breakdown memory and packet of
lab/llm_reader/runs/e2e. NOTHING is written to the database and nothing in src/ is changed: the rule and the prompt
fixes are applied in this process only.

    python lab/coverage/run.py today              free: the SAVED plan (12_raphael/E01-S03.json) -> shot rows ->
                                                  video prompts twice: today's serializer, then with the fixes
    python lab/coverage/run.py coverage --yes     paid: Raphael re-plans the scene with the coverage rule (a lab
                                                  house rule, H-90), then video prompts with the fixes

What the arms change
    RULE   (coverage arm only) a house rule on Raphael's `objects` topic: an accident is an insert + a wide that opens
           with the object already where it fell (+ an optional still of the object); one action and one setup a
           clip; a timed exit and somewhere to look; a physical cause; no camera words in the action; the first frame
           never contradicted by the text.
    FIXES  (the serializer, code only) 1. a shot where something leaves a hand drops "Objects stay put unless ..." and
           "each hand keeps its own, neither is put down"; 2. a beat's camera note is never put in front of its
           action; 3. a static camera is said firmly (tripod, no push-in, no pan, no drift).

Each arm writes runs/<arm>/: plan.txt (the shot breakdown), prompts.md (every shot's summary and video prompt) and
checks.md (what the code finds in each prompt). Money: the coverage arm runs Raphael under its own meter
(RAPHAEL_SCENE_CAP_USD = SCENE_CAP_USD); the saved run cost $0.11 for this scene.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT / "src" / "libs"), str(ROOT / "src"), str(ROOT / "lab")]

SID = "E01-S03"
E2E = ROOT / "lab" / "llm_reader" / "runs" / "e2e"
SAVED = E2E / "12_raphael" / f"{SID}.json"
RULE_FILE = HERE / "h90_coverage.md"
SCENE_CAP_USD = 0.40
PROD = "prod-lab"
NL = "\n"

# the fixes' words
STAY_PUT = "Objects stay put unless someone deliberately moves them. "
NEITHER = "; each hand keeps its own, neither is put down."
TRIPOD = "The camera is mounted on a tripod and does not move at all: no push-in, no pan, no drift."
# what the checks look for in a prompt's action text
CAMERA_WORDS = re.compile(r"\b(unchanged|tableau|hold(?:s|ing)? (?:the )?(?:composition|frame)|frame holds|"
                          r"locked[- ]off|static|fixed (?:frame|wide)|wide fixed|camera)\b", re.IGNORECASE)
LETS_GO = re.compile(r"\b(drops?|dropped|slips?|slipped|falls?|fell|lets go|tips? out|knock(?:s|ed)? over|spills?)\b",
                     re.IGNORECASE)
NOT_NOTICING = re.compile(r"\b(without (?:looking|noticing|pausing)|does(?:n't| not) notice|unaware|never looks)\b",
                          re.IGNORECASE)
MOVES_ON = re.compile(r"\b(continues?|keeps? (?:walking|moving)|walks? (?:on|away)|maintains? (?:her|his) stride)\b",
                      re.IGNORECASE)


# ── the scene as the product would store it, from the saved breakdown memory ─────────────────────────────────────────


def world() -> dict[str, Any]:
    """Production, canon, scene and line rows for E01-S03, built by `contracts.breakdown.fill` (the product's own fill)
    from the saved memory: block i of the scene is script block i; a dialogue block's line id is its block id, as the
    saved Raphael run named it."""
    from contracts.breakdown import fill
    from contracts.breakdown.schema import Breakdown

    bd = Breakdown.model_validate_json((E2E / "03_memory.json").read_text(encoding="utf-8"))
    sc = next(s for s in bd.scenes if s.id == SID)
    packet = json.loads((E2E / "05_packets.json").read_text(encoding="utf-8"))[SID]
    canon = [{"id": f"id-{c['id']}", "production_id": PROD, "kind": c["kind"], "name": c["name"], "code": c["id"],
              "aliases": [], "current": {"version": 1, "card": c["card"], "wardrobe_anchor": "", "voice_pin": ""}}
             for c in fill.canon_cards(bd)]
    by_code = {c["code"]: c for c in canon}
    script, lines = [], []
    for i, (b, row) in enumerate(zip(sc.blocks, fill.scene_blocks(bd, sc), strict=True)):
        if row["kind"] == "dialogue":
            who = by_code.get(str(b.get("speaker") or ""))
            lines.append({"id": b["id"], "production_id": PROD, "scene_id": SID, "ord": len(lines),
                          "speaker": row["speaker"], "character_id": who["id"] if who else None,
                          "text": row["text"], "delivery": row["delivery"]})
            script.append({"kind": "dialogue", "line_id": b["id"]})
        else:
            script.append({"kind": row["kind"], "text": row["text"], "by": "person"})
        del i
    place = by_code.get(str(packet["C_place"]["id"]))
    scene = {"id": SID, "production_id": PROD, "episode_id": "ep-1", "number": sc.number, "heading": sc.heading,
             "title": packet["A_scene"]["title"], "location_id": place["id"] if place else None,
             "envelope_s": packet["H_length"]["stated_seconds"], "status": "draft", "note": "", "script_version": 1,
             "time_of_day": "DAY", "script": script, "staging": fill.staging(bd, sc, script_version=1),
             "episode": {"number": sc.episode, "title": ""}}
    production = {"id": PROD, "title": "Api Denna", "orientation": "horizontal", "settings": {}}
    return {"production": production, "canon": canon, "scene": scene, "lines": lines, "packet": packet}


# ── shot rows and video prompts ──────────────────────────────────────────────────────────────────────────────────────


def shot_rows(w: dict[str, Any], stored: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Raphael's result written as the product writes it (`raphael_write`): shot rows with their IR and design."""
    from hiru_ai.steps.raphael.raphael_write import step

    out = step.run({"scene": w["scene"], "lines": w["lines"], "stored": stored, "canon": w["canon"],
                    "production": w["production"], "job_id": "lab-coverage"})
    if "shots" not in out:
        raise SystemExit(f"raphael_write refused the result: {out}")
    return out["shots"], out["lines"]


def refit(got: list[dict[str, Any]], windows: list[tuple[int, int]]) -> list[dict[str, Any]]:
    """Fix 4: Raphael's beats on the shot's windows without loss or repeat: a beat belongs to the window its start
    falls in; a window's text is its beats' text in order."""
    from hiru_ai.steps.serialize.shots import _window

    out = []
    for n, (a, b) in enumerate(windows):
        last = n == len(windows) - 1
        mine = [g for g in got if (w := _window(g)) and (a <= w[0] < b or (last and w[0] >= b))]
        out.append({"time": f"{a}-{b}s", "camera": "",
                    **{k: " ".join(str(g.get(k) or "").strip() for g in mine if str(g.get(k) or "").strip())
                       for k in ("director_line", "action", "performance")}})
    return out


def after_event(scene: Any, shot: Any) -> bool:
    """An earlier stage-1 clip plays the same blocks and something leaves a hand in it: this clip is the 'after'
    half of a split accident (the insert shows the fall, this one opens with the thing already where it fell)."""
    if int(shot.row.get("stage") or 1) != 1:
        return False
    a, b = int(shot.row.get("block_start") or 0), int(shot.row.get("block_end") or 0)
    return any(o.number < shot.number and int(o.row.get("stage") or 1) == 1
               and int(o.row.get("block_start") or 0) <= a and int(o.row.get("block_end") or 0) == b
               and " lets go " in o.hands for o in scene.shots)


def prompt(w: dict[str, Any], shots: list[dict[str, Any]], lines: list[dict[str, Any]], number: int,
           fixed: bool, original: dict[str, list[dict[str, Any]]] | None = None) -> tuple[list[Any], Any]:
    """`hiru_ai.steps.serialize.step.run`, line for line, with a first frame attached; `fixed` applies the four
    fixes (`original`: each slate's beats as Raphael wrote them, for fix 4)."""
    from hiru_ai.steps.serialize.logic import Context, build_sections
    from hiru_ai.steps.serialize.model import production_input, scene_input

    prod = production_input(w["production"], w["canon"], None)
    scene = scene_input(w["scene"], shots, lines, w["canon"], prod)
    shot = next(s for s in scene.shots if s.number == number)
    previous = next((s for s in scene.shots if s.number == number - 1), None)
    ir = copy.deepcopy(dict(shot.row.get("ir") or {}))
    ctx = Context(aspect_ratio=prod.aspect_ratio, camera=shot.camera(scene), recommended=shot.recommended(scene),
                  previous_code=previous.code if previous else "", has_frame=True)
    if fixed and after_event(scene, shot):  # fix 5: the second clip of a split block opens AFTER the event
        from contracts.holding import earlier_text, ledger_for, shot_hands

        end = int(shot.row.get("block_end") or 0)
        shot.hands = shot_hands(ledger_for(scene.row, shot.row), block_start=end, block_end=end + 1,
                                seen=[c.name for c in shot.seen], framing=shot.framing,
                                earlier=earlier_text(scene.row, shot.row), video=False).sentence
    lets_go = "During the shot" in shot.hands and ("lets go" in shot.hands or "passes" in shot.hands)
    if fixed:
        if original:  # fix 4: every beat Raphael wrote lands once, in the window it starts in, in order
            ir["beats"] = refit(original.get(str(shot.row.get("slate")), []), shot.beats)
        for b in ir.get("beats") or []:  # fix 2: the camera is in the Camera section only
            if isinstance(b, dict):
                b["camera"] = ""
        if lets_go:  # fix 1: no line that forbids the shot's own action
            shot.hands = shot.hands.replace(NEITHER, ".")
    sections = build_sections(shot, ir, ctx)
    if fixed:
        for s in sections:
            for seg in s.segments:
                if seg.text is None:
                    continue
                if s.id == "constraints" and lets_go:
                    seg.text = seg.text.replace(STAY_PUT, "")
            if s.id == "camera" and ctx.camera.movement == "Static":  # fix 3
                s.segments[-1].text = (s.segments[-1].text or "").rstrip() + " " + TRIPOD
    return sections, shot


def text_of(section: Any) -> str:
    return "".join(seg.text if seg.text is not None else f"«{seg.sinhala}»" for seg in section.segments)


def checks(sections: list[Any], shot: Any) -> list[str]:
    """What the five takes taught, looked for in one prompt."""
    whole = {s.id: text_of(s) for s in sections}
    action = whole.get("action", "")
    every = " ".join(whole.values())
    out = []
    hands = str(getattr(shot, "hands", ""))
    if "During the shot" in hands and " lets go " in hands and (STAY_PUT.strip() in every
                                                              or NEITHER.strip("; ") in every):
        out.append("CONTRADICTION: the action lets go of a thing, a constraint says it stays put / is never put down")
    cam = sorted({m.group(0).lower() for m in CAMERA_WORDS.finditer(action)})
    if cam:
        out.append(f"CAMERA WORDS IN THE ACTION: {', '.join(cam)}")
    neg = sorted({m.group(0).lower() for m in NOT_NOTICING.finditer(action)})
    if neg:
        out.append(f"NOT-NOTICING WRITTEN AS A NEGATIVE (the model fills it with a pause): {', '.join(neg)}")
    if LETS_GO.search(action) and MOVES_ON.search(action):
        out.append("COMPOUND: the accident and the person moving on are asked of one clip")
    bodies = [b.split(":", 1)[-1].strip() for b in re.split(r"\n(?=\d[\d.]*-[\d.]+s:)", action)[1:]]
    if len(bodies) != len(set(bodies)):
        out.append("REPEATED BEAT: two windows carry the same text (the action happens twice)")
    if "Static" in str(getattr(shot, "row", {}).get("design", {}).get("recommended", {}).get("movement", "")) \
            and TRIPOD not in every:
        out.append("STATIC CAMERA SAID SOFTLY: no tripod / no push-in sentence")
    return out or ["clean"]


# ── reports ──────────────────────────────────────────────────────────────────────────────────────────────────────────


def write_reports(out: Path, w: dict[str, Any], result: dict[str, Any], runs: dict[str, bool], ids: dict[str, str],
                  status: str) -> None:
    from two_memories.live import clip_text

    out.mkdir(parents=True, exist_ok=True)
    (out / "plan.txt").write_text(clip_text(SID, result, w["packet"], ids, status), encoding="utf-8")
    shots, lines = shot_rows(w, result)
    original = {str(c.get("slate")): [b for b in (c.get("ir") or {}).get("beats") or [] if isinstance(b, dict)]
                for c in result.get("clips") or []}
    for label, fixed in runs.items():
        doc, found = [f"# {SID} video prompts: {label}", ""], [f"# {SID} checks: {label}", ""]
        for row in sorted(shots, key=lambda r: int(r["number"])):
            sections, shot = prompt(w, shots, lines, int(row["number"]), fixed, original)
            head = (f"## S{int(row['number']):02d} · {row.get('slate')} · {row.get('role')} · {row.get('framing')} · "
                    f"{row.get('duration_s')} s · stage {row.get('stage')}")
            summary = next((c.get("summary") for c in result.get("clips") or [] if c.get("slate") == row.get("slate")),
                           "")
            doc += [head, "", f"**Summary:** {summary}", "", "```text"]
            doc += [f"[{s.title}] {text_of(s).strip()}" for s in sections]
            doc += ["```", ""]
            found += [head, *[f"- {c}" for c in checks(sections, shot)], ""]
        name = "fixed" if fixed else "today"
        (out / f"prompts_{name}.md").write_text(NL.join(doc), encoding="utf-8")
        (out / f"checks_{name}.md").write_text(NL.join(found), encoding="utf-8")
    print(f"written: {out}")


def today() -> None:
    saved = json.loads(SAVED.read_text(encoding="utf-8"))
    write_reports(HERE / "runs" / "today", world(), saved["result"], {"today's serializer": False,
                                                                      "with the fixes": True},
                  saved["ids"], "saved run (llm_reader e2e step 6)")


def coverage() -> None:
    """Raphael on the packet path (as e2e step 6 ran it) with the lab rule added to every house-rule block."""
    os.environ["RAPHAEL_SCENE_CAP_USD"] = str(SCENE_CAP_USD)
    from cinematic.run import load_env

    from hiru_ai.core import house_rules
    from hiru_ai.core.settings import get_settings

    load_env()
    os.environ["RAPHAEL_SCENE_CAP_USD"] = str(SCENE_CAP_USD)
    get_settings.cache_clear()
    deployed = house_rules.load()
    extra = house_rules.parse(RULE_FILE)
    house_rules.rules = lambda: tuple(sorted((*deployed, extra), key=lambda r: r.id))  # this process only
    assert any(r.id == extra.id for r in house_rules.select(["objects"]))

    from two_memories.live import raphael_one

    w = world()
    out = HERE / "runs" / "coverage"
    (out / "12_raphael").mkdir(parents=True, exist_ok=True)
    s = raphael_one(out, SID, w["packet"], int(SID[-2:]))
    r = json.loads((out / "12_raphael" / f"{SID}.json").read_text(encoding="utf-8"))
    (out / "spend.txt").write_text(f"{s['status']}, {s['calls']} calls, {s['seconds']} s, ${s['dollars']:.4f}" + NL,
                                   encoding="utf-8")
    if not r.get("result"):
        raise SystemExit(f"Raphael did not finish: {s['status']}")
    write_reports(out, w, r["result"], {"with the fixes": True}, r["ids"], s["status"])


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    ap = argparse.ArgumentParser()
    ap.add_argument("arm", choices=["today", "coverage"])
    ap.add_argument("--yes", action="store_true", help="the person said yes to the paid arm")
    a = ap.parse_args()
    if a.arm == "coverage" and not a.yes:
        raise SystemExit(f"the coverage arm is paid (Raphael, cap ${SCENE_CAP_USD}): add --yes after the person's yes")
    today() if a.arm == "today" else coverage()


if __name__ == "__main__":
    main()
