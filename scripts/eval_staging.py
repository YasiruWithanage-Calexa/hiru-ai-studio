"""Staging quality gate (plan/2026-11-01 fix 12). Run after any change to the shot planner, the
intent agent, the DoP prompt, the staging rules or the frame prompt.

    python scripts/eval_staging.py                      # rules mode without a key, model mode with one
    python scripts/eval_staging.py --rules -v           # force rules mode, print every shot
    python scripts/eval_staging.py --update-thresholds  # accept the current numbers as the baseline

Runs tests/eval/staging_scenes.json IN MEMORY (no database): the shot list (script_split), then
the shot producer (intent → design → review), then who each frame would attach
(contracts.staging). Model mode calls OpenAI with the configured tiers.

Scores, per mode, against tests/eval/staging_thresholds.json (a drop fails):
  heard_kept_out  share of heard-only people who are never on screen and never attached to a frame
  seen_shown      share of people who must be seen that are on screen in at least one shot
  speaker_framed  share of on-camera lines whose shot has their speaker on screen
  size_variety    share of scenes with more than three shots that use at least two sizes
  info_carried    share of "it is her father" style information blocks that ride with a line that says
                  it, sit in an INSERT, or come right before the voice shot (plan 2026-11-01b)
  button_present  share of scenes whose reading asks for a last image that end on it (plan 2026-11-01d)
  breath_band     share of scenes whose reading asks for breath that hold 15-30% of the scene as breath
  inner_as_behaviour  share of STORY NOTEs (a thought nobody can film) the reading turned into behaviour (model mode)
and counts that must stay at or under the `ceilings` of the thresholds file, in every mode:
  crowded_shots        shots that hold more than they can show (or that the kernel had to cut)
  voice_before_source  a heard voice that starts before the picture shows its source ring
  inner_filmed         a thought ("he had no idea ...") that reaches a shot's intent
  turn_unseen          priority-1 reactions played while the face that reacts is not in frame (plan 2026-11-01d)
  teleport             people who change spot with nothing to show the way, after the implied steps are added
  line_crossed         cuts that swap two people's sides of the frame, and shot / reverse shots that look one way

A case may carry "staging": the map a model would answer (each mark names its block by a piece of its text), so the
steps the staging adds and the checks on it run offline too. Without a model, a case with no "staging" has no map.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "src", ROOT / "src" / "libs", ROOT / "src" / "services" / "shot_producer",
          ROOT / "src" / "services" / "script_split"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from script_split.engine import critic  # noqa: E402
from script_split.engine import reading as reading_engine  # noqa: E402
from script_split.engine.pipeline import plan_scene, prepare, stage  # noqa: E402
from shot_producer.engine import pipeline  # noqa: E402

from contracts import (  # noqa: E402
    bridges,
    sceneplan,
    stagemap,
)
from contracts import reading as scene_reading  # noqa: E402
from contracts.beats import sentences  # noqa: E402
from contracts.bridges import _RING  # noqa: E402
from contracts.jobs import DispatchPayload, JobKind  # noqa: E402
from contracts.producer import shot_canon_ids, shot_items  # noqa: E402
from contracts.shotplan import shot_clock  # noqa: E402
from contracts.staging import _keys, shot_cast, staging  # noqa: E402
from contracts.timing import BREATH_BAND  # noqa: E402

CASES = ROOT / "tests" / "eval" / "staging_scenes.json"
THRESHOLDS = ROOT / "tests" / "eval" / "staging_thresholds.json"
PID = UUID("e0000000-0000-4000-8000-00000000e002")
Row = dict[str, Any]


def _id(case: str, code: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"hiru-staging-eval/{case}/{code}"))


class Store:
    """shot_producer's store, in memory, for one scene."""

    def __init__(self, scene: Row, lines: list[Row], shots: list[Row], canon: list[Row]) -> None:
        self.scene_row, self.line_rows, self.canon_rows = scene, lines, canon
        self.shot_rows = {s["id"]: s for s in shots}

    def production(self, production_id: UUID) -> Row:
        return {"id": str(production_id), "title": "Staging eval", "orientation": "horizontal", "settings": {}}

    def scenes(self, production_id: UUID, scene_ids: list[str]) -> list[Row]:
        return [self.scene_row]

    def neighbours(self, scene: Row) -> tuple[None, None]:
        return None, None

    def shots(self, scene_id: str) -> list[Row]:
        return sorted((dict(s) for s in self.shot_rows.values()), key=lambda s: s["number"])

    def shot_scenes(self, production_id: UUID, shot_ids: list[str]) -> list[str]:
        return [self.scene_row["id"]]

    def lines(self, scene_id: str) -> list[Row]:
        return self.line_rows

    def canon(self, production_id: UUID) -> list[Row]:
        return self.canon_rows

    def lead_persona(self, production_id: UUID) -> None:
        return None

    def accepted_frames(self, shot_ids: list[str]) -> dict[str, Row]:
        return {}

    def last_prompt_version(self, shot_id: str) -> int:
        return 0

    def techniques(self, query: str, embedding: list[float] | None, k: int = 4) -> list[Row]:
        return []

    def save_design(self, shot_id: str, ir: Row, design: Row) -> None:
        self.shot_rows[shot_id].update(ir=ir, design=design)

    def save_intent(self, shot_id: str, intent: Row) -> None:
        self.shot_rows[shot_id]["intent"] = intent

    def save_coverage(self, scene_id: str, coverage: Row) -> None:
        self.scene_row["coverage"] = coverage

    def add_prompt(self, row: Row) -> None:
        pass

    def audit(self, row: Row) -> None:
        pass


