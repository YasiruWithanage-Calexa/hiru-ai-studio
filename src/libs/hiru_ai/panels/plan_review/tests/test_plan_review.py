"""plan_review against `pipeline.plan_scene` (the splitter's critic round) and the critics_judge pattern's rules."""
from __future__ import annotations

from typing import Any

from script_split.engine import pipeline, planner
from tests.hiru_ai.steps_fixtures import felt_scene
from tests.services.fakes import FakeLLM

from contracts import reading as scene_reading
from contracts import sceneplan, stagemap
from contracts.shotplan import ProposedShot, fit
from hiru_ai.core import llm
from hiru_ai.core.context import RunContext
from hiru_ai.core.testing import RoutedChatModel
from hiru_ai.panels.plan_review import graph
from hiru_ai.steps.scene_listing.logic import scene_listing

LENS_MARK = {"coverage": "COVERAGE editor", "emotion": "EMOTION editor", "editor": "EDITOR and"}
ENVELOPE = 24


def shot(start: int, end: int, framing: str, title: str, sound: str = "dialogue", duration: int = 8) -> dict[str, Any]:
    return {"start": start, "end": end, "framing": framing, "title": title, "sound_mode": sound, "duration": duration,
            "camera_link": "cut"}


def scene_inputs() -> dict[str, Any]:
    scene, lines, _ = felt_scene()
    reading = scene_reading.SceneReading.of(scene)
    items = scene_reading.apply(sceneplan.scene_items(scene, lines), reading)
    n = len(items)
    plan1 = {"shots": [shot(0, n, "WIDE", "Everything at once")]}
    plan2 = {"shots": [shot(0, n // 2, "WIDE", "Kasun at the stall"), shot(n // 2, n, "CU", "Anudi takes the call")]}
    names = {str(ln.get("character_id")): "Kasun" for ln in lines}
    return {"scene": scene, "reading": reading, "items": items, "plans": [plan1, plan2], "names": names}


def legacy_run(case: dict[str, Any], critics: dict[str, Any], plans: list[dict[str, Any]]) -> Any:
    queue = list(plans)

    def critic(system: str, user: str) -> dict[str, Any]:
        lens = next(name for name, mark in LENS_MARK.items() if mark in system)
        if lens not in critics:
            raise RuntimeError("down")
        return critics[lens]  # type: ignore[no-any-return]

    llm_ = FakeLLM({"shot_plan": lambda s, u: queue.pop(0), "shot_review": critic})
    scene = case["scene"]
    return pipeline.plan_scene(case["items"], heading=scene["heading"], envelope_s=ENVELOPE, fixed=None, llm=llm_,
                               speaker_names=case["names"], reading=case["reading"],
                               staging=stagemap.SceneStaging.of(scene))


def proposal(raw: dict[str, Any]) -> list[ProposedShot]:
    return [ProposedShot(s["start"], s["end"], s["framing"], s["title"], s["sound_mode"], s["duration"], False,
                         s["camera_link"]) for s in raw["shots"]]


def panel_run(case: dict[str, Any], critics: dict[str, Any], plans: list[dict[str, Any]], **graph_args: Any) -> Any:
    """What the splitter does around the panel: a first model plan, the panel, then the rules' plan as a rival."""
    scene = case["scene"]
    staging = stagemap.SceneStaging.of(scene)
    items = case["items"]
    first = fit(items, proposal(plans[0]), envelope_s=ENVELOPE, fixed_seconds=None)
    brief = {
        "items": items, "reading": case["reading"], "staging": staging, "cast": list(case["names"].values()),
        "listing": scene_listing(items, case["names"]), "reading_text": case["reading"].text(),
        "staging_text": staging.text() if staging else "",
        "found": [f.message for f in stagemap.checks(staging, items, first, list(case["names"].values()))],
        "plan_input": {"items": items, "speaker_names": case["names"], "heading": scene["heading"],
                       "envelope_s": ENVELOPE, "allowed": [4, 6, 8], "context": "", "reading": case["reading"].text()},
        "envelope_s": ENVELOPE, "fixed_seconds": None}
    replies: dict[str, list[Any]] = {"planner": [plans[1]] if len(plans) > 1 else [],
                                     **{lens: [critics[lens]] for lens in critics}}

    def route(messages: list[Any]) -> str:
        system = str(messages[0].content)
        return next((lens for lens, mark in LENS_MARK.items() if mark in system), "planner")

    with llm.use_models(RoutedChatModel(routes=replies, choose=route)):
        built = graph.build(RunContext(), **graph_args)
        lenses = graph.lenses(graph.PanelKit(graph.ID, manifest=graph_args.get("manifest")))
        out = built.invoke({"brief": brief, "candidates": [first], "lenses": lenses})
    return out, brief


def decide(out: dict[str, Any], brief: dict[str, Any]) -> tuple[Any, str]:
    """The splitter's last step: the panel's winner against the rules' plan."""
    from hiru_ai.steps.kernel_score.logic import kernel_score

    best = out["candidates"][out["winner"]]
    rules_items, rules_shots = planner.rules_plan(brief["items"], envelope_s=ENVELOPE, fixed_seconds=None)
    rules = fit(rules_items, rules_shots, envelope_s=ENVELOPE, fixed_seconds=None)

    def score(r: Any) -> Any:
        return kernel_score(r, brief["reading"], rules_items if r is rules else brief["items"], brief["staging"],
                            brief["cast"])

    return (rules, "rules") if score(rules) < score(best) else (best, "model")


NOTE = {"acceptable": False, "notes": [{"note": "S01 never changes size", "severity": 1}]}
CONTENT = {"acceptable": True, "notes": []}


def titles(result: Any) -> list[str]:
    return [s.title for s in result.shots]


def test_the_panel_picks_the_same_plan_and_notes_as_the_splitters_critic_round():
    case = scene_inputs()
    critics = {"coverage": NOTE, "emotion": CONTENT, "editor": {"acceptable": False, "notes": [
        {"note": "Cut on the look", "severity": 2}]}}
    legacy, used, notes = legacy_run(case, critics, case["plans"])
    out, brief = panel_run(case, critics, case["plans"])
    result, _ = decide(out, brief)
    assert out["notes"] == notes == ["S01 never changes size", "Cut on the look"]
    assert titles(result) == titles(legacy)
    assert len(out["candidates"]) == 2  # one revision, never more
    assert titles(result) in (titles(decide(out, brief)[0]),) and used in ("model", "rules")


def test_content_critics_leave_the_first_plan_and_ask_the_planner_nothing():
    case = scene_inputs()
    critics = {"coverage": CONTENT, "emotion": CONTENT, "editor": CONTENT}
    legacy, _, _ = legacy_run(case, critics, case["plans"][:1])
    out, brief = panel_run(case, critics, case["plans"][:1])
    assert out["notes"] == [] and out["winner"] == 0 and len(out["candidates"]) == 1
    assert titles(decide(out, brief)[0]) == titles(legacy)


def test_a_failed_critic_is_left_out_and_the_others_still_count():
    case = scene_inputs()
    critics = {"coverage": NOTE}  # emotion and editor have no reply: they fail
    legacy, _, notes = legacy_run(case, critics, case["plans"])
    out, brief = panel_run(case, critics, case["plans"])
    assert out["notes"] == notes == ["S01 never changes size"]
    assert titles(decide(out, brief)[0]) == titles(legacy)


def test_every_critic_failing_keeps_the_first_plan():
    case = scene_inputs()
    legacy, _, notes = legacy_run(case, {}, case["plans"][:1])
    out, brief = panel_run(case, {}, case["plans"][:1])
    assert out["notes"] == [] and out["winner"] == 0
    assert titles(decide(out, brief)[0]) == titles(legacy) and notes == []


def test_a_planner_that_fails_keeps_the_first_plan_and_the_notes():
    case = scene_inputs()
    out, _ = panel_run(case, {"coverage": NOTE}, case["plans"][:1])  # no second plan scripted: the planner is down
    assert out["notes"] == ["S01 never changes size"] and out["winner"] == 0 and len(out["candidates"]) == 1


def test_switching_a_critic_off_in_the_manifest_removes_its_lens_from_the_graph():
    kit = graph.PanelKit(graph.ID)
    smaller = kit.manifest.model_copy(update={"members": [m for m in kit.manifest.members if m.label != "emotion"]})
    assert graph.lenses(graph.PanelKit(graph.ID, manifest=smaller)) == ["coverage", "editor"]
    case = scene_inputs()
    out, _ = panel_run(case, {"coverage": NOTE, "editor": CONTENT}, case["plans"], manifest=smaller)
    assert out["notes"] == ["S01 never changes size"] and len(out["results"]) == 2


def test_across_plan_pairs_the_panel_and_the_splitter_choose_alike_and_the_revision_wins_only_when_strictly_better():
    import itertools

    case = scene_inputs()
    n = len(case["items"])
    _, rules_shots = planner.rules_plan(case["items"], envelope_s=ENVELOPE, fixed_seconds=None)
    variants = {
        "one shot": [shot(0, n, "WIDE", "One")],
        "the rules' shape": [shot(s.start, s.end, s.framing, s.title) for s in rules_shots],
        "two shots": [shot(0, 2, "WIDE", "a", "ambient", 6), shot(2, n, "MCU", "b")]}
    critics = {"coverage": NOTE, "emotion": CONTENT, "editor": CONTENT}
    winners = set()
    for first, second in itertools.permutations(variants, 2):
        plans = [{"shots": variants[first]}, {"shots": variants[second]}]
        legacy, _, _ = legacy_run(case, critics, plans)
        out, brief = panel_run(case, critics, plans)
        assert titles(decide(out, brief)[0]) == titles(legacy), (first, second)
        winners.add(out["winner"])
    assert winners == {0, 1}  # the revision is taken in some pairs and refused in others
