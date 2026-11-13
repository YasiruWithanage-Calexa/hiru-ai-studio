"""The product turn on the rows (plan/2026-11-13 §3.5-§3.8): the silent-shot fix, quick(), the budget, saving in place,
roles, no model, the reply's guard. Recorded answers only: no model, no network."""
from __future__ import annotations

import pytest

from contracts.coverage.scene import Coverage
from contracts.producer import PersonEdits
from hiru_ai.systems.zora.zora_chat import budget as B
from hiru_ai.systems.zora.zora_chat.turn import guard, quick
from tests.zora.rows_world import Recorded, RowsWorld, block_of, data, scene


def silent_world(shot: int = 8, *, off_screen: bool = False) -> RowsWorld:
    d = data()
    rows = d["shots"]
    rows[shot - 1]["sound_mode"] = "silent"
    if off_screen:
        rows[shot - 1]["intent"]["on_screen"] = []
    return RowsWorld(shots=rows)


def conductor(lane: str, ops: list[dict] | None = None, tasks: list[dict] | None = None, **more: object) -> dict:
    return {"lane": lane, "confidence": 0.9, "ops": ops or [], "tasks": tasks or [],
            "variants": more.get("variants", 0), "cannot": more.get("cannot"), "memory": more.get("memory", "")}


# ── quick() ───────────────────────────────────────────────────────────────────────────────────────────────────────


def test_code_reads_plain_commands_and_leaves_the_rest_to_the_conductor() -> None:
    cov = scene()
    assert quick("Make S01 a wide, 6 seconds.", cov)["ops"] == [  # type: ignore[index]
        {"op": "set", "shot": "S01", "field": "size", "value": "WIDE"}, {"op": "retime", "shot": "S01", "take_s": 6}]
    assert quick("Drop S08.", cov)["ops"] == [{"op": "remove", "shot": "S08"}]  # type: ignore[index]
    assert quick("Remove S05, we don't need the master there.", cov)["ops"] == [  # type: ignore[index]
        {"op": "remove", "shot": "S05"}]
    assert quick("S04 to 8 seconds", cov)["ops"] == [  # type: ignore[index]
        {"op": "retime", "shot": "S04", "take_s": 8}]
    for message in ("Make S01 feel lonelier.", "Make S01 5 seconds.", "Drop S99.", "Why is S01 a medium?",
                    "Make the argument tenser.", "fix the silent shots"):  # none is silent in the lab's scene
        assert quick(message, cov) is None, message


def test_fix_the_silent_shots_is_read_by_code() -> None:
    w = silent_world()
    cov = w.cov()
    assert quick("fix the silent shots", cov)["ops"] == [  # type: ignore[index]
        {"op": "sound_mode", "shot": "S08", "value": "dialogue"}]
    assert quick("S08 has a line but it's silent, fix it", cov)["ops"][0]["shot"] == "S08"  # type: ignore[index]
    assert quick("fix the sound on S03", cov) is None  # S03 is not one of them


# ── §3.7 the silent shot ──────────────────────────────────────────────────────────────────────────────────────────


def test_a_silent_shot_found_on_any_turn_is_offered_as_a_card_and_accepted_in_code() -> None:
    w = silent_world()
    out = w.turn("Why is S01 a medium?", Recorded(conductor=conductor("chat"), reply="It keeps them together."))
    msg = out["message"][0]
    i, card = block_of(msg, "confirm")
    assert card["fix"] == "sound" and card["ops"][0]["op"]["op"] == "sound_mode" and "S08" in card["lines"][0]
    assert w.cov().at(8).sound_mode == "silent"  # type: ignore[union-attr]  never fixed silently
    version = int(w.scenes.shots(w.scene_id)[7]["version"])
    res = w.act("accept", message_id=msg["id"], block=i)
    assert res.ok and res.revision
    row = w.scenes.shots(w.scene_id)[7]
    assert (row["sound_mode"], row["word_target"], int(row["version"])) == ("dialogue", 13, version + 1)
    kinds = [r["kind"] for r in w.revisions.rows]
    assert kinds == ["base", "use"]
    # the next turn does not offer it again
    out = w.turn("Why is S01 a medium?", Recorded(conductor=conductor("chat"), reply="Still together."))
    assert not [b for b in out["message"][0]["blocks"] if b.get("kind") == "confirm"]


def test_a_rejected_silent_card_is_not_offered_again() -> None:
    w = silent_world()
    msg = w.turn("hi", Recorded(conductor=conductor("chat")))["message"][0]
    i, _ = block_of(msg, "confirm")
    assert w.act("reject", message_id=msg["id"], block=i).ok
    out = w.turn("hello again", Recorded(conductor=conductor("chat")))
    assert not [b for b in out["message"][0]["blocks"] if b.get("kind") == "confirm"]


