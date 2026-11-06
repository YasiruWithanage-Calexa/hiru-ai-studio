"""plan/2026-11-05 Phases 3 and 4: the one-take planner and the fixer ladder, end to end on localhost with fakes.

The model is scripted with the gold master's own answers (the take as ONE answer, the sound, the critic) and, where a
plan needs fixing, a fixer's answer. That shows the wiring: what is handed on, retried, fixed, refused and written,
which tier each call used, and that code decides every time. It does not show that a model can write those answers:
that is what the Phase 1 spike and the Phase 5 gate measure.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from tests.adam import stages
from tests.adam.test_system import NAME, World
from tests.adam.test_system import route as route_staged
from tests.adam.test_system import run as run_staged
from tests.adam.test_system import script_routes as stages_routes

from contracts.adam.stored import StoredPlan
from hiru_ai.core import llm
from hiru_ai.core.settings import get_settings
from hiru_ai.core.testing import RoutedChatModel
from hiru_ai.systems.adam.adam_shot_planner import graph, ladder
from hiru_ai.systems.adam.adam_shot_planner import scene as planner

MARKS = {"adam_take": "the planner of Shot Planner Adam", "adam_sound_designer": "the Sound Designer",
         "adam_critic": "the critic of Shot Planner Adam", "adam_fixer": "the Fixer of Shot Planner Adam"}
LENSES = ("audience", "editor", "opportunity", "fidelity")
MASTER = stages.master_with_stance(NAME)
# Dasun's own card; its one moment is an elaboration, so a take without it breaks nothing, it only leaves a hole
HOLE_CARD = 11


def route(messages: list[Any]) -> str:
    system = str(messages[0].content)
    return next(k for k, mark in MARKS.items() if mark in system)


def per_tier(model: RoutedChatModel) -> Any:
    """One model instance per tier that shares the routes and the record of calls: `model.models` lists the tiers."""
    return lambda tier: model.model_copy(update={"model_name": tier.name})


def critic(*notes: dict[str, Any]) -> dict[str, Any]:
    return {"notes": list(notes), "scores": [{"lens": lens, "score": 4} for lens in LENSES]}


def note(card: int, text: str, *, severity: str = "high", kind: str = "change", cell: str = "",
         lens: str = "editor") -> dict[str, Any]:
    return {"lens": lens, "card": card, "severity": severity, "kind": kind, "cell": cell, "note": text}


def take_without(card_number: int) -> dict[str, Any]:
    reply = stages.replies("adam_take", NAME)
    reply["cards"]["cards"] = [c for n, c in enumerate(reply["cards"]["cards"], start=1) if n != card_number]
    return reply


def sound_for(p: Any) -> dict[str, Any]:
    return dict(stages.sound_wire(p).model_dump(mode="json"))


def routes_for(take: dict[str, Any] | None = None, *, fixers: list[Any] | None = None, critic_says: Any = None,
               sound: dict[str, Any] | None = None) -> dict[str, list[Any]]:
    return {"adam_take": [take or stages.replies("adam_take", NAME)],
            "adam_sound_designer": [sound or stages.replies("adam_sound_designer", NAME)],
            "adam_critic": [critic_says if critic_says is not None else critic()],
            "adam_fixer": list(fixers or [])}


def insert_back(after: int, card_number: int = HOLE_CARD, *, remove: str = "") -> dict[str, Any]:
    """A fixer's answer that gives the missing face its card again: the master's own card, inserted after `after`."""
    ops = [{"op": "insert_card", "why": "the missing face", "number": after, "after": "", "id": "",
            "card": stages.card_wire(MASTER.cards[card_number - 1]).model_dump(mode="json"), "moment": None}]
    if remove:
        ops.append({"op": "remove_moment", "why": "x", "number": 0, "after": "", "id": remove, "card": None,
                    "moment": None})
    return {"operations": ops, "dispositions": [{"note_id": "p1", "done": list(range(1, len(ops) + 1)),
                                                 "declined": ""}]}


def declined(why: str = "the face is already shown") -> dict[str, Any]:
    return {"operations": [], "dispositions": [{"note_id": "p1", "done": [], "declined": why}]}


def run(world: World, routes: dict[str, list[Any]], **state: Any) -> tuple[dict[str, Any], RoutedChatModel]:
    state.setdefault("mode", "take")
    state.setdefault("edit", {})
    model = RoutedChatModel(routes=routes, choose=route, model_name="model")
    with llm.use_models(per_tier(model)):
        return graph.run(world.payload(**state), world.ctx()), model


def stored_of(world: World) -> StoredPlan:
    stored = StoredPlan.load(world.row()["adam"])
    assert stored is not None
    return stored


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(planner, "TAKE_BACKOFF_S", 0.0)


# ── the whole scene in one take ──────────────────────────────────────────────────────────────────


def test_the_gold_scene_is_planned_in_three_model_calls_and_written_as_thirteen_shots():
    world = World()
    out, model = run(world, routes_for())
    assert out == {"scenes": 1, "skipped": 0, "shots": 13, "failed": 0} and world.jobs.status == "done"
    assert [route(c) for c in model.calls] == ["adam_take", "adam_sound_designer", "adam_critic"]
    assert model.models == ["high", "medium", "medium"]  # one gpt-5 call; the rest are small
    stored = stored_of(world)
    assert stored.cards == MASTER.cards and stored.moments == MASTER.moments and stored.staging == MASTER.staging
    assert stored.chosen == stages.stance_of(NAME) and stored.chosen_by == "model" and len(stored.alternates) == 2
    assert stored.report["mode"] == "take" and stored.report["score"]["percent"] == 100.0
    assert stored.report["fidelity"]["ok"] and stored.report["fit"]["overruns"] == 0
    assert stored.report["coverage"]["coverage"] == 1.0 and stored.report["ledger"]["ok"]
    assert [e["kind"] for e in stored.report["history"]["events"]] == ["written", "notes", "kept"]
    assert stored.report["screening"]["ran"] and stored.report["screening"]["kept"] == "first"
    assert stored.input_hash and len(world.shots()) == 13 and all(s["planner"] == "adam" for s in world.shots())


def test_the_take_is_given_the_facts_and_a_person_s_removed_additions_in_words():
    world = World()
    _, model = run(world, routes_for())
    user = str(model.calls[0][1].content)
    assert "<facts>" in user and "shortest take that holds it alone" in user and "<removed>" not in user
    assert "<given_analysis>" not in user and "<stance>" not in user


def test_a_take_that_cannot_be_made_is_asked_once_more_and_a_second_failure_names_the_classic_planner():
    world = World()
    routes = routes_for()
    routes["adam_take"] = [RuntimeError("down"), stages.replies("adam_take", NAME)]
    _, model = run(world, routes)
    assert world.jobs.status == "done" and [route(c) for c in model.calls].count("adam_take") == 2
    assert any("asking once more" in line for line in stored_of(world).report["log"])
    dead = World()
    routes["adam_take"] = [RuntimeError("down"), RuntimeError("down")]
    run(dead, routes)
    assert dead.jobs.status == "failed" and "classic planner" in dead.jobs.fields["error"] and not dead.shots()


def test_a_take_that_breaks_the_script_is_sent_back_once_with_its_reasons_and_then_planned():
    world = World()
    good = stages.replies("adam_take", NAME)
    bad = stages.replies("adam_take", NAME)
    bad["moments"]["moments"] = [m for m in bad["moments"]["moments"] if m["lines"] != ["L4"]]
    routes = routes_for()
    routes["adam_take"] = [bad, good]
    _, model = run(world, routes)
    sent_back = [c for c in model.calls if route(c) == "adam_take"][1]
    assert "<notes>" in str(sent_back[1].content) and "L4" in str(sent_back[1].content)
    stored = stored_of(world)
    assert any(e["kind"] == "sent_back" for e in stored.report["history"]["events"]) and world.jobs.status == "done"
    twice = World()
    routes["adam_take"] = [bad, bad]
    run(twice, routes)
    assert twice.jobs.status == "failed" and "classic planner" in twice.jobs.fields["error"] and not twice.shots()


def test_a_line_on_the_wrong_card_is_moved_by_code_and_costs_no_model_call():
    """Rung 0: the one fault code mends with no judgement. The take binds L4 to the card before its own."""
    world = World()
    take = stages.replies("adam_take", NAME)
    cards = take["cards"]["cards"]
    home = next(i for i, c in enumerate(cards) if any(ln["line_id"] == "L4" for ln in c["lines"]))
    moved = cards[home]["lines"][:]
    cards[home]["lines"] = []
    cards[home - 1]["lines"] = cards[home - 1]["lines"] + moved
    _, model = run(world, routes_for(take))
    stored = stored_of(world)
    assert stored.cards == MASTER.cards and [route(c) for c in model.calls].count("adam_take") == 1
    assert any(e["kind"] == "mended" for e in stored.report["history"]["events"])
    assert any("line L4" in line for line in stored.report["log"])


def test_an_added_moment_that_invents_a_person_is_dropped_with_its_card_reference_and_the_books_close():
    world = World()
    take = stages.replies("adam_take", NAME)
    moments = take["moments"]["moments"]
    waiter = {**moments[1], "id": "m90", "tier": "elaboration", "kind": "reaction", "who": ["Waiter"],
              "seen": "a waiter looks up", "lines": [], "serves": ["b0"]}
    take["moments"]["moments"] = [*moments, waiter]
    take["cards"]["cards"][0]["moments"] = [*take["cards"]["cards"][0]["moments"], "m90"]
    run(world, routes_for(take))
    stored = stored_of(world)
    assert "m90" not in {m.id for m in stored.moments} and stored.cards[0].moments == MASTER.cards[0].moments
    assert stored.report["moments"]["dropped"] == ["m90"] and stored.report["ledger"]["ok"]
    assert stored.report["ledger"]["buckets"]["dropped_fidelity"] == ["m90"]


def test_the_critic_failing_leaves_the_take_as_it_is_and_the_scene_is_still_planned():
    world = World()
    routes = routes_for()
    routes["adam_critic"] = [RuntimeError("down")]
    run(world, routes)
    stored = stored_of(world)
    assert world.jobs.status == "done" and stored.cards == MASTER.cards
    assert stored.report["screening"]["kept"] == "first" and stored.report["screening"]["notes"] == []
    assert any("critic could not answer" in line for line in stored.report["log"])


def test_without_screening_there_is_no_critic_and_no_ladder():
    world = World()
    _, model = run(world, routes_for(), screening=False)
    assert [route(c) for c in model.calls] == ["adam_take", "adam_sound_designer"]
    assert stored_of(world).report["screening"] == {"ran": False}


# ── the fixer ladder ─────────────────────────────────────────────────────────────────────────────


def hole_world() -> tuple[World, dict[str, Any]]:
    """A take that leaves out Dasun's own card: code finds the hole, no critic is needed to say so."""
    p = MASTER.model_copy(update={"cards": [c.model_copy(update={"number": n}) for n, c in enumerate(
        [c for c in MASTER.cards if c.number != HOLE_CARD], start=1)]})
    return World(), {"take": take_without(HOLE_CARD), "sound": sound_for(p)}


