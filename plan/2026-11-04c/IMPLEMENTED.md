# Shot Planner Adam: make the system defend the scene: what is built

Plan: [PLAN.md](PLAN.md). Written 2026-11-04. Phases 1 to 6 are built **as far as code can take them without a person**.
Phase 7 (the live runs) is **not done**: it costs model calls and is a person's to start. Nothing is deployed, nothing was
run against the hosted database, and no model was called: everything ran offline with scripted answers. Work is
uncommitted in both repositories.

## Where things stand

| Phase | State | What is open |
|---|---|---|
| 1. The yardstick (F2 coverage, F3 mutation tests) | **Built; every mutant caught but one named blind spot** | The plan's "run 3 scores below run 2's" cannot be tested: run 2's plan was not saved. See *Deviations*. |
| 2. Conservation and history (F1) | **Built** | The interface shows the history; there is no endpoint that replays an older job. |
| 3. Selection and repair (F4) | **Built** | Never run on a real model. |
| 4. The notes ledger (F5) | **Built** | Never run on a real model: whether a model answers every note honestly is what Phase 7 shows. |
| 5. The design step (F6) | **Built** | The designer's new prompt lines are untested on a real model. Density is reported, not targeted. |
| 6. Story questions (F7) and the interface | **Built; tests and typecheck pass** | Answering a question has no screen of its own: it is the scene's note. Not looked at in a browser. |
| 7. Live verification | **Not done** | `python scripts/adam_live.py --yes --runs 3` (about 165 model calls), started by a person. |

## The numbers the plan asked for (offline, on the gold set)

| Measure | Plan's target | Now |
|---|---|---|
| Score of the bare master (every added moment out except plant, break, ending) | below 80 % | **76.5 %** (it was 100 %) |
| The saved third live run, against the master | at least 15 points below | **72.8 % against 100 %** (27 points); its holes: Dasun at the turn, Anudi's and Dasun's own card before the break; and the clock now refuses "I'll come" over her own face (`bad_listener`) |
| Mutants of the gold masters the score catches | 100 % | **34 of 35**: the one left is a named blind spot (below) |
| Moments that leave a plan without a record | 0, enforced | enforced: `adam_ledger` fails the scene |
| Revisions kept that lose a required cell | 0 | 0 by construction (the rank), tested in `tests/adam/test_screening.py` |

`hiru-ai eval` (no agent, or an `adam_` one) prints the mutation line.

## Phase 1: the yardstick

- **`steps/adam/adam_coverage`** (new, code only). The grid: rows are the analysis' beats, columns the people; a cell is
  filled from a card's subject and framing (`faces`): the frame is on the person, a line plays over them, or they share a
  two-shot or group; an INSERT never shows a face. Required cells come from the analysis, never from the model: the
  reactor at the turn, **every other person at the turn or the beat after** (Murch's listener), the **irony** face of
  whoever does not know (from the block the audience knows), each **subtext**, each person's **stake** (a card of their own,
  single or over-the-shoulder, before and after the break), and the baseline, the key moment, the plant and payoff, the
  ending. "Involved" means a cast member who speaks or is named in the action; a voice marked "(on the phone)", "(V.O.)",
  "(off)" has no face to cover. A plant serves the block where it pays off, so its block is not counted where the card
  sits. Output: `cells`, `holes` (`{cell, why, suggest}`), `coverage`, `grid`; with no cards yet it gives the designer
  the required faces in words.
- **`adam_score`**: two new signals, `coverage` (weight 3, one check per required cell) and `one_job_per_card`; every
  signal now scores the share it needs (`baseline_shown` per baseline block, `variety` per card); `size_arc_kept` also asks
  that the cards reach the arc's widest and closest size; `line_placement` needs a listener who is present and not the
  speaker. `percent` is the craft share **times the coverage share** (see *Deviations*); `rank` is
  `(fidelity breaks, required cells lost to the other candidate, overruns, -score)`.
- **`tests/adam/mutants.py` and `test_score_mutations.py`**: seven kinds of mutant, built for each master where they
  apply (the other side removed, the bare plan, the break moved, a flat size arc, an own line over hands, the irony face
  cut, every adjacent pair merged that changes the face or the beat), 35 in all, must each lower the score by at least one
  point of 100. The suite also holds the numbers above.

## Phase 2: conservation and history

- **`steps/adam/adam_ledger`**: every moment the writer made ends in exactly one bucket: kept, dropped by fidelity
  (with the reason), removed by a person, removed by an operation **that answers a note**. One in no bucket, in two, or
  removed for no note fails the scene: "moment m8 left the plan without a record".
- **`report.ledger`** (the buckets and the inputs, so a person's later removal is reconciled too) and **`report.history`**:
  the first plan as it entered screening (compact), then events in order: cards sent back (with the reasons), cards split
  by code, the critics' notes, the revision (each operation with its `why`, the note it answered, whether it applied; the
  ledger of notes; any reason it did not stand; splits), and how both plans ranked and which was kept. A person's removal
  appends an event. `report.coverage`, `report.questions` and `report.density` sit beside them.

## Phase 3: selection and repair

- **`steps/adam/adam_split`**: a crowded card is repaired in code before screening. First the shortest longer take that
  holds it (4, 6 or 8); only if none does, a split at a moment boundary into takes of 4/6/8 s, the later parts copying the
  first's camera and cutting in on a `look` or an `action`. A line stays with the moment that says it. A moment that alone
  needs more than 8 s stays and is reported. The planner repairs before it sends a card back, so an overrun alone no longer
  costs a model call; the revision's cards are repaired the same way.
- **The reviser prompt** no longer says "removing is a fine revision"; it says a moment that fills a listed face is never
  removed and an overrun is never a reason to delete.

