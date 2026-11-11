"""Offline tests of the two-memories lab (plan/2026-11-11 phase 0): no model, no network.

Run from the repo root:  .venv/Scripts/python.exe -m pytest lab/two_memories/tests -q
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from two_memories import build, checks, ids, packet, rehearsal
from two_memories.lines import Doc, Span
from two_memories.schema import BlockW, EventW, SpanW


@pytest.fixture(scope="module")
def doc() -> Doc:
    return rehearsal.doc()


@pytest.fixture()
def bd(doc):
    b = build.build(rehearsal.split(doc), doc, "ekama")
    names = {k: e.id for k, e in zip(rehearsal.KEYS, b.entities, strict=True)}
    build.apply_episode(b, doc, rehearsal.episode(doc, names))
    return b


def test_cut_copies_words_only_by_pointer(doc):
    n = doc.find_line("ARUNI - Dinu...")
    assert doc.text([Span(n, 2, len(doc.words(n)))]) == "Dinu... oyata meka ahenne nadda?"
    assert not doc.span_ok(Span(n, 3, 99))


def test_ids_are_numbered_by_code():
    r = ids.Registry()
    assert [r.new("C"), r.new("C"), r.new("L")] == ["C01", "C02", "L01"]
    assert ids.scene(0 or 1, 3) == "E01-S03" and ids.valid("E01-S03-B04-e2") and not ids.valid("Dinu")


def test_build_skeleton(doc):
    b = build.build(rehearsal.split(doc), doc, "ekama")
    assert [s.id for s in b.scenes] == [f"E01-S0{n}" for n in range(1, 10)]
    dinu = b.entity("C01")
    assert dinu and dinu.name == "Dinu" and dinu.card["age"].value == "30,"
    assert not any(f.blocking for f in b.findings)
    assert b.rules[0].scope_id == b.entities[6].id  # "Colombo palette" -> the place id
    assert {r.about for r in b.rules} >= {"palette", "lens", "slow_motion", "action"}


def test_gold_passes_every_check(doc, bd):
    found = checks.run_all(bd, doc)
    assert [f for f in found if f.blocking] == [], found


def test_mudalali_call_is_its_own_dialogue_block(bd):
    s2 = bd.scene("E01-S02")
    call = [b for b in s2.blocks if b["kind"] == "dialogue" and b["presence"] == "phone"]
    assert len(call) == 1 and call[0]["text"].startswith("Route eka maru")


def test_a_speech_line_lost_in_action_is_caught(doc, bd):
    """Astra's miss (§1): the call stays inside an action block."""
    s2 = bd.scene("E01-S02")
    merged = [b for b in s2.blocks if b["id"] != "E01-S02-B04"]
    s2.blocks = merged
    s2.blocks[2]["events"][0]["speech"] = True  # the model says someone speaks, in an action block
    found = checks.words(bd, doc)
    assert any("speech" in f.message for f in found) and any("no block" in f.message for f in found)


def test_overlap_and_gap_are_caught(doc, bd):
    s1 = bd.scene("E01-S01")
    s1.blocks[0]["spans"][0][2] = 3  # shorten block 1's first line: words left in no block
    assert any(f.code == "words" for f in checks.words(bd, doc))


def test_presence_rules(doc, bd):
    s2 = bd.scene("E01-S02")
    for p in s2.brief["people"]:
        if p["presence"] == "voice_message":
            p["presence"] = "on_screen"  # a voice message listed as a person on screen
    assert any(f.code == "presence" for f in checks.presence(bd))


def test_unresolved_id_is_blocking(doc, bd):
    bd.scene("E01-S01").brief["people"][0]["person"] = "C99"
    assert any(f.code == "ids" and f.blocking for f in checks.id_check(bd))


def test_packet_shows_only_the_scenes_people(bd):
    p = packet.assemble(bd, "E01-S03")
    names = {x["name"] for x in p["B_people"]}
    assert names == {"Nimal", "Dinu"}  # Mudalali is named in a line: never shown (D3)
    assert packet.incomplete(bd, p) == []
    p2 = packet.assemble(bd, "E01-S02")
    assert {x["name"]: x["presence"] for x in p2["B_people"]} == {"Dinu": "on_screen", "Aruni": "voice_message", "Mudalali": "phone"}


