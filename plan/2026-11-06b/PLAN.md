# Shot Planner Jonathan: the cinematic planner, proved in the lab (plan/2026-11-06b)

Status: written 2026-11-06. Plain words: [human-read.md](human-read.md). Evidence: `lab/cinematic/RESULTS.md` (plan/2026-11-06).

## 1. Why Jonathan

Shot Planner David (plan/2026-11-05e) plans a scene as 12 flat shots with one short note. The cinematic lab (plan/2026-11-06) proved
a planner that works like a director, DoP, producer and editor, and that stays good on any scene:

| What the lab proved | Evidence |
|---|---|
| A **treatment** first (logline, arc, approach, colour script, geography, key image, advice), then sequences, then shots with lens, angle and a story purpose | blind read 2026-11-06: lab 9, ChatGPT 8.5, David today 6 |
| **General** craft rules in the prompt, with no story in them (motion follows meaning, close shots for story objects, purpose first, a producer's time budget kept with 2 s cutaways) | five scenes, none used to tune |
| A **stabiliser**: a draft, code's checks, then up to two revise passes with the findings, best kept | drafts had faults in 2 of 5 scenes; every scene ended with 0 faults and at most 1 craft gap |
| The author must **see** which blocks move a person and which line is a thought | teleports 3 a run → 0 or 1 |

Jonathan is that planner, as a fourth choice beside classic, Adam and David. Name: **Jonathan** (`planner = "jonathan"`).

## 2. The rules this plan follows

1. **The Hiru AI pattern** (`docs/AI_PATTERN.md`, ADR 0010): one author per creative unit; code judges facts and people judge taste;
   repair, don't redo; memory in, state out. Jonathan's one change to rule 4: the repair call is a **revise** that returns a
   whole corrected plan from the author's own draft and code's findings (the lab measured it: it converges in two passes; a
   patch cannot move the treatment or the sequences). It is still the same strong model, never a critic, never a score that
   picks between two creative versions, never more than 2 passes. The budget per scene is **1 author + at most 2 revises**.
2. **Group isolation** (plan 2026-11-05e §4.0): Jonathan is a `jonathan/` group in each layer, independent of Adam and David, so
   `hiru-ai remove --group jonathan` lists everything that goes. It is built **as David was built from Adam**: its own copy of the
   contracts and parts, then changed. Nothing in David or Adam changes except the one-line shared exceptions in §4.2.
3. **No credits or costs in the interface** (interface CLAUDE.md). The lab's dollars stay in the lab.
4. **Prove before shipping** (the person's rule): the lab's gate decides the default (§9); the migration, live runs and the
   default are the person's.

## 3. What Jonathan is, in one picture

```
 pack (code)  ─►  ① AUTHOR (one strong call: treatment, sequences, shots, added, staging, end state)
              ─►  ② CHECK (code: hard faults + craft measures)      ─►  ③ MEND (code, incl. the split fix)
              ─►  ④ REVISE (only if a fault or a craft gap remains; the author's own best draft + findings → a corrected plan;
                            at most 2 passes; a worse pass is never built on; the best is kept)
              ─►  ⑤ WRITE (shots, design with pins, scenes.jonathan: the plan, the report, the end state)
```

## 4. The parts

### 4.0 Where Jonathan lives

```
src/libs/hiru_ai/agents/jonathan/      jonathan_author, jonathan_revise
src/libs/hiru_ai/steps/jonathan/       jonathan_pack, jonathan_links, jonathan_check, jonathan_mend, jonathan_seams, jonathan_write
src/libs/hiru_ai/systems/jonathan/     jonathan_shot_planner
src/libs/contracts/jonathan/           plan.py, wire.py (JonathanWire), stored.py, scene.py, checks.py, measures.py, mend.py, links.py, seams.py
src/services/shot_planner_jonathan/    the Cloud Run function (port 8211)
tests/jonathan/   tests/eval/jonathan/ tests, and the gold scenes (a copy)
docs/jonathan/                          README
hiru-ai-studio-interface/src/features/jonathan/   the Jonathan tab (other repository)
```

### 4.1 What comes from the lab, where it goes

| Lab file | Becomes |
|---|---|
| `prompt/system.md`, `prompt/example.json` | `jonathan_author/prompts/system.md` and its worked example (the `refuses_money` scene) |
| `schema.py` (`CinemaWire`) | `contracts/jonathan/wire.py` (`JonathanWire`: David's wire plus treatment, sequences, size list, angle, lens, `use_s`) |
| `checks.py` (hard checks, measures) | `contracts/jonathan/checks.py` and `measures.py` (the craft measures, reported never blocking) |
| `mend.py` (the split fix, F8) | `contracts/jonathan/mend.py` |
| `pack.py` (essence, style, time policy, `[move]`, `a thought`) | `steps/jonathan/jonathan_pack` |
| `run.py auto`, `revise_message` | the system `jonathan_shot_planner` and the agent `jonathan_revise` |
| `render.py` (`shot_card`) | the interface's Jonathan tab (cards), and `scripts/jonathan_compare.py` for blind reads |

### 4.2 Outside the group, on purpose (one line or a small block each, named in `tests/jonathan/test_removal.py`)

`contracts/jobs.py` (job kind `plan_scene_jonathan`), `contracts/build.py` (a pipeline branch), `contracts/production.py`
(`shot_planner` literal gains `"jonathan"`), `contracts/staging.py` (`AUTHORED` gains `"jonathan"`), `api/routers/scenes.py`,
`api/workers/task_manager.py`, `.github/workflows/deploy-functions.yml`, `scripts/start-functions.ps1`, `core/settings.py` (the model
for Jonathan's tiers reuses `author` and `repair`: no new tier), `pyproject.toml` (import-linter), `.env.example`, `CLAUDE.md`,
`docs/AI_CATALOG.md`, `langgraph.json`, and the **database pair** (§4.4).

### 4.3 The system `jonathan_shot_planner`

As David's (same pool, chains, links, seams, budget, reuse, cascade, edits), with the stabiliser in place of David's repair:
author → check → mend → revise ≤ 2 (best kept) → write. A scene whose `input_hash` is unchanged makes no call. Edits: `{"note"}`
makes one revise call with the person's note as the finding; `{"remove_added": n}` needs no model.

### 4.4 Storage (one migration; applying it is the person's)

`shots.planner` check gains `'jonathan'`; new column `scenes.jonathan jsonb not null default '{}'` holding the plan (with
`treatment`, `sequences`, `use_s`), the report (what code mended, what each revise changed, what is reported), the end state, the
link, `input_hash`. A new `supabase/migrations/…_jonathan.sql` and the `Database/` pair (v13, or folded into v12 if it is still
unapplied). `ProductionSettings.shot_planner` gains `"jonathan"`.

### 4.5 After the plan

As David: `AUTHORED` gains `"jonathan"`, so the shot producer does not call the DoP or the intent agent for its shots; the Veo
prompt is written in code from the author's IR. `use_s` (the seconds the edit keeps of a 4/6/8 s take) is **stored and shown**;
the editor reading it is a later plan.

### 4.6 API and interface

`GET /scenes/{id}/jonathan`, `POST /scenes/{id}/jonathan/plan {note?}`, `POST /scenes/{id}/jonathan/added/{n}/remove`, all behind
`CanDirect`. The interface gets a **Jonathan tab** beside David's: the treatment card (the existing `TreatmentCard`), the colour
strip, the sequences with their time windows, one card per shot (the lab's `shot_card` fields: size, angle, lens, movement,
purpose, line, sound, take and kept seconds), the staging (the existing `StagingMap`), what code mended, what a revise changed,
the end state. **No costs or credits.**

## 5. The checks

Every David check (blocks, lines in order and once, the clock, invented names, quoted speech, staging, end state, heard voices
out of frame) **plus** the lab's hard checks: a beat that says someone speaks in a shot with no line; `use_s` within 2 to the
take and never below a line's need; every shot in one sequence; the colour script names every sequence. The **craft measures**
(opens on geography, introductions, story objects get a close shot, reactions, compound actions, size variety, the grade moves,
sequence endings, **motion follows meaning**, totals, additions) are reported and drive the revise pass; they never block a plan.

## 6. Cost and time (from the lab, gpt-5 at high effort; never shown in the app)

About $0.15 to $0.27 a call, 2 to 4 minutes; $0.18 to $0.58 a scene with the stabiliser (1 to 3 calls). A scene over budget is
reported and spends no more.

## 7. Phases

| Phase | What | Model calls | Exit |
|---|---|---|---|
| 0 | This plan; the `jonathan` group folders (copy of David's, renamed); the isolation and removal tests; shared one-line exceptions | no | `hiru-ai validate`, import-linter, `tests/jonathan` green |
| 1 | `contracts/jonathan`: `JonathanWire`, the hard checks and craft measures, the split-fix mend, `stored`; gold plans by hand | no | the five gold scenes pass; mutants fail with the right sentence |
| 2 | `jonathan_author` (the lab's prompt and example), `jonathan_revise`, `jonathan_pack`; scripted eval cases | no | `hiru-ai eval jonathan_*` scripted green |
| 3 | The system with the stabiliser, `jonathan_write`, the function, the job kind, settings, the migration | no | `tests/jonathan/test_system.py`: a clean scene makes one call; a fault makes one revise; two failed revises are reported not failed; a worse revise is not built on; chains, reuse and cascade as David's |
| 4 | The shot producer reads Jonathan's design (`AUTHORED`) | no | `tests/jonathan/test_producer.py` |
| 5 | API and the Jonathan tab | no | `tests/jonathan/test_api.py`; the interface's feature tests |
| 6 | The gate in the product (§8), run by the person: the system on five real scenes, blind read by a Hiru director | live, the person's | the gate |
| 7 | The default (`shot_planner = "jonathan"`), and whether David is retired (a separate plan) | | the person's |

Phases 0 to 5 are built offline, as David's were. Applying the migration, running a live scene, the gate and the default are
the person's.

## 8. The gate (before Jonathan is a default)

1. Zero hard faults on five scenes, repeated three times each (the lab ran each once).
2. A blind read by a Hiru director who has not seen the plans: Jonathan at least equal to ChatGPT and clearly above David.
3. The stabiliser reaches 0 faults in at most 3 calls on at least 4 of 5 scenes.
4. No regression in the shot producer on a Jonathan scene (the Veo prompts pass `prompt_lint`).

## 9. What Jonathan does not do

No critic, no score that picks between plans, no second author, no tools, no agent that decides its own steps. It does not read
the person's taste: advice is shown, never applied. It does not trim a line. The reader's gaps (the narrator's closing line kept
as a voice-over, the rain not cut into its own scene, an implied move step for a car across the road) are the reader's, in their
own plan; until then they appear as the author's `advice`.

## 10. Risks

| Risk | Answer |
|---|---|
| Two copies of David's contracts drift apart | They are independent by rule (a planner can be removed without touching the others); a later plan may extract shared code once one planner is retired. |
| The craft measures are rules of thumb the lab wrote | They never block; the blind read is the judge (§8). |
| The revise pass hides a weak first draft behind three calls | The report stores the draft's and each pass's findings, so a regression in the author is visible. |
| The stabiliser's repeatability is unmeasured | The gate (§8.1) repeats each scene three times. |

## 11. Decisions for the person

| | Question | Suggestion |
|---|---|---|
| J1 | The name and ids (`jonathan`, `plan_scene_jonathan`, port 8211) | as written |
| J2 | Copy David's contracts (independent groups) or share code | **copy**, per the isolation rule |
| J3 | The model | `gpt-5` at high effort (the lab's), set by the environment, not code |
| J4 | The migration: a new v13 or folded into v12 | whichever is still unapplied on the hosted project |
| J5 | Who reads the blind comparison | a Hiru director, plus you |
| J6 | The default, and whether David is retired | after the gate; a separate plan |