class Jobs:
    def check(self, payload: DispatchPayload) -> None:
        return None

    def set(self, *a: Any, **k: Any) -> None:
        pass

    def event(self, *a: Any, **k: Any) -> None:
        pass

    def finish(self, *a: Any, **k: Any) -> None:
        pass


class NoModel:
    enabled = False

    def json(self, **kw: Any) -> Row:
        raise RuntimeError("no model")

    def embed(self, texts: list[str], *, phase: str) -> list[list[float]]:
        raise RuntimeError("no model")


class FixtureStaging:
    """Answers the staging call with the case's own map, as a model would, and nothing else."""

    enabled = True

    def __init__(self, case: Row, items: list[Any]) -> None:
        self.case, self.items = case, items

    def json(self, *, schema_name: str, **kw: Any) -> Row:
        if schema_name != "scene_staging":
            raise RuntimeError("no model")
        raw = self.case["staging"]
        marks = []
        for m in raw["marks"]:
            at = next((i.index for i in self.items if m["at"].lower() in i.text.lower()), None)
            if at is not None:
                rest = {k: v for k, v in m.items() if k != "at"}
                marks.append({"facing": "", "frame_side": "", "holding": "", **rest, "block": at})
        return {"zones": raw["zones"], "marks": marks}


def build(case: Row) -> tuple[Row, list[Row], list[Row]]:
    """The case as stored rows: canon, the scene and its lines (no shots yet)."""
    cid = case["id"]
    canon = [{"id": _id(cid, code), "kind": "character", "code": code, "name": name, "aliases": [], "locked": False,
              "current": {"version": 1, "card": {"gender": gender}, "wardrobe_anchor": "", "voice_pin": ""}}
             for code, name, gender in case["cast"]]
    canon.append({"id": _id(cid, "L01"), "kind": "location", "code": "L01", "name": case["heading"], "aliases": [],
                  "locked": False, "current": {"version": 1, "card": {}, "wardrobe_anchor": "", "voice_pin": ""}})
    names = {code: name for code, name, _ in case["cast"]}
    scene_id = _id(cid, "scene")
    blocks, lines = [], []
    for kind, text, who, delivery in case["script"]:
        if kind == "dialogue":
            lid = str(uuid4())
            lines.append({"id": lid, "production_id": str(PID), "scene_id": scene_id, "ord": len(lines),
                          "speaker": names[who], "text": text, "delivery": delivery,
                          "character_id": _id(cid, who)})
            blocks.append({"kind": "dialogue", "text": "", "line_id": lid})
        elif kind == "action":  # one visible event per block, as a new build writes them
            blocks += [{"kind": "action", "text": sentence, "line_id": None} for sentence in sentences(text)]
        else:
            blocks.append({"kind": kind, "text": text, "line_id": None})
    scene = {"id": scene_id, "production_id": str(PID), "episode_id": _id(cid, "episode"), "number": 1,
             "heading": case["heading"], "title": "", "note": "", "time_of_day": "", "envelope_s": 30,
             "status": "approved", "script_version": 1, "script": blocks, "location_id": _id(cid, "L01"),
             "episode": {"number": 1, "title": "", "synopsis": ""}}
    return scene, lines, canon