def test_a_missing_face_is_fixed_by_the_small_model_and_the_big_one_is_never_asked():
    world, given = hole_world()
    _, model = run(world, routes_for(given["take"], sound=given["sound"], fixers=[insert_back(HOLE_CARD - 1)]))
    stored = stored_of(world)
    assert [route(c) for c in model.calls] == ["adam_take", "adam_sound_designer", "adam_critic", "adam_fixer"]
    assert model.models == ["high", "medium", "medium", "medium"]  # the fixer's first rung is the small tier
    assert stored.cards == MASTER.cards and stored.report["coverage"]["coverage"] == 1.0
    assert stored.report["score"]["percent"] == 100.0 and stored.report["screening"]["kept"] == "revision"
    (fix,) = stored.report["fixer"]["problems"]
    assert fix["fixed"] and fix["rung"] == 1 and fix["tier"] == "medium" and fix["kind"] == "local"
    assert fix["cell"] == "other:2:dasun" and fix["source"] == "code"
    events = stored.report["history"]["events"]
    assert [e["kind"] for e in events] == ["written", "notes", "fixed", "kept"]
    assert events[2]["rung"] == 1 and events[-1]["which"] == "revision"
    assert stored.report["ledger"]["ok"]


def test_a_fix_code_refuses_goes_up_to_the_big_model_which_is_told_why():
    world, given = hole_world()
    routes = routes_for(given["take"], sound=given["sound"], fixers=[declined(), insert_back(HOLE_CARD - 1)])
    _, model = run(world, routes)
    stored = stored_of(world)
    assert model.models[-2:] == ["medium", "fixer"]  # the second rung is gpt-5 at low effort, not the `high` tier
    (fix,) = stored.report["fixer"]["problems"]
    assert fix["fixed"] and fix["rung"] == 2 and fix["tier"] == "fixer"
    assert [t["stood"] for t in fix["tries"]] == [False, True] and "declined" in fix["tries"][0]["why"][0]
    second = [c for c in model.calls if route(c) == "adam_fixer"][1]
    assert "<earlier>" in str(second[1].content) and "declined" in str(second[1].content)
    assert [e["kind"] for e in stored.report["history"]["events"]] == ["written", "notes", "refused", "fixed", "kept"]


