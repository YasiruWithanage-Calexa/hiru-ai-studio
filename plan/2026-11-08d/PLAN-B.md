# Shot Planner DaVinci, plan B: staged, not an orchestrator (plan/2026-11-08d)

Status: written 2026-11-08; **the lab half (§4) is built and tested offline, 2026-11-08** (see [IMPLEMENTED.md](IMPLEMENTED.md)); the
third paid run (§5) waits for the person's yes. Replaces the architecture of [PLAN.md](PLAN.md) §4 (the orchestrator) after the lab's
two paid runs ([RESULTS.md](RESULTS.md)). Everything else in PLAN.md still holds unless this file says otherwise: the goal
(raw coverage for the post team), the intended cut + shoot bin + editor notes, the camera vocabulary, the person's length rule
(the bin is at most the given length + 50%), the $5 run cap, the rules kept, and decisions D1-D8.

## 1. Why the change

The orchestrator worked mechanically but was too slow and never finished (RESULTS §1, `runs/ledger.csv`):

| | Run 1 | Run 2 | Jonathan (cinematic lab) |
|---|---|---|---|
| Model calls | 87 | 59 | 1-3 |
| Wall clock | 30 min | 15.5 min | about 2.5 min a call |
| Cost | $0.93 | $0.81 | about $0.16-0.20 a call |
| Finished | no (40 turns) | no (40 turns) | yes |

At 15-30 min per minute of story, a 15-minute screenplay would take 4-7 hours. The causes, from the traces:

1. **Designs were written before the plan was settled.** Clip writers (the slow, expensive step: about 70% of the time,
   30-96 s a call) designed clips the director then removed (35 in run 1) or replaced, which cleared the design (run 2).
2. **One action per turn, in series.** Per-clip tools made 26 single `replace_clip` turns in run 2. Every turn re-sent the
   growing context: 1.25 M director input tokens in run 2.
3. **Free order, no convergence.** Run 1's blocking faults went 27, 13, 16, 16, 12; more turns would not have finished it.

The person's decision (2026-11-08): **drop the orchestrator; build the staged version.** The director still makes every
creative decision. Code decides the order of the work.

## 2. The stages

```
 1. PLAN      director, ONE structured call
              edit plan + the whole coverage menu + the look sheet
              → code checks the menu (coverage, length, clock, speak rule, feasibility) + code mend
 2. REPAIR    only if blocking faults: director, ONE call with ALL faults → the complete corrected menu
              kept only if it has fewer blocking faults; at most 2 rounds; no design exists yet, nothing is thrown away
 3. DESIGN    clip writers, ALL clips at once, in parallel (2-3 clips a call)
              → code fills the look sheet in, code checks the designs
 4. RE-DESIGN only the failing clips, all in one parallel group, with their faults; at most 2 rounds
 5. FINISH    code writes the result (or the best result with its faults, D1)
```

No loop, no turn limit, no tool calls. At most **1 + 2 director calls** and **3 parallel groups** of clip-writer calls.

### 2.1 Stage 1: plan (director)

One structured call (a strict JSON schema, like `jonathan_author`), not a tool loop. It returns:

- `edit_plan`: the intended cut, as today (`EditPlanW`: treatment, sequences, moments).
- `clips`: the whole menu, as today (`MenuW` rows: moment, role, setup, blocks, lines, speaks, size, angle, lens, technique,
  why, take_s, handles, priority).
- `looks` (new): for each moment, the ONE `setting` sentence, the ONE `lighting` sentence, and each person's `description`.
  Aerial, establishing and atmosphere clips may carry their own.

