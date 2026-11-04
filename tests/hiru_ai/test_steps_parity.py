"""Each step against the legacy engine function it was ported from (plan/2026-11-03 Phase 2 exit: "matches").

Same inputs, both implementations, the whole outcome compared. The legacy copies stay until Phase 8; until then this
file is what says the port did not drift. A step that changes on purpose changes here too, in the same commit.
"""
from __future__ import annotations

import base64
import copy
import json
from typing import Any

import pytest
from canon_extract.engine import pipeline as legacy_canon
from director_chat.engine import agents as legacy_agents
from director_chat.engine import refusals as legacy_refusals
from director_chat.engine import ripple as legacy_ripple
from director_chat.engine import turn as legacy_turn
from doc_ingest.engine import chunking as legacy_chunking
from doc_ingest.engine import extract as legacy_extract
from script_split.engine import critic as legacy_critic
from shot_producer.engine import feeling as legacy_feeling
from shot_producer.engine import model as legacy_model
from shot_producer.engine import serialize as legacy_serialize

from contracts import sceneplan, stagemap
from contracts.reading import SceneReading
from contracts.shotplan import fit
from hiru_ai.core import parts
from tests.hiru_ai.steps_fixtures import CAST, IR, PERSONA, PRODUCTION, bundle, felt_scene, teleporting_scene
from tests.services.director_chat.conftest import fixture_scene
from tests.services.doc_ingest.conftest import CORPUS, make_pdf
from tests.services.production_fixture import PHONE_CANON


def same(a: Any) -> Any:
    """JSON round-trip, so tuples/sets/dataclasses compare as the data they are."""
    return json.loads(json.dumps(a, default=lambda o: sorted(o) if isinstance(o, set) else str(o), sort_keys=True))


def step(ident: str) -> Any:
    return parts.step(ident, "step")


# ── refusal_screen ─────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("reason", [
    "that shot is already as long as it can be", "", "   ", "takes text", "OpError: block.set failed", "value is None",
    "there is no shot 9", "must be an object", "a {dict} leaked", "unknown operation 'x.y'",
])
def test_refusal_wording_matches(reason: str):
    assert step("refusal_screen").run({"reason": reason})["text"] == legacy_refusals.for_person(reason)


# ── scene_kernel ───────────────────────────────────────────────────────────────────────────

BATCHES = [
    [{"op": "set", "shot": 2, "field": "framing", "value": "CU"}, {"op": "retime", "shot": 1, "seconds": 8}],
    [{"op": "split", "shot": 1, "at_block": 1}, {"op": "merge", "shot": 2}],
    [{"op": "retime", "shot": 1, "seconds": 10}, {"op": "set", "shot": 2, "field": "duration_s", "value": "8"},
     {"op": "line.edit", "line": 1, "text": "x"}, {"op": "nope"}, "not an object", {"op": "set", "shot": 9}],
    [{"op": "insert", "after_shot": 1, "description": "A gull on the rail.", "framing": "INSERT"},
     {"op": "set_join", "shot": 2, "link": "continuous"}, {"op": "beat.set", "shot": 1, "beat": 0,
                                                          "field": "action", "value": "looks away"}],
    [{"op": "set", "shot": 1, "field": "sound_mode", "value": "silent"}, {"op": "remove", "shot": 3}],
    [{"op": "block.set", "block": 1, "field": "text", "value": "changed"}],
]


@pytest.mark.parametrize("by", ["conductor", "you", "timing"])
@pytest.mark.parametrize("n", range(len(BATCHES)))
@pytest.mark.parametrize("scene_no", [0, 2])
def test_the_kernel_applies_the_same_batches_the_same_way(scene_no: int, n: int, by: str):
    scene, lines, shots = fixture_scene(scene_no)
    old = legacy_turn.kernel_for(copy.deepcopy(scene), copy.deepcopy(lines), copy.deepcopy(shots), None)
    new = step("scene_kernel").kernel_for(copy.deepcopy(scene), copy.deepcopy(lines), copy.deepcopy(shots), None)
    ops = BATCHES[n]
    a = old.apply(copy.deepcopy(ops), by=by, respect_locks=by != "you")
    b = new.apply(copy.deepcopy(ops), by=by, respect_locks=by != "you")
    assert same((a.applied, a.rejected, a.changes, old.shots, old.items, old.notes, old.describe())) == \
        same((b.applied, b.rejected, b.changes, new.shots, new.items, new.notes, new.describe()))