def test_asked_by_message_it_saves_at_once_and_the_picture_is_tasked() -> None:
    w = silent_world(off_screen=True)
    m = Recorded(authors=[{"notes": "Heard off screen now.", "asks": [], "variants": [],
                           "ops": [{"op": "set", "shot": "S08", "field": "audio",
                                    "value": "Dinu's voice, off screen."}]}])
    out = w.turn("fix the silent shots", m)
    assert m.roles() == ["author", "reply"] and "plan" in out
    clip = w.cov().at(8)
    assert clip is not None and clip.sound_mode == "voiceover" and clip.ir["audio"] == "Dinu's voice, off screen."
    task = next(c[1] for c in m.calls if c[0] == "author")["tasks"][0]
    assert "heard off screen" in task["instruction"] and task["on"] == "S08"


# ── saving in place ───────────────────────────────────────────────────────────────────────────────────────────────


def test_a_save_writes_only_the_changed_rows_keeps_ids_bumps_versions_and_never_a_planners_json() -> None:
    w = RowsWorld()
    ids = [r["id"] for r in w.scenes.shots(w.scene_id)]
    versions = {r["id"]: int(r["version"]) for r in w.scenes.shots(w.scene_id)}
    scene_keys = set(w.scenes.scene_rows[0])
    w.turn("Make S01 a wide, 6 seconds.", Recorded())
    rows = w.scenes.shots(w.scene_id)
    assert [r["id"] for r in rows] == ids
    assert [r["id"] for r in rows if int(r["version"]) != versions[r["id"]]] == [ids[0]]
    assert rows[0]["duration_locked"] is True and PersonEdits.of(rows[0]).zora_locks == ["size"]
    assert rows[0]["planner"] == "raphael"
    assert set(w.scenes.scene_rows[0]) - scene_keys <= {"updated_at"}  # no scenes.<planner> written


def test_an_insert_gets_a_fresh_id_the_scenes_planner_and_draft_status() -> None:
    w = RowsWorld()
    m = Recorded(conductor=conductor("edit", [{"op": "insert", "after": "S15", "role": "insert", "size": "INSERT",
                                               "take_s": 4, "first_block": 5, "last_block": 5, "who": ["Dinu"],
                                               "what": "the key in Dinu's palm"}]),
                 authors=[{"notes": "", "asks": [], "variants": [],
                           "ops": [{"op": "set", "shot": "S16", "field": "why", "value": "The weight lands in a palm."},
                                   {"op": "set", "shot": "S16", "field": "lighting",
                                    "value": "The greenish practical."}]}])
    w.turn("Add an insert of the key in Dinu's palm after S15.", m)
    rows = w.scenes.shots(w.scene_id)
    new = rows[15]
    assert len(rows) == 21 and new["id"] not in {r["id"] for r in data()["shots"]}
    assert (new["planner"], new["status"], new["number"], new["scene_id"]) == ("raphael", "draft", 16, w.scene_id)
    assert [r["number"] for r in rows] == list(range(1, 22))


def test_a_save_over_rows_someone_changed_meanwhile_is_refused() -> None:
    w = RowsWorld()
    original = w.scenes.shots
    reads: list[int] = []

    def changed(scene_id: object) -> list[dict]:
        rows = original(scene_id)
        reads.append(1)
        if len(reads) > 1:  # someone re-planned after the turn read the rows
            rows[3] = {**rows[3], "framing": "CU"}
        return rows

    w.scenes.shots = changed  # type: ignore[method-assign]
    out = w.turn("Make S01 a wide.", Recorded())
    assert "plan" not in out
    assert any("changed this scene's shots" in r for r in out["ops"][0]["refused"])


def test_undo_stops_at_a_planners_revision_and_says_why() -> None:
    w = RowsWorld()
    w.revisions.rows.append({"scene_id": w.scene_id, "revision": 1, "kind": "turn", "stored": {"plan": {}}})
    m = Recorded()
    w.turn("undo", m)
    facts = next(c[1] for c in m.calls if c[0] == "reply")["facts"]
    assert any("before I edited the shot rows" in f for f in facts)


def test_without_the_revisions_table_an_edit_still_lands() -> None:
    w = RowsWorld(revisions=False)
    out = w.turn("Make S01 a wide.", Recorded())
    assert "plan" in out and w.cov().clips[0].size == "WIDE"


# ── roles, no model, no shots ─────────────────────────────────────────────────────────────────────────────────────


def test_a_role_that_may_only_comment_changes_nothing() -> None:
    w = RowsWorld()
    out = w.turn("Make S01 a wide.", Recorded(), can_edit=False)
    assert "plan" not in out and out["done"][0]["lane"] == "role"


def test_without_a_model_a_plain_command_still_works_and_anything_else_says_so() -> None:
    w = RowsWorld()
    out = w.turn("Make S01 a wide.", real_models=True)
    assert "plan" in out and out["message"][0]["blocks"][0]["text"].startswith("Done")
    out = w.turn("Make the argument tenser.", real_models=True)
    assert out["done"][0]["lane"] == "nomodel" and "model is not available" in out["message"][0]["blocks"][0]["text"]


