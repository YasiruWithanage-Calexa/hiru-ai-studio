# Shot Planner Raphael: raw coverage for post-production, planned by one agent (plan/2026-11-08e)

Status: written 2026-11-08; nothing built, no model called. Plain words: [human-read.md](human-read.md). A **new** planner
beside Adam, David, Jonathan and DaVinci; none of them change.

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

### 2.1 Length: aim for the scene's length, 1.5x is a hard cap

The person's rule (2026-11-08):

- **Target = the length the script gives.** A bin whose takes add up to the scene's given length (60 s -> about 60 s) is
  the correct way to go: the must clips that build the intended cut, little more.
- **Headroom up to 1.5x, never past it.** Raphael may add alternates, reactions and extras only where the story earns them,
  and the takes in all may never pass **given length x 1.5** (60 s -> 90 s). This is a **hard cap**: a blocking check, and
  `finish` refuses over it.
- The headroom is room, not a goal. The prompt says so, and the report shows the seconds used against both the target and
  the cap, so the agent is not nudged to fill it. Over the cap, drop nice clips first, then should, never must.
- Code reports the length; it never trims a clip or a line.

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

## 4. Spending cap

As DaVinci: **$5 of model tokens per scene run**, one number in config. After each call code adds its cost; at $5 the run
stops (the last call may take it a few cents over). No budget is shown to the model; no cost in the UI beyond what the
interface's CLAUDE.md allows. What is saved on a stop is D1.

A guess, never measured: a 60 s scene is about 25-40k output tokens in all (clips + reasoning) and a conversation that grows to
about 40k input, mostly cached. With `gpt-5` that is roughly $0.40-0.80; with `gpt-5.5` roughly $1.50-3. `dry` prints the worst
case before any paid run.

## 5. Rules kept

- Dialogue is never trimmed, reworded or translated; a line is named by its id; the clock reports overruns.
- Never invent story: no new speaking person, line, event or object; a voice-only person is never in frame.
- Adam, David, Jonathan and DaVinci do not change.
- No live model call without the person's yes, each time.

## 6. Decisions (the person's)

DaVinci's D1-D8 carry over unchanged (D4 is settled by the length rule). New ones:

| # | Question | Recommendation |
|---|---|---|
| D1 | At the $5 cap or the turn cap: save nothing, or save what it has, marked *incomplete*? | save, marked incomplete (the post team can still read it) |
| D7 | The model | lab: `gpt-5` high for the first run, so it is compared with DaVinci on the same model; product: the person's choice (Jonathan uses `gpt-6.1-sol`; `gpt-5` shuts down 2026-12-11) |
| R1 | Turn cap | 20 |
| R2 | The lab: import DaVinci's checks, schema, bin and money code, or copy them? | import (one copy of the checks, so both labs are judged the same); copy only if DaVinci's lab is deleted |
| R3 | If both labs work: keep both, or move only the better one into the product? | only the better one; phases 1, 2, 4 and 5 are the same for either, so they are built once |

## 7. Phases

| Phase | Work |
|---|---|
| 0a | **Lab, free half.** `lab/raphael/`: the agent loop, the `put_clips` schema (DaVinci's clip plan + `IrW` in one), the one prompt (DaVinci's director prompt, minus delegation, plus the clip writer's design rules), a scripted rehearsal on Episode 1 (a refused `finish`, one batch repair, `finish` accepted), `dry`, the same page and `pick`. Offline tests. $0. |
| 0b | **Lab, paid.** Episode 1 under the $5 run cap and a **$5 lab budget** (own ledger). One change per paid run, with a hypothesis. Stop after 3 paid runs for the person's read. Pass = `finish` accepted within 20 turns, no blocking fault, bin never over 1.5x the given length and, by preference, close to the given length. Then the same small sample as DaVinci (one moment x 3 angles, a transition pair, a drone or B-roll clip) for the post team. |
| 1 | Contracts in `src/` (shared with DaVinci if R3 picks either). |
| 2 | Checks as product code (reuse Jonathan's checks and DaVinci's). |
| 3 | Raphael's prompt and loop in `src/`, the cap, the turn cap. |
| 4 | Storage (D5: extra fields on the shots table) and scene chaining. |
| 5 | Interface: a Raphael tab; intended cut view and shoot bin view grouped by role. |
| 6 | Live trial on one episode; the post team's verdict. |

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

## 9. Not in this plan

Transitions across neighbouring scenes; EDL / XML export; Zora editing Raphael's plans; a continuity critic.