def test_a_problem_no_rung_can_fix_is_reported_never_hidden_and_the_scene_is_still_written():
    world, given = hole_world()
    run(world, routes_for(given["take"], sound=given["sound"], fixers=[declined(), declined("still shown")]))
    stored = stored_of(world)
    assert world.jobs.status == "done" and len(stored.cards) == 12 and len(world.shots()) == 12
    (fix,) = stored.report["fixer"]["problems"]
    assert not fix["fixed"] and fix["reason"].startswith("the fixer declined") and len(fix["tries"]) == 2
    assert stored.report["coverage"]["holes"][0]["cell"] == "other:2:dasun"  # the plan says what it still lacks
    assert stored.report["screening"]["kept"] == "first"
    assert stored.report["history"]["events"][-2]["kind"] == "reported"


def test_a_fix_for_a_fault_of_code_never_removes_a_moment():
    world, given = hole_world()
    greedy = insert_back(HOLE_CARD - 1, remove="m8")  # also drops Dasun's listener card
    run(world, routes_for(given["take"], sound=given["sound"], fixers=[greedy, insert_back(HOLE_CARD - 1)]))
    stored = stored_of(world)
    (fix,) = stored.report["fixer"]["problems"]
    assert "never removes a moment" in fix["tries"][0]["why"][0] and fix["rung"] == 2 and "m8" in {
        m.id for m in stored.moments}


