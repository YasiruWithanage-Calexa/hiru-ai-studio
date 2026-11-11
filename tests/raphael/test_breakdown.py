"""The director's breakdown (plan/2026-11-10): its wire shape, its code check, its blocks in the openings, and the
planner's flow with a scripted model (one request, one retry, a fall-back, the stored breakdown reused). No model is
called."""

from __future__ import annotations

from typing import Any

from contracts.raphael import checks, pack
from contracts.raphael.bin import Bin
from contracts.raphael.wire import BreakdownW
from hiru_ai.core import llm
from tests.raphael import gold, world
from tests.raphael.test_system import planner
from tests.raphael.world import World


def shots(**override: Any) -> list[dict[str, Any]]:
    """One story shot per block of the gold scene (60 s), the line of a block on its shot."""
    scene = gold.scene()
    n = len(scene.blocks)
    out = []
    for i, b in enumerate(sorted(scene.blocks, key=lambda x: x.index), start=1):
        out.append(
            {
                "n": i,
                "blocks": [b.index],
                "lines": [b.line_id] if b.line_id else [],
                "kind": "story",
                "size": "MS",
                "lens": "50 mm",
                "move": "locked_off",
                "action": f"What block {b.index} shows.",
                "why": "It tells the beat.",
                "must_read": "The face.",
                "about_s": 60 / n,
                **override,
            }
        )
    return out


def breakdown(items: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "objective": "Two strangers meet in the rain.",
        "direction": {"palette": "wet grey", "camera": "patient", "lens": "50 mm", "sound": "rain"},
        "shots": items if items is not None else shots(),
        "notes": ["She does not scream."],
    }


def made(items: list[dict[str, Any]] | None = None) -> BreakdownW:
    return BreakdownW.model_validate(breakdown(items))


# ── the code check ───────────────────────────────────────────────────────────────────────────────


def test_a_good_breakdown_has_no_faults() -> None:
    assert checks.breakdown_faults(gold.brief(), made()) == []


def test_a_block_in_no_shot_is_a_fault() -> None:
    items = [s for s in shots() if s["blocks"] != [5]]
    for k, s in enumerate(items, start=1):
        s["n"], s["about_s"] = k, 60 / len(items)
    found = checks.breakdown_faults(gold.brief(), made(items))
    assert any("b5" in f and "no shot" in f for f in found)


def test_shots_out_of_the_scripts_order_are_a_fault() -> None:
    items = shots()
    items[3], items[4] = items[4], items[3]
    assert any("order" in f for f in checks.breakdown_faults(gold.brief(), made(items)))


def test_a_line_must_sit_on_exactly_one_story_shot() -> None:
    twice = shots()
    twice[0]["lines"] = ["L3"]  # L3 is on its own shot too
    assert any("L3" in f for f in checks.breakdown_faults(gold.brief(), made(twice)))
    detail = shots()
    next(s for s in detail if s["lines"] == ["L7"])["kind"] = "detail"
    assert any("L7" in f for f in checks.breakdown_faults(gold.brief(), made(detail)))
    unknown = shots()
    unknown[0]["lines"] = ["L99"]
    assert any("L99" in f for f in checks.breakdown_faults(gold.brief(), made(unknown)))
    missing = shots()
    next(s for s in missing if s["lines"] == ["L9"])["lines"] = []
    assert any("L9" in f and "no shot" in f for f in checks.breakdown_faults(gold.brief(), made(missing)))


def test_a_voice_only_person_is_never_in_an_action() -> None:
    items = shots()
    items[15]["action"] = "Father shouts into the phone."
    assert any("Father" in f for f in checks.breakdown_faults(gold.brief(), made(items)))


def test_the_seconds_are_held_between_the_floor_and_stage_1s_cap() -> None:
    n = len(shots())
    assert any("add up" in f for f in checks.breakdown_faults(gold.brief(), made(shots(about_s=20 / n))))  # < 48 s
    assert any("add up" in f for f in checks.breakdown_faults(gold.brief(), made(shots(about_s=120 / n))))  # > 90 s
    assert checks.breakdown_faults(gold.brief(), made(shots(about_s=75 / n))) == []


def test_a_breakdown_shot_with_no_must_clip_on_its_blocks_is_a_report_not_a_block() -> None:
    work = gold.stage1()
    covered = {b for c in work.musts() for b in c.blocks}
    assert checks.breakdown_missing(made(), work) == [] or all(
        f.fix == "report" for f in checks.breakdown_missing(made(), work)
    )
    empty = Bin(scene="1")
    found = checks.breakdown_missing(made(), empty)
    assert len(found) == len(shots()) and all(
        f.fix == "report" and f.key.startswith("breakdown:missing:") for f in found
    )
    assert checks.breakdown_missing(None, empty) == [] and covered


# ── the blocks in the openings ───────────────────────────────────────────────────────────────────


def test_stage_1_gets_the_whole_breakdown_after_length_and_stage_2_the_shot_list_only() -> None:
    w = World()
    p = planner(w)
    plain = pack.opening_stage1(p.production, p.context, p.brief, "")
    with_it = pack.opening_stage1(p.production, p.context, p.brief, "", made())
    assert with_it.index("<length>") < with_it.index("<breakdown>") < with_it.index("Plan this scene.")
    assert "Objective: Two strangers meet in the rain." in with_it and "Must read: The face." in with_it
    assert plain == with_it.replace(pack.breakdown_block(made()) + "\n\n", "")  # nothing else changed
    short = pack.breakdown_block(made(), full=False)
    assert "Objective" not in short and "Must read" not in short and "1. [story]" in short
    work = gold.stage1()
    two = pack.opening_stage2(p.production, p.context, p.brief, work, 2, "", made())
    assert short in two and two.index("<breakdown>") < two.index("<intended_cut>")
    assert pack.breakdown_block(None) == ""


