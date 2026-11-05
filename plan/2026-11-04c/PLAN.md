# Shot Planner Adam: make the system defend the scene: plan

Status: proposed (2026-11-04). Nothing in this plan is built. It builds on [plan/2026-11-04b](../2026-11-04b/PLAN.md)
(Shot Planner Adam, Phases 0 to 10 built) and changes none of its rules: never invent story, never trim a line, the Veo
clock, every elaboration labelled and removable. Decisions marked **(default)** in §8 are the assumptions this plan is
written on.

## 1. What the live runs showed

Three live runs on the test scene "An Unexpected Phone Call" (`phone_call`), 2026-11-04:

| Run | What ran | Cards | Runtime | Score | Code checks | Dasun's side |
|---|---|---|---|---|---|---|
| 1 | stages 1–6, before the fixes | 10 | 44 s | 88.9 % (a loss: 6 refused moments) | fidelity and continuity fail | almost absent |
| 2 | stages 1–6, after the two bug fixes and two prompt lines | 10 | 44 s | 98.8 % | all pass | his "doesn't know" face gets a card |
| 3 | the full system (`scripts/adam_live.py`), with screening and one revision | 8 | 44 s | 95.8 % | all pass | **lost again** |
| §9 master | the person's breakdown, drafted into the card format | 13 | 66 s | 100 % | all pass | stake, irony, reading her, left behind |

Run 3 meets every exit the 2026-11-04b plan can check by code: 0 fidelity breaks, 0 overruns, "the revision won". Yet it
is the flattest of the three. **A system that passes all its own checks while getting worse means the checks are
measuring the wrong thing.** This plan is about that, more than about any one prompt.

## 2. Analysis: from symptoms to causes

### 2.1 The evidence

Four measurements made for this plan (offline, no model calls), on the master and on run 3's saved plan
(`tests/eval/adam/live/phone_call.json`):

| Measurement | Master | Run 3 | What it says |
|---|---|---|---|
| Moments imagined | 17 | 16 | The moment writer imagines almost as much as the master. **The loss happens after it.** |
| Cards | 13 | 8 | |
| Moments per card | 1.31 | 2.00 | The shot designer packs. |
| Average shot length | 5.1 s | 5.5 s | Almost the same: ASL is **not** the right measure of what is missing. |
| Score of the master with **every added moment removed except the plant, the break and the ending** | 100 % | | **The score cannot see the difference between a director's plan and a bare one.** |
| Score of the master without Dasun's four added moments | 91.7 % | | It drops only because the last card (the ending) went with them, not because Dasun did. |

And the chain that removed Dasun's "doesn't know" moment in run 3, from the run's own log and report:

1. The moment writer wrote `m7` (Anudi listens), `m8` and `m9` (the smile thins). The analysis says the audience knows
   what Dasun does not from block 4, and the prompt asks for his face then: `m8` is almost certainly that face.
2. The shot designer put `m7`, `m8`, `m9` in one card. It needed 8.5 s; the longest take is 8 s. Sent back once, still
   over: "1 overrun(s) remain".
3. An overrun is a **loss** in `adam_score.rank` (fidelity breaks, then overruns, then craft, in that order). So the first
   plan entered screening already lost.
4. The fidelity critic flagged the overrun on card 3. The reviser's prompt says "prefer the smallest change" and
   "removing is a fine revision". Removing `m8` is the smallest change that ends the overrun.
5. The revision had 0 overruns, so it won **whatever it removed**. "The revision won on 1 of 1" is true and means
   nothing.
6. Nothing recorded it: the report keeps neither the first plan (`previous` is empty) nor the revision's five operations,
   and `report.moments.dropped` lists only fidelity drops. `m8` is simply missing from the ids.

This cannot be proven from the saved run because the first plan was not kept; that is itself a finding (C3).

### 2.2 Root causes

The eight issues from the runs come down to five causes. Fixing the symptoms (a prompt line per issue) without these
would make the next run pass differently and fail the same way.

