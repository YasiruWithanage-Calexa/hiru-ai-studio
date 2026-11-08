# Shot Planner DaVinci: what is built (plan/2026-11-08d)

Updated 2026-11-08. What the two paid runs found is in [RESULTS.md](RESULTS.md). Only **Phase 0** is built (the free half, then two paid runs that did not finish). Phases 1 to 6 are not started. The lab is `lab/davinci/`
(see its [README](../../lab/davinci/README.md)); nothing under `src/` changed.

## Plan B, the staged runner (lab half): built and tested offline, 2026-11-08, $0.00 spent

Everything in [PLAN-B.md](PLAN-B.md) §4 for the lab. The third paid run (§5) is not made: it needs the person's yes.

| Piece | State |
|---|---|
| `stages.py`: plan -> repair (at most 2, kept only if fewer blocking faults) -> design (all clips in parallel, 3 a call, by sequence, 8 threads) -> re-design (only failing clips, each with its fault, replaced only if better, at most 2) -> finish | built, tested |
| Per-stage start, end, calls, dollars in `trace.jsonl`, `outcome.json` and a Stages table in `bin.html` | built, tested |
| `schema.PlanW` / `LookW` / `plan_schema()`; `Bin.load`, `Bin.looks` (`looks.json`) | built, strict-schema test |
| `checks.plan_checks`, `design_checks`, `looks`, `better`, `mend`, `apply_looks` | built, tested |
| Prompts `director_plan.md`, `director_repair.md`, `clip_writer_staged.md` | written; **never run against a model** |
| `run.py --mode staged` (default) / `orchestrator`; `dry` prints the stage-1 message, schema sizes and the worst case of the whole run | built; worst case **$2.21** (plan $0.33, repair $0.74, design $0.38, re-design $0.76) against $3.27 left; likely about $0.46 (a guess) |
| Staged rehearsal `runs/rehearsal-staged/` | finishes: plan 2 blocking faults + 1 mend fix -> repair 2 -> 0 -> 6 design calls, 1 voice-only fault -> re-design of c11 alone -> 0; 9 calls, 14 clips, 90 s |

74 offline tests pass (44 of the orchestrator, 30 new); `ruff check lab/davinci` is clean; the cinematic lab's 38 tests pass.

**Where the build departs from PLAN-B's text, and why**
- New prompt files instead of rewriting `director.md` / `clip_writer.md`: PLAN-B §4 also says the orchestrator "stays in place so runs 1 and 2 can be reproduced", and rewriting those two would break that.
- `mend(reading, work)`, not `mend(scene, work)`: the take rounding needs the length limit.
- `mend` adds a missing line id only to the first MUST clip that covers the line's block, and only when no must clip carries the line at all. The plan's wording ("a clip that covers a block with a line but lists no line id") would also add it to reaction and insert clips that deliberately do not carry it.
- The look sheet is a new blocking plan check (`looks`): a moment without an entry is the director's fault, so the repair stage can cure it.
- `editor_notes` are the existing `edit_plan.editor_notes` (one place, not two).
- A failed or unparseable stage-1 answer ends the run as `error`; a bad repair answer keeps the earlier plan; a clip writer call that fails leaves its clips without a design, and stage 4 sends them back.
- If the repair is not better, round 2 sends the same message again (a second sample); it can be cut to one round if the paid run shows it is wasted.

**Still open (the person's):** the share of the +50% that goes to alternates (the stage-1 prompt says the cap is "never a goal to fill" and keeps run 2's one-clip-per-beat rule), D1, D3, D5, D6, D7, D8, and the yes for the third run.

## Phase 0 (lab): built offline, $0.00 of $5.00 spent

| Piece | State |
|---|---|
| Shapes: intended cut, clip menu entry, clip design, bin entry (role, covers, handles, take, priority, technique, speaks, slate, ir) | built, strict JSON schemas, tested |
| Code tools: coverage, clock, feasibility, designs, consistency; faults name their owner; `finish` refuses until they pass | built, tested |
| Money: the run's $5 cap (stops after the call that reaches it), the lab's $5 budget (refuses before a call that could pass it), ledger | built, tested incl. parallel reservations |
| Orchestrator: director loop, `coverage_planner` and `clip_writer` workers (parallel), `read_bin`, `check`, `finish` | built; runs end to end on a scripted rehearsal |
| Rehearsal (no model): Episode 1 in 14 clips and 90 s, a refused `finish`, a fault found, one clip re-sent, `finish` accepted | `run.py rehearse` -> `runs/rehearsal/bin.html` |
| The small part for the post team (one moment x 3 angles, a transition pair, a drone clip) | `run.py pick` -> `post_test.md` + one JSON per clip |
| Prompts: director, coverage planner, clip writer | written; **never run against a model** |