def test_packet_direction_follows_the_region(bd):
    s2 = {r["about"] for r in packet.assemble(bd, "E01-S02")["G_direction"]}
    s1 = packet.assemble(bd, "E01-S01")["G_direction"]
    colombo = [r for r in packet.assemble(bd, "E01-S02")["G_direction"] if r["about"] == "palette"]
    village = [r for r in s1 if r["about"] == "palette"]
    assert "Cold blue" in colombo[0]["text"] and "Warm amber" in village[0]["text"] and "lens" in s2


def test_packet_holds_no_camera_words(bd):
    text = str(packet.assemble(bd, "E01-S01")["E_blocks"]).lower()
    assert "close-up" not in text and "shot size" not in text


def test_incomplete_packet_waits(doc, bd):
    bd.scene("E01-S01").blocks[0]["text"] = ""
    assert any("no words" in m for m in packet.incomplete(bd, packet.assemble(bd, "E01-S01")))
    _ = (BlockW, EventW, SpanW)


def test_card_fields_widen_to_the_whole_sentence(doc):
    from two_memories.lines import sentence_spans

    n = doc.find_line("30,")
    ws = doc.words(n)
    s = sentence_spans(doc, Span(n, len(ws) - 2, len(ws)), n - 1, n + 1)  # "cornered." only, on the wrapped line
    assert doc.text(s).startswith("Quiet, experienced") and doc.text(s).endswith("cornered.")


def test_a_label_line_is_not_part_of_the_sentence(doc):
    from two_memories.lines import sentence_spans

    n = doc.find_line("34,")
    s = sentence_spans(doc, Span(n, 1, 3), n - 1, n)
    assert doc.text(s).startswith("34,") and "Nimal" not in doc.text(s).split(",")[0]


GOLD = Path(__file__).resolve().parents[1] / "gold"


@pytest.fixture()
def real(doc):
    """The model's answers, saved: the approved split, and its episode and continuity answers for Ekama S01 to S03."""
    from two_memories.schema import EpisodeW, SplitW

    b = build.build(SplitW.model_validate_json((GOLD / "split_ekama.json").read_text(encoding="utf-8")), doc, "ekama")
    build.apply_episode(b, doc, EpisodeW.model_validate_json((GOLD / "episode_ekama_s1_s3.json").read_text(encoding="utf-8")))
    return b


@pytest.fixture()
def cont():
    return json.loads((GOLD / "continuity_ekama.json").read_text(encoding="utf-8"))


def test_ids_in_prose_become_names_but_structured_ids_stay(real):
    p = packet.assemble(real, "E01-S02")
    assert "C01" not in p["A_scene"]["summary"] and "Dinu" in p["A_scene"]["summary"]
    assert p["E_blocks"][3]["speaker"] == "C02" and p["B_people"][0]["id"] == "C01"
    assert p["ids"]["C01"] == {"name": "Dinu", "kind": "person"}


def test_shared_names_keep_their_id(real):
    real.entities[1].name = "Dinu"  # two cards called Dinu
    p = packet.assemble(real, "E01-S02")
    assert "Dinu [C01]" in p["A_scene"]["summary"]


def test_wide_summary_and_other_scene_facts_are_withheld(real):
    cash = packet.assemble(real, "E01-S02")["C_place"]
    thread = next(e for e in real.entities if e.name == "red thread")
    assert thread.lines[1] - thread.lines[0] > 6
    thing = next(t for t in packet.assemble(real, "E01-S02")["D_things"] if t["name"].lower() == "red thread")
    assert "summary" in thing["card"] and "value" not in thing["card"]["summary"]
    assert "Aruni ties the red thread" not in str(thing)  # S09's sentence
    assert cash["name"] == "Cash Van"


def test_continuity_enters_the_packet_in_story_order(real, cont):
    a = packet.assemble(real, "E01-S02", cont)["A_scene"]
    assert a["time"]["story_order"] == 2
    assert a["before_in_story"]["id"] == "E01-S03"  # the flashback comes first in the story
    assert "Dinu" in a["before_in_story"]["ends_with"]
    s3 = packet.assemble(real, "E01-S03", cont)["A_scene"]
    assert s3["time"]["kind"] == "flashback" and s3["time"]["relative"] == "Six hours earlier"
    assert any(t["kind"] == "journey" for t in s3["threads"])  # the key's journey touches S03


