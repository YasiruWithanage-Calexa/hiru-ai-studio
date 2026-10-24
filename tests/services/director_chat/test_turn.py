"""A whole director turn against an in-memory store: rules (no key) and a fake model."""
from __future__ import annotations

import json
from uuid import UUID, uuid4

from director_chat.app.handler import CLIENT_ERROR, stream
from director_chat.engine import turn

from contracts.director import TurnPayload
from tests.services.director_chat.conftest import PID, DirectorLLM, FakeStore, fixture_scene, tool_call

ACTOR = uuid4()


def payload(store: FakeStore, message: str, *, can_edit: bool = True) -> TurnPayload:
    return TurnPayload(production_id=PID, scene_id=UUID(store.scene_row["id"]), thread_id=uuid4(),
                       actor_user_id=ACTOR, actor_name="Dee Director", can_edit=can_edit, message=message,
                       user_message_id=uuid4())


def run(store: FakeStore, message: str, llm: DirectorLLM | None = None, **kw) -> list[tuple[str, dict]]:
    return list(turn.run(payload(store, message, **kw), store, llm or DirectorLLM(enabled=False)))


def kinds(events: list[tuple[str, dict]]) -> list[str]:
    out: list[str] = []
    for name, _ in events:
        if not out or out[-1] != name:
            out.append(name)
    return out


def store0(**kw) -> FakeStore:
    return FakeStore(*fixture_scene(0), **kw)


# ── without a key ──────────────────────────────────────────────────────────────────────────


def test_an_explicit_edit_is_applied_saved_and_reported():
    store = store0()
    ids = [s["id"] for s in store.shots(PID)]
    events = run(store, "make shot 2 eight seconds")
    assert kinds(events) == ["status", "plan", "status", "delta", "message", "done"]
    saved = store.saved[-1]
    assert [s["id"] for s in saved["shots"]] == ids and not saved["removed"]  # ids kept
    s2 = saved["shots"][1]
    assert s2["duration_s"] == 8 and s2["duration_locked"] and s2["version"] == 2
    assert saved["shots"][0]["version"] == 1  # untouched shot keeps its version
    assert saved["scene"]["fit_report"]["planner"] == "director"
    assert all(ln["shot_id"] in ids for ln in saved["lines"])
    message = store.message_rows[-1]
    assert message["kind"] == "director" and message["ops"][0]["op"] == "retime"
    assert [b["kind"] for b in message["blocks"]] == ["text", "edit-note"]
    assert "S02 is now 8 s" in message["blocks"][0]["text"]
    assert store.audits[-1]["actor_agent"] == "director_chat" and store.audits[-1]["actor_user_id"] == str(ACTOR)


def test_a_role_without_direct_is_answered_but_nothing_changes():
    store = store0()
    events = run(store, "make shot 2 eight seconds", can_edit=False)
    assert not store.saved and "plan" not in kinds(events)
    assert "can comment but not change" in store.message_rows[-1]["blocks"][0]["text"]


def test_an_approved_scene_is_left_alone():
    store = store0()
    store.scene_row["status"] = "approved"
    run(store, "make shot 2 eight seconds")
    assert not store.saved and "approved and locked" in store.message_rows[-1]["blocks"][0]["text"]


def test_an_edit_that_restructures_most_of_the_scene_is_offered_as_a_resplit():
    store = store0()
    run(store, "remove shot 1, remove shot 2, remove shot 3")
    assert not store.saved and "Re-split" in store.message_rows[-1]["blocks"][0]["text"]


def test_refused_operations_are_explained():
    store = store0()
    run(store, "make shot 9 six seconds")
    assert not store.saved and "there is no shot 9" in store.message_rows[-1]["blocks"][0]["text"]


def test_standing_rules_go_to_production_memory():
    store = store0()
    run(store, "Remember: Kamala never cries on screen.")
    assert store.memory_rows[-1]["kind"] == "decision" and "never cries" in store.memory_rows[-1]["text"]
    assert store.memory_rows[-1]["embedding"] is None  # no key: kept for keyword search
    reviewer = store0()
    run(reviewer, "Remember: Kamala never cries on screen.", can_edit=False)
    assert not reviewer.memory_rows


def test_a_scene_that_is_gone_answers_an_error():
    store = store0()
    req = payload(store, "hi").model_copy(update={"scene_id": uuid4()})
    assert list(turn.run(req, store, DirectorLLM(enabled=False)))[-1][0] == "error"