## Phase 4: the notes ledger

- Critics give each note a `kind` (add, remove, change, risk) and, for an `add`, the `cell` (a coverage cell id or a moment
  kind). `adam_notes` gives merged notes ids (`n1` ...). The reviser answers every note with a **disposition**: the
  operations that answered it, or why it declined. `check_revision` (`contracts/adam/screening.py`) holds it to it: every
  high note needs one; each is done xor declined; a "done" names an operation that applied; an `add` marked done must
  fill the cell it named; a `remove` marked done must remove the card it named; a removed moment must be named by an
  operation that answers a note. A revision that fails does **not** stand: the first plan is kept and `report.revision`
  says why. The fidelity critic and the reviser are also told the coverage report ("Never remove a moment that fills one
  of these").

## Phase 5: the design step

- **Prompt** (`adam_shot_designer`): one main job per card, a cut costs only the part of the take that is kept (a 4 s
  reaction with a `[0, 2]` beat, trimmed by `adam_trim`), an off-speaker line plays over a listener; it receives
  `<required>` (the faces to see); a hole after design is a **send-back** with the hole named.
- **`adam_fit`**: `bad_listener` (an overrun-level issue) when an off-speaker line's `over_whom` is the speaker, no one or
  not a person present.
- **D3**: Adam plans with the editorial trims on (`PLAN_WITH_TRIMS` in `adam_shot_planner/graph.py`), so the runtime counts
  the part of a take that is kept; the final cut applies them only when the production's `final_cut_trim` is on.
- **`report.density`**: cards, moments, moments per card, used shot length. No target (D4).

## Phase 6: story questions and the interface

- **`adam_dramaturg`** gains `questions` (what the script leaves open, with its blocks); `adam_continuity` raises one for a
  prop put down and never picked up before someone leaves (English action verbs only; the dramaturg covers the rest). A
  question is never an issue, never changes `ok`, and no model answers it. `phone_call` raises the phone question; a script
  that says she takes it raises none. The master of `phone_call` carries it.
- **Interface** (`hiru-ai-studio-interface/src/features/adam/`): "What screening changed" (each step and the note it
  answered, each note with its answer or reason, what code repaired, which plan was kept, why a revision did not stand, an
  undo for what screening added through the same removal path), "Open questions" (with the blocks), a "Faces seen" chip and
  the holes in "Things to look at". No credits or costs.

## Deviations from the plan, and why

1. **The percent is gated by coverage.** On the signals alone (`craft_percent`) the bare master reads 93.5 % and run 3
   92.6 %: missing 2 of 11 (or 3 of 14) required faces cannot cost 20 points when each is one check among many. The
   percent is now craft share × coverage share (bare 76.5 %, run 3 72.8 %). The signal stays as the plan says, so a hole
   counts twice on purpose: it is required content.
2. **The rank is lexicographic**, `(breaks, lost cells, overruns, -score)`, not `breaks + lost`: with the sum, a plan with a
   fidelity break could tie one that lost a cell and then win on craft.
3. **`adam_split` lengthens first.** A take too short for its card is given the shortest longer take that holds it; a
   split only follows when no take does. The plan says "split"; lengthening deletes nothing and costs less runtime.
4. **Equivalent merges.** A merge of two adjacent cards that stays on one face and one beat is no fault by the plan's own
   rule, so it is not a mutant (`equivalent_merges` lists them). **One blind spot is named, not hidden**:
   `silent_morning/bare`: a one-person scene with no break, no irony and no plant has nothing the score requires, so
   stripping its atmosphere and inserts scores like the master. Only a person sees that. The test fails if the score ever
   starts catching it, so the list stays true.
5. **Run 3's irony cell is filled**, by Dasun's single card at block 9 (his point of view after she leaves). The plan says
   run 3 has a hole there; the holes the grid finds are Dasun at the turn and the stake before the break. "Below run 2's"
   is not tested (run 2 was not saved); the gap to the master is.
6. **The key cell is stricter than "as today"**: the treatment's break moment must be in a card marked as the break, on the
   key block, so removing the break moment loses a cell.
7. **`bad_listener` is an overrun-level fit issue**, so a refused line is a send-back and a loss the way a line past its
   cut is.
8. **Not done:** the treatment's waiver of "each person's stake" (D1) and its "named long take" exemption for
   `one_job_per_card`: both need a field on the director's wire, which changes the director's prompt and cases. A solo or
   monologue scene is covered by what the analysis says (one person, no other cells).
9. **Answering a question** is the scene's note; there is no new endpoint or screen for it.

## What is NOT done (a person's)

- `python scripts/adam_live.py --yes --runs 3` on the 5 gold scenes; it prints, per scene, the median coverage, moments
  without a record, revisions that lost a required face, and the density. The exits: coverage at least 90 %, 0 lost, 0
  lost faces; `phone_call` showing Dasun's stake, his "doesn't know" face and his reading of her. A person judges the
  plans against the masters (2026-11-04b section 8 rubric).
- D4: measuring 3 to 5 aired Hiru scenes for density before any density target is set.
- D5: whether Anudi takes her phone. The answer goes into the scene as a director's note and the master is corrected.
- D6 (three densities side by side): not started, as decided.
- The masters are still Claude's drafts; the rules are derived from the analysis, not the masters, so they should hold on
  a director's corrections.

## Quirks hit while building

- `tests/adam/stages.py` generates the prompts' examples and the eval cases: run `write_all()` after changing a wire
  shape (the notes and the revision changed here).
- The repository's files mix LF and CRLF; patch with something that preserves each file's own endings.
- `npm run format:check` already fails on files this work did not touch (line endings and config files); the Adam files
  pass.