def picture_counts(result: Any, items: list[Any], intents: list[str]) -> Row:
    """What the kernel and the intents say about pictures, for one scene (plan 2026-11-01b)."""
    crowded = len(result.crowded) + sum(1 for i in result.issues if i.code == "split")
    # a heard voice must start after the picture that shows its source (the ring) has played
    ends: dict[int, float] = {}
    for shot in result.shots:
        for slot in shot_clock(items[shot.start:shot.end])[0]:
            ends[slot.index] = shot.start_s + slot.end_s
    starts = {fl.line_id: fl.start_s for fl in result.lines}
    early = 0
    for line in (i for i in items if i.is_line and i.delivery and "phone" in i.delivery.lower()):
        rings = [i for i in items if i.index < line.index and i.kind == "action" and _RING.search(i.text)]
        if rings and line.line_id in starts and starts[line.line_id] < ends.get(rings[-1].index, 0.0) - 1e-6:
            early += 1
    film = " ".join(intents)
    filmed = sum(1 for i in items if i.kind == "action" and i.screen == "inner" and i.text.strip()
                 and len(_keys(i.text) & _keys(film)) / max(1, len(_keys(i.text))) >= 0.5)
    carried = total = 0
    for i in items:
        if i.kind != "action" or i.screen != "info":
            continue
        total += 1
        shot = next(s for s in result.shots if s.start <= i.index < s.end)
        following = next((s for s in result.shots if s.start == shot.end), None)
        nxt_line = following is not None and any(items[k].is_line for k in range(following.start, following.end))
        carried += bool(shot.line_ids) or shot.framing == "INSERT" or nxt_line
    return {"crowded": crowded, "voice_early": early, "inner_filmed": filmed, "info_total": total,
            "info_carried": carried}


def feeling_counts(result: Any, items: list[Any], reading: scene_reading.SceneReading,
                   staging: stagemap.SceneStaging | None, cast: list[str]) -> Row:
    """What the reading and the map say about feeling and places, for one scene (plan 2026-11-01d)."""
    wants_button = any(b.kind == "button" and not b.off for b in reading.breath)
    wants_breath = any(not b.off for b in reading.breath) and result.total_s > 0
    low, high = BREATH_BAND
    notes = scene_reading.story_notes(items)
    behaved = sum(1 for t in reading.subtext if not t.narration_only and t.block in notes)
    share = result.breath_s / result.total_s if result.total_s else 0.0
    return {"turn_unseen": critic.turn_unseen(result, reading, items, staging, cast),
            "teleport": len(stagemap.teleports(staging, items, cast)),
            "line_crossed": len(stagemap.line_crossed(staging, items, result, cast))
            + len(stagemap.eyeline(staging, items, result)),
            "button_total": int(wants_button),
            "button_ok": int(wants_button and not critic.no_button(result, reading, items)),
            "breath_total": int(wants_breath), "breath_ok": int(wants_breath and low <= share <= high),
            "notes_total": len(notes), "notes_behaved": behaved,
            "moves_added": sum(1 for i in items if bridges.is_move_block(i.bridge))}


