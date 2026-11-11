"""plan/2026-11-08f: the fixes after the 2026-11-08 build that cost $3.92 for three scenes, two of which could never
finish. No model is called: the checks and sessions are code, and the conversations are scripted.

  §1  an action longer than any take is shown over consecutive must clips; it no longer fails every clip forever
  §2  the script listing gives each action's seconds
  §3  a must bin under 80 % of the target cannot finish; the length block gives the script's own time
  §4  a stuck scene stops early; a scene has its own money limit; fewer turns
  §6  each scene's calls carry its id
"""

from __future__ import annotations

import pytest

from contracts.raphael import checks, pack
from contracts.raphael.bin import Bin
from contracts.raphael.money import Meter
from contracts.raphael.scene import Brief, SceneS, listing, long_actions, parts_needed, script_s
from contracts.raphael.tools import STAGE1_TURNS, STAGE2_TURNS, STUCK_AFTER, Stage1Session
from contracts.raphael.wire import Clip
from hiru_ai.core import llm
from hiru_ai.systems.raphael.raphael_shot_planner import scene as raphael
from tests.raphael import gold, world
from tests.raphael.test_system import planner
from tests.raphael.world import World

LONG = 1  # gold block b1 ("act", 1.5 s), made a 12.5 s walk below; c01 covers b0-b2


def long_scene(events: int = 5) -> SceneS:
    """The gold scene with b1 read as a walk of `events` events (2.5 s each): longer than any take."""
    scene = gold.scene()
    blocks = [b.model_copy(update={"screen": "move", "events": events}) if b.index == LONG else b for b in scene.blocks]
    return scene.model_copy(update={"blocks": blocks})


def clip_over_long(work: Bin, n: int, *, take: int = 8, handle: float = 1.0) -> Clip:
    """A must clip over b1 alone, silent: one part of the walk."""
    base = work.by_id("c01")
    assert base is not None
    return base.model_copy(
        update={
            "id": f"w{n}",
            "blocks": [LONG],
            "lines": [],
            "take_s": take,
            "handle_in_s": handle,
            "handle_out_s": handle,
        }
    )


def blocking_keys(brief: Brief, work: Bin) -> set[str]:
    return {f.key for f in checks.blocking(checks.check_stage1(brief, work))}


# ── §1 long actions ──────────────────────────────────────────────────────────────────────────────


def test_a_block_longer_than_any_take_is_found_by_code() -> None:
    assert long_actions(long_scene()) == {LONG: 12.5}
    assert long_actions(gold.scene()) == {}  # the lab's scene has none: nothing changes for it
    assert parts_needed(12.5) == 3 and parts_needed(15.0) == 3 and parts_needed(10.0) == 2 and parts_needed(6.0) == 1


def test_before_the_fix_every_clip_over_a_long_action_failed_now_one_clip_shows_a_part() -> None:
    """The live trap: scene 1's 15 s walk. c01 (b0-b2, 6 s, 1 s handles) no longer fails the clock for b1's whole
    12.5 s; it is told it shows too little of the walk."""
    brief = Brief(scene=long_scene(), guide_s=60)
    work = gold.stage1()
    found = blocking_keys(brief, work)
    assert "clock:fit:c01" not in found
    assert "clock:long:1" in found
    long = next(f for f in checks.check_stage1(brief, work) if f.key == "clock:long:1")
    assert "12.5 s action" in long.sentence and "more" in long.sentence and long.clips == ["c01"]


def test_consecutive_must_clips_that_add_up_to_the_action_pass() -> None:
    brief = Brief(scene=long_scene(), guide_s=60)
    work = gold.stage1()
    work.clips = [c.model_copy(update={"blocks": [0, 2]}) if c.id == "c01" else c for c in work.clips]
    work.clips += [clip_over_long(work, 1), clip_over_long(work, 2)]
    assert "clock:long:1" in blocking_keys(brief, work)  # 6 + 6 = 12 s of a 12.5 s walk
    work.clips.append(clip_over_long(work, 3, take=4, handle=0.5))  # + 3 s
    assert not {k for k in blocking_keys(brief, work) if k.startswith("clock")}


def test_a_clip_over_a_long_action_still_needs_room_for_a_part() -> None:
    brief = Brief(scene=long_scene(), guide_s=60)
    work = gold.stage1()
    work.clips.append(clip_over_long(work, 1, take=4, handle=2.0))  # 0 s between its handles
    assert "clock:fit:w1" in blocking_keys(brief, work)


def test_the_gold_bins_still_pass_unchanged() -> None:
    assert checks.blocking(checks.check_stage1(gold.brief(), gold.stage1())) == []
    assert checks.blocking(checks.check_stage2(gold.brief(), gold.final())) == []


# ── §2 the listing ───────────────────────────────────────────────────────────────────────────────


def test_the_listing_gives_every_action_its_seconds_and_marks_a_long_one() -> None:
    rows = listing(long_scene()).splitlines()
    walk = next(r for r in rows if r.startswith(f"b{LONG} "))
    assert "12.5 s on screen, longer than any take" in walk and "3 consecutive clips" in walk
    other = next(r for r in rows if r.startswith("b2 "))
    assert "(1.5 s on screen)" in other