def test_the_kernel_step_runs_on_json_alone():
    scene, lines, shots = fixture_scene(0)
    out = step("scene_kernel").run({"scene": scene, "lines": lines, "shots": shots, "by": "you",
                                    "ops": [{"op": "retime", "shot": 2, "seconds": 8}, {"op": "nope"}]})
    assert [o["op"] for o in out["applied"]] == ["retime"] and out["rejected"][0]["op"] == {"op": "nope"}
    assert out["shots"][1]["duration"] == 8 and "S02" in out["described"]
    json.dumps(out)


# ── ripple ─────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("scene_no", [0, 1])
def test_ripple_reviews_an_edit_the_same_way(scene_no: int):
    scene, lines, shots = fixture_scene(scene_no)
    dialogue = next(i for i, b in enumerate(scene["script"]) if b["kind"] == "dialogue")
    ops = [{"op": "block.set", "block": dialogue, "field": "text", "value": "a completely different sentence"},
           {"op": "set", "shot": 1, "field": "sound_mode", "value": "silent"}]
    before = legacy_turn.kernel_for(copy.deepcopy(scene), copy.deepcopy(lines), copy.deepcopy(shots), None, PHONE_CANON)
    after = copy.deepcopy(before)
    result = after.apply(copy.deepcopy(ops), by="you", respect_locks=False)
    rv = legacy_ripple.review(before, after, result.applied, result.changes)
    expected = {"impact": rv.impact, "notes": [{"shots": list(n.shots), "text": n.text, "check": n.check}
                                               for n in rv.notes],
                "scripted": rv.scripted, "checked": legacy_ripple.checked(rv),
                "words": legacy_ripple.words_line(before, after, result.changes),
                "continuity_task": legacy_ripple.continuity_task(rv, "why")}
    out = step("ripple").run({"scene": scene, "lines": lines, "shots": shots, "canon": PHONE_CANON, "ops": ops,
                              "by": "you", "summary": "why"})
    assert same({k: out[k] for k in expected}) == same(expected)
    assert out["applied"] and out["scripted"]


def test_ripple_reads_the_real_kernel_through_its_own_protocol():
    """The protocol in ripple/logic.py is written by hand: if the kernel stops satisfying it, this fails."""
    scene, lines, shots = fixture_scene(0)
    k = step("scene_kernel").kernel_for(scene, lines, shots, None, PHONE_CANON)
    for name in ("items", "shots", "canon", "number_of", "fit", "character_id", "_present"):
        assert hasattr(k, name), name


# ── board_settle ───────────────────────────────────────────────────────────────────────────

OUTPUTS = [
    [{"agent": "cinematography", "ops": [{"op": "set", "shot": 2, "field": "framing", "value": "CU"}],
      "note": "tighter"},
     {"agent": "timing", "ops": [{"op": "split", "shot": 2, "at_block": 3}], "note": "cut earlier"}],
    [{"agent": "cinematography", "ops": [{"op": "beat.set", "shot": 1, "beat": 0, "field": "camera", "value": "push"}],
      "note": "push in"},
     {"agent": "continuity", "ops": [{"op": "beat.set", "shot": 1, "beat": 0, "field": "camera", "value": "hold"}],
      "note": "hold it"}],
    [{"agent": "sound", "ops": [{"op": "set", "shot": 1, "field": "sound_mode", "value": "silent"}], "note": "quiet"},
     {"agent": "cinematography", "ops": [{"op": "set", "shot": 1, "field": "sound_mode", "value": "ambient"}],
      "note": "no"},
     {"agent": "continuity", "ops": [{"op": "set_join", "shot": 2, "link": "match"}], "note": ""}],
    [],
]


@pytest.mark.parametrize("outputs", OUTPUTS)
def test_the_board_settles_collisions_the_same_way(outputs: list[dict[str, Any]]):
    old = legacy_agents.settle([legacy_agents.Output(o["agent"], o["ops"], o["note"]) for o in outputs])
    out = step("board_settle").run({"outputs": outputs})
    assert same({"ops": [{"agent": a, "op": op} for a, op in old.ops], "disagreements": old.disagreements}) == same(out)


# ── verbatim_check ─────────────────────────────────────────────────────────────────────────

WRITTEN = "Change Kamala's line to: “I won't sell the boat… not ever.” and the restarunt scene stays"