def test_a_crash_becomes_one_client_safe_error_frame():
    class Broken(FakeStore):
        def lines(self, scene_id):
            raise RuntimeError("secret internals")

    broken = Broken(*fixture_scene(0))
    frames = list(stream(payload(broken, "hi"), broken, DirectorLLM(enabled=False)))
    assert frames[-1].startswith("event: error") and CLIENT_ERROR in frames[-1] and "secret" not in frames[-1]


def test_history_leaves_out_the_message_being_answered():
    store = store0()
    req = payload(store, "why?")
    store.history = [{"id": str(req.user_message_id), "kind": "user", "speaker": "Dee", "text": "why?", "blocks": []},
                     {"id": "x", "kind": "director", "speaker": "CT", "text": "",
                      "blocks": [{"kind": "text", "text": "Because."}]}]
    llm = DirectorLLM({"turn_plan": lambda s, u: {"lane": "chat", "ops": [], "tasks": [], "memory": []}})
    list(turn.run(req, store, llm))
    history = llm.calls[0]["user"].split("<recent_chat>")[1].split("</recent_chat>")[0]
    assert "Because." in history and "why?" not in history


# ── with a model ───────────────────────────────────────────────────────────────────────────


def plan_answer(lane: str, ops=(), tasks=(), memory=()) -> dict:
    return {"lane": lane, "ops": [{**{k: None for k in ("shot", "field", "value", "seconds", "at_block", "end_block",
                                                         "link", "beat", "after_shot", "description", "framing",
                                                         "title")}, **o} for o in ops],
            "tasks": list(tasks), "memory": list(memory)}


def test_craft_request_tasks_specialists_and_the_owner_wins_a_collision():
    store = store0(board=[{"seat": "advisor", "persona": {"id": str(uuid4()), "name": "Lyrical Eye",
                                                          "charter": "Let place carry emotion."}}])
    tasks = [{"agent": "cinematography", "shots": [1, 2, 4], "instruction": "more intimate"},
             {"agent": "sound", "shots": [1], "instruction": "quieter dawn"}]
    responders = {
        "turn_plan": lambda s, u: plan_answer("craft", tasks=tasks),
        "cinematography_ops": lambda s, u: {"ops": [
            {"op": "set", "shot": 2, "field": "framing", "value": "CU"},
            {"op": "set", "shot": 1, "field": "sound_mode", "value": "music_only"}], "note": "Closer on both."},
        "sound_ops": lambda s, u: {"ops": [{"op": "set", "shot": 1, "field": "sound_mode", "value": "silent"}],
                                   "note": "Let the dawn be silent."},
        "advisor_view": lambda s, u: {"agrees": False, "view": "I would hold the wide longer."},
    }
    llm = DirectorLLM(responders)
    events = run(store, "Make this scene more intimate", llm)
    shots = store.saved[-1]["shots"]
    assert shots[1]["framing"] == "CU"
    assert shots[0]["sound_mode"] == "silent"  # sound owns sound_mode; cinematography's view is heard, not applied
    message = store.message_rows[-1]
    blocks = [b["kind"] for b in message["blocks"]]
    assert blocks.count("disagreement") == 2  # the ownership collision, and the advisor
    assert any(b.get("title") == "Lyrical Eye sees it differently" for b in message["blocks"])
    assert {o["by"] for o in message["ops"]} == {"cinematography", "sound"}
    assert "".join(d["text"] for e, d in events if e == "delta") == llm.reply
    tiers = {c["phase"]: c["tier"] for c in llm.calls}
    assert tiers["director.conduct"] == "medium" and tiers["director.cinematography"] == "high"
    assert tiers["director.reply"] == "medium"  # the smallest tier invented changes in the replay


def test_specialists_cannot_use_operations_outside_their_craft_or_break_locks():
    store = store0()
    store.shot_rows[1]["duration_locked"] = True
    responders = {
        "turn_plan": lambda s, u: plan_answer("craft", tasks=[{"agent": "sound", "shots": [2], "instruction": "x"}]),
        "sound_ops": lambda s, u: {"ops": [{"op": "merge", "shot": 1}, {"op": "retime", "shot": 2, "seconds": 8}],
                                   "note": ""},
    }
    run(store, "tighten it", DirectorLLM(responders))
    assert not store.saved  # nothing applied
    assert store.message_rows[-1]["ops"] == []