# ── §3 the length floor ──────────────────────────────────────────────────────────────────────────


def test_a_must_bin_far_under_the_target_cannot_finish_and_says_why() -> None:
    brief = Brief(scene=gold.scene(), guide_s=120)  # the gold bin holds 70 s; 80 % of 120 is 96
    found = checks.check_stage1(brief, gold.stage1())
    short = next(f for f in checks.blocking(found) if f.key == "length:short")
    assert "70 s of takes" in short.sentence and "96 s" in short.sentence and "times at" in short.sentence
    assert "length:short" not in blocking_keys(Brief(scene=gold.scene(), guide_s=85), gold.stage1())  # 70 >= 68


def test_stage_2_never_holds_the_locked_must_bin_to_the_floor() -> None:
    brief = Brief(scene=gold.scene(), guide_s=120)
    assert "length:short" not in {f.key for f in checks.check_stage2(brief, gold.final(), cap=3)}


def test_the_length_block_gives_the_scripts_own_time_and_the_floor() -> None:
    block = pack.length_block(Brief(scene=long_scene(), guide_s=120))  # the scene times at 59 s: 61 s is coverage
    assert "The script itself times at 59 s" in block and "the other 61 s of the target is COVERAGE" in block
    assert f"b{LONG} 12.5 s" in block and "a bin under 96 s" in block
    own = script_s(gold.scene())
    tight = pack.length_block(Brief(scene=gold.scene(), guide_s=own))  # no gap, no long action: no coverage line
    assert "COVERAGE" not in tight and "Long actions" not in tight


# ── §4 stops and limits ──────────────────────────────────────────────────────────────────────────


def test_a_session_is_stuck_after_reports_that_do_not_cut_its_faults() -> None:
    work = gold.stage1()
    broken = [
        c.model_copy(update={"take_s": 4, "handle_in_s": 2.0, "handle_out_s": 2.0}) if c.id == "c01" else c
        for c in work.clips
    ]
    run = Stage1Session(gold.brief(), work)
    run.work.clips = broken
    for _ in range(STUCK_AFTER):
        run.report()
        assert not run.stuck
    run.report()
    assert run.stuck and run.blocked >= 1


def test_a_bin_still_being_built_is_never_stuck() -> None:
    run = Stage1Session(gold.brief())  # no edit plan: every report says so
    for _ in range(STUCK_AFTER + 3):
        run.report()
    assert not run.stuck


def test_a_stuck_stage_1_stops_early_keeps_its_clips_and_says_so() -> None:
    w = World()
    turns = world.stage1_turns(finish=False)
    first = gold.stage1().clips[0]
    bad = world.wire(first, id="c01", take_s=4, handle_in_s=2.0, handle_out_s=2.0)
    spin = [world.call("put_clips", {"clips": [bad]}, n) for n in range(20)]
    model = world.model_for(turns, spin)
    with llm.use_models(model):
        done = planner(w).plan(previous={}, job_id="j1")
    stored = done.stored
    assert (stored.stage1, stored.stage2) == ("stopped", "skipped")
    assert stored.stopped == raphael.STOPPED["stuck"]
    assert stored.report["turns"]["stage1"] < STAGE1_TURNS  # it did not use every turn


def test_turn_caps_and_the_scene_money_limit() -> None:
    assert (STAGE1_TURNS, STAGE2_TURNS) == (10, 8)
    p = planner(World())
    assert p.meter.cap_usd == pytest.approx(1.00)  # settings.raphael_scene_cap_usd
    assert planner(World(), meter=Meter(cap_usd=0.4)).meter.cap_usd == pytest.approx(0.4)


# ── a recording in the scene (lab arm C, scene 2) ────────────────────────────────────────────────


def test_a_line_the_action_calls_a_voice_message_is_heard_not_performed() -> None:
    from contracts.raphael.scene import BlockS, is_heard, mark_recorded

    blocks = [
        BlockS(index=0, kind="action", text="Dinu drives. Aruni's voice message plays."),
        BlockS(index=1, kind="dialogue", speaker="Aruni", line_id="L1", text="Nimal thama gedara awilla ne."),
        BlockS(index=2, kind="action", text="Dinu looks at the red thread."),
        BlockS(index=3, kind="dialogue", speaker="Dinu", line_id="L3", text="Hari."),
    ]
    marked = mark_recorded(blocks)
    assert is_heard(marked[1]) and marked[1].delivery == "voice message"
    assert not is_heard(marked[3])  # Dinu's own line is still performed
    # a voice message someone else's action names does not make this speaker heard
    other = [BlockS(index=0, kind="action", text="Kasun's voice message plays."), blocks[1]]
    assert not is_heard(mark_recorded(other)[1])


def test_the_repair_tier_takes_over_once_clips_are_written() -> None:
    from hiru_ai.agents.raphael.raphael_planner import agent as planner_agent
    from hiru_ai.agents.raphael.raphael_planner.schema import Input

    inp = Input.model_validate({"opening": "x", "scene": gold.scene().model_dump(mode="json"), "guide_s": 60})
    run = planner_agent.session(inp)
    later = planner_agent.converse_args(inp, run)["later_when"]
    assert not later(2)  # only the edit plan so far: the first model writes the clips too
    run.work = gold.stage1()
    assert later(3)
