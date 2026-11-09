"""The scene state ledger in Raphael (plan/2026-11-09 phases 3-8). No model is called: the stager and Raphael are
scripted, everything else is the product's code.

    phase 3   the system keeps or makes the map (one stager call at most), saves it with the shots, plans without it
              when the stager fails, and the input hash moves with the map
    phase 4   the listing says the state at the start and what changes at each block, capped; no map, no change
    phase 5   each clip's opening and closing state; `read_bin` shows them for one moment
    phase 6   the state checks, report only: a mutant for every key, on the roadside and the body scene
    phase 7   the shot's intent (story, feeling, opens, ends), the Veo prompt and the first frame, Raphael's only
    phase 8   production memory on both agents; the API's states and state faults
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from langchain_core.messages import AIMessage

from contracts import stagemap as sm
from contracts.raphael import checks, pack, state
from contracts.raphael.bin import Bin
from contracts.raphael.scene import Brief, SceneS, listing, scene_dump
from contracts.raphael.tools import Stage1Session, Stage2Session
from contracts.raphael.wire import Clip
from contracts.staging import ShotIntent
from hiru_ai.core import llm, parts
from hiru_ai.core.registry import PACKAGE_ROOT
from hiru_ai.core.testing import RoutedChatModel
from hiru_ai.systems.raphael.raphael_shot_planner import graph
from tests.raphael import gold, world
from tests.raphael.test_system import planner
from tests.raphael.world import World

FIXTURES = Path(__file__).parent / "fixtures"
BODY = json.loads((FIXTURES / "staging_body.json").read_text(encoding="utf-8"))


def body_scene() -> SceneS:
    scene = SceneS.model_validate(BODY["scene"])
    staging = sm.validate(BODY["staging"], scene.items(), scene.cast, version=1, by="person")
    return state.attach(scene, staging, scene.items(), BODY["codes"])


def clip(cid: str, blocks: list[int], *subjects: dict[str, Any], beats: list[str] = (), moment: int = 1,
         **extra: Any) -> Clip:
    """A must clip with a design: its subjects ({id, action, position}) and its beats' actions."""
    base = gold.stage1().by_id("c05")
    assert base is not None
    ir = dict(base.ir or {})
    ir["subjects"] = [{"description": "as written", **s} for s in subjects]
    ir["beats"] = [{"time": "0-1s", "camera": "", "director_line": "", "action": b, "performance": ""} for b in beats]
    ir["first_frame"] = {"composition": "", "subjects": [], "setting": "", "lighting": ""}
    return base.model_copy(update={"id": cid, "blocks": blocks, "lines": [], "speaks": False, "moment": moment,
                                   "ir": ir, **extra})


def bin_of(*clips: Clip) -> Bin:
    work = Bin(scene="1")
    work.edit = gold.edit_plan()
    work.clips = list(clips)
    return work


def keys(scene: SceneS, *clips: Clip) -> set[str]:
    return {f.key for f in checks.state(scene, bin_of(*clips))}


# ── phase 3: the system ──────────────────────────────────────────────────────────────────────────


def stager_reply() -> dict[str, Any]:
    raw = gold.staging_raw()
    return {"zones": raw["zones"], "marks": raw["marks"], "props": raw["props"]}


def routed(*turns: list[AIMessage], stager: list[Any] | None = None) -> RoutedChatModel:
    """Raphael's scripted turns on one route, the stager's replies on another (told apart by its system prompt)."""
    queue = [t for part in turns for t in part]

    def choose(messages: list[Any]) -> str:
        return "stager" if "Blocking Director" in str(messages[0].content) else "all"

    return RoutedChatModel(routes={"all": queue, "stager": list(stager or [])}, choose=choose)


def run(w: World, model: RoutedChatModel, **state_: Any) -> dict[str, Any]:
    with llm.use_models(model):
        return graph.run(w.payload(replan=True, **state_), w.ctx())


def stager_calls(model: RoutedChatModel) -> int:
    return sum(1 for m in model.calls if "Blocking Director" in str(m[0].content))