The coverage planner worker is dropped: the director plans the whole menu in the same call (run 2's director never used it).

### 2.2 Code checks and mend after stage 1

The plan checks that exist today, without the design ones: `edit_plan`, `coverage`, `length`, `clock`, `feasibility`. Then
`mend` fixes in code what needs no judgement:

- a clip that covers a block with a line but lists no line id gets the id (run 2's L16 and L22 fault);
- ids, setups and slates are assigned by code (as today);
- numbers out of range are clamped only where the rule is mechanical (a take rounded up to 4 / 6 / 8 to hold its handles).

Code never deletes a clip, never trims a line, never changes a picture.

### 2.3 Stage 2: repair (director)

Same system prompt, the first message, its own answer and **every** blocking fault, each naming its clip (the
`jonathan_revise` pattern). It returns the complete corrected menu. Code keeps the new one only if it has fewer blocking
faults; at most 2 rounds. If faults remain, stage 3 still runs and they are reported at the end (D1).

### 2.4 Stage 3: design (clip writers)

- All clips at once: batches of 2-3 clips grouped by sequence, sent in parallel (8 threads instead of 4).
- **Consistency by construction.** Code writes `setting`, `lighting`, `first_frame.setting / lighting` and every subject's
  `description` from the look sheet *after* the design returns, overwriting what the writer wrote. Angles of a moment cannot
  differ any more, and the batches need no "copy from the first designed clip" context (which cannot work when all run at
  once). `checks.consistency` stays as a guard.
- The `<voice_only>` block and the two hard rules stay.

### 2.5 Stage 4: re-design

Only clips with a design fault, each sent with its own fault sentence, in one parallel group. At most 2 rounds. A design is
replaced only if the new one has fewer faults.

### 2.6 Stage 5: finish

Code writes `edit_plan.json`, `bin.json`, `bin.html`, `outcome.json` and the editor notes (the director writes them in stage 1
as an `editor_notes` field). If blocking faults remain, D1 decides what is saved; the lab saves the bin, marked incomplete.

## 3. Expected time and cost (an estimate, to be measured)

| Stage | Calls | Time | Cost |
|---|---|---|---|
| 1 plan | 1 director (about 15-20 k output) | 2-3 min | $0.15-0.25 |
| 2 repair | 0-2 director | 0-4 min | $0-0.30 |
| 3 design | 5-7 writers in parallel | 1-1.5 min | $0.10-0.20 |
| 4 re-design | 0-2 parallel groups | 0-3 min | $0-0.10 |
| **total** | | **about 4-10 min** | **about $0.30-0.80** |

Read from the lab's own calls: a gpt-5 call of 15-19 k output took about 2.5 min (cinematic lab), a gpt-5-mini clip writer
30-96 s (DaVinci ledger). Not tested yet.

## 4. Changes to the existing lab (`lab/davinci/`)

The orchestrator stays in place, so runs 1 and 2 can still be reproduced and their tests keep passing. The staged version is
added beside it and becomes the default.

| File | Change |
|---|---|
| `orchestrator.py` | **No change** (kept for the record). Its worker helpers (`ask`, `charge`, `voice_only`, the write-clips batching) move to a shared module, or `stages.py` imports them. |
| `stages.py` (new) | The five stages of §2: `Stages(reading, backend, meter, folder, cfg).run() -> Outcome`. Records each stage's start, end, calls and dollars in `trace.jsonl` and `outcome.json` (today the ledger has only each call's end time, so where time went had to be inferred). |
| `schema.py` | New `PlanW` (edit plan + clips + looks + editor_notes) and `plan_schema()`; `LookW` (per moment: setting, lighting, people). `MenuW`, `IrW`, `Clip` unchanged. |
| `state.py` | `Bin.load(plan)`: replace the whole menu at once, assign ids, setups and slates; `Bin.looks`. `replace_clip` / `remove` no longer used by the staged path. |
| `checks.py` | Split `check_all` into `plan_checks` (edit_plan, coverage, length, clock, feasibility) and `design_checks` (designs, consistency). New `mend(scene, work)` (§2.2). New `apply_looks(work)` (§2.4). `better(a, b)`: fewer blocking faults wins. |
| `prompts/director.md` | Rewritten for one structured answer: no tools, no "how you work" loop; adds the look sheet and the editor notes; keeps the length, roles, speaking, vocabulary and rules sections. |
| `prompts/director_repair.md` (new) | The repair message: your answer, the faults (each with its clip), return the whole corrected plan, change only what the faults need. |
| `prompts/clip_writer.md` | `setting`, `lighting` and `description` come from <looks> and are copied as given (code overwrites them anyway); <context> removed. |
| `prompts/coverage.md` | Unused by the staged path (kept for the orchestrator). |
| `orchestrator.Config` → `stages.Config` | `threads` 8, `batch` 3, `director_max_output` 32 000 (a whole plan + menu with reasoning), `repair_rounds` 2, `redesign_rounds` 2; `max_turns` gone. Models unchanged (gpt-5 medium, gpt-5-mini medium; D7). |
| `money.py` | **No change.** Run cap $5, lab budget $5 (remaining $3.27), parallel calls reserved before sending. |
| `rehearsal.py` | A staged rehearsal with no model: a plan with two coverage faults and a missing line id → mend fixes the id → repair fixes the rest → designs with one voice-only fault → re-design → finish. Writes `runs/rehearsal-staged/`. |
| `render.py` | Adds a stage table (time, calls, dollars per stage) to `bin.html`. |
| `run.py` | `--mode staged` (default) / `--mode orchestrator`; `dry` prints the stage-1 message, schema size and the worst case of the whole staged run. `paid` unchanged (asks for `--yes` and `--hypothesis`). |
| `tests/test_lab.py` | New tests: plan schema strict; mend fills a missing line id and nothing else; looks overwrite the three fields; repair kept only when better; re-design sends only failing clips; parallel batches by sequence; the staged rehearsal finishes; the run cap still stops a staged run. The orchestrator's tests stay. |
| `README.md` | The staged version is the default; the orchestrator is the record of runs 1-2. |

## 5. The third paid run (needs the person's yes)

- **Hypothesis:** "staged: one plan call, at most 2 repairs, all designs in parallel, looks by code".
- **Same scene and models** as runs 1-2 (Episode 1, gpt-5 / gpt-5-mini medium), so only the architecture changes.
- **Pass:** `finish` reached with no blocking fault; **10 min or less**; **$1 or less**.
- Clip writers at **low** effort is a later, separate run (one change per run).
- Then: the person reads `bin.html`; `pick` chooses the post team's sample; Veo; the post team's cut.

## 6. Decisions

- **Made (2026-11-08):** staged, not an orchestrator; this file.
- **Still open:** the share of the +50% that goes to alternates (RESULTS §8: run 2 went all-must, so the post team got no extra
  angles; the stage-1 prompt is where the rule goes); D1, D3, D5, D6, D7, D8 from PLAN.md §7.

## 7. Related: Shot Planner Raphael (plan/2026-11-08e)

A separate session is testing a third shape for the same output: ONE strong agent (gpt-5 high) that writes the plan and every
Veo design itself, with batch tools (`put_clips`) and a check report on every write (`lab/raphael/`, which imports DaVinci's
checks, `Bin` and money). Its length rule from the person applies here too: **the target is the script's given length; +50%
is headroom and a hard cap, never a goal to fill.** Raphael's results (`plan/2026-11-08e/RESULTS.md`, once written) should be
read beside plan B's third run: the same scene, three shapes (orchestrator, staged, single agent).

## 8. What changes in PLAN.md

§4 (architecture) and §4.5 (three model slots → two: director, clip writer; the critic was already left out of the lab) are
replaced by this file. §8 phase 3 reads "the staged runner" instead of "the orchestrator loop". The rest stands.