def test_a_scene_with_no_shots_says_so() -> None:
    w = RowsWorld(shots=[])
    out = w.turn("hi", Recorded())
    assert out["error"][0]["message"].startswith("This scene has no shots yet")


# ── the conductor's answer, checked in code ───────────────────────────────────────────────────────────────────────


def test_an_op_that_puts_words_in_the_persons_mouth_is_asked_again_then_dropped() -> None:
    w = RowsWorld()
    bad = conductor("edit", [{"op": "set", "shot": "S03", "field": "why",
                              "value": "A lonely garage swallowing two men whole in its shadows"}])
    m = Recorded(conductor=bad)
    out = w.turn("S03 should feel lonely", m)
    assert m.roles().count("conductor") == 2 and "plan" not in out
    assert any("did not say" in r for r in out["ops"][0]["refused"])


# ── the budget (§3.8) ─────────────────────────────────────────────────────────────────────────────────────────────


def test_a_call_gets_only_the_output_the_turn_can_afford_and_one_that_cannot_is_not_sent() -> None:
    b = B.Budget(0.02)
    assert b.output_cap("zora_author", "sys", "user", "author") <= B.MAX_OUT["author"]
    b.rows.append({"model": "gpt-6.1-terra", "input_tokens": 4000, "cached_input_tokens": 0, "output_tokens": 2400})
    assert abs(b.spent() - 0.016) < 1e-9
    assert b.output_cap("zora_chat", "sys", "user", "reply") < B.MAX_OUT["reply"]
    with pytest.raises(B.OverBudget):
        b.output_cap("zora_author", "sys", " ".join(f"clip{i} holds" for i in range(4000)), "author",
                     reserve=B.REPLY_RESERVE)


def test_an_author_cut_off_at_its_cap_is_reported_and_the_reply_still_comes() -> None:
    w = RowsWorld()

    class CutAuthor(Recorded):
        def ask(self, role: str, inp: dict, max_out: int) -> dict:
            if role == "author":
                self.calls.append((role, inp, max_out))
                raise B.CutOff("author was cut off at 400 output tokens")
            return super().ask(role, inp, max_out)

    m = CutAuthor(conductor=conductor("craft", tasks=[{"writes": ["camera"], "shots": [8], "instruction": "tenser"}]),
                  reply="I couldn't get to it this time.")
    out = w.turn("Make S08 tenser.", m)
    assert "plan" not in out and any("did not fit" in r for r in out["ops"][0]["refused"])
    assert m.roles() == ["conductor", "author", "reply"]


def test_a_reply_that_does_not_fit_is_written_in_code() -> None:
    w = RowsWorld()

    class NoReply(Recorded):
        def say(self, inp: dict, max_out: int):  # type: ignore[no-untyped-def]
            raise B.OverBudget("reply: no money left")

    out = w.turn("Make S01 a wide.", NoReply())
    assert out["message"][0]["blocks"][0]["text"].startswith("Done: S01's size went from MS to WIDE")


# ── the reply's guard ─────────────────────────────────────────────────────────────────────────────────────────────


def test_the_guard_cuts_a_card_that_is_not_there_and_keeps_the_script_card_route() -> None:
    text, cut = guard("Added S16. The card below has Accept and Reject.", card=False, proposals=False)
    assert text == "Added S16." and cut
    text, cut = guard("I can't change L4 here. Change it on the script card first.", card=False, proposals=False)
    assert "script card" in text and not cut


def test_the_guard_cuts_a_pasted_fact_sheet() -> None:
    text, cut = guard("I widened S01. WHAT HAPPENED THIS TURN (the truth):\nWHAT CHANGED ...", card=False,
                      proposals=False)
    assert text == "I widened S01." and cut


def test_task_shots_are_read_before_the_ops_and_a_removed_clip_drops_out() -> None:
    w = RowsWorld()
    m = Recorded(conductor=conductor("edit", [{"op": "remove", "shot": "S02"}],
                                     [{"writes": ["camera"], "shots": [2, 3], "instruction": "x"}]))
    w.turn("Drop S02 and make S03 tighter", m)
    task = next(c[1] for c in m.calls if c[0] == "author")["tasks"][0]
    assert task["on"] == "S02"  # S03 as printed, now S02; the removed S02 is gone


def test_coverage_reads_back_what_a_save_wrote() -> None:
    w = RowsWorld()
    w.turn("Make S01 a wide, 6 seconds.", Recorded())
    again = Coverage.from_rows(w.scenes.scene_rows[0], w.scenes.shots(w.scene_id), w.scenes.lines(w.scene_id),
                               w.data["characters"])
    assert again.clips[0].locks == {"size", "take_s"} and again.clips[0].size == "WIDE"