def test_a_fixer_that_cannot_answer_is_a_rung_that_failed_not_a_scene_that_did():
    world, given = hole_world()
    run(world, routes_for(given["take"], sound=given["sound"], fixers=[RuntimeError("down"),
                                                                       insert_back(HOLE_CARD - 1)]))
    (fix,) = stored_of(world).report["fixer"]["problems"]
    assert fix["fixed"] and fix["rung"] == 2 and "could not answer" in fix["tries"][0]["why"][0]


def test_a_high_note_is_a_problem_and_a_lower_one_is_only_kept_for_a_person():
    world = World()
    fix = {"operations": [{"op": "replace_card", "why": "n1", "number": 2, "after": "", "id": "", "moment": None,
                           "card": stages.card_wire(MASTER.cards[1]).model_dump(mode="json")}],
           "dispositions": [{"note_id": "n1", "done": [1], "declined": ""}]}
    says = critic(note(2, "Hold the face a beat longer before the cut."),
                  note(3, "A polish on the cut.", severity="low", lens="audience"))
    _, model = run(world, routes_for(critic_says=says, fixers=[fix]))
    stored = stored_of(world)
    assert [route(c) for c in model.calls].count("adam_fixer") == 1  # only the high note
    ledger = {r["id"]: r for r in stored.report["screening"]["revision"]["ledger"]}
    assert ledger["n1"]["answered"] and ledger["n1"]["done"] == [1] and ledger["n1"]["severity"] == "high"
    assert not ledger["n2"]["answered"] and ledger["n2"]["done"] == []  # kept in the report for a person
    (done,) = stored.report["fixer"]["problems"]
    assert done["source"] == "note" and done["note_id"] == "n1" and done["fixed"]
    assert stored.cards == MASTER.cards and stored.report["ledger"]["ok"]