def test_a_persons_map_is_kept_and_costs_no_call():
    w = World()
    model = routed(world.stage1_turns(), world.stage2_turns())
    assert run(w, model)["scenes"] == 1
    assert stager_calls(model) == 0 and w.row()["staging"]["by"] == "person"


def test_a_current_model_map_costs_no_call_and_a_stale_one_costs_one_and_is_saved_with_the_shots():
    w = World(staging="model")
    model = routed(world.stage1_turns(), world.stage2_turns())
    run(w, model)
    assert stager_calls(model) == 0
    w2 = World(staging="model")
    w2.row()["staging"]["for_version"] = 0  # written for another script version: stale
    model = routed(world.stage1_turns(), world.stage2_turns(), stager=[stager_reply()])
    assert run(w2, model)["scenes"] == 1
    assert stager_calls(model) == 1
    saved = sm.SceneStaging.of(w2.row())
    assert saved is not None and saved.by == "model" and saved.for_version == 1 and saved.marks
    assert len(w2.shots()) == 21


def test_a_scene_with_no_map_asks_the_stager_once_and_saves_what_it_made():
    w = World(staging="")
    model = routed(world.stage1_turns(), world.stage2_turns(), stager=[stager_reply()])
    run(w, model)
    assert stager_calls(model) == 1
    assert sm.SceneStaging.of(w.row()) is not None
    intents = [ShotIntent.of(s) for s in w.shots()]
    assert any(i is not None and i.opens for i in intents)


def test_a_failing_stager_is_not_a_failing_scene():
    w = World(staging="")
    model = routed(world.stage1_turns(), world.stage2_turns(), stager=[RuntimeError("the stager is down")])
    result = run(w, model)
    assert result["scenes"] == 1 and result["failed"] == 0 and len(w.shots()) == 21
    assert "staging" not in w.row() or not w.row()["staging"]
    said = [e for e in w.jobs.events if "No state map for this scene; planned without it" in json.dumps(e)]
    assert said
    assert all(not (ShotIntent.of(s) or ShotIntent()).opens for s in w.shots())


def test_the_input_hash_moves_with_the_map_and_a_scene_with_no_map_hashes_as_before():
    w = World()
    p = planner(w)
    bare = p.input_hash()
    p.scene = state.attach(p.scene, gold.staging(), gold.scene().items(), gold.CODES)
    with_map = p.input_hash()
    assert with_map != bare
    moved = gold.staging().model_copy(update={"zones": ["stall counter", "road"]})
    p.scene = state.attach(planner(w).scene, moved, gold.scene().items(), gold.CODES)
    assert p.input_hash() not in (bare, with_map)
    # a scene with no map dumps exactly the keys it had before the ledger existed
    dump = scene_dump(gold.scene())
    assert set(dump) == {"blocks", "cast", "others", "place", "envelope_s"}
    assert all("now" not in b for b in dump["blocks"])


def test_an_unchanged_scene_with_a_map_still_makes_no_call():
    w = World()
    run(w, routed(world.stage1_turns(), world.stage2_turns()))
    model = routed()
    with llm.use_models(model):
        result = graph.run(w.payload(), w.ctx())
    assert result["scenes"] == 0 and model.calls == []


# ── phase 4: the listing ─────────────────────────────────────────────────────────────────────────


def test_the_listing_says_what_changes_at_each_block():
    text = listing(gold.ledger_scene())
    rows = {line.split(" ", 1)[0]: line for line in text.splitlines()}
    assert rows["b5"].endswith(
        "| now: Anudi: walking, at the pavement, umbrella in right hand, carrying the handbag; phone: on the ground "
        "by the three-wheeler"
    )
    assert rows["b6"].endswith("| now: Kasun: running, at the pavement, phone in right hand")
    assert rows["b9"].endswith(
        "| now: Kasun: hands empty; Anudi: phone in left hand, umbrella in right hand, carrying the handbag"
    )
    assert "| now:" not in rows["b10"] and "| now:" not in rows["b22"]


def test_the_listing_says_the_state_at_the_start_under_present():
    lines = listing(body_scene()).splitlines()
    assert lines[0].startswith("Present: ")
    assert lines[1] == (
        "At the start: Aruni: walking, at the paddy path, carrying the medical bag; Nimal: lying, at the canal gate, "
        "small metal key in right hand, dead"
    )


