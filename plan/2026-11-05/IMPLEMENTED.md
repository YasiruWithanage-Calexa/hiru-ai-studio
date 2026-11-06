# Shot Planner Adam in one take: what is built

Plan: [PLAN.md](PLAN.md) (plain words: [human-read.md](human-read.md)). Written 2026-11-05. The plan's phases 0 to 4 are built
**as far as code can take them without a person**, and the Phase 1 spike is written and not run. Nothing was run on a real
model, nothing is deployed, nothing was run against the hosted database, and no migration was applied: everything ran offline
with scripted answers. Work is uncommitted.

`ADAM_MODE` is `staged` until a person says otherwise, so **nothing changes for a production** until then: the five stages and
four critics are untouched and are what the A/B needs.

## Where things stand

| Phase | State | What is open |
|---|---|---|
| 0. Reasoning and cost on the record | **Built** | Applying `upgrade_v11_to_v12.sql` and setting `USAGE_DETAIL=true` are a person's. |
| 1. The spike | **Script written, not run** (`scripts/adam_take_spike.py`) | A person starts it (about $3), reads `tests/eval/adam/spike/summary.md` and decides D7. |
| 2. The take wire and agent | **Built** (variants A and B) | The sixth gold scene (20 or more blocks) is not written. Variant C (think-then-type) is not built. |
| 3. The one-take planner and reliability | **Built** | The default stays `staged` until Phase 6. |
| 4. One critic and the fixer ladder | **Built** | Never run on a real model: whether a small model's fixes are accepted is what the spike measures. |
| 5. The live gate | **Not done** | `python scripts/adam_live.py --yes --runs 3 --mode take` and `--mode staged`, then `adam_ab.py`: a person's. |
| 6. The default | **Not done** | A person decides (D7, D8, D6 follow). |

**There are no measured numbers in this file.** Every cost in PLAN.md §6 is still an estimate; the first measured ones come from
the spike.

## Phase 0: reasoning and cost on the record

- **`token_usage.reasoning_tokens`** (`supabase/migrations/20261105043213_token_usage_reasoning.sql`,
  `Database/schema_v12.sql`, `Database/upgrade_v11_to_v12.sql`, a pgTAP test `supabase/tests/database/011_...`). The hosted dev
  database already runs v11 (it was used on 2026-11-04), so this is a **new version pair**, not a fold into v11; the local
  `supabase test db` was not run (no Docker here). **Running the upgrade is the person's.**
- **`UsageCallback`** reads `output_token_details.reasoning` and writes it with the other per-call detail columns, so it is
  written only when `USAGE_DETAIL=true`: PostgREST refuses a row that names a column the table lacks, and the hosted table
  does not have this one until the upgrade is run. **Set `USAGE_DETAIL=true` only after it is run.**
- **`scripts/adam_cost.py`** prices a row at OpenAI list prices (standard tier) and prints calls per agent (prompt, cached,
  answer, thought, dollars) and the cost of a scene. **`scripts/adam_live.py`** keeps its calls in memory (the same rows) and
  prints that table per run and the median cost per scene at the end; it gained `--mode take|staged`, and saves a take plan
  under `tests/eval/adam/live/take/` so it never replaces the saved staged runs. Costs appear nowhere in the interface.
  `adam_ab.py` makes no model call, so it records nothing.
- **L5, reuse an unchanged plan.** `StoredPlan.input_hash` (a hash of the scene's script and context, the real line ids, what a
  person removed, `screening`, `editorial` and the mode). `graph.py` keeps a scene whose stored hash matches and that still has
  Adam's shots, counts it as skipped, and says so in the job log. "Plan with Adam" (`POST .../adam/plan`) sends `replan: true`,
  so a person's click always plans; a treatment switch and a moment removal never reuse.
- **Exit:** unit tests; the staged tests are unchanged and pass (the staged plans are byte-identical; only the new
  `input_hash` field is added to what is stored).

## Phase 1: the spike (not run)

