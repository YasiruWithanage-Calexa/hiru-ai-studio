# Shot Planner Jonathan

The cinematic shot planner: the planner the cinematic lab proved (`lab/cinematic/`, plan/2026-11-06), moved into the product
(plan: [plan/2026-11-06b](../../plan/2026-11-06b/PLAN.md); what is built and what waits for a person:
[IMPLEMENTED.md](../../plan/2026-11-06b/IMPLEMENTED.md)). It sits beside the classic `script_split`,
[Shot Planner Adam](../adam/README.md) and [Shot Planner David](../david/README.md), which it does not change, and it follows
[the Hiru AI pattern](../AI_PATTERN.md) ([ADR 0010](../adr/0010-one-author-pattern.md)).

It plans a scene the way a production team would: the TREATMENT first (logline, arc, approach, colour script, geography, key
image, advice), then the SEQUENCES, then every shot with its size (eleven, from EWS to ECU and POV), angle, lens, the Veo take and
the seconds the edit keeps (`use_s`), and a `why` that starts with the shot's story function. Code checks it, and while a fault
or a craft gap is left, the same model revises its own best plan: the lab's **stabiliser**.

A production picks it with `settings.shot_planner = "jonathan"` (the one branch in the build); a scene can also be planned with
it on its own ("Plan with Jonathan"). With no model the job fails clearly and names the classic planner.

## One scene

```
pack (code) → author (ONE call) → mend + check (code) → revise (0 to 2 calls, the best plan kept) → write (code)
```

| Part | Kind | Does |
|---|---|---|
| `jonathan_pack` | step | the author's message, the lab's to the letter for a scene with no scene before it: the style guide and each person's look, voice and who they are (the canon card's summary); the scene and the time budget (the envelope, landed within about 20% in `use_s`); the script with each line's clock, `[move]` on the blocks that move a person, and `a thought` or `heard not seen` on a line that is not spoken on screen. A linked scene also gets its start state and the last shot before, word for word |
| `jonathan_author` | agent (tier `jonathan`: the author model at high effort) | ONE call with the lab's team prompt and its one worked example: the treatment, the sequences, every shot with its camera design (the Veo clip IR the DoP also fills), what was added, the staging, the end state |
| `jonathan_mend` | step | a longer take; a crowded shot cut at a block boundary, **each part keeping only its own beats, re-timed, a part with no line made silent** (the lab's split fix); speech out of free text and the treatment; `use_s` never below a line's need nor above the take; the sequences' spans; the end state's places from the staging |
| `jonathan_check` | step | every hard check (lines, blocks, the clock, additions, names, speech, staging, heard-not-seen, feasibility, the end state, nobody speaking in a shot with no line, `use_s`, the sequences, the colour script) and the **craft measures** (opens on geography, introductions, story objects in close shots, reactions, compound actions, motion follows meaning, size variety, the grade moves, sequence endings), reported and never blocking. The plan's score is (faults, craft gaps) |
| `jonathan_revise` | agent (tier `jonathan`) | the author's own prompt and message, its best plan so far and what code found → the WHOLE corrected plan. Code keeps it only when its score is lower; at most two passes; a worse pass is never built on |
| `jonathan_write` | step | the shots rows (Jonathan's size as its nearest `shots.framing`, a design whose pins are current), the lines bound to them, the fit report (with the seconds kept), `scenes.jonathan` (the plan, the measures, every pass) |
| `jonathan_links`, `jonathan_seams` | steps | which scenes carry on from the one before; the join between two scenes (at most one more pass) and a person's look changes |
| `jonathan_shot_planner` | system | the pool, the chains, the time budget, reuse, the cascade, the edits |

That Jonathan asks the model what the lab asked, and judges the answer as the lab did, is a test while the lab exists
(`tests/jonathan/test_lab_parity.py`): the prompt, the schema, the message and the revise message to the letter, and every saved
lab answer scored the same (faults, craft gaps). The one difference is on purpose: the end state's place is written from the
staging by code, a fault the lab reported against itself.

## Many scenes

As David's: scenes that **carry on** from the one before run in order inside one worker, each fed the end state and the last shot
of the one before; every other chain runs at once (`JONATHAN_WORKERS`, default 10). No new scene starts after 900 s of the 1800 s
deadline. A scene whose input is unchanged keeps its plan with no call. A replan cascades until an end state comes out the same,
and an approved scene stops it.

## What a person can do

`GET /scenes/{id}/jonathan` reads the plan. `POST /scenes/{id}/jonathan/plan` plans the scene again, or with `{"note": "..."}`
makes one revise pass with the note (kept unless it adds a fault). `POST /scenes/{id}/jonathan/added/{n}/remove` takes an
addition out with no model; the same addition never comes back. The interface's Jonathan tab shows the treatment, the colour
script, the sequences with their place in the edit, each shot as a shot card under its sequence (size, take and kept seconds,
angle, lens, movement, what we see, purpose, the line in the script's words, the sound), each addition with Remove, what code
mended, each revision and whether it was kept, what is left, the craft notes, the staging and the end state. It shows no costs
or credits.

## Running it

```
OPENAI__API_KEY= .venv/Scripts/python.exe -m pytest tests/jonathan                  # offline, the lab parity included
OPENAI__API_KEY= .venv/Scripts/hiru-ai.exe eval jonathan_author                     # scripted: the structure gate
.venv/Scripts/python.exe scripts/jonathan_spike.py --yes --repeat 3 --budget 5      # the live trial for the gate (§8)
.venv/Scripts/python.exe scripts/jonathan_compare.py                                # the blind pages for a director
.venv/Scripts/hiru-ai.exe remove --group jonathan                                   # lists everything that goes
```

The live trial and the blind comparison are a person's to start: they spend model calls and need a Hiru director. Quality
problems are fixed in the prompt, the pack or a code check, never by adding an agent (pattern rule 8).
