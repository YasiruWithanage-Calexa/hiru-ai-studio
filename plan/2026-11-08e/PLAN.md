# Shot Planner Raphael: raw coverage for post-production, planned by one agent (plan/2026-11-08e)

Status (2026-11-08, after the lab): **the lab is done and the person has said to move to the product phases.** Phase 0c
built ($0), phase 0d run: two stage 2 passes, both finished, $0.53 ([RESULTS.md](RESULTS.md)). After pass 4 the person
changed three things (2x room, a review of every moment, 3 a moment) and struck the screen-text rule; pass 5 with them is
the shape the product builds. **New (the person, 2026-11-08): the length cap is a choice** (1.5x, 2x ...), §2.1. **Built offline 2026-11-08: phases 1-5
(the product, the API and the interface tab), see [IMPLEMENTED.md](IMPLEMENTED.md); phase 0e, the live trial (6) and the default (7)
are the person's.** Written 2026-11-08; phase 0a built and phase 0b run the same day (3 paid runs, all finished, $1.18:
[RESULTS.md](RESULTS.md)). **Updated 2026-11-08 after the person's read:** the must bin is good, but it needs cinematic shots
too, so Raphael becomes **two stages**: stage 1 (as built) writes the must clips; stage 2, a second agent, reads that bin and
adds cinematic clips to selected moments, for post to blend in (§2.2, §3.5, phases 0c-0d). Plain words:
[human-read.md](human-read.md). A **new** planner beside Adam, David, Jonathan and DaVinci; none of them change.

## 1. Why

Raphael delivers what DaVinci delivers ([plan/2026-11-08d](../2026-11-08d/PLAN.md)): **raw material for Hiru's expert post
team**, guided by an intended cut. The difference is the architecture: **one agent, not a team.**

DaVinci's two paid runs on Episode 1 (2026-11-08, `lab/davinci/runs/`) show where a team costs us:

| Run | Spent | Ended | Clips / seconds | Faults left | Owned by a worker |
|---|---|---|---|---|---|
| 1 | $0.93 | all 40 turns used | 21 / 130 s (limit 90 s) | 15 | 7 |
| 2 | $0.81 | all 40 turns used | 14 / 88 s | 11 | 9 |

- **Hand-offs lose context.** The clip writers see a brief and a few clips, not the scene. They put the voice-only father on
  screen, asked for readable screen text, and left designs empty; the director then spends turns sending the same clips back.
- **Repairs go one at a time.** Run 2 used 26 of its 40 turns on `replace_clip`, one clip per turn.
- **Neither run finished.** Money was never the limit (both under $1 of $5); turns and the round trips were.

Raphael is one strong model, in one conversation, that sees the whole scene and writes every part itself: the intended cut,
each clip's plan **and** its Veo design. Code checks after every write and hands the faults straight back. Fewer turns,
nothing lost between agents, and one voice across all the clips of a moment.

## 2. What Raphael delivers

The same result as DaVinci, so the post team, the page and later storage do not care which planner made it:

1. **Intended cut**: treatment (logline, arc, approach, colour script, geography, key image), sequences, moments, and for each
   moment the clip the vision uses and why. A reference for the editor only.
2. **Shoot bin**: each clip has `role`, `covers`, `handles`, `take_s` (4 / 6 / 8 s), `priority` (must / should / nice),
   `technique` + `why`, `speaks`, `slate` (e.g. `12B-3`), `ir` (the full Veo clip). Fields as DaVinci §2.2.
3. **Editor notes**: what each clip is for, risky match cuts, techniques left for post, what was avoided because Veo cannot
   do it.