44 offline tests pass; `ruff check lab/davinci` and `mypy lab/davinci` are clean; the cinematic lab's 38 tests still pass.

## Not built, on purpose

- The **continuity critic**, `entity_state` and `check_continuity` (plan §4.2, §4.3): phase 0 asks whether the coverage can be
  cut, which only the post team can say. Added later if their cut shows drift that `checks.consistency` cannot see.
- Phases 1-6 (contracts in `src/`, tools as parts, storage, interface, live trial).

## What waits for the person

1. **A yes to the first paid run** (`run.py dry` first: the worst case of one director turn is about $0.17, a likely whole run
   about $0.60 by a guess, never measured). The run stops at $5.00 on its own, and the lab never passes $5.00 in all.
2. **D7**, the models (the lab defaults to `gpt-5` for the director and `gpt-5-mini` for the workers).
3. **Generate the sample with Veo** from `post_test.md` and give it to the post team with their questions. This is paid
   Veo generation, separate from the model budget.
4. The post team's verdict, and a blind read of Jonathan's cut against the bin.
5. The open decisions D1-D6, D8 (see PLAN.md §7) as the lab's answers come in.

## Known limits of the offline half

- The prompts and the director's tool use are untested against a real model: the first paid run may find schema or wording
  problems (a strict-schema rejection, a model that never calls `finish`). The run is bounded either way.
- The rehearsal's coverage is hand-written: its page shows the shape of a result, not a model's quality.
- Whether Veo keeps gestures and timing steady across angles (the plan's first risk) is not something code can check.

## First paid run, 2026-11-08: $0.93 of $5.00, did not finish

`runs/1-gpt_5_episode1`: all 40 turns used, 14 blocking faults, 21 clips left (24 planned, 33 removed and re-added over the
run, ids to c55). The director repaired by removing clips (7 `remove_clips`, 5 `check`s in 40 turns), which left moment 2 and
blocks b3, b9, b11 and b17 without a must clip; the clip writers kept putting the voice-only father on screen and writing
"calls out" in clips that perform no line. Its bin was 130 s of takes for a 60 s scene.

## The length rule (the person, 2026-11-08), built offline after that run

"30-40 clips for a 60 s video is too much ... the total shot length should not exceed the given length + 50%": the bin's
takes add up to at most the scene's given length x 1.5 (60 s -> 90 s, about 15-22 clips). Do not cover every shot or action
from several angles. Built: `checks.length` (blocking, owner director; `LENGTH_MARGIN = 0.5`), the limit and the seconds
left told to the director and the coverage planner as a `<length>` block (seconds, never money), the prompts rewritten to
plan the must clips first and add alternates only where the story turns, and the rehearsal cut to 14 clips, exactly 90 s.
This replaces the plan's "2-4x" (risk 5) and answers D4. A consequence: with long lines the must clips alone are about 76 s
of a 90 s bin, so the phase-0 sample's transition pair and drone clip fit only if a scene leaves room (`pick` says so).

## Repairs that cannot open a hole (built offline, 2026-11-08, after the first run)

1. `replace_clip` (new tool): a new plan in a clip's place; it keeps the id, a must clip stays must, the design is cleared.
2. `remove_clips` now simulates each removal and REFUSES one that would leave a block, a moment or a line without its must
   clip or its performer (the bin is left as it was; the message says to replace the clip instead).
3. Clip-writer prompt: two hard rules (the voice-only person, the speaking verbs) and a `<voice_only>` block that code builds
   from the script and puts in every clip-writer message.
4. Tests: no removal of any clip in the rehearsal bin can leave the coverage worse; replace keeps id and must; the block is sent.

44 offline tests pass; `ruff` and `mypy` are clean on `lab/davinci`. Nothing here has met a model yet: whether these fixes make
the director converge is what a second paid run (about $1, needs the person's yes) would show.
