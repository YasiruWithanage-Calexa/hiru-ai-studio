"""shot_producer, plan/2026-11-01b Phase 7: the intent and the DoP work on the shot's timeline, can say
"split here", and the checks catch a dropped step or a size that cannot show what is described."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from shot_producer.engine import intent, shots

from contracts import bridges, sceneplan
from contracts.producer import shot_items
from contracts.shotplan import ProposedShot, fit, timeline_text
from contracts.staging import ShotIntent, skipped_beats, staging, staging_checks
from tests.services.production_fixture import ANUDI, FATHER, PHONE_CANON, phone_scene
from tests.services.shot_producer.conftest import FakeStore, ProducerLLM
from tests.services.shot_producer.test_shot_producer import design_calls, run
from tests.services.shot_producer.test_staging import call, dp, store_for


def intent_answer(what_we_see: str, *, split_after: int = -1, reason: str = "") -> dict[str, Any]:
    entries = [{"number": n, "purpose": "The call pulls her back", "what_we_see": what_we_see,
                "emotional_beat": "warmth to dread", "on_screen": ["C02"], "heard_only": ["C03"],
                "voice_source": "phone", "split_after": split_after if n == 2 else -1,
                "split_reason": reason if n == 2 else ""} for n in (1, 2)]
    return {"shots": entries, "coverage": {"axis": "", "motif": "", "progression": "tighten"}}


def run_with(what_we_see: str, **kw: Any) -> tuple[FakeStore, ProducerLLM]:
    store = store_for()
    llm = ProducerLLM({"shot_intent": lambda s, u: intent_answer(what_we_see, **kw),
                       "scene_design": lambda s, u: dp([1, 2]),
                       "craft_problems": lambda s, u: {"problems": []},
                       "design_review": lambda s, u: {"acceptable": True, "notes": []}})
    run(store, llm, scene_ids=[store.scene_row["id"]])
    return store, llm


def test_the_timeline_text_is_the_kernels_clock_in_words():
    scene, lines, _ = phone_scene()
    items = sceneplan.items_for(scene["script"], lines)
    text = timeline_text(items[2:6], lambda i: "Father" if i.is_line else "")
    assert text == ("0.0–1.5 Anudi smiles back · 1.5–3.0 Suddenly, her phone rings · "
                    "3.0–8.9 LINE Father (on the phone)")  # "It is her father" takes no time of its own
    with_bridge = bridges.with_bridges(scene["script"], lines, 1, cast=["Anudi", "Kasun"])  # Anudi never speaks here
    items = sceneplan.items_for(with_bridge, lines)
    text = timeline_text(items[2:7], lambda i: "Father" if i.is_line else "")
    assert "3.0–4.5 Anudi answers the phone (implied)" in text and "4.5–10.4 LINE Father" in text


def test_the_intent_prompt_carries_the_timeline_and_names_what_is_not_filmed():
    _, llm = run_with("Anudi smiles back. Her phone rings.")
    prompt = next(c for c in llm.calls if c["schema"] == "shot_intent")["user"]
    assert "TIMELINE (seconds from the start of the shot): 0.0–1.5 Anudi smiles back" in prompt
    assert "THE VIEWER LEARNS: It is her father. (show it with an insert, a line or a look)" in prompt
    assert "[3] ACTION: Suddenly, her phone rings." in prompt or "ACTION: Suddenly, her phone rings." in prompt
    dop = design_calls(llm)[0]["user"]
    assert "TIMELINE (seconds from the start of the shot; the beats follow it): 0.0–1.5" in dop
    assert "THE VIEWER LEARNS:" in dop
    assert "Follow the shot's TIMELINE in order" in " ".join(intent.SYSTEM.split())
    assert "IMPLIED steps" in intent.SYSTEM


def test_a_story_note_is_labelled_not_filmed():
    scene, lines, _ = phone_scene()
    scene["script"].append({"kind": "action", "text": "He has no idea that this will change his life.",
                            "line_id": None})
    items = sceneplan.items_for(scene["script"], lines)
    assert intent.block_label(items[-1]) == "STORY NOTE (not filmed)" and items[-1].picture_s == 0


def test_an_intent_that_drops_the_ring_gets_skips_beat_and_one_that_keeps_it_does_not():
    scene, lines, _ = phone_scene()
    items = shot_items(sceneplan.items_for(scene["script"], lines), 2, 6)
    dropped = ShotIntent(what_we_see="Anudi smiles back at Kasun.", by="model")
    assert skipped_beats(items, dropped) == ["Suddenly, her phone rings"]
    kept = ShotIntent(what_we_see="Anudi smiles back at Kasun. Her phone rings and she looks at the screen.",
                      by="model")
    assert skipped_beats(items, kept) == []
    assert skipped_beats(items, ShotIntent(what_we_see="Anudi smiles.", by="person")) == []  # a person's own words

    store, _ = run_with("Anudi smiles back at Kasun.")
    row = call(store)
    chars = [c for c in PHONE_CANON if c["kind"] == "character"]
    staged = staging(items, chars, row)
    labels = [c.label for c in staging_checks(
        staged=staged, names={ANUDI: "Anudi", FATHER: "Anudi's Father"}, sound_mode="voiceover", speaker_ids=[FATHER],
        intent=ShotIntent.of(row), items=items, framing="MCU")]
    assert "What we see skips a beat · Suddenly, her phone rings" in labels


def test_an_mcu_whose_intent_says_two_shot_and_walks_away_gets_size_vs_intent():
    scene, lines, _ = phone_scene()
    items = shot_items(sceneplan.items_for(scene["script"], lines), 2, 6)
    said = ShotIntent(what_we_see="A two-shot of Anudi and Kasun as she walks away from the stall.", by="model")
    checks = staging_checks(staged=staging(items, [c for c in PHONE_CANON if c["kind"] == "character"],
                                           {"sound_mode": "voiceover"}),
                            names={}, sound_mode="voiceover", speaker_ids=[], intent=said, items=items,
                            framing="MCU")
    size = [c for c in checks if c.code == "coverage"]
    assert size and "can show" in size[0].label and size[0].tone == "advisory"
    wide = staging_checks(staged=staging(items, [], {"sound_mode": "voiceover"}), names={}, sound_mode="voiceover",
                          speaker_ids=[], intent=said, items=items, framing="WIDE")
    assert not [c for c in wide if c.code == "coverage"]


def test_the_intent_may_say_split_here_and_it_is_stored_and_validated():
    store, _ = run_with("Anudi smiles back. Her phone rings.", split_after=3,
                        reason="The call is a new feeling")
    it = call(store)["intent"]
    assert it["split_after"] == 3 and it["split_reason"] == "The call is a new feeling"
    nothing, _ = run_with("Anudi smiles back. Her phone rings.", split_after=-1, reason="ignored")
    none = call(nothing)["intent"]
    assert none["split_after"] is None and none["split_reason"] == ""
    outside, _ = run_with("Anudi smiles back. Her phone rings.", split_after=99, reason="made up")
    assert call(outside)["intent"]["split_after"] is None  # not a block of this shot
    last, _ = run_with("Anudi smiles back. Her phone rings.", split_after=5, reason="the last block")
    assert call(last)["intent"]["split_after"] is None  # cutting after the last block cuts nothing
    assert "split_after" in intent.SCHEMA["properties"]["shots"]["items"]["required"]


def test_the_dop_beats_are_matched_by_time_not_by_position():
    shot = SimpleNamespace(beats=[(0, 3), (3, 6), (6, 8)], beat_notes=[])
    ir = {"beats": [{"time": "0-2s", "camera": "a", "director_line": "smile", "action": ""},
                    {"time": "2-5s", "camera": "b", "director_line": "ring", "action": ""},
                    {"time": "5-8s", "camera": "c", "director_line": "answer", "action": ""}]}
    out = shots.fit_beats(ir, shot)["beats"]  # type: ignore[arg-type]
    assert [b["time"] for b in out] == ["0-3s", "3-6s", "6-8s"]
    # the window 3-6 s overlaps "ring" (2-5) most; 6-8 s is "answer" (5-8); 0-3 s is "smile" (0-2)
    assert [b["director_line"] for b in out] == ["smile", "ring", "answer"]
    two = {"beats": [{"time": "0-6s", "director_line": "first"}, {"time": "6-8s", "director_line": "second"}]}
    assert [b["director_line"] for b in shots.fit_beats(two, shot)["beats"]] == ["first", "first", "second"]  # type: ignore[arg-type]
    unstamped = shots.fit_beats({"beats": [{"director_line": "x"}, {"director_line": "y"}]}, shot)["beats"]  # type: ignore[arg-type]
    assert [b["director_line"] for b in unstamped] == ["x", "x", "y"]  # no times: across in order


def test_a_heard_line_says_what_happens_first_in_the_video_prompt():
    scene, lines, _ = phone_scene()
    script = bridges.with_bridges(scene["script"], lines, 1, cast=["Anudi", "Kasun"])
    scene = {**scene, "script": script}
    items = sceneplan.items_for(script, lines)
    ring = next(i.index for i in items if "rings" in i.text)
    plan = [ProposedShot(0, ring - 1, "MCU", "Kasun's start"),
            ProposedShot(ring - 1, len(items), "MCU", "Anudi takes the call", "voiceover", 8, True)]
    shot_rows, _, _ = sceneplan.rows_after_fit(scene, [{"start": p.start} for p in plan],
                                               fit(items, plan, envelope_s=60), lines)
    for s in shot_rows:
        s.update(ir={}, design={}, camera_overrides={}, intent={})
    store = FakeStore(scene, lines, shot_rows, canon=PHONE_CANON)
    target = sorted(store.shot_rows.values(), key=lambda s: s["number"])[1]
    store.frames[target["id"]] = {"id": str(uuid4()), "shot_id": target["id"], "pins": {}}
    run(store, mode="prompt", shot_ids=[target["id"]])
    prose = store.prompts[0]["prose"]
    assert "Anudi answers the phone; then the voice: " in prose