Kept from DaVinci without change: the camera vocabulary and its Veo refusals (§3 there) and the speak rule (D2: the master
and the speaker's single speak, other angles play silent).

### 2.1 Length: aim for the scene's length; the cap is a choice

The person's rule (2026-11-08), as changed after the lab:

- **Target = the length the script gives.** Stage 1's must bin aims at the scene's given length (60 s -> about 60 s); runs
  1-3 landed at 70 s. Stage 1 keeps its own hard cap of **1.5x** (it builds the cut, not coverage).
- **The whole bin's cap is chosen by a person: the length cap.** Choices: **1.5x, 2x, 2.5x, 3x** the scene's given length
  (L1). The default is **2x** (pass 5: 70 s must + 42 s cinematic = 112 of 120 s). Stage 2's room is the cap minus what
  stage 1 used. It is a **hard cap**: a blocking check, `finish` refuses over it, and over it nice clips go first, then
  should, never must.
- **Where it is set (L2):** a production setting `raphael_length_cap` (admin, with the other production settings), and a
  choice on the scene when someone plans it or presses "More cinematic" (it overrides the production's for that run). The
  cap used is stored with the plan and shown beside the seconds.
- The prompt names the room as the place for what the moments earn, never repeats of a must angle or filler; the report shows
  the seconds against the target and the cap. Code reports the length; it never trims a clip or a line.
- No money is involved: the cap is seconds of takes. What it costs to generate the takes is the person's, outside this plan.

### 2.2 Two stages: the must bin, then the cinematic pass

The person's read of runs 1-3 (2026-11-08): the bins are right as **must** shots, the shots the scene cannot be cut
without, but there is nothing cinematic: no insert, no B-roll, no drone, no slow reveal, no reaction held where a line lands.
Those are **nice to have**: not needed to tell the story, but what makes it look like cinema. Post blends them in.

So Raphael works in stages, each checked and saved before the next:

| Stage | Agent | Reads | Writes | Priority | Length |
|---|---|---|---|---|---|
| 1 | **Raphael** (built, phase 0a/0b) | the scene | intended cut + must bin + editor notes | `must` only (S1) | aims at the given length |
| 2 | **the cinematic pass** (new, §3.5) | the scene, the intended cut, stage 1's finished bin (read only) | cinematic clips on the moments that earn them + blend notes + the moment review | `should` / `nice` | the room up to the chosen cap (§2.1, default 2x) |

Why staged and not one bigger prompt:

- **The must bin is safe first.** Stage 1 is proven (3 of 3 finished). Asking the same call for extras is what took run 2
  from 70 s to 88 s with alternates that were not cinematic, only more of the same. A separate pass, with its own job and
  its own checks, cannot spoil the must clips: its tools refuse to touch them.
- **A different eye.** Stage 1 thinks "what does the cut need"; stage 2 thinks "where does this scene deserve more than
  coverage". One prompt doing both does the first well and the second thinly (runs 1-3).
- **Stage 2 is optional and repeatable.** If it fails or is skipped, stage 1's bin is still the deliverable. It can be run
  again on the same must bin without paying for stage 1 again, and later on moments a person picks (§9).

What a cinematic clip is (stage 2's job, in the prompt):

- **Every moment reviewed, the turning moments first** (written first as "selected, not everywhere, most moments get none,
  at most 2 a moment, 3-6 a scene"; changed after pass 4, see *Settled in the lab* below): at most **3 a moment**, no
  count guide, a moment that earns nothing says why.
- **Anchored.** Every cinematic clip names its **anchor**: the must clip (or clips) it sits with, the moment, and **how post
  blends it**: `cut_in` (cut away and back inside the anchor), `under_line` (B-roll or a reaction over the anchor's audio),
  `open` / `close` (before or after the moment), `transition` (a pair that carries one sequence into the next).
- **Different from its anchor.** Another role or technique, never the same angle again (that is an alternate, not a
  cinematic shot). Roles: `insert`, `cutaway`, `reaction`, `establishing`, `atmosphere`, `pov`, `transition_out` /
  `transition_in`; techniques from the shared vocabulary: drone, slow creep, rack focus, silhouette, light across a face,
  slow motion, tilt reveal, push past foreground and so on, with their Veo refusals.
- **Silent.** A cinematic clip speaks no line (`speaks` empty); the dialogue stays on the must clips and post lays it under.
  Reactions are silent by the speak rule already. Slow motion carries no dialogue, as before.
- **No new story.** No new person, event or object; a voice-only person is never in frame; the place, light and people are
  worded as the anchor words them (the consistency check, per moment), so the editor can cut between them.
- **A story reason.** Each clip's `why` says what it gives the scene that the must clips do not.

**Settled in the lab (passes 4-5, the person's changes):**

- **Every moment is reviewed, the turning moments first** (a call, a parting, the closing line), not in script order.
  `finish` takes a `moment_review`: every moment once, `earns` yes or no, and why; it refuses a review that does not match
  the bin. This replaced "selected, not everywhere" (pass 4 spent its room on moments 1-7 and never reached the call).
- **What moments usually earn** is in the prompt as a starting point: a call -> an extreme close-up of the phone and the
  listener's face; an object -> an insert; an arrival -> an establishing view or drone; a line that lands -> a held reaction;
  an exit -> the empty frame; a closing voice-over -> a drone pull-away or slow push; time or mood -> textures of the place;
  sequence to sequence -> a transition pair.
- **At most 3 cinematic clips a moment** (blocking). No per-scene count guide: the room and the 3 a moment are the limits.
- **Phone close-ups are welcome.** The screen-text rule ("Veo cannot render readable screen text") is struck for Raphael:
  removed from its prompts and dropped from its checks. The shared check in `contracts.david` still holds for the other
  planners (S6).
- **Variety (pass 5's gap, written into the product prompt, D-V):** pass 5 gave 8 clips but 5 were rain-texture atmosphere,
  two of them 8 s, and no held reaction, drone or transition. The product prompt asks for variety: at most 2 atmosphere
  clips a scene, atmosphere takes of 4 s, a held reaction where a line lands and on a call. Checked in phase 0e.

Result: the same shoot bin, now with two layers. Each clip carries `stage` (1 / 2), stage 2 clips carry `anchor` and
`blend`, and the editor notes gain **blend notes**: for each cinematic clip, where it goes in the intended cut and over whose
audio. The intended cut itself stays the must cut; cinematic clips are listed under their moment as *optional*.

## 3. Architecture: one agent, code tools only

```
        ┌──────────────────────────────────────────────┐
        │  RAPHAEL (one strong model, one conversation) │
        │  reads the scene → writes → reads faults →    │
        │  repairs → finish                             │
        └───────────────────────┬──────────────────────┘
                                │ calls (no other model)
                                ▼
   CODE TOOLS: write_edit_plan · put_clips · remove_clips · read_bin · finish
   every write returns the check report (coverage, length, clock, feasibility,
   designs, consistency); finish refuses until it is clean
                                │
                                ▼
          intended cut + shoot bin (slates) + editor notes
```

### 3.1 The agent

One model in a tool-calling loop. Everything comes in the first message: the production (style guide, people, visual
language), the scene, the numbered script (line ids, speakers, seconds, shortest take, *heard not seen*, *a thought*), the
`<voice_only>` and `<length>` blocks DaVinci already builds. It never asks another model for anything.

The prompt asks for this order, but the agent decides the steps inside it:

1. `write_edit_plan`: the vision first.
2. The bin, **a sequence at a time** (or the whole scene in one call if it is short): each clip complete, plan and design
   together. The must clips first, aiming at the scene's given length; extras only where the story turns, within the 1.5x
   cap (§2.1).
3. Repair what the report names, **many clips per call**.
4. `finish(editor_notes)`.

Expected: about 6-10 turns for a 60 s scene. Turn cap: **20** (R1).

### 3.2 Tools

| Tool | Does | From DaVinci lab |
|---|---|---|
| `write_edit_plan(plan)` | the intended cut; may be called again to change it | `tool_write_edit_plan`, `EditPlanW` |
| `put_clips(clips[])` | adds new clips or replaces clips by id, **any number per call**, each with plan + `ir`; code gives ids and slates; a must clip stays must on replace | `add_clips` + `replace_clip` + the clip writer's `IrW`, merged |
| `remove_clips(ids[])` | refuses a removal that opens a coverage hole (says to replace instead) | `tool_remove_clips` as is |
| `read_bin(moment?)` | the clips, all or one moment, for when the conversation is long | `tool_read_bin` |
| `finish(editor_notes)` | writes the result; refuses until no blocking fault remains | `tool_finish` |

There is **no separate `check` tool**: every `write_edit_plan`, `put_clips` and `remove_clips` returns the report of the
whole bin (blocking faults first, each naming the clips, the fix and whether it was tried before). That saves a turn per
change, the turn DaVinci's director often spent calling `check`.

Fault owners shrink to two: **code** (reported, nothing to do) and **Raphael** (everything else).

### 3.3 Checks

DaVinci's `lab/davinci/checks.py` as it is: coverage (every block, moment and line has its must clip and performer), length
(blocking over given length x 1.5; the report also shows the seconds against the given length, the target), clock (4 / 6 / 8 s, handles, 2.2 words/s; overruns reported, never trimmed), feasibility (Veo limits,
refused techniques, the visual language), designs (every clip has a complete `ir`, voice-only people never in frame), and
consistency (the clips of one moment word place, light and people the same).

No continuity critic, no second model: if the post team's cut shows match-action drift that code cannot see, that is a later
plan.

### 3.4 Memory

The conversation is the memory. Code holds the bin, the edit plan and the work log (calls, results, faults, repeated fixes),
and every tool reply is short: ids, slates, the report. Traced in Langfuse step by step, as every agent run is.

### 3.5 Stage 2: the cinematic pass

The same shape as stage 1: one model, one conversation, code tools only, the report after every write. A fresh
conversation, not a continuation of stage 1's (it starts clean, and stage 1's turns do not count against it).

```
   stage 1 finished bin (must, locked) + intended cut + scene
                                │
                                ▼
        ┌──────────────────────────────────────────────┐
        │  CINEMATIC PASS (one model, one conversation) │
        │  picks moments → writes cinematic clips →     │
        │  reads faults → repairs → finish(blend notes) │
        └───────────────────────┬──────────────────────┘
                                ▼
   CODE TOOLS: put_extras · remove_extras · read_bin · finish
                                ▼
           the same bin, must + cinematic, with blend notes
```

First message: everything stage 1 had, plus the intended cut and the must bin as a short table (id, slate, moment, role,
technique, take, covers, the first line of its design), and the seconds left under the cap.

| Tool | Does |
|---|---|
| `put_extras(clips[])` | adds or replaces cinematic clips, any number per call; each has plan + `ir` + `anchor` + `blend` + `why`; **refuses any must clip id** and any `priority: must`; code gives ids and slates (next take letter in the anchor's setup, or a new setup) |
| `remove_extras(ids[])` | removes cinematic clips only |
| `read_bin(moment?)` | as stage 1 (must clips marked locked) |
| `finish(blend_notes, moment_review)` | refuses until no blocking fault, a blend note names every cinematic clip, and the review covers every moment once and matches the bin (zero clips is a review of noes, each with its reason) |

Checks: every stage 1 check on the whole bin (length cap, clock, feasibility, designs, consistency, voice-only), plus:

| Check | Blocking? |
|---|---|
| anchor names a real must clip in the same moment (or, for `transition`, the neighbouring moment) | yes |
| `blend` is one of the five; `speaks` is empty | yes |
| differs from its anchor in role or technique | yes |
| more than 3 cinematic clips in a moment | yes |
| the whole bin over the chosen length cap (§2.1, default 2x) | yes |
| `finish`: a blend note per cinematic clip; a review of every moment that matches the bin | yes (refused) |

Measured (passes 4-5, `gpt-5` high): 4-6 turns, $0.26-0.27 a pass. Turn cap 12 (S4).

## 4. Spending cap

As DaVinci: **$5 of model tokens per scene run**, one number in config. After each call code adds its cost; at $5 the run
stops (the last call may take it a few cents over). No budget is shown to the model; no cost in the UI beyond what the
interface's CLAUDE.md allows. What is saved on a stop is D1.

A guess, never measured: a 60 s scene is about 25-40k output tokens in all (clips + reasoning) and a conversation that grows to
about 40k input, mostly cached. With `gpt-5` that is roughly $0.40-0.80; with `gpt-5.5` roughly $1.50-3. `dry` prints the worst
case before any paid run.

Measured (phases 0b, 0d): stage 1 cost $0.32-0.46 per run and stage 2 $0.26-0.27 per pass with `gpt-5` high, so a scene is
about $0.60-0.75 for both stages, far under the cap. The **$5 cap covers both stages** of one scene: stage 2
gets what stage 1 left. If the cap stops stage 2, stage 1's bin is saved whole and stage 2's clips are saved only if they
pass the checks (D1).

## 5. Rules kept

- Dialogue is never trimmed, reworded or translated; a line is named by its id; the clock reports overruns.
- Never invent story: no new speaking person, line, event or object; a voice-only person is never in frame.
- Adam, David, Jonathan and DaVinci do not change.
- No live model call without the person's yes, each time.

## 6. Decisions (the person's)

DaVinci's D1-D8 carry over (D4 is settled by the length rule).

**Settled (2026-11-08):**

| # | Question | Answer |
|---|---|---|
| R1 | Turn cap | 20 (stage 1); runs used 4-7 |
| R2 | The lab imports DaVinci's code | yes (done) |
| R3 | DaVinci or Raphael into the product | **Raphael** (the person's go to the product phases, 2026-11-08): it finished every run, DaVinci's orchestrator never did. DaVinci stays a lab; the product code is Raphael's own (`contracts/raphael`), copied from the DaVinci lab where it imports it |
| S2 | Stage 2's length | within ONE cap on the whole bin, and the cap is a choice (§2.1, L1-L2) |
| S3 | How many cinematic clips | at most 3 a moment (blocking); no count guide; every moment reviewed |
| S4 | Stage 2's model and turns | the same model as stage 1; 12 turns (used 4-6) |
| — | The screen-text rule | struck for Raphael (prompts and checks) |

**Open:**

| # | Question | Recommendation |
|---|---|---|
| L1 | The length cap's choices and default | 1.5x, 2x, 2.5x, 3x; default 2x (pass 5). Over 3x the room fills with filler (risk 1) |
| L2 | Who sets it | the production default: admin (as every production setting); the per-scene choice: whoever may plan a scene (`CanDirect`) |
| S1 | Stage 1: must clips only | yes: `raphael_must.md` (written, not yet paid for); phase 0e runs it once before the product prompt is frozen |
| D-V | The variety rule (§2.2) | in the product prompt; atmosphere at most 2 a scene as a **report**, not blocking, until 0e shows it is needed |
| S5 | When stage 2 runs | right after stage 1, automatically; "More cinematic" re-runs stage 2 alone on a scene (with a cap choice) |
| S6 | The screen-text rule for the OTHER planners (`contracts.david.checks`, DaVinci's prompts) | the person's: striking it there changes Adam, David and Jonathan too, so it is a separate small change |
| D1 | At the $5 cap or a turn cap | save, marked incomplete; stage 1's bin is whole whenever stage 2 fails |
| D7 | The product's model | the person's: the lab used `gpt-5` high (shuts down 2026-12-11); Jonathan uses `gpt-6.1-sol`. Phase 6 runs on the chosen one |
| D5 | Storage of the bin | Raphael's own column on `scenes` plus the clip fields on `shots` (phase 4) |

## 7. Phases

Done: **0a, 0b** (stage 1 lab: 3 runs, $1.18), **0c** (stage 2 lab, $0), **0d** (2 passes, $0.53). Lab total $1.70 of $5.

The product follows Jonathan's shape (plan/2026-11-06b §4): a `raphael` group, isolated, removable, nothing else changes
but the named one-line seams.

| Phase | What | Model calls | Exit |
|---|---|---|---|
| 0e | **One full lab run** (optional, can run beside 1-2): stage 1 with `raphael_must.md` (S1) + stage 2 with the variety lines (D-V), default cap 2x, `run.py full`. Also a `--cap` option on `stage2` and `full` (the L1 choices) | yes, ≤ $1.50, the person's yes | stage 1 finishes must-only; stage 2 gives reactions and not mostly atmosphere; the person's read |
| 1 | **Contracts** `contracts/raphael`: the wire (`ClipW`, `ExtraW` with `stage` / `anchor` / `blend`, the edit plan, the moment review), the length cap type (`LengthCap = Literal[1.5, 2, 2.5, 3]`), `stored`. `ProductionSettings`: `shot_planner` gains `"raphael"`, new `raphael_length_cap: LengthCap = 2` | no | strict-schema tests; settings round-trip |
| 2 | **Checks as product code** `contracts/raphael/checks.py`: the lab's checks (DaVinci's, ported, not imported) with the screen-text rule out, the cap a parameter, stage 2's checks and the review match. Gold bins: run 3 (stage 1) and pass 5 (stage 2) as fixtures | no | gold bins pass; mutants (must id touched, same angle, 4 a moment, over each cap, a heard voice in frame, a speaking extra) fail with the right sentence |
| 3 | **The agents and the system**: `agents/raphael/raphael_planner` (stage 1 loop, its tools) and `raphael_cinematic` (stage 2); `systems/raphael/raphael_shot_planner` runs stage 1 then stage 2 (S5) under one $5 cap, turn caps 20 / 12, the chosen cap passed to both; Langfuse traces each turn; job kinds `plan_scene_raphael`, `cinematic_scene_raphael`; the build branch | scripted only | the lab's two rehearsals pass as product tests; for each of the four caps stage 2's room is the cap minus stage 1's seconds; stage 2 failing leaves stage 1's bin saved |
| 4 | **Storage** (one migration, v19; applying it is the person's): `scenes.raphael jsonb` (edit plan, editor notes, blend notes, moment review, report, the cap used, `input_hash`); `shots.planner` gains `'raphael'`; on `shots`: `role`, `priority`, `slate`, `handle_in_s`, `handle_out_s`, `stage`, `anchor`, `blend`. The shot producer's `AUTHORED` gains `"raphael"` (the Veo prompt is written from Raphael's `ir`) | no | migration tests; a scene re-planned with an unchanged `input_hash` makes no call |
| 5 | **API and interface**: `GET /scenes/{id}/raphael`, `POST /scenes/{id}/raphael/plan {cap?, note?}`, `POST /scenes/{id}/raphael/cinematic {cap?}`, behind `CanDirect`. A **Raphael tab**: the intended cut, the shoot bin by moment and role with slates, cinematic clips under their anchor marked *cinematic, optional* with the blend note, the moment review, the seconds against the target and the cap. A **length cap select** (1.5x / 2x / 2.5x / 3x) in the tab beside "Plan" and "More cinematic", and in production settings. **No costs or credits** | no | API tests; the interface's feature tests; seen in a browser |
| 6 | **Live trial** on one episode, run by the person, on the D7 model: every scene, two caps (2x and one other) on one scene; the post team cuts a sample (`pick`) | live, the person's | the post team's verdict |
| 7 | The default planner, and whether DaVinci's lab is deleted | | the person's |

## 8. Risks

| Risk | Answer |
|---|---|
| The agent treats the 1.5x headroom as a goal and fills it | the prompt names the given length as the target; the report shows seconds against target and cap; the blind read and the post team judge the extras |
| One model writing 10-22 full clips runs out of output room or rushes the later ones | a sequence per `put_clips` call; `max_output_tokens` sized in `dry`; the designs check catches thin clips |
| The conversation grows and gets expensive | short tool replies; cached input; `read_bin` instead of repeating clips; the $5 cap |
| The agent repeats a fix that already failed | the report marks repeated faults; the prompt says to change approach, not retry |
| The agent removes must clips to make faults go away (DaVinci run 1) | `remove_clips` refuses a removal that opens a hole, as in DaVinci now |
| Veo drifts across angles so the editor cannot cut on action | the same as DaVinci: the same simple action worded identically in every angle; the post team's sample proves it |
| A single model is less inventive than a team | it is the strongest slot, sees everything, and the vocabulary and the "story reason" rule stay; the blind read decides |
| Stage 2 fills the headroom with a clip on every moment | at most 3 per moment (blocking); the moment review asks why for each; a "no" is allowed and was used (pass 5: 4 of 11) |
| Stage 2 adds alternates, not cinematic shots | "differs from its anchor in role or technique" is blocking; the `why` must say what the clip adds |
| A cinematic clip does not match its anchor (light, wardrobe, place), so post cannot blend it | the consistency check covers the whole moment; the prompt asks it to reuse the anchor's wording; the post team's sample includes one |
| Stage 2 breaks the must bin | its tools refuse must ids; a test proves stage 1's clips are byte-identical after stage 2 |
| Stage 2 fills the room with one idea (pass 5: 5 of 8 rain-texture atmosphere) | the variety lines (D-V); atmosphere counted in the report; 0e checks it |
| A high cap (3x) is filled with filler | the review asks why each moment earns its clips; repeats of a must angle are blocked; the person picks the cap per scene and sees the seconds |
| Raphael and the other planners judge screen text differently | named in S6; Raphael's checks say so in one line |

## 9. Not in this plan

Transitions across neighbouring scenes; EDL / XML export; Zora editing Raphael's plans; a continuity critic; a person
picking the moments for stage 2 in the interface (later: the same stage 2, given a list of moment ids).