def test_a_change_that_makes_a_line_overrun_gets_a_bounded_second_round():
    store = store0()
    for ln in store.line_rows:
        ln["text"] = " ".join([ln["text"]] * 4)  # long enough that 4 s cannot hold it
    rounds = {"n": 0}

    def timing(system: str, user: str) -> dict:
        rounds["n"] += 1
        return {"ops": [], "note": "Give the line room."}

    responders = {"turn_plan": lambda s, u: plan_answer("edit", ops=[{"op": "retime", "shot": 2, "seconds": 4}]),
                  "timing_ops": timing}
    run(store, "make shot 2 four seconds", DirectorLLM(responders))
    assert rounds["n"] == 1  # asked once for the overrun this turn made; not looped
    issues = store.saved[-1]["scene"]["fit_report"]["issues"]
    assert any(i["code"] == "line_overrun" for i in issues)  # reported, never trimmed
    assert any(b["kind"] == "continuity" for b in store.message_rows[-1]["blocks"])


def test_questions_use_the_read_tools_scoped_to_the_turn():
    store = store0()
    script = [type("M", (), {"content": "", "tool_calls": [tool_call("get_canon", json.dumps({"name": "amma"})),
                                                             tool_call("search_production",
                                                                       json.dumps({"query": "Kamala age"}))]})()]
    llm = DirectorLLM({"turn_plan": lambda s, u: plan_answer("chat")}, tool_script=script, reply="Kamala is 52.")
    events = run(store, "How old is Kamala?", llm)
    assert not store.saved
    tool_msgs = [m for m in llm.tool_rounds[-1] if m["role"] == "tool"]
    assert "low, clipped female voice" in tool_msgs[0]["content"]  # alias resolved to C01
    assert store.searches[0]["production_id"] == str(PID)  # scope from the turn, not the model
    message = store.message_rows[-1]
    assert message["blocks"][0]["text"] == "Kamala is 52." and message["citations"][0]["label"].startswith("bible.md")
    assert [d["text"] for e, d in events if e == "delta"] == ["Kamala is 52."]


def test_a_failing_model_falls_back_to_rules_and_the_plain_reply():
    store = store0()

    def broken(system: str, user: str) -> dict:
        raise RuntimeError("model down")

    class Mute(DirectorLLM):
        def stream(self, **kw):
            raise RuntimeError("model down")
            yield ""

    run(store, "make shot 2 eight seconds", Mute({"turn_plan": broken}))
    assert store.saved[-1]["shots"][1]["duration_s"] == 8
    assert "Done: S02 is now 8 s" in store.message_rows[-1]["blocks"][0]["text"]


def test_a_split_the_kernel_makes_is_saved_as_a_new_shot():
    store = store0()
    for ln in store.line_rows:
        ln["text"] = " ".join([ln["text"]] * 6)
    run(store, "merge shots 1 and 2")  # the merged shot cannot hold its speech: refit splits it again
    saved = store.saved[-1]
    numbers = [s["number"] for s in saved["shots"]]
    assert numbers == list(range(1, len(numbers) + 1))
    ids = [s["id"] for s in saved["shots"]]
    assert len(set(ids)) == len(ids)


def test_specialists_are_held_to_their_task_shots():
    store = store0()
    responders = {
        "turn_plan": lambda s, u: plan_answer("craft", tasks=[{"agent": "cinematography", "shots": [2],
                                                                "instruction": "closer on Nimal"}]),
        "cinematography_ops": lambda s, u: {"ops": [
            {"op": "set", "shot": 2, "field": "framing", "value": "close-up"},
            {"op": "set", "shot": 4, "field": "framing", "value": "WIDE"}], "note": "Closer."},
    }
    run(store, "closer on Nimal", DirectorLLM(responders))
    shots = store.saved[-1]["shots"]
    assert shots[1]["framing"] == "CU"  # "close-up" is understood
    assert shots[3]["framing"] == "MS"  # S04 was not in the task: dropped


def test_the_reply_is_told_when_nothing_changed():
    store = store0()
    llm = DirectorLLM({"turn_plan": lambda s, u: plan_answer("edit", ops=[{"op": "retime", "shot": 9, "seconds": 6}])})
    run(store, "make shot 9 six seconds", llm)
    reply_prompt = llm.streamed[-1][1]["content"]
    assert "Applied: nothing" in reply_prompt and "there is no shot 9" in reply_prompt