def test_direction_says_how_it_applies(real):
    g = {r["about"] + r["id"]: r for r in packet.assemble(real, "E01-S02")["G_direction"]}
    assert g["paletteD07"]["applies"] == "scoped"
    assert not [k for k in g if k.startswith("lens")]  # S02 is no love or action scene: the episode call listed none
    assert g["lightingD11"]["applies"] == "general"


def test_a_later_relationship_change_is_not_in_an_earlier_scene(real, cont):
    rel = packet.assemble(real, "E01-S02", cont)["A_scene"]["relationships"]
    order = {t["scene"]: t["story_order"] for t in cont["timeline"]}
    assert all(order[r["scene"]] <= order["E01-S02"] for r in rel)


def test_rules_met_narrows_conditional_rules(real):
    real.scene("E01-S02").brief["rules_met"] = None  # not stated: both lens rules kept, labelled conditional
    lens = [r["id"] for r in packet.assemble(real, "E01-S02")["G_direction"] if r["about"] == "lens"]
    assert len(lens) == 2
    real.scene("E01-S02").brief["rules_met"] = []
    assert [r for r in packet.assemble(real, "E01-S02")["G_direction"] if r["about"] == "lens"] == []
    real.scene("E01-S02").brief["rules_met"] = [lens[0]]
    got = [r for r in packet.assemble(real, "E01-S02")["G_direction"] if r["about"] == "lens"]
    assert [r["id"] for r in got] == [lens[0]] and "meets" in got[0]["applies"]


def test_a_person_seen_and_heard_from_a_device_is_fine(real):
    """Mudalali fights on screen in S08 and his recorded voice plays: not a presence fault (a speaker who is NEVER seen still is)."""
    from two_memories.schema import EpisodeW

    real.scene("E01-S02").brief["people"][2]["presence"] = "on_screen"  # Mudalali, who only calls in S02
    assert any(f.code == "presence" for f in checks.presence(real))
    _ = EpisodeW


def test_a_speakers_name_is_not_a_dialogue_block(real, doc):
    b = real.scene("E01-S03").blocks[2]
    b["text"] = real.entity(b["speaker"]).name
    assert any("narration" in f.message for f in checks.words(real, doc))


def test_stager_marks_expand_per_block_and_disagreement_is_a_finding(real):
    from hiru_ai.agents.stager.schema import Mark, Output, PropMark
    from two_memories import stage

    sc = real.scene("E01-S03")  # Nimal (C03) and Dinu (C01); the key goes from Nimal to Dinu
    blank = {"facing": "", "frame_side": "", "holding": "", "posture": "", "left_hand": "", "right_hand": "", "condition": "",
             "wearing": ""}
    out = Output(zones=["table", "door"], props=[PropMark(block=1, prop="box", where="on the table", state="open")], marks=[
        Mark(block=0, who="Nimal", zone="table", **{**blank, "posture": "standing", "right_hand": "metal box"}),
        Mark(block=0, who="Dinu", zone="door", **blank),
        Mark(block=5, who="Dinu", zone="table", **{**blank, "right_hand": "a pen"}),  # not the key
        Mark(block=99, who="Dinu", zone="door", **blank),  # no such block: dropped
        Mark(block=1, who="Nobody", zone="door", **blank)])  # no such person: dropped
    found = stage.apply(real, sc, out)
    assert len([f for f in found if "dropped" in f.message]) == 2
    st = stage.states(sc)
    nimal = real.entities[2].id
    assert st[nimal][0]["posture"] == "standing" and st[nimal][-1]["right_hand"] == "metal box"  # the last mark holds
    assert any("holding" in f.message for f in found)  # the episode call says Dinu ends with the key
    part = packet.assemble(real, "E01-S03")["stage"]
    assert part["zones"] == ["table", "door"] and part["people"]["C03"]["in"]["zone"] == "table"


def test_the_packet_says_who_was_not_placed(real):
    from hiru_ai.agents.stager.schema import Mark, Output
    from two_memories import stage

    sc = real.scene("E01-S03")
    blank = {"facing": "", "frame_side": "", "holding": "", "posture": "", "left_hand": "", "right_hand": "", "condition": "",
             "wearing": ""}
    stage.apply(real, sc, Output(zones=["table"], props=[], marks=[Mark(block=3, who="Dinu", zone="table", **blank)]))
    np = packet.assemble(real, "E01-S03")["stage"]["not_placed"]
    assert np["Dinu"] == "no position before block 3" and np["Nimal"] == "never placed"
