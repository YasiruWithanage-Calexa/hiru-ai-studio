# Shot Planner David

A third shot planner, built beside the classic `script_split` and [Shot Planner Adam](../adam/README.md), which it does not
change. It plans a scene's shots **and their camera design** in **one model call**, keeps every Hiru guarantee in code (no
invented story, lines word for word, the Veo clock, continuity), repairs only what code cannot, and writes the shots so the
shot producer asks neither the DoP nor the critic. It is the first system built on [the Hiru AI pattern](../AI_PATTERN.md)
([ADR 0010](../adr/0010-one-author-pattern.md)). Plan: [plan/2026-11-05e](../../plan/2026-11-05e/PLAN.md); what is built and
what waits for a person: [IMPLEMENTED.md](../../plan/2026-11-05e/IMPLEMENTED.md).

A production picks it with `settings.shot_planner = "david"` (the one branch in the build); a scene can also be planned with it
on its own ("Plan with David"). With no model the job fails clearly and names the classic planner: David has no rules fallback.

## One scene

```
pack (code) → author (ONE call) → mend (code) → check (code) → repair (same model, a patch, ≤ 2 rounds) → write (code)
```

| Part | Kind | Does |
|---|---|---|
| `david_pack` | step | builds the author's context pack as text, static part first so it caches: production rules and cast, the scene's context, the start state (or canon looks), the last shot of the scene before word for word, the numbered script with each line's clock facts |
| `david_author` | agent (tier `author`) | ONE call: notes, every shot with its camera design (the Veo clip IR the DoP also fills), what was added, the staging, the end state |
| `david_mend` | step | a longer take, a crowded shot cut at a block boundary, speech out of free text, an addition code refuses, the numbering; never deletes a line or trims one |
| `david_check` | step | lines, blocks, the clock, additions, names, speech in free text, staging, heard-not-seen, feasibility, the end state; each failure an exact sentence and who fixes it |
| `david_repair` | agent (tier `repair`) | the exact problems, the shots involved and their neighbours → a PATCH (replacements, a new staging or end state); code refuses a patch that creates a new failure |
| `david_write` | step | the shots rows (card, intent, finished IR, a design whose pins are current), the lines bound to them, the fit report in the classic shape, `scenes.david` |
| `david_links`, `david_seams` | steps | which scenes carry on from the one before; the join between two scenes and a person's look changes |
| `david_shot_planner` | system | the pool, the chains, the time budget, reuse, the cascade, the edits |

The failures and who fixes them are `contracts/david/checks.py`; the mend is `contracts/david/mend.py`; the closed lists, the
wire shapes and the stored plan are `contracts/david/`.

## Many scenes

Scenes that **carry on** from the one before (same episode, same place, CONTINUOUS / MOMENTS LATER / SAME TIME; or every pair in
`episode` order, `settings.david_order`) run in order inside one worker, each fed the end state and the last shot of the one
before; every other chain runs at once (`DAVID_WORKERS`, default 10). No new scene starts after 900 s of the 1800 s deadline;
the rest go to a fresh delivery, which carries on from the end state stored in `scenes.david`. A scene whose input is unchanged
keeps its plan with no call. A replan changes the scene's end state; the scenes after it that David planned are planned again in
order until one's end state comes out the same, and an approved scene stops it (its join is reported).

## What a person can do

`GET /scenes/{id}/david` reads the plan. `POST /scenes/{id}/david/plan` plans the scene again, or with `{"note": "..."}` makes
one repair with the note as the problem. `POST /scenes/{id}/david/added/{n}/remove` takes an addition out with no model; the
same addition never comes back. The interface's David tab shows the notes, the shots, each addition with Remove, what code
mended, what a repair changed, what is reported, the end state, the look changes and the joins. It shows no costs or credits.

## Running it

```
OPENAI__API_KEY= .venv/Scripts/python.exe -m hiru_ai eval david_author          # scripted: the structure gate
.venv/Scripts/python.exe scripts/david_spike.py --yes                            # the spike (about $5 to $10)
.venv/Scripts/python.exe scripts/david_compare.py                                # the blind pages for a director
.venv/Scripts/python.exe -m hiru_ai remove --group david                         # lists everything that goes
```

The spike (`scripts/david_spike.py`) and the blind comparison are a person's to start: they spend model calls and need a Hiru
director. Quality problems are fixed in the prompt, the pack or a code check, never by adding an agent (pattern rule 8).