def test_the_addition_is_capped_and_the_props_in_no_hand_go_first(monkeypatch: pytest.MonkeyPatch):
    full = gold.ledger_scene()
    added = len(full.opening_state) + sum(len(b.now) for b in full.blocks)
    assert 0 < added <= state.STATE_LISTING_CHARS
    monkeypatch.setattr(state, "STATE_LISTING_CHARS", 300)
    capped = state.attach(gold.scene(), gold.staging(), gold.scene().items(), gold.CODES)
    nows = [b.now for b in capped.blocks if b.now]
    assert len(capped.opening_state) + sum(len(n) for n in nows) <= 300
    assert nows and not any("on the ground" in n or "tea flask" in n for n in nows)


def test_no_map_leaves_the_scene_and_the_opening_byte_for_byte():
    scene = gold.scene()
    for staging in (None, sm.SceneStaging()):
        same = state.attach(scene, staging, scene.items(), gold.CODES)
        assert same is scene
    production = {"style_note": "", "rules": [], "people": []}
    brief = Brief(scene=scene, guide_s=60)
    assert pack.opening_stage1(production, {}, brief) == pack.opening_stage1(
        production, {}, Brief(scene=state.attach(scene, None, scene.items()), guide_s=60)
    )


def test_both_prompts_carry_the_state_line():
    for agent in ("raphael_planner", "raphael_cinematic"):
        text = (PACKAGE_ROOT / "agents" / "raphael" / agent / "prompts" / "system.md").read_text(encoding="utf-8")
        assert "- STATE (plan/2026-11-09)." in text and "which hand takes it" in text


# ── phase 5: a clip's opening and closing state ──────────────────────────────────────────────────


def test_each_clip_opens_and_ends_in_the_ledgers_state():
    scene, work = gold.ledger_scene(), gold.stage1()
    states = state.clip_states(scene, work)
    opens, ends = states["c05"]
    assert opens.prop_text("phone") == "phone: Kasun's right hand"
    assert ends.prop_text("phone") == "phone: Anudi's left hand"
    assert state.clip_states(gold.scene(), work) == {}


def test_a_cinematic_clip_with_no_block_plays_its_anchors_blocks():
    final = gold.final()
    blockless = next(c for c in final.extras() if not c.blocks and c.anchor)
    anchor = final.by_id(blockless.anchor[0])
    assert anchor is not None
    assert state.clip_blocks(blockless, final) == sorted(set(anchor.blocks))
    assert state.clip_blocks(blockless, final.clips) == sorted(set(anchor.blocks))
    assert state.clip_blocks(blockless.model_copy(update={"anchor": []}), final) == []


def test_read_bin_shows_opens_and_ends_for_one_moment_only():
    scene = gold.ledger_scene()
    run1 = Stage1Session(Brief(scene, 60), gold.stage1())
    one = run1.tool_read_bin({"moment": 5})
    assert "opens: " in one and "ends: " in one and "Anudi: standing, at the pavement, phone in left hand" in one
    assert "opens:" not in run1.tool_read_bin({})
    assert "opens:" not in Stage1Session(Brief(gold.scene(), 60), gold.stage1()).tool_read_bin({"moment": 5})
    run2 = Stage2Session(Brief(scene, 60), gold.final())
    assert "opens: " in run2.tool_read_bin({"moment": 5})


# ── phase 6: the checks, report only ─────────────────────────────────────────────────────────────

KASUN = "C01"
ANUDI = "C02"
ARUNI = "C01"
NIMAL = "C02"


def test_no_map_no_check():
    assert checks.state(gold.scene(), gold.stage1()) == []


def test_a_thing_in_a_hand_the_ledger_gives_to_someone_else():
    scene = gold.ledger_scene()
    wrong = clip("c07", [12, 13], {"id": KASUN, "action": "smiles", "position": "holding the phone up"})
    assert "state:hand:c07:phone:Kasun" in keys(scene, wrong)
    side = clip("c04", [6, 7], {"id": KASUN, "action": "runs", "position": "phone in left hand"})
    assert "state:hand:c04:phone:Kasun:side" in keys(scene, side)
    right = clip("c04", [6, 7], {"id": KASUN, "action": "runs", "position": "phone in right hand"})
    assert keys(scene, right) == set()