@pytest.mark.parametrize("op", [
    {"op": "block.set", "value": "I won't sell the boat... not ever."},
    {"op": "block.set", "value": "I will sell the boat"},
    {"op": "block.set", "value": "the restaurant scene stays", "speaker": "Kamala"},
    {"op": "block.set", "value": "boat", "delivery": "whispers"},
    {"op": "block.remove"},
    {"op": "block.insert", "value": "", "speaker": " "},
])
def test_the_verbatim_rule_matches(op: dict[str, Any]):
    flat = legacy_turn._flat(WRITTEN)
    expected = legacy_turn._verbatim(op, flat, set(legacy_turn._words(WRITTEN)))
    assert step("verbatim_check").run({"op": op, "written": WRITTEN}) == {"ok": expected}


# ── kernel_score, stage_check, bridges, feeling ────────────────────────────────────────────

SCENES = {"felt": felt_scene, "teleporting": teleporting_scene}


@pytest.mark.parametrize("name", SCENES)
def test_the_kernel_score_matches(name: str):
    scene, lines, shots = SCENES[name]()
    items = sceneplan.scene_items(scene, lines)
    result = fit(items, sceneplan.proposal_for(sceneplan.plan_from_rows(shots)), envelope_s=int(scene["envelope_s"]))
    expected = legacy_critic.kernel_score(result, SceneReading.of(scene), items, stagemap.SceneStaging.of(scene), CAST)
    out = step("kernel_score").run(bundle(scene, lines, shots))
    assert out["score"] == list(expected)
    assert out["described"] == legacy_critic.describe(result, items)


def test_a_teleport_costs_the_plan_a_point():
    felt, tele = (step("kernel_score").run(bundle(*SCENES[n]()))["score"] for n in ("felt", "teleporting"))
    assert tele[4] == felt[4] + 1  # the fifth term counts teleports


@pytest.mark.parametrize("name", SCENES)
def test_the_stage_check_matches_the_stage_map_rules(name: str):
    scene, lines, shots = SCENES[name]()
    items = sceneplan.scene_items(scene, lines)
    staging = stagemap.SceneStaging.of(scene)
    result = fit(items, sceneplan.proposal_for(sceneplan.plan_from_rows(shots)), envelope_s=int(scene["envelope_s"]))
    out = step("stage_check").run(bundle(scene, lines, shots))
    assert [f["message"] for f in out["findings"]] == [f.message for f in stagemap.checks(staging, items, result, CAST)]
    assert [(m["before_block"], m["who"], m["zone"]) for m in out["moves"]] == stagemap.plan_moves(staging, items, CAST)


def test_the_stage_check_finds_a_teleport_and_nothing_in_a_clean_scene():
    assert step("stage_check").run(bundle(*felt_scene()))["findings"] == []
    found = step("stage_check").run(bundle(*teleporting_scene()))
    assert [f["code"] for f in found["findings"]] == ["teleport"] and found["moves"][0]["who"] == "Anudi"


def test_bridges_add_the_implied_phone_step_once_and_say_so():
    scene, lines, shots = felt_scene()
    out = step("bridges").run(bundle(scene, lines, shots))
    implied = [b for b in out["script"] if b.get("implied")]
    assert [b["bridge"] for b in implied] == ["answer_phone"] and implied[0]["text"] == "Anudi answers the phone."
    assert out["planned"] == [{"before_block": 5, "kind": "answer_phone", "who": "Anudi"}]
    again = step("bridges").run(bundle({**scene, "script": out["script"]}, lines, shots))
    assert [b["bridge"] for b in again["script"] if b.get("implied")] == ["answer_phone"]  # added once, not twice


@pytest.mark.parametrize("name", SCENES)
@pytest.mark.parametrize("which", [0, 1])
def test_feeling_matches(name: str, which: int):
    scene, lines, shots = SCENES[name]()
    items = sceneplan.scene_items(scene, lines)
    shot = shots[which]
    windows = [(int(b["start_s"]), int(b["end_s"])) for b in shot["beats"]]
    from contracts.producer import shot_items

    expected = legacy_feeling.feeling_for(SceneReading.of(scene), stagemap.SceneStaging.of(scene), items,
                                          shot_items(items, int(shot["block_start"]), int(shot["block_end"])),
                                          windows, CAST)
    out = step("feeling").run(bundle(scene, lines, shots, shot=shot))
    assert out["beat_notes"] == {str(k): v for k, v in expected.beat_notes.items()}
    assert out["turn_beats"] == sorted(expected.turn_beats)
    assert (out["wants"], out["person_wants"]) == (expected.wants, expected.person_wants)
    assert out["performance"] == expected.performance_text(windows)
    assert out["start_text"] == legacy_feeling.positions_text(expected.start)


