# Shot Planner Raphael

Raw coverage for Hiru's post-production team, planned by **one agent per stage with code tools only**
([plan/2026-11-08e/PLAN.md](../../plan/2026-11-08e/PLAN.md); what is built and what waits for a person:
[IMPLEMENTED.md](../../plan/2026-11-08e/IMPLEMENTED.md)). A **fifth** planner beside `script_split`, Adam, David and Jonathan;
none of them change. Plain words: [human-read.md](../../plan/2026-11-08e/human-read.md).

## What it delivers

A scene's **intended cut** (treatment, sequences, moments: a reference for the editor), a **shoot bin** of clips with a slate
each (`12B-3`), their role, handles, take (4 / 6 / 8 s), priority and the full Veo design, and **notes for the editor**.
The bin has two layers:

| Stage | Agent | Writes | Priority |
|---|---|---|---|
| 1 | `raphael_planner` | the intended cut and the **must** clips (the shots the scene cannot be cut without) | `must` only |
| 2 | `raphael_cinematic` | **cinematic** clips on the moments that earn them, each anchored to a must clip, silent, with a blend (`cut_in`, `under_line`, `open`, `close`, `transition`), blend notes and a review of every moment | `should` / `nice` |

Stage 2 is a fresh conversation over stage 1's locked bin: its tools refuse every must clip id, so stage 1's clips leave it
exactly as they came in. If stage 2 fails, stage 1's bin is saved whole.

## The length cap is a choice

The target is the scene's given length. The whole bin's hard cap is **1.5x, 2x (default), 2.5x or 3x** that length, chosen
per production (`settings.raphael_length_cap`, admin) and per run (the Raphael tab's select). Stage 2's room is the cap
minus what stage 1 used. Over the cap, nice clips go first, then should, never must. It is seconds of takes, never money.

## How it runs

```
the scene --> raphael_planner  (one conversation, <= 20 turns)
                 tools: write_edit_plan, put_clips, remove_clips, read_bin, finish
                 every write returns the check report of the whole bin; finish refuses until nothing blocks
          --> raphael_cinematic (a fresh conversation, <= 12 turns)
                 tools: put_extras, remove_extras, read_bin, finish(blend_notes, moment_review)
          --> raphael_write (code): one shot per clip, lines bound to the clip that performs them
```

* The loop is `Agent.converse` (agent shape `loop`): the model must call a tool each turn, the tools are the caller's code
  (`contracts/raphael/tools.py`), usage rows and Langfuse traces are the middleware's as for every agent.
* The checks are `contracts/raphael/checks.py`: coverage, length, clock, feasibility, designs, consistency, and stage 2's
  anchors, silence, difference from the anchor, at most 3 a moment, the cap and the moment review.
* **One $5 run cap per scene covers both stages** (`contracts/raphael/money.py`). It is kept in code and logs only; the
  interface shows seconds and counts, never money. A model with no price in that table is refused before any call.
* Nothing is ever trimmed or reworded: a line too long for its take is reported with the way out (overlapping clips).

## The director's breakdown (plan/2026-11-10)

Before stage 1, ONE request with no tools (`agents/raphael/raphael_breakdown`, tier `raphael_breakdown`, the same model and
effort as stage 1 by default) writes a director's shot breakdown of the scene: objective, direction, shots (one action
each, the blocks and line ids they sit on, `story` or `detail`) and notes. Code checks it (`checks.breakdown_faults`); on
faults it is asked once more with them listed, and if it still fails there is no breakdown, the job gets a warning and
stage 1 runs exactly as before. Stage 1 gets it as `<breakdown>` after `<length>` (its shots, in order, are the intended cut
and the must clips; a `detail` shot is a must clip too), stage 2 gets the shot list only. A breakdown shot with no must clip
on its blocks is the report `breakdown:missing` (it never blocks `finish`). The call counts inside `RAPHAEL_SCENE_CAP_USD`.
Stored in `scenes.raphael.breakdown` (JSON, no schema change); a re-plan with the same input hash reuses it, "More
cinematic" reads it. Switch: `RAPHAEL_BREAKDOWN` (default true; false is Raphael as it was). The interface shows it as a
read-only "Breakdown" table at the top of the Raphael tab. Open: D1 approval step, D2 report or block, D3 a stronger model,
D4 shrinking stage 1's own edit plan.

## Where things live

`src/libs/contracts/raphael/` (wire, bin, checks, tools, pack, money, stored, scene), `agents/raphael/`,
`steps/raphael/raphael_write`, `systems/raphael/raphael_shot_planner`, `src/services/shot_planner_raphael/` (the function,
port 8215), `tests/raphael/`. Job kinds `plan_scene_raphael` and `cinematic_scene_raphael` (one function). Storage: schema
v19 (`scenes.raphael`, the clip fields on `shots`). The interface's tab: `src/features/raphael/` in the interface repository.
`hiru-ai remove --group raphael` lists everything that goes.