| # | Cause | Symptoms it explains | Where |
|---|---|---|---|
| **C1** | **The yardstick is blind.** Every signal asks "is there at least one?" (a baseline, a turn face, a plant). A compact plan satisfies them as easily as a rich one, and `percent` normalises the rest away. Nothing counts the other person's side, the irony, the listener at the turn or a merged card. `variety` even gets easier with fewer cards (fewer adjacent pairs). | the 100 % bare plan; 95.8 % for 8 cards; Dasun lost without penalty | `steps/adam/adam_score/logic.py` |
| **C2** | **Selection has a deletion loophole.** Ranking is lexicographic and an overrun is a loss, so any revision without one wins, including one that deletes the scene's best moment. Nothing protects required content. This is the pattern reward-hacking studies find when agents delete the tests they must pass (EvilGenie, 2025). | m8 removed; "revision won" on every run with an overrun | `adam_score.rank`, `panels/adam/adam_screening/graph.py`, reviser prompt |
| **C3** | **Nothing is conserved or traced.** A moment can leave the plan between stages with no record. The first plan and the revision's operations are not stored. A person cannot see what screening changed, and neither could this analysis. | m8 vanished; can't tell who removed it | `systems/adam/adam_shot_planner/scene.py`, `StoredPlan.report` |
| **C4** | **The design step compresses.** "Pick the shortest take that holds them" and "a few moments that belong together" push moments into shared cards; with 4 s as the shortest take every extra cut costs 4 s of runtime, so packing is the cheap way to keep a scene short. The trims of 2026-11-04b Phase 9 (`use_s`, a 2 s reaction cut from a 4 s take) exist but the designer is never told to use them. | 2.0 moments per card; Dasun's reading of her folded into 1.5 s of another card; "I'll come" over her hands | `agents/adam/adam_shot_designer/prompts/system.md`, `adam_fit` |
| **C5** | **Notes are advisory and unowned.** The reviser "does not have to answer every note"; there is no record of which notes were acted on and which were declined, or why. Two critics asked for more Dasun and the answer was less. LLM revision research finds the same: revision without targeted, checkable feedback behaves like regeneration and favours its own output (Self-Refine; RefineBench 2025; "Pride and Prejudice", 2024). | the opportunity note ignored; screening tidies instead of improving | reviser prompt, panel `merged()` |

Two smaller issues are not causes but gaps in the contract: a speaker's own line can play over her hands (C4/C1: the
`over_whom` rule does not require a listener), and there is no channel for a **story question** the script leaves open
(does Anudi leave her phone on the bench?).

## 3. What other fields do about the same problems

Some of the best fixes come from outside film. Each row is a problem we have, a field that has had it for longer, and
what we take.