# ── serialize ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", SCENES)
@pytest.mark.parametrize("number", [1, 2])
@pytest.mark.parametrize("has_frame", [False, True])
def test_the_prompt_is_serialized_the_same_way(name: str, number: int, has_frame: bool):
    scene, lines, shots = SCENES[name]()
    prod = legacy_model.production_input(PRODUCTION, PHONE_CANON, PERSONA)
    built = legacy_model.scene_input(scene, shots, lines, PHONE_CANON, prod)
    shot = next(s for s in built.shots if s.number == number)
    previous = next((s for s in built.shots if s.number == number - 1), None)
    ctx = legacy_serialize.Context(aspect_ratio=prod.aspect_ratio, camera=shot.camera(built),
                                   recommended=shot.recommended(built), style_note=prod.style_note,
                                   previous_code=previous.code if previous else "", carried="", has_frame=has_frame)
    sections = legacy_serialize.build_sections(shot, IR, ctx)
    out = step("serialize").run({"production": PRODUCTION, "persona": PERSONA, "canon": PHONE_CANON, "scene": scene,
                                 "shots": shots, "lines": lines, "shot_number": number, "ir": IR,
                                 "has_frame": has_frame})
    assert same(out["sections"]) == same([s.model_dump(exclude_none=True) for s in sections])
    checks = legacy_serialize.prompt_checks(shot, sections, ctx, IR)
    assert same(out["checks"]) == same([c.model_dump() for c in checks])


def test_serialized_dialogue_is_the_scripts_own_words():
    scene, lines, shots = felt_scene()
    out = step("serialize").run({"production": PRODUCTION, "persona": PERSONA, "canon": PHONE_CANON, "scene": scene,
                                 "shots": shots, "lines": lines, "shot_number": 1, "ir": IR})
    spoken = [seg["sinhala"] for s in out["sections"] for seg in s["segments"] if seg.get("sinhala") is not None]
    assert spoken and spoken[0] == lines[0]["text"]
    assert {"label": "Lines verbatim from the script", "tone": "pass"} in out["checks"]


# ── extract_text and chunk ─────────────────────────────────────────────────────────────────

FILES = [("harbour-lights-ep01-script.fountain", "text/plain"), ("harbour-lights-bible.md", "text/markdown"),
         ("harbour-lights-canon-index.md", "text/markdown"), ("director-notes.txt", "text/plain")]


@pytest.mark.parametrize(("name", "mime"), FILES)
def test_extraction_and_chunking_match(name: str, mime: str):
    data = (CORPUS / name).read_bytes()
    old = legacy_extract.extract(data, name, mime)
    out = step("extract_text").run({"filename": name, "mime_type": mime, "data_b64": base64.b64encode(data).decode()})
    assert out["lines"] == [{"text": ln.text, "page": ln.page} for ln in old.lines]
    assert (out["kind"], out["page_count"], out["warnings"], out["has_sinhala"]) == \
        (old.kind, old.page_count, old.warnings, old.has_sinhala)
    for script_like in (False, True):
        made = legacy_chunking.chunk(old, script_like=script_like)
        expected = [{**c.__dict__, "content_hash": c.content_hash} for c in made]
        got = step("chunk").run({"kind": out["kind"], "lines": out["lines"], "script_like": script_like})["chunks"]
        assert got == expected


def test_a_scanned_pdf_is_a_result_not_a_crash():
    out = step("extract_text").run({"filename": "scan.pdf", "mime_type": "application/pdf",
                                    "data_b64": base64.b64encode(make_pdf(["", ""])).decode()})
    assert out["rejected"]


# ── canon_rules ────────────────────────────────────────────────────────────────────────────


def test_the_canon_rules_find_the_same_candidates():
    roles = {"harbour-lights-ep01-script.fountain": "script", "harbour-lights-bible.md": "bible",
             "harbour-lights-canon-index.md": "canon_index"}
    docs = [{"filename": n, "role": r, "text": (CORPUS / n).read_text(encoding="utf-8")} for n, r in roles.items()]
    expected = legacy_canon.rule_candidates(docs)
    out = step("canon_rules").run({"documents": docs})
    assert same(out["candidates"]) == same(expected)
    assert out["chips"] == legacy_canon.chips(expected)
    assert expected, "the fixture corpus should give candidates"
