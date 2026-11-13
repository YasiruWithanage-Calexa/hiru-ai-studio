"""Phase 4 (plan/2026-11-13 §4): the lab's twelve-turn scenario replays offline through the PRODUCT's turn, with the
models' recorded answers of lab run 6 (`lab/zora_rows/runs/run6/turns.json`). It asserts the facts run 6 had: the lanes,
what saved, the cards, Accept / Reject / undo, the options and "Use this" (exact replies may differ: facts, not
wording). No model, no network."""
from __future__ import annotations

from typing import Any

from tests.zora.rows_world import Recorded, RowsWorld, block_of, run6


def recorded(t: dict[str, Any]) -> Recorded:
    return Recorded(conductor=t.get("conductor"), authors=list(t.get("author") or []), reply=str(t.get("reply") or ""))


def test_the_twelve_lab_turns_make_the_same_lanes_saves_and_cards() -> None:
    turns = {t["slot"]: t for t in run6()}
    w = RowsWorld()

    # t01 a question: chat, nothing saved, the conductor and the reply only
    m = recorded(turns["t01"])
    out = w.turn(turns["t01"]["message"], m)
    assert out["done"][0]["lane"] == "chat" and "plan" not in out and m.roles() == ["conductor", "reply"]

    # t02 an exact change code reads itself: no conductor, saved, S01 is a 6 s WIDE and both are the person's
    m = recorded(turns["t02"])
    out = w.turn(turns["t02"]["message"], m)
    assert m.roles() == ["reply"] and out["done"][0]["lane"] == "edit" and "plan" in out
    s01 = w.cov().clips[0]
    assert (s01.size, s01.take_s, s01.locks) == ("WIDE", 6, {"size", "take_s"})

    # t03 a craft note: one author call, its work kept to its task, saved
    m = recorded(turns["t03"])
    before = {c.row_id: c.content() for c in w.cov().clips}
    out = w.turn(turns["t03"]["message"], m)
    assert m.roles() == ["conductor", "author", "reply"] and out["done"][0]["lane"] == "craft" and "plan" in out
    after = w.cov()
    touched = [after.code(c.h) for c in after.clips if before.get(c.row_id) != c.content()]
    assert touched and set(touched) <= {f"S{n:02d}" for n in range(8, 14)}

    # t04 "Drop S08": a must clip that performs L3 → a card, nothing saved
    shots_before = w.scenes.shots(w.scene_id)
    out = w.turn(turns["t04"]["message"], recorded(turns["t04"]))
    msg = out["message"][0]
    i, card = block_of(msg, "confirm")
    assert "removes S08, a must clip" in card["reasons"] and card["state"] == ""
    assert w.scenes.shots(w.scene_id) == shots_before

    # t05 Accept: replayed with no model, saved as a revision, the card settled
    res = w.act("accept", message_id=msg["id"], block=i)
    assert res.ok and res.revision and len(w.scenes.shots(w.scene_id)) == 19
    assert block_of(w.director.message(msg["id"]) or {}, "confirm")[1]["state"] == "accepted"
    l3 = w.cov().lines["L3"]
    assert w.cov().clip(l3.by) is not None and w.cov().clip(l3.by).slate == "3C-3"  # type: ignore[union-attr]

    # t06 "Undo that.": the clip and its line come back
    out = w.turn(turns["t06"]["message"], Recorded(reply="Back as it was."))
    assert out["done"][0]["lane"] == "undo" and len(w.scenes.shots(w.scene_id)) == 20
    assert w.cov().clip(w.cov().lines["L3"].by).slate == "3A-4"  # type: ignore[union-attr]

    # t07 + t08: "Remove S05" asks; Reject changes nothing and is remembered for the conductor
    out = w.turn(turns["t07"]["message"], recorded(turns["t07"]))
    msg7 = out["message"][0]
    i7, card7 = block_of(msg7, "confirm")
    assert "removes S05, a must clip" in card7["reasons"]
    res = w.act("reject", message_id=msg7["id"], block=i7)
    assert res.ok and len(w.scenes.shots(w.scene_id)) == 20
    assert block_of(w.director.message(msg7["id"]) or {}, "confirm")[1]["state"] == "rejected"

    # t09 a script change: not possible here, the route given; nothing saved
    m = recorded(turns["t09"])
    out = w.turn(turns["t09"]["message"], m)
    assert out["done"][0]["lane"] == "cannot" and "plan" not in out
    reply_facts = next(c[1] for c in m.calls if c[0] == "reply")["facts"]
    assert any("NOT POSSIBLE HERE" in f and "Veo" in f for f in reply_facts)
    conductor_in = next(c[1] for c in m.calls if c[0] == "conductor")
    assert conductor_in["rejected"] and "removes S05, a must clip" in conductor_in["rejected"]

    # t10 an insert: code tasks the new clip's picture; saved as clip 16 with the person's words locked
    m = recorded(turns["t10"])
    out = w.turn(turns["t10"]["message"], m)
    assert "plan" in out and m.roles() == ["conductor", "author", "reply"]
    new = w.cov().clips[15]
    assert new.size == "INSERT" and new.why and "sees" in new.locks and len(w.cov().clips) == 21

    # t11 options: two variants tried on a copy, shown with "Use this", nothing saved
    shots_before = w.scenes.shots(w.scene_id)
    out = w.turn(turns["t11"]["message"], recorded(turns["t11"]))
    msg11 = out["message"][0]
    i11, options = block_of(msg11, "options")
    assert len(options["options"]) == 2 and w.scenes.shots(w.scene_id) == shots_before

    # t12 Use 1: the option's batch replayed with the numbers of its start, saved
    res = w.act("use", message_id=msg11["id"], block=i11, option=0)
    assert res.ok and res.revision
    assert block_of(w.director.message(msg11["id"]) or {}, "options")[1]["chosen"] == 0



def test_a_stale_card_is_refused_and_nothing_is_applied() -> None:
    turns = {t["slot"]: t for t in run6()}
    w = RowsWorld()
    out = w.turn(turns["t04"]["message"], recorded(turns["t04"]))
    msg = out["message"][0]
    i, _ = block_of(msg, "confirm")
    w.turn("Make S01 a wide, 6 seconds.", Recorded(reply="Done."))  # the scene changes while the card waits
    res = w.act("accept", message_id=msg["id"], block=i)
    assert not res.ok and "changed" in res.text and len(w.scenes.shots(w.scene_id)) == 20