def run_case(case: Row, llm: Any) -> Row:
    scene, lines, canon = build(case)
    speaker_names = {_id(case["id"], code): name for code, name, _ in case["cast"]}
    # The split reads the script as pictures and adds the steps it implies, as the real build does.
    names = [name for _, name, _ in case["cast"]]
    scene["script"], items = prepare(scene, lines, llm, names)
    ask = None
    if llm.enabled:
        def ask(system: str, user: str) -> Row:
            return llm.json(tier="high", phase="eval.reading", system=system, user=user, schema_name="scene_reading",
                            schema=reading_engine.READING_SCHEMA)
    reading, _ = reading_engine.reading_for(scene, items, ask, names, speaker_names=speaker_names)
    staging_llm = llm if llm.enabled else (FixtureStaging(case, items) if case.get("staging") else llm)
    scene["script"], items, reading, stage_map = stage(scene, lines, scene["script"], items, reading, staging_llm,
                                                     speaker_names)
    timed = scene_reading.apply(items, scene_reading.clear_envelope(reading))
    result, planner, _ = plan_scene(timed, heading=scene["heading"], envelope_s=scene["envelope_s"], fixed=None,
                                    llm=llm, speaker_names=speaker_names, reading=reading, staging=stage_map)
    scene["reading"] = scene_reading.mark_off(reading, timed, result.breath_dropped).model_dump(mode="json")
    if stage_map is not None:
        scene["staging"] = stage_map.model_dump(mode="json")
    shots, line_rows, _ = sceneplan.rows_after_fit(scene, [{"start": s.start} for s in result.shots], result, lines)
    for s in shots:
        s.update(ir={}, design={}, camera_overrides={}, intent={}, person_edits={})
    store = Store(scene, line_rows, shots, canon)
    payload = DispatchPayload(job_id=uuid4(), kind=JobKind.SHOT_PRODUCE, actor_user_id=uuid4(), production_id=PID,
                              pipeline=[JobKind.SHOT_PRODUCE], state={"scene_ids": [scene["id"]]})
    pipeline.run(payload, store, Jobs(), llm)  # type: ignore[arg-type]

    characters = [c for c in canon if c["kind"] == "character"]
    out_shots = []
    for row in store.shots(scene["id"]):
        own = shot_items(items, int(row["block_start"]), int(row["block_end"]))
        ids = shot_cast(own, characters, row)
        staged = staging(own, characters, row, cast_ids=ids)
        refs = [c for c in shot_canon_ids(scene, staged.on_screen, None) if c in {x["id"] for x in characters}]
        out_shots.append({"code": f"S{row['number']:02d}", "framing": row["framing"], "sound": row["sound_mode"],
                          "on_screen": staged.on_screen, "refs": refs,
                          "speakers": [i.speaker_id for i in own if i.is_line and i.speaker_id],
                          "on_camera_speakers": [i.speaker_id for i in own if i.is_line and i.speaker_id
                                                 and row["sound_mode"] in ("dialogue", "sung")],
                          "intent": (row.get("intent") or {}).get("what_we_see", "")})
    counts = picture_counts(result, items, [s["intent"] for s in out_shots])
    feeling = feeling_counts(result, timed, reading, stage_map, [name for _, name, _ in case["cast"]])
    return {"id": case["id"], "planner": planner, "shots": out_shots, "pictures": counts, "feeling": feeling,
            "heard": [_id(case["id"], c) for c in case["heard"]], "seen": [_id(case["id"], c) for c in case["seen"]],
            "names": {_id(case["id"], code): name for code, name, _ in case["cast"]}}