# ── the planner ──────────────────────────────────────────────────────────────────────────────────


def run(*replies: Any, reuse: BreakdownW | None = None, on: bool = True) -> tuple[Any, Any]:
    w = World()
    p = planner(w)
    p.use_breakdown = on
    model = world.model_for(list(replies), world.stage1_turns())
    with llm.use_models(model):
        done = p.plan(previous={}, job_id="j1", only_stage1=True, reuse=reuse)
    return done, model


def test_a_breakdown_is_made_stored_and_given_to_stage_1() -> None:
    done, model = run(breakdown())
    stored = done.stored
    assert stored.breakdown is not None and len(stored.breakdown.shots) == len(shots())
    assert stored.stage1 == "finished" and done.warnings == []
    assert any("<breakdown>" in str(m.content) for call_ in model.calls for m in call_ if m.type == "human")
    assert StoredRoundTrip.ok(stored)


class StoredRoundTrip:
    @staticmethod
    def ok(stored: Any) -> bool:
        from contracts.raphael.stored import StoredRaphael

        back = StoredRaphael.load(stored.data())
        return back is not None and back.breakdown == stored.breakdown and back.version == 1


def test_a_breakdown_with_faults_is_asked_again_once_with_the_faults_listed() -> None:
    bad = shots()[1:]  # block 0 is in no shot
    for k, s in enumerate(bad, start=1):
        s["n"] = k
    done, model = run(breakdown(bad), breakdown())
    assert done.stored.breakdown is not None and done.warnings == []
    asks = [
        str(m.content)
        for call_ in model.calls
        for m in call_
        if m.type == "human" and "director's shot" in str(m.content)
    ]
    assert len(asks) == 2 and "Your last breakdown had these problems" in asks[1] and "b0" in asks[1]


def test_a_breakdown_that_fails_twice_leaves_stage_1_as_it_was_and_warns() -> None:
    bad = shots()[1:]
    done, model = run(breakdown(bad), breakdown(bad))
    assert done.stored.breakdown is None and len(done.warnings) == 1 and "planned without it" in done.warnings[0]
    assert done.stored.stage1 == "finished"
    assert not any("<breakdown>" in str(m.content) for call_ in model.calls for m in call_ if m.type == "human")


def test_the_switch_off_is_raphael_as_it_was() -> None:
    done, model = run(on=False)
    assert done.stored.breakdown is None and done.warnings == []
    assert all("director's shot" not in str(m.content) for call_ in model.calls for m in call_ if m.type == "human")


def test_the_same_input_reuses_the_stored_breakdown_and_asks_nothing() -> None:
    kept = made()
    done, model = run(reuse=kept)
    assert done.stored.breakdown == kept
    assert all("director's shot" not in str(m.content) for call_ in model.calls for m in call_ if m.type == "human")


def test_the_hash_does_not_depend_on_the_breakdown() -> None:
    w = World()
    p = planner(w)
    before = p.input_hash()
    p.breakdown = made()
    assert p.input_hash() == before


def test_the_breakdown_call_counts_inside_the_scenes_money_cap() -> None:
    done, _ = run(breakdown())
    assert done.stored.report["calls"] >= 2  # the breakdown request, then stage 1's turns


# ── the shot card (2026-11-10): takes check, the fields reach stage 1, dialogue by code ─────────


def test_takes_must_be_veo_lengths() -> None:
    found = checks.breakdown_faults(gold.brief(), made(shots(takes=[5])))
    assert any("takes" in f and "4, 6 or 8" in f for f in found)
    assert not any("takes" in f for f in checks.breakdown_faults(gold.brief(), made(shots(takes=[6, 4]))))


def test_card_fields_reach_the_stage_1_block_and_old_breakdowns_still_load() -> None:
    b = made(shots(mood="held breath", performance="jaw sets", takes=[8], priority="optional"))
    block = pack.breakdown_block(b)
    assert "Mood: held breath." in block and "Performance: jaw sets." in block
    assert "Takes: 8 s." in block and "Priority: optional." in block
    assert "Mood" not in pack.breakdown_block(made())  # a breakdown without the card: nothing added


def test_the_shot_card_prints_the_dialogue_from_the_script_not_from_the_model() -> None:
    scene = gold.scene()
    line = next(b for b in scene.blocks if b.line_id)
    card = pack.shot_cards(made(), scene)
    assert f'{line.line_id} {line.speaker}: "{line.text}"' in card


# ── a name on a phone screen is welcome (the person, 2026-11-10) ─────────────────────────────────


def test_a_heard_name_on_a_phone_screen_is_not_a_person_in_the_picture() -> None:
    assert checks.mentions_as_person("Mudalali sits in the car.", "Mudalali")
    assert not checks.mentions_as_person("The phone screen lights up with Mudalali's name.", "Mudalali")
    assert not checks.mentions_as_person("A voicemail from Mudalali plays.", "Mudalali")
    assert not checks.mentions_as_person("Dinu waits.", "Mudalali")


def test_the_voice_only_block_allows_the_name_on_a_phone_screen() -> None:
    scene = gold.scene()
    heard = checks.heard_names(scene)
    block = pack.voice_only(scene)
    if heard:  # the gold scene has a phone voice: the block must say the name on a screen is welcome
        assert "phone screen" in block and "welcome" in block


def test_a_phone_shot_that_shows_the_callers_name_is_not_a_fault() -> None:
    assert not checks.mentions_as_person("The phone displays Mudalali's incoming call.", "Mudalali")
    assert not checks.mentions_as_person("Phone with a text-only caller display: Aruni.", "Aruni")
    assert checks.mentions_as_person("Mudalali stands at the door.", "Mudalali")
