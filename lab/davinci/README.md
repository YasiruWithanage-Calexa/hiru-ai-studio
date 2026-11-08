# DaVinci lab

Phase 0 of [plan/2026-11-08d/PLAN.md](../../plan/2026-11-08d/PLAN.md): proves the orchestrator and its raw-coverage result on
one of the person's scenes (Episode 1) before anything moves into the product. Nothing under `src/` changes, no database row
is written, the other labs and planners are untouched, and deleting this folder removes the lab.

## Status

The **free half is built** (2026-11-08): shapes, checks, money rules, the orchestrator, a scripted rehearsal, the page, and the
chooser for the post team's sample. **Two paid runs so far ($1.73 of $5.00 in all; neither reached `finish`): results in [plan/2026-11-08d/RESULTS.md](../../plan/2026-11-08d/RESULTS.md).** What waits for the person is in
[plan/2026-11-08d/IMPLEMENTED.md](../../plan/2026-11-08d/IMPLEMENTED.md): the paid run, generating the sample with Veo, and the
post team's cut.

**Plan B (2026-11-08): the staged runner is the default and is built and tested offline** (`stages.py`; [PLAN-B.md](../../plan/2026-11-08d/PLAN-B.md)):
plan (one director call) -> repair (at most 2) -> design (all clips in parallel) -> re-design (only failing clips, at most 2)
-> finish. The orchestrator of runs 1-2 is kept unchanged (`--mode orchestrator`). The third paid run needs the person's yes.

## Run it (from the repo root)

```
.venv/Scripts/python.exe -m pytest lab/davinci/tests -q       # the offline tests (74)
OPENAI__API_KEY= .venv/Scripts/python.exe lab/davinci/run.py dry        # staged: the stage-1 message, schema, worst case of the whole run; calls nothing
OPENAI__API_KEY= .venv/Scripts/python.exe lab/davinci/run.py rehearse   # staged, NO model; writes runs/rehearsal-staged/bin.html (with a stage table)
OPENAI__API_KEY= .venv/Scripts/python.exe lab/davinci/run.py rehearse --mode orchestrator   # the orchestrator with NO model; runs/rehearsal/
OPENAI__API_KEY= .venv/Scripts/python.exe lab/davinci/run.py pick       # the small part for the post team (runs/rehearsal/post_test.md)
.venv/Scripts/python.exe lab/davinci/run.py paid --yes --hypothesis "…" # a REAL run: ask the person first, read `dry` first
```

Blank `OPENAI__API_KEY` for everything but `paid`: only `paid` reads `.env` or builds a client.

## The money rules (they are code, in `money.py`)

- `RUN_CAP_USD = 5.00` (the plan's §5): after each model call its cost is added to the run's total; at the cap the run stops.
  The last call or parallel group may take it a few cents over.
- `LAB_BUDGET_USD = 5.00` (phase 0): a call is refused before it is sent when the ledger total + calls in flight + this call's
  worst case (input at the input price + `max_output_tokens` at the output price) would pass it. Parallel clip-writer calls
  are all reserved before any is sent.
- A model with no price in `lab/cinematic/run.py` `PRICES` is refused. A failed call is entered at its worst case.
- No model is told a budget. After the first paid run, `--hypothesis` is required (one change, one reason).

## What is here

| File | What it is |
|---|---|
| `schema.py` | `EditPlanW` (the intended cut), `MenuW` (a clip's plan), `IrW` (its Veo design), `Clip`; staged: `PlanW` (edit plan + whole menu + `LookW` look sheet); strict JSON schemas |
| `state.py` | `Bin`: clips, ids and slates (code gives them), the work log; `Bin.load(plan)` replaces the whole menu at once, `Bin.looks` |
| `checks.py` | coverage, clock, feasibility, designs, consistency: every fault names its owner; `measures` for the page. Staged: `plan_checks`, `design_checks`, `mend`, `apply_looks`, `better` |
| `stages.py` | the staged runner: the five stages, parallel clip writers, per-stage time/calls/dollars in `trace.jsonl` and `outcome.json` |
| `money.py` | `Meter`: the run cap, the lab budget, the ledger |
| `brain.py` | the `Backend` interface and `OpenAIBackend` (Responses API, function tools); built only by `paid` |
| `orchestrator.py` | the director's loop, the worker calls, the code tools (`replace_clip`; `remove_clips` refuses a removal that opens a coverage hole), `finish` that refuses until the checks pass |
| `prompts/` | orchestrator: `director`, `coverage`, `clip_writer`. Staged: `director_plan`, `director_repair`, `clip_writer_staged` (new files, so runs 1-2 stay reproducible). No story words; a test holds it |
| `rehearsal.py` | hand-written tables run through the REAL code: the orchestrator's loop (a refused `finish`, a fault, a repair) and the staged run (a plan with 2 coverage faults and a missing line id -> mend -> repair -> a voice-only design fault -> re-design of that one clip) |
| `render.py` | `bin.html`: the intended cut, the bin by moment, the checks, Jonathan's numbers beside it |
| `run.py` | `dry`, `rehearse`, `paid`, `pick`, `ledger` |

## What differs from the plan's text, and why

- **The bin is held to the given length + 50%** (the person's rule, 2026-11-08): `checks.length` blocks `finish` over it. The plan allowed 2-4x.
- **No continuity critic, no `entity_state`, no `check_continuity`.** Phase 0 asks whether the coverage is cuttable, which only
  the post team can say; the critic is a strong-model cost to add if their cut shows match-action drift that code cannot see.
  `checks.consistency` holds the one match rule code can: every angle of a moment words the place, light and people the same.
- **Both $5 numbers exist** (the run's cap and the lab's budget); the lab's is stricter (it refuses before a call that could
  pass it), which phase 0's "under the $5 cap" needs.
- **Models are the lab's defaults, not D7:** director `gpt-5` (medium), workers `gpt-5-mini` (medium); both are in `PRICES`.
  Change with `--director` and `--worker` (a model with no price is refused).
- **Slates are `{scene}{setup}-{n}`** (`1B-3`), counted by code; D8 (the post team's convention) replaces this.
- **Jonathan's side of the comparison** is the cinematic lab's best plan of Episode 1 (`cinematic/runs/17-gpt_5-high`), shown as
  numbers and a shot list on the page. The blind read of two plans is the person's.