`scripts/adam_take_spike.py --yes` runs variant A (the full `TakeWire`, no facts) and B (A plus the facts about the clock) on
three gold scenes with the critic and the ladder on, saves the plans and calls under `tests/eval/adam/spike/`, and writes
`summary.md`: score, coverage, breaks, overruns, hidden reasoning and dollars per variant beside the saved staged runs, and the
number of small-model fixes code accepted, **per kind of problem and rung**. It refuses without `--yes`. Variant C is not
built (it needs a breakdown wire and a typist agent, and the plan keeps it only if A and B miss the cost target).

## Phase 2: the take wire and agent

- **`contracts/adam/wire.py`**: `TakeWire` (analysis, the chosen treatment, `pitches`, moments, staging, cards), `TakeCardW`
  (a card without `sound`, a test keeps its fields equal to `CardW`'s), `TakePlan`, and `TakeWire.plan(analysis, stance)`,
  which builds the plan's parts through the methods the five stages use; also `CriticsWire` (below).
- **`agents/adam/adam_take`**: manifest (`model: high`, `timeout_s: 600`), schema, hooks, `ORIGIN.md`, and one system prompt made
  from the five stage prompts in the order the stages ran. Their rules are kept; the hand-off instructions are cut. It carries
  one worked example (`refuses_money`), generated by `tests/adam/stages.py`. Input: the scene, its context, the retrieved
  grammar and devices, **`<facts>`** (each line's words, seconds to say and the shortest take that holds it, from
  `scene.facts_of`), what a person removed, and for a treatment switch `<given_analysis>` and `<stance>`.
- **Tests:** on every gold scene the one scripted answer rebuilds the master (analysis, moments, staging, cards, pitches) and
  passes fidelity, fit, continuity, feasibility and scores 100 %.
- **Not done:** the sixth gold scene with 20 or more blocks (a draft master for a director to correct). D4 says it is needed
  only if the long scene loses, so it waits for the spike.

## Phase 3: the one-take planner and reliability

- **`scene.Planner.plan_take`**: take (one retry after a short wait if the call cannot be made: R3) → `adam_write` for what a
  person removed → `adam_fidelity` drops an added moment that invents story (and its card references and staging) → rung-0 mend
  of a misplaced line → `adam_fit` and `adam_split` → a **send-back of the whole take once** if the script is broken (then the
  scene fails and names the classic planner, as staged does) → `adam_sound_designer` (D3: it stays) → `adam_trim` → the code
  reports and the score → critic → ladder → `finish` (the same report, score, ledger and `history` as staged). `report.mode`
  says `take`; `report.fixer` lists each problem and what became of it.
- **`ADAM_MODE`** (`take` | `staged`, default `staged`; a delivery may carry `mode`). A treatment switch in take mode asks the
  take again with the pitch as `<stance>` and the stored analysis as `<given_analysis>` (the stored analysis wins whatever the
  take wrote); the treatment just left stays one click away.
- **R2:** `AgentManifest.timeout_s` replaces the tier's timeout for one agent (`adam_take`: 600 s; the tier says 180). It is
  passed to `get_llm`/`get_structured`. **R4** is unchanged: `TIME_BUDGET_S` and `PLAN_WORKERS` stay.
- **`StoredPlan.chosen_by`** gains `"model"` (the one take chose); the interface already shows anything but `person` as "Picked
  by Adam". The pitches are stored as `alternates` with a stance, a name and a concept only.
- **Exit:** `tests/adam` pass in both modes (24 new system tests); the stored plan and report keep their shape (the interface is
  unchanged and was not touched). Not run: the interface's own tests.

## Phase 4: one critic and the fixer ladder

- **`agents/adam/adam_critic`** (`medium`): the four lenses in one call, notes tagged by lens, one score per lens;
  `CriticsWire.results()` gives one answer per lens in the shape `adam_notes` merges, so the notes ledger is unchanged. Every
  lens reads the code's report. (`adam_screening` is not used in take mode: `scene.screen_take` does the same job directly.)
- **`steps/adam/adam_problems`**: `mend` (rung 0, code: a script line goes to the card that shows its moment) and `sort` (what
  code still finds, in a fixed order, then the critic's high notes, as `Problem`s of kind mechanical / local / creative, at most
  `MAX_PROBLEMS = 6` a scene, the rest left over and reported). A note that names a hole's cell is that hole's problem, so one
  fix answers both. Teleports and props that change hands unseen are the staging's, which no fixer operation writes: they stay
  in the report.
- **`agents/adam/adam_fixer`**: one problem in, the reviser's operations out. It sees the problem, the treatment's concept and
  the cards within two of the problem's card (all of them for a problem about the scene) with their moments.
- **`systems/adam/adam_shot_planner/ladder.py`** and **`fixer.yaml`**: for each problem, rungs from the file (`tiers: {small:
  medium, big: fixer}`, `kinds: {local: [small, big], creative: [small, big]}`, `rounds: 2`). **Moving a kind up a tier is one
  word in `fixer.yaml`; a test shows the called model changes with no code change.** A new tier `fixer` (gpt-5 at
  `effort_fixer=low`) is the big rung. After every fix code checks the whole plan: `adam_fidelity` (an invented moment is
  dropped), `adam_split`, `check_revision` (an `add` that names a face must fill it; a removal must answer a note; a fix for a
  fault code found **never removes a moment**), a fidelity break the fix added, "code still finds this problem", and
  `adam_score.rank` against the plan before. Refused → the next rung is told why. A fixer that cannot answer is a rung that
  failed, not a scene that did. At most two model rungs per problem and one pass; what is left is reported (`history` event
  `reported`, `report.fixer`, the ledger's `declined`). The final plan replaces the take's only if code ranks it no worse.
- **The gpt-5 reviser is not used in take mode.**
- **Exit:** tests with scripted fixers: accepted on rung 1 (the big model never asked), refused and sent up with the reason,
  refused at the top and reported (the scene is still written, the hole is named), a removal refused, a fixer that raises, a
  high note fixed with its ledger row answered, a low note kept for a person.

## Deviations from the plan, and why

1. **A new database version pair (v12), not a fold into v11.** The hosted database already runs v11.
2. **`reasoning_tokens` is written only with `USAGE_DETAIL=true`**, with the other detail columns, so a row never names a column
   the table lacks. The plan says only "fills it".
3. **The critic is called from `scene.screen_take`, not from `adam_screening`.** The panel's pattern (critics in parallel, one
   reviser, `critics_judge`) fits four critics and a reviser; one critic and a ladder is a different shape. The panel is
   untouched and still serves staged mode.
4. **`adam_distinct` is not used in take mode** (one treatment and two pitches; D2), so `report.treatments` is absent. The
   interface does not read it.
5. **The fixer's big tier is a new tier (`fixer`)**, because "gpt-5 at low effort" was not one of the four. `fixer.yaml` maps
   `small → medium`, `big → fixer`.
6. **Coverage holes are not sent back to the take** (staged sends the designer back once for a hole). In take mode a hole is a
   problem for the ladder, as the plan says; only a broken script sends the take back.
7. **Variant C and the sixth gold scene are not built** (see above).
8. **The interface and `adam_screening` were not changed.** `StoredPlan` gained one field and one allowed value.

## What is NOT done (a person's)

- Apply `Database/upgrade_v11_to_v12.sql`, then `USAGE_DETAIL=true` (restart the API and the functions).
- `python scripts/adam_take_spike.py --yes` (about $3), read `tests/eval/adam/spike/summary.md`, decide D7: which variant, whether
  Phases 2 to 4 stay, where each kind starts on the ladder.
- Phase 5: `python scripts/adam_live.py --yes --runs 3 --mode take` and `--mode staged` on the gold scenes (roughly $5 + $10), then
  the blind A/B with a Hiru director. The §7 gate is code (median score, coverage, no breaks, no overruns, no moment without a
  record) then the A/B.
- Phase 6: `ADAM_MODE=take` as the default. D6 (delete the stage agents) and D8 (L4, L6) follow.
- The pre-existing failing test `test_the_third_live_runs_plan_reads_far_below_the_master` is not caused by this work: the saved
  `tests/eval/adam/live/phone_call.json` is now the 2026-11-04 live run (92.2 %), not the run 3 the test names.

## Quirks hit while building

- A long shell heredoc silently wrote nothing on this machine: the patches were applied with the file tools instead.
- `tests/adam/stages.py` generates the take prompt's example and the eval cases of `adam_take`, `adam_critic` and `adam_fixer`:
  run `write_all()` after changing a wire shape or the take's input.
- The repository's files mix LF and CRLF; the edits kept each file's own endings.