def test_a_handover_names_both_people_and_the_taking_hand():
    scene = gold.ledger_scene()
    vague = clip("c05", [8, 9], {"id": ANUDI, "action": "accepts the phone", "position": "facing C01"})
    assert "state:handover:c05:phone:9" in keys(scene, vague)
    shown = clip("c05", [8, 9], {"id": ANUDI, "action": "takes the phone from C01's hand in her left hand",
                                 "position": "facing C01, umbrella in right hand"})
    assert not any(k.startswith("state:handover") for k in keys(scene, shown))


def test_a_lying_dead_man_neither_stands_nor_breathes():
    scene = body_scene()
    stands = clip("c01", [0], {"id": NIMAL, "action": "stands at the gate", "position": "centre"})
    assert "state:posture:c01:Nimal" in keys(scene, stands)
    breathes = clip("c01", [0], {"id": NIMAL, "action": "lies still; his chest rises", "position": "at the gate"})
    assert "state:condition:c01:Nimal" in keys(scene, breathes)
    still = clip("c01", [0], {"id": NIMAL, "action": "lies still, not breathing, the key in his right hand",
                              "position": "at the canal gate"})
    assert keys(scene, still) == set()


def test_a_dead_person_who_speaks_is_a_fault():
    scene = body_scene().model_copy()
    blocks = [b.model_copy(update={"speaker": "Nimal"}) if b.line_id else b for b in scene.blocks]
    scene = scene.model_copy(update={"blocks": blocks})
    talks = clip("c02", [1], {"id": NIMAL, "action": "lies still", "position": "at the canal gate"},
                 lines=["L1"], speaks=True)
    assert "state:condition:c02:Nimal" in keys(scene, talks)


def test_a_person_the_ledger_has_off():
    scene = gold.ledger_scene()
    gone = clip("c14", [21, 22], {"id": ANUDI, "action": "walks", "position": "on the pavement"})
    assert "state:off:c14:Anudi" in keys(scene, gone)


def test_a_position_at_another_spot():
    scene = gold.ledger_scene()
    stall = clip("c07", [12, 13], {"id": KASUN, "action": "smiles", "position": "by the counter"})
    assert "state:zone:c07:Kasun" in keys(scene, stall)
    pavement = clip("c07", [12, 13], {"id": KASUN, "action": "smiles", "position": "on the pavement, near the stall"})
    assert "state:zone:c07:Kasun" not in keys(scene, pavement)


def test_a_carried_prop_no_clip_places_is_reported_once():
    scene = gold.ledger_scene()
    a = clip("c05", [8, 9], {"id": ANUDI, "action": "turns", "position": "umbrella in right hand"})
    b = clip("c06", [10, 11], {"id": ANUDI, "action": "asks", "position": "umbrella in right hand, phone in left"})
    found = [k for k in keys(scene, a, b) if k.startswith("state:unplaced")]
    assert found == ["state:unplaced:handbag"]
    placed = clip(
        "c06", [10, 11], {"id": ANUDI, "action": "asks", "position": "handbag on her shoulder, phone in left"}
    )
    assert not any(k.startswith("state:unplaced") for k in keys(scene, a, placed))
    body = body_scene()
    kneels = clip("c02", [1], {"id": ARUNI, "action": "kneels by the gate", "position": "at the canal gate"})
    assert "state:unplaced:bag" in keys(body, kneels)


def test_every_state_fault_is_a_report_that_never_blocks_finish():
    scene = body_scene()
    bad = clip("c01", [0], {"id": NIMAL, "action": "stands up, breathing hard", "position": "at the paddy path"})
    found = checks.state(scene, bin_of(bad))
    assert found and all(f.fix == "report" and f.code == "state" for f in found)
    assert not checks.blocking(found)


# ── phase 7: into the shot, the Veo prompt and the first frame ──────────────────────────────────