def test_a_note_that_names_a_hole_s_cell_is_that_holes_problem_so_one_fix_answers_both():
    world, given = hole_world()
    says = critic(note(10, "Dasun's face is never in frame when the call turns.", kind="add", cell="other:2:dasun",
                       lens="audience"))
    _, model = run(world, routes_for(given["take"], sound=given["sound"], critic_says=says,
                                     fixers=[insert_back(HOLE_CARD - 1)]))
    stored = stored_of(world)
    (fix,) = stored.report["fixer"]["problems"]
    assert fix["note_id"] == "n1" and fix["source"] == "code" and fix["fixed"]
    assert [route(c) for c in model.calls].count("adam_fixer") == 1
    ledger = stored.report["screening"]["revision"]["ledger"]
    assert ledger[0]["id"] == "n1" and ledger[0]["answered"] and ledger[0]["done"]


def test_moving_a_kind_to_a_stronger_tier_is_one_word_in_fixer_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg = tmp_path / "fixer.yaml"
    cfg.write_text("rounds: 2\ntiers: {small: medium, big: fixer}\nkinds:\n  local: [big]\n  creative: [small, big]\n",
                   encoding="utf-8")
    monkeypatch.setattr(ladder, "CONFIG", cfg)
    world, given = hole_world()
    _, model = run(world, routes_for(given["take"], sound=given["sound"], fixers=[insert_back(HOLE_CARD - 1)]))
    assert model.models[-1] == "fixer" and stored_of(world).report["fixer"]["problems"][0]["rung"] == 1


def test_the_ladders_settings_are_checked_and_say_which_tier_each_rung_runs_on():
    config = ladder.load_config()
    assert config.rounds == 2 and config.rungs("local") == [("small", "medium"), ("big", "fixer")]
    assert config.rungs("creative") == [("small", "medium"), ("big", "fixer")]
    assert config.rungs("mechanical") == config.rungs("local")  # a mechanical fault code could not mend has a card