def score(results: list[Row]) -> dict[str, float]:
    heard_total = heard_ok = seen_total = seen_ok = lines_total = lines_ok = big = varied = 0
    for r in results:
        for h in r["heard"]:
            heard_total += 1
            heard_ok += all(h not in s["on_screen"] and h not in s["refs"] for s in r["shots"])
        for v in r["seen"]:
            seen_total += 1
            seen_ok += any(v in s["on_screen"] for s in r["shots"])
        for s in r["shots"]:
            for sp in s["on_camera_speakers"]:
                if sp in r["heard"]:
                    continue
                lines_total += 1
                lines_ok += sp in s["on_screen"]
        if len(r["shots"]) > 3:
            big += 1
            varied += len({s["framing"] for s in r["shots"]}) >= 2
    def ratio(a: int, b: int) -> float:
        return round(a / b, 3) if b else 1.0

    pic = [r["pictures"] for r in results]
    feel = [r["feeling"] for r in results]
    return {"heard_kept_out": ratio(heard_ok, heard_total), "seen_shown": ratio(seen_ok, seen_total),
            "speaker_framed": ratio(lines_ok, lines_total), "size_variety": ratio(varied, big),
            "info_carried": ratio(sum(p["info_carried"] for p in pic), sum(p["info_total"] for p in pic)),
            "crowded_shots": sum(p["crowded"] for p in pic),
            "voice_before_source": sum(p["voice_early"] for p in pic),
            "inner_filmed": sum(p["inner_filmed"] for p in pic),
            "button_present": ratio(sum(f["button_ok"] for f in feel), sum(f["button_total"] for f in feel)),
            "breath_band": ratio(sum(f["breath_ok"] for f in feel), sum(f["breath_total"] for f in feel)),
            "inner_as_behaviour": ratio(sum(f["notes_behaved"] for f in feel), sum(f["notes_total"] for f in feel)),
            "turn_unseen": sum(f["turn_unseen"] for f in feel), "teleport": sum(f["teleport"] for f in feel),
            "line_crossed": sum(f["line_crossed"] for f in feel)}


def evaluate(llm: Any) -> tuple[dict[str, float], list[Row]]:
    cases = json.loads(CASES.read_text(encoding="utf-8"))["cases"]
    results = [run_case(c, llm) for c in cases]
    return score(results), results


def failures(scores: dict[str, float], mode: str) -> list[str]:
    thresholds = json.loads(THRESHOLDS.read_text(encoding="utf-8"))
    floor = thresholds.get(mode) or {}
    out = [f"{k}: {scores.get(k, 0.0)} < {v}" for k, v in floor.items() if v is not None and scores.get(k, 0.0) < v]
    ceilings = thresholds.get("ceilings") or {}  # counts: higher is worse
    return out + [f"{k}: {scores.get(k, 0)} > {v}" for k, v in ceilings.items() if scores.get(k, 0) > v]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rules", action="store_true", help="never call a model")
    ap.add_argument("--update-thresholds", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    llm: Any = NoModel()
    if not args.rules:
        from _common import load_env

        load_env()
        from shot_producer.runtime.config import get_config
        from shot_producer.runtime.llm import LLM

        config = get_config()
        if config.llm_enabled:
            llm = LLM(config)
    mode = "model" if getattr(llm, "enabled", False) else "rules"
    scores, results = evaluate(llm)
    for r in results:
        bad = [r["names"][h] for h in r["heard"] if any(h in s["on_screen"] or h in s["refs"] for s in r["shots"])]
        print(f"{'FAIL' if bad else ' ok '} {r['id']:<22} {len(r['shots'])} shots ({r['planner']})"
              + (f"  heard-only person on screen: {', '.join(bad)}" if bad else ""))
        if args.verbose:
            for s in r["shots"]:
                seen = ", ".join(r["names"].get(c, c) for c in s["on_screen"]) or "nobody"
                print(f"       {s['code']} {s['framing']:<6} {s['sound']:<10} seen: {seen}  | {s['intent'][:90]}")
    print(f"\n{mode} mode: " + ", ".join(f"{k} {v}" for k, v in scores.items()))
    if args.update_thresholds:
        data = json.loads(THRESHOLDS.read_text(encoding="utf-8")) if THRESHOLDS.exists() else {}
        ceilings = (data.get("ceilings") or {}).keys()
        data[mode] = {k: v for k, v in scores.items() if k not in ceilings}  # counts are ceilings, not floors
        THRESHOLDS.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        print(f"thresholds for {mode} mode updated")
        return
    problems = failures(scores, mode)
    if problems:
        sys.exit("below threshold: " + "; ".join(problems))


if __name__ == "__main__":
    main()