def written(w: World) -> dict[str, Any]:
    stored = world.stored_stage1(w)
    return parts.step("raphael_write", "step").run({
        "scene": w.row(), "lines": w.line_rows, "stored": stored.data(), "canon": w.scenes.canon_rows,
        "production": w.scenes.production_row if hasattr(w.scenes, "production_row") else {"id": w.production},
    })


def test_the_shot_carries_its_story_feeling_and_the_state_it_opens_and_ends_in():
    w = World()
    out = written(w)
    shots = {s["slate"]: s for s in out["shots"]}
    stored = world.stored_stage1(w)
    c05 = next(c for c in stored.clips if c.id == "c05")
    moment = next(m for m in stored.edit.moments if m.n == c05.moment)  # type: ignore[union-attr]
    intent = ShotIntent.model_validate(shots[c05.slate]["intent"])
    assert intent.story == moment.what[:300] and intent.emotional_beat == moment.feeling[:200]
    assert "Kasun: running, at the pavement, phone in right hand" in intent.opens
    assert "phone in left hand" in intent.ends


def test_without_a_map_the_shot_has_no_states():
    w = World(staging="")
    intents = [ShotIntent.model_validate(s["intent"]) for s in written(w)["shots"]]
    assert all(not i.opens and not i.ends for i in intents) and all(i.story for i in intents)


def test_the_stamp_of_an_intent_without_the_ledger_is_unchanged():
    old = ShotIntent(purpose="p", what_we_see="w", on_screen=["a"], by="raphael")
    assert old.stamp() == old.model_copy(update={"story": "", "opens": "", "ends": ""}).stamp()
    assert old.stamp() != old.model_copy(update={"opens": "Kasun: standing"}).stamp()


def prompt_of(w: World, shots: list[dict[str, Any]], lines: list[dict[str, Any]], slate: str) -> str:
    shot = next(s for s in shots if s["slate"] == slate)
    out = parts.step("serialize", "step").run({
        "production": {"id": w.production, "settings": {}}, "persona": None, "canon": w.scenes.canon_rows,
        "scene": w.row(), "shots": shots, "lines": lines, "shot_number": shot["number"], "ir": shot["ir"],
        "has_frame": False})
    return " ".join(seg.get("text") or seg.get("sinhala") or "" for s in out["sections"] for seg in s["segments"])


def test_the_veo_prompt_of_a_raphael_shot_carries_position_opens_ends_and_story():
    w = World()
    out = written(w)
    text = prompt_of(w, out["shots"], out["lines"], next(s["slate"] for s in out["shots"]
                                                           if (s["intent"] or {}).get("opens")))
    assert "As the clip opens: " in text and "By the end of the clip: " in text
    assert "What happens in this clip: " in text


def test_the_veo_prompt_of_another_planners_shot_is_as_it_was():
    w = World()
    out = written(w)
    slate = next(s["slate"] for s in out["shots"] if (s["intent"] or {}).get("opens"))
    before = prompt_of(w, out["shots"], out["lines"], slate)
    other = [{**s, "planner": "classic"} for s in out["shots"]]
    plain = prompt_of(w, other, out["lines"], slate)
    assert "As the clip opens" not in plain and "What happens in this clip" not in plain
    assert "As the clip opens" in before


def test_the_first_frame_opens_in_the_same_state():
    compose = parts.step("frame_compose")
    shot = {"planner": "raphael", "intent": {"by": "raphael", "opens": "Kasun: standing, at the stall counter."}}
    assert compose.opens_line(shot) == "In this frame, as the clip opens: Kasun: standing, at the stall counter."
    assert compose.opens_line({**shot, "planner": "classic"}) == ""
    assert compose.opens_line({"planner": "raphael", "intent": {"by": "raphael"}}) == ""


# ── phase 8: production memory and the API ──────────────────────────────────────────────────────


def test_both_agents_read_the_productions_direction():
    for agent in ("raphael_planner", "raphael_cinematic"):
        manifest = yaml.safe_load(
            (PACKAGE_ROOT / "agents" / "raphael" / agent / "component.yaml").read_text(encoding="utf-8"))
        assert "production_memory" in manifest["middleware"]
        assert manifest["memory"] == ["camera", "visual", "lighting", "performance"]