def test_a_bad_fixer_setting_is_refused_with_its_reasons(tmp_path: Path):
    bad = tmp_path / "fixer.yaml"
    bad.write_text("rounds: 9\ntiers: {small: nonesuch}\nkinds:\n  local: [small, huge]\n", encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        ladder.load_config(bad)
    text = str(exc.value)
    assert "nonesuch" in text and "huge" in text and "rounds is 9" in text


# ── reuse, switching and the mode ────────────────────────────────────────────────────────────────


def test_a_scene_whose_input_is_unchanged_is_kept_unless_the_delivery_says_to_plan_again():
    world = World()
    run(world, routes_for())
    first = stored_of(world)
    again, model = run(world, {})  # a rebuild: no model call is scripted, none may be made
    assert not model.calls and again["scenes"] == 0 and again["skipped"] == 1 and stored_of(world) == first
    forced, model = run(world, routes_for(), replan=True)
    assert route(model.calls[0]) == "adam_take" and forced["scenes"] == 1
    other = World()
    run(other, routes_for())
    other.row()["note"] = "play it colder"  # the script's surroundings changed: the hash differs
    changed, model = run(other, routes_for())
    assert model.calls and changed["scenes"] == 1


def test_the_two_modes_do_not_share_a_hash_and_a_removed_addition_changes_it():
    world = World()
    script, ids = planner.script_of(world.scene, world.scenes.lines(world.scene_id), cast=["Anudi"], place="x",
                                    objects=[])
    from hiru_ai.core.context import RunContext

    a = planner.Planner(RunContext(), script, context={}, line_ids=ids, removed=[])
    b = planner.Planner(RunContext(), script, context={}, line_ids=ids, removed=[])
    assert a.input_hash("take") == b.input_hash("take") != a.input_hash("staged")
    b.removed = [planner.Removed(kind="hands", blocks=[3])]
    assert a.input_hash("take") != b.input_hash("take")


def test_switching_the_treatment_in_take_mode_keeps_the_analysis_and_asks_the_take_again_with_the_stance():
    world = World()
    run(world, routes_for())
    first = stored_of(world)
    other = first.alternates[0].stance
    again = stages.replies("adam_take", NAME)
    again["treatment"] = {**again["treatment"], "stance": other}
    again["analysis"]["about"] = "something the stored analysis must win over"
    _, model = run(world, routes_for(again), edit={"treatment": other})
    user = str(model.calls[0][1].content)
    assert "<given_analysis>" in user and f"<stance>\n{other}\n</stance>" in user
    stored = stored_of(world)
    assert stored.chosen == other and stored.chosen_by == "person" and stored.analysis.about == first.analysis.about
    assert first.treatment.stance in {t.stance for t in stored.alternates} and len(stored.alternates) == 2


def test_a_person_taking_an_elaboration_out_needs_no_model_in_either_mode():
    world = World()
    run(world, routes_for())
    before = stored_of(world)
    gone = next(m for m in before.moments if m.tier == "elaboration" and any(c.moments == [m.id] for c in before.cards))
    model = RoutedChatModel(routes={}, choose=route)
    with llm.use_models(model):
        out = graph.run(world.payload(mode="take", edit={"remove_moment": gone.id}), world.ctx())
    after = stored_of(world)
    assert out["scenes"] == 1 and not model.calls and gone.id not in {m.id for m in after.moments}
    assert after.report["ledger"]["ok"] and after.report["mode"] == "take"
    assert after.input_hash != before.input_hash  # the removal is part of what Adam is given now


def test_the_mode_comes_from_the_setting_unless_the_delivery_names_one(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ADAM_MODE", "take")
    get_settings.cache_clear()
    world = World()
    _, model = run(world, routes_for(), mode="")
    assert route(model.calls[0]) == "adam_take"
    monkeypatch.setenv("ADAM_MODE", "nonsense")  # a mode nobody knows is the staged one
    get_settings.cache_clear()
    odd = World()
    _, model = run(odd, stages_routes(), mode="")
    assert route_staged(model.calls[0]) == "adam_dramaturg"


def test_a_staged_plan_and_a_take_plan_have_the_same_shape_for_everything_that_reads_them():
    staged, took = World(), World()
    run_staged(staged, stages_routes())
    run(took, routes_for())
    a, b = stored_of(staged), stored_of(took)
    assert set(a.report) - {"mode", "fixer", "treatments"} == set(b.report) - {"mode", "fixer", "treatments"}
    assert a.cards == b.cards and a.moments == b.moments and a.staging == b.staging and a.sound_map == b.sound_map
    assert set(a.report["screening"]) == set(b.report["screening"])


def test_a_card_a_fixer_inserts_in_the_wrong_place_is_put_where_its_moment_is_by_code():
    """The first real build's commonest refusal (17 of 26) was "they put the moments in a different order":
    the fixer added a card a few places from its moment's. Code orders the cards by the moments they show."""
    world, given = hole_world()
    _, model = run(world, routes_for(given["take"], sound=given["sound"], fixers=[insert_back(2)]))  # the face is at 11
    stored = stored_of(world)
    (fix,) = stored.report["fixer"]["problems"]
    assert fix["fixed"] and fix["rung"] == 1 and [route(c) for c in model.calls].count("adam_fixer") == 1
    assert [c.moments for c in stored.cards] == [c.moments for c in MASTER.cards] and len(stored.cards) == 13
    assert [c.number for c in stored.cards] == list(range(1, 14))


def test_in_moment_order_changes_no_card_and_leaves_an_ordered_plan_alone():
    cards, moved = ladder.in_moment_order(MASTER.moments, MASTER.cards)
    assert cards == MASTER.cards and moved == {n: n for n in range(1, 14)}
    shuffled = [MASTER.cards[1], MASTER.cards[0], *MASTER.cards[2:]]
    shuffled = [c.model_copy(update={"number": n}) for n, c in enumerate(shuffled, start=1)]
    again, moved = ladder.in_moment_order(MASTER.moments, shuffled)
    assert [c.moments for c in again] == [c.moments for c in MASTER.cards] and moved[1] == 2 and moved[2] == 1