| Our problem | Field | How they handle it | What Adam takes |
|---|---|---|---|
| A scene "covered" with no reaction of the other person (C1) | **Film, the script supervisor's lined script** | Every setup is drawn as a line (a tramline) down the script page over the dialogue and action it covers. The page shows at a glance whether a line was covered in the master, whether a reaction was shot, whether an insert exists. The director asks "is his reaction covered?" and the page answers. | A **coverage grid**: beats × people present, filled from the cards. Holes are named, like a missing tramline. (§4 F2) |
| The listener's face is where the drama is (C1, C4) | **Film editing** (Murch, Dmytryk) | Murch lets the speaker's line run into the listener's reaction shot, holds the listener, then cuts back to the speaker reacting. | Listener at the turn and a reaction to each turn are **required cells** in the grid, not optional devices. |
| A score that optimised becomes wrong (C1) | **Software testing, mutation testing** | Coverage alone says little: delete every assertion and coverage is unchanged. Mutation testing injects small faults and checks the tests fail; the share of faults caught is the suite's real quality. Google and Facebook show mutants in code review. | **Mutation tests for the score.** Take each gold master, break it on purpose (remove the other person, merge cards, drop the baseline, move the break), and require the score to drop. A mutant that survives is a blind spot. (§4 F3) |
| A metric that is gamed once it is a target (C1, C2) | **Measurement, Goodhart's law**; LLM evaluation | "Evaluator stress tests": perturb the input and check whether a score moves for content or for format. | The same mutation tests, run on every change to the score, in CI. |
| An agent passes by deleting what it must keep (C2) | **AI safety, reward hacking** (EvilGenie benchmark) | Agents told to make tests pass sometimes delete or edit the tests. Benchmarks detect it with held-out tests and edit detection. | Required content becomes **protected**: a revision that removes a required grid cell loses, like a fidelity break. Overruns are repaired by code before screening, so deletion is never the cheap way out. (§4 F4) |
| A thing vanishes between stages (C3) | **Accounting, double-entry reconciliation**; **data engineering, lineage**; **event sourcing** | Every unit in must equal every unit out plus every unit accounted for, or the books don't close. ETL pipelines reconcile row counts per stage. An event log keeps every change, so any state can be explained and replayed. | A **conservation rule**: every moment id the writer creates ends as kept, dropped by fidelity (with the reason), removed by a person, or removed by an operation (with the note it answered). Anything else fails the job. An append-only plan log keeps the first draft and every operation. (§4 F1) |
| Required items must be traced to evidence (C1, C5) | **Aerospace, DO-178C requirements traceability** | Every requirement links to a test and every test to a result, in both directions; a requirement with no test is an audit finding. | Each analysis item that needs a picture (a turn, an irony, a subtext, the baseline) links to the card that shows it, and each card links back to what it serves. An unlinked item is a hole. |
| Notes are given, then lost (C5) | **TV production, network notes tracking**; **code review** | Productions keep a notes log: each note, the change made for it, or why not, tied to the script version. Code review comments end "done" or "won't fix, because". | A **notes ledger**: every note gets an id, a kind (add, remove, change, risk) and a disposition: an operation, or "declined: reason". A high-severity note with no disposition fails the revision. (§4 F5) |
| Criticism that only tears down (C5) | **Animation, Pixar's Braintrust and "plussing"** | Notes aim at the cause of a problem, not a prescribed fix; and a criticism must carry a constructive addition ("plus"). The director still decides. | Critics already propose; each note now names its kind and the cell or card it would fill, so its effect can be checked. The reviser still decides, but must say why when it declines. |
| One panel doing two jobs (C4) | **Storyboarding and animation layout** | A panel represents one action and should have one main job; a new background or camera angle starts a new scene in the board. | **One card, one main job**: a change of the face we are on, or of the emotional beat, starts a new card unless the treatment names a long take as a device. |
| Cutting costs runtime (C4) | **Editing practice**; Veo's fixed take lengths | Editors cut shorter than the take; the shot's "used length" is the editorial decision. | Plan short reactions as a 4 s take used for 2 s (`use_s`), so a cut costs 2 s, not 4. Requires the Phase 9 trims to be on for Adam (§8 D3). |
| Questions the script leaves open (the phone) | **Script supervision, script breakdown** | The supervisor and the breakdown raise queries to the writer and director instead of deciding them. | A **story questions** list from the dramaturg and the continuity step, shown to the person, never answered by a model. (§4 F7) |
| Averaging three ideas into one (later) | **Evolutionary search, Quality-Diversity (MAP-Elites, QDAIF)** | Keep the best solution in each niche of a behaviour space rather than one global best. | Later: keep the best plan per density (sparse, standard, dense) and let the person choose, instead of one score picking one plan. Optional (§5 Phase 7). |

## 4. The fixes

### F1. Conservation and lineage (C3)

- **The conservation rule** (`steps/adam/adam_ledger`, new): given the moments the writer made and the final plan, every
  id ends in exactly one bucket: `kept`, `dropped_fidelity {reason}`, `removed_by_person`, `removed_by_operation {op,
  note_id}`. An id in no bucket fails the job with "moment m8 left the plan without a record". Run after every stage that
  can change moments (fidelity, person removals, the revision).
- **The plan log** in `StoredPlan.report.history`: the first plan (cards and moments, compact), the cards after each
  send-back, the critics' notes, the revision's operations with `why` and `note_id`, and which version was kept and the
  rank of each. Append-only within a job.
- The interface shows the history as "What screening changed": each operation, the note it answered, and an undo that is
  the same "remove an elaboration" path a person already has.

**Test:** a scripted revision that removes a moment without naming a note fails the ledger; the run 3 shape (a removal
by `remove_moment`) appears in the history with its note.

### F2. The coverage grid (C1)

A new step `steps/adam/adam_coverage`, pure code, from the analysis, the moments and the cards:

- **Rows** are the beats; **columns** are the people present. A cell is filled when a card on that beat shows that
  person's face (subject, `over_whom`, or in a two-shot with them sharp).
- **Required cells**, each derived from the analysis, never from the model's own claims:

| Required | From | Filled by |
|---|---|---|
| The turn on the reactor | `beats[].turn`, `reactor` | the reactor in frame on that beat (today's `turn_seen`) |
| **The other person at the turn** | every other person present on the turn beat | their face on the turn beat or the one after (Murch's listener) |
| **The irony** | `audience_knows[] {who_doesnt, from_block}` | the face of `who_doesnt` on a card at or after `from_block`, before the fact reaches them |
| **Each subtext** | `subtext[]` | a card whose moment serves that block and shows the behaviour, object or sound |
| **Each person's stake** | every person present who speaks or is named in the action | at least one card of their own (single or OTS on them) before the break and one after |
| The baseline, the key moment, the plant and payoff, the ending | as today | as today |

- Output: the grid, the holes (`{cell, why, suggest}`), and `coverage` = filled required cells ÷ required cells.
- The shot designer receives the required cells in its user message ("these faces must be seen, on these beats"), the
  way it receives the Veo clock today. A hole after design is a **send-back** to the designer with the hole named.

**Test:** on the master the grid is full; run 3's plan shows a hole at "Dasun, block 4–5 (irony)" and "Dasun at the
turn"; a plan without Dasun's stake card shows "Dasun's stake before the break".

### F3. A score that can be trusted (C1)

1. **New signals**: `coverage` (F2, weighted 3, since it carries what the other signals miss), `one_job_per_card`
   (a card whose moments span two faces or two feelings without a camera move or a rack that links them loses a point
   each; a named long take is exempt), `line_placement` tightened (F6).
2. **Fractions, not existence**: every signal scores the share of its required items that are met, so one baseline card
   no longer earns the signal for a scene with two baselines.
3. **Remove the reward for fewer cards**: `variety` is counted per card, not per adjacent pair.
4. **Mutation tests** (`tests/adam/test_score_mutations.py`): for every gold master, each mutant must lower the score by
   at least one point of 100, and the real master must out-score every mutant:

| Mutant | Simulates |
|---|---|
| remove every added moment of the non-POV person | run 3's lost side |
| merge each pair of adjacent cards whose takes fit 8 s | compression |
| remove every added moment except plant, break and ending | the bare plan that scores 100 % today |
| move the rhythm break off the key moment | a misplaced break |
| make every card the same size | a flat size arc |
| play the speaker's own line over an insert of her hands | the "I'll come" card |
| remove the irony face | run 3's `m8` |

   A mutant that survives is a failing test with the mutant's name. The mutation score (killed ÷ all) is printed by
   `hiru-ai eval` and must be 100 % on the gold set before any score change merges.
5. Weights stay equal apart from `coverage` until the person's A/B (2026-11-04b Phase 10) tunes them.

**Test:** the mutation suite, and the numbers in §2.1: the bare master must score below 80 %.

### F4. Selection without a deletion loophole (C2)

1. **Repair overruns in code before screening** (`steps/adam/adam_split`, new): a crowded card is split at a moment
   boundary into two takes (4/6/8 by the Veo clock, the second card copying the first's camera fields and a `cut_in`
   with motive `look` or `action`). Deterministic, so the plan that enters screening has no overrun, and deletion is
   never the cheapest fix. If no split fits (one moment alone overruns 8 s), the overrun is reported as today.
2. **Protected content**: a candidate that leaves a required coverage cell empty that the other candidate fills
   **loses**, ranked with fidelity breaks: `rank = (fidelity breaks + coverage holes lost, overruns, -score)`.
3. The reviser prompt drops "removing is a fine revision" and gains: "a moment that fills a required cell (listed) is
   never removed; to fix a crowded card, split it (`insert_card`) or lengthen it".
4. The exit measure of 2026-11-04b Phase 5 changes from "the revision wins on score" to "the revision wins on score
   **and loses no required cell**".

**Test:** run 3's shape, scripted: a first plan with a crowded card, a revision that removes the irony moment; the split
repairs the first plan, and the revision loses on coverage.

### F5. The notes ledger (C5)

- Critics return each note with `kind` (`add`, `remove`, `change`, `risk`), `card`, and, for `add`, the coverage cell or
  the moment kind it would fill.
- The reviser returns `dispositions`: for every note, `{note_id, done: [operation indexes] | declined: reason}`. A
  high-severity note with no disposition, or a "done" that names no operation, makes the revision invalid (the first plan
  stands, and the report says why).
- Code checks what it can: an `add` note marked done must fill the cell it named; a `remove` note marked done must remove
  the card or moment it named.
- The ledger is stored with the history (F1) and shown in the interface next to the cards.

**Test:** a scripted reviser that answers 3 of 4 high notes is invalid; one that declines with a reason is valid and the
reason is stored.

### F6. One card, one job, and cuts that cost less (C4)

- **The shot designer prompt**:
  - Replace "pick the shortest take that holds them" with "one main job per card: a change of the face we are on, or of
    what the viewer feels, starts a new card, unless the treatment names a long take."
  - Add "a reaction can be a 4 s take of which 2 s is used (`use_s`)" when trims are on (§8 D3).
  - Add "an off-speaker line plays over a listener: a person present who is not the speaker. Never over an object or the
    speaker's own hands."
- **`adam_fit`**: an off-speaker line whose `over_whom` is the speaker or no person is refused (`bad_listener`). With trims
  on, the runtime uses `use_s`, so a dense plan no longer costs 4 s per cut.
- **Density is measured, not targeted**: report moments per card and used shot length per scene. Don't enforce a target
  until we have measured real Hiru teledrama scenes (cinemetrics method: count the cuts in 3–5 aired scenes) and the gold
  masters. ASL is the wrong single number here (§2.1).

**Test:** the "I'll come over her hands" card is refused; on the master with trims on, a 2 s reaction from a 4 s take fits
and counts 2 s.

### F7. Story questions (the phone)

- `adam_dramaturg` gains `questions`: what the script leaves open that changes what is filmed ("Does Anudi take her phone
  when she leaves?"), each with the blocks it concerns. Never answered by a model.
- `adam_continuity` adds one: a prop the script never moves again, left where a person exits.
- Shown on the scene in the interface as open questions with the blocks highlighted. An answer becomes a director's note
  the next plan reads.

**Test:** the phone question appears for `phone_call`; a scene where the script says she takes the phone raises none.

## 5. Phases

The yardstick comes first. Changing the generators before the measure can see the problem would repeat this round.

### Phase 1: the yardstick (F3 mutation tests, F2 coverage)
`adam_coverage`, the new and changed signals, `test_score_mutations.py`.
**Exit:** every mutant of every gold master is killed; the bare master scores below 80 %; run 3's saved plan scores
below run 2's, and below the master by at least 15 points; the parity fixtures and `script_split` untouched.

### Phase 2: conservation and history (F1)
`adam_ledger`, `report.history`, the conservation check after each stage.
**Exit:** a scripted run 3 shows `m8` removed by operation N answering note K; a removal with no record fails the job.

### Phase 3: selection and repair (F4)
`adam_split`, the new rank, the reviser prompt change.
**Exit:** the scripted run 3 keeps the irony moment: the split fixes the overrun, and the deleting revision loses.

### Phase 4: the notes ledger (F5)
Critic note kinds, reviser dispositions, the checks, storage.
**Exit:** every high note in a scripted screening has a disposition; an `add` marked done that fills nothing is refused.

### Phase 5: the design step (F6)
The shot designer prompt, `bad_listener` in `adam_fit`, density reporting; trims on for Adam if §8 D3 says so.
**Exit:** offline, the master's cards pass; the evals of `adam_shot_designer` updated from the gold set.

### Phase 6: story questions (F7) and the interface
Dramaturg `questions`, the continuity query, and in `hiru-ai-studio-interface/src/features/adam/`: "What screening
changed" (history and ledger) and "Open questions".
**Exit:** `npx next typegen && npm run check && npm run format:check`; the person can see why each change was made.

### Phase 7: live verification (a person starts it)
`scripts/adam_live.py --yes` on the 5 gold scenes, 3 runs each (models vary from run to run, so one run proves little).
**Exit, per scene, as a median of 3:** coverage ≥ 90 %; 0 moments lost without a record; the revision never loses a
required cell; `phone_call` shows Dasun's stake, his "doesn't know" face, and his reading of her. The person judges the
plans against the masters (2026-11-04b §8 rubric).
**Optional (only if the person wants several plans to choose from):** keep the best plan at each of three densities
(sparse, standard, dense) instead of one winner, as Quality-Diversity search does, and show the three side by side.

## 6. Success measures

| Measure | Today (run 3) | Target |
|---|---|---|
| Score of the bare master (§2.1) | 100 % | < 80 % |
| Mutants of the gold masters that the score catches | not measured | 100 % |
| Moments that leave the plan without a record | 1 (`m8`) | 0, enforced |
| Required coverage cells filled (live, median of 3) | Dasun's irony and his reading of her missing | ≥ 90 % |
| High-severity notes with a disposition | not recorded | 100 % |
| Revisions kept that lose a required cell | 1 of 1 | 0 |
| Fidelity breaks, unreported overruns | 0 | 0 (unchanged) |

## 7. Risks

- **Over-correction to density.** If coverage rewards more cards, plans get busy. Coverage asks for specific faces on
  specific beats, not for more cards. `one_job_per_card` lets the treatment name a long take. The opportunity critic can
  still remove. Watch moments per card in Phase 7; the master's 1.3 is a reference, not a target.
- **Runtime.** More cards mean a longer scene unless trims are on: the master is 66 s against an envelope that may be 40
  s (2026-11-04b §12 D2). F6 makes cuts cheaper; the envelope decision stays the person's.
- **The masters are Claude's drafts.** The mutation tests and coverage rules are written against them. If a Hiru director
  corrects them, the rules must still hold on the corrected versions (they are derived from the analysis, not the
  masters, for that reason).
- **The model gaming the grid.** A designer could tag a face as present without really giving it a card. The grid fills
  cells from the card's subject and framing, never from a model's claim that a cell is covered.
- **Cost.** No new model calls; the split, the coverage grid, the ledger and the checks are code. The live verification is
  15 scene runs of about 11 calls each, started by a person.

## 8. Decisions for the person

| # | Question | Recommendation |
|---|---|---|
| D1 | The required cells (§4 F2): the other person at the turn, the irony face, each subtext, each person's stake | **(default)** Yes, as listed; a treatment may waive "each person's stake" by naming why ("a monologue") |
| D2 | Coverage holes and lost cells as a loss, like fidelity | **(default)** A hole after design is a send-back; a revision that loses a cell the first plan had loses |
| D3 | Turn on the Phase 9 trims (`use_s`) for Adam's plans | **(default)** Yes for planning and runtime; the final cut uses them when the editorial setting is on |
| D4 | Measure real Hiru teledrama scenes for density (3–5 scenes) | Recommended before any density target is set; no target until then |
| D5 | The phone: does Anudi take her phone when she leaves? | The person's answer goes into the scene as a director's note, and the master is corrected to match |
| D6 | Phase 7 optional: three densities kept side by side | **(default)** Not now; after Phase 7 shows the single plan is right |

## 9. Sources

Film: lined scripts and coverage tracking (Scriptation, "Lining for script supervisors",
https://scriptation.com/features/lining-script-supervisors ; StudioBinder, "How to line a film script",
https://studiobinder.com/blog/how-to-line-a-film-script ; Rowlands, *The Continuity Supervisor*, 4th ed., "Coverage/Tramline
scripts", https://www.oreilly.com/library/view/continuity-supervisor-4th/9780240516134/87_chapter80.html ). Murch on
running a line into the listener's reaction (MovieMaker, "Walter Murch: cutting from the heart",
https://www.moviemaker.com/walter-murch-cutting-from-the-heart-3217/ ). Average shot length and its limits (Salt, Cinemetrics,
https://cinemetrics.uchicago.edu/article/ed328545-4793-48f9-91ed-7ab04ac4a560 ). Storyboard panels and scenes (Toon Boom,
https://learn.toonboom.com/modules/intro-to-storyboarding/topic/what-are-shots-scenes-and-panels ). Network notes tracking
(https://www.entertainmentcareers.net/resource/what-is-notes-tracking/292/ ). Pixar's Braintrust and plussing
(https://www.athena.com/blog/posts/how-to-run-a-brain-trust-pixar-style-feedback-meeting ; Catmull, *Creativity, Inc.*,
2014).

Software and engineering: mutation testing (Zeller et al., *The Fuzzing Book*, "Mutation analysis",
https://www.fuzzingbook.org/beta/MutationAnalysis.html ); DO-178C requirements traceability
(https://www.parasoft.com/learning-center/do-178c/requirements-traceability/ ).

AI research: Madaan et al., *Self-Refine* (2023) https://arxiv.org/abs/2303.17651 ; Xu et al., *Pride and Prejudice: LLM
amplifies self-bias in self-refinement* (2024) https://arxiv.org/abs/2402.11436 ; *RefineBench* (NeurIPS 2025)
https://neurips.cc/virtual/2025/128009 ; *EvilGenie: a reward hacking benchmark* (2025) https://arxiv.org/abs/2511.21654 ;
*Large Language Models as In-context AI Generators for Quality-Diversity* (2024) https://arxiv.org/abs/2404.15794 ;
Bradley et al., *Quality-Diversity through AI Feedback* (QDAIF, 2023).
