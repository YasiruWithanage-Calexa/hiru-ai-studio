# The Adam gold set (plan/2026-11-04b §8)

A system cannot get better than the yardstick it is judged by. This folder is that yardstick.

```
scenes/<id>.yaml      the scene: SceneScript (blocks, cast, place), what kind of scene it covers
masters/<id>.yaml     the MASTER breakdown: an AdamPlan in the card format of §5.1, plus a director's note on why
baselines/<id>.yaml   what script_split stores for the scene (`shots` rows), for the blind A/B and the score comparison
treatments/<id>.yaml  the two other treatments of the scene (the master's own is the third): drafts, in the director's wire shape
RUBRIC.md             how a person judges a plan (Murch's order, "I felt I was there", the mute test)
ab_form.json          the blind A/B record: two unlabelled plans, 1-5 on each lens
```

## Status (honest)

| | Now | Target |
|---|---|---|
| Scenes | 5 of 15: `phone_call`, `father_refuses`, `silent_morning`, `refuses_money`, `arrival` | 15 before Phase 10 (§8.1) |
| Masters | 5 of 15, **all `status: draft`** | at least 5 before Phase 3 (met as drafts), all 15 before Phase 10 |
| Who wrote them | Claude drafted them from the plan's §9 (the person's test scene) and from the 3-episode drama fixture; the **wording of every scene is a draft** | The person and a Hiru director correct each master (§12 D6) and flip `status` to `approved` |
| Baselines | **hand estimates** of `script_split` (5-6 shots for the test scene, as §1 says), marked `source: hand estimate` | `script_split` run on each gold scene live, by a person, plans stored (Phase 0 step 2) |

The tests in `tests/adam/test_gold.py` hold every master to the code rules (fidelity, fit, continuity, feasibility)
and require it to out-score its baseline. They prove the masters are internally consistent and that the code can tell
a vivid plan from a flat one. They do NOT prove the masters are good: that is a Hiru director's judgement, which is
what the status field records.

## The score is held to the masters

`tests/adam/test_score_mutations.py` breaks each master on purpose (`tests/adam/mutants.py`: the other person's moments
removed, a bare plan, the break moved, a flat size arc, an own line over hands, the irony face cut, adjacent cards merged)
and requires the score to drop by a point of 100 for each. `hiru-ai eval` prints the mutation score. A change to the
score must keep it at 100 % of the mutants that are faults; what the score cannot see is named in `mutants.BLIND_SPOTS`
(today: a bare `silent_morning`). `live/phone_call.json` is the saved plan of the third live run (2026-11-04), kept as the
yardstick's worst case: its score must stay well below the master's.

## Remaining scene kinds to cover (§8.1)

The test scene (a call that breaks a mood), an argument (`father_refuses`), a silent scene (`silent_morning`), a
confession (`refuses_money`) and an arrival (`arrival`) are drafted. Still to write, with the team: a group scene, a
walk-and-talk, a scene with a STORY NOTE, a comedy beat, a scene with narration, an exit watched, a scene in one wide
place, a scene in a vehicle, a night scene, a song or prayer.

## Adding a scene

1. `scenes/<id>.yaml`: the blocks of a real script, the people present, the location card's objects.
2. `masters/<id>.yaml`: the plan, written by the director, in the card format. Quote every text value that has a comma.
3. `baselines/<id>.yaml`: `script_split`'s stored shots for the scene.
4. `pytest tests/adam/test_gold.py`: the master must pass the code rules and beat the baseline.
5. A director reads it, corrects it, and sets `status: approved` in the master's header.

Dialogue stays in the language the script was written in. A master never contains a line of its own: lines are named
by id (`L1`) and bound to the script's words by code.
