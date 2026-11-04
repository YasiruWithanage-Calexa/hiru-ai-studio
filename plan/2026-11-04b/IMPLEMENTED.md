# Shot Planner Adam: what is built

Plan: [PLAN.md](PLAN.md). Written 2026-11-04. Phases 0 to 10 are built **as far as code can take them without a person**.
Nothing is deployed and nothing was applied to the hosted database (the migration is written, not run). Apart from the one
live try below, no model was called: everything runs offline on localhost, with scripted answers. What only a person can
do (live runs, a Hiru director's judgement, the A/B, the decision on the default) is listed at the end and is NOT done.

## Where things stand

| Phase | State | What is open |
|---|---|---|
| 0. The `adam` folders and the yardstick | **Built, with two parts that need a person** | The 5 masters are **drafts by Claude**, not a Hiru director's. The baselines are **hand estimates**; the live `script_split` run is not done. 10 of 15 gold scenes are not written. |
| 1. Contracts and code | **Built** | The score weights are the plan's starting point (all equal); tuning waits for the person's A/B (Phase 10). |
| 2. Knowledge | **Built, not ingested** | `hiru-ai ingest adam_film_grammar` writes to the hosted dev database, so it waits for a person. The "10 probe questions" were run **offline against a keyword proxy**, not against `match_chunks`. The house drama notes are a **first draft by Claude**, not written with the person. |
| 3. The thinking (analyse, conceive, imagine) | **Built; never run on a real model** | The exit needs a **live run and a Hiru director**: "a person judges >= 4 of 5 treatments a real director's idea" is not done. That the three treatments of a scene differ is a code check (`adam_distinct`), passing on the gold scenes. The two alternate treatments per gold scene are **drafts by Claude**. |
| 4. The cards (stage, design, sound) | **Built; never run on a real model** | "The test scene's cards read like section 9 **to the person**" and "0 unreported overruns on the gold set" **for a model's cards** need a live run. Shown offline: the wiring rebuilds every master, and the masters pass every code rule. |
| 5. Screening | **Built; never run on a real model** | The exit "the revised plan wins on score in >= 60% of gold scenes" needs `scripts/adam_live.py --yes` (model calls). |
| 6. System, storage, switch | **Built offline; migration not run** | No Docker here: `supabase db reset`, `supabase test db` and the dump comparison are not done. Nothing deployed. "A production set to Adam builds end to end on localhost" is shown with fakes, not against the stack. |
| 7. After the plan | **Built, both engines** | "The 13 prompts render (live) and a person judges them against section 9" is not done. |
| 8. Interface | **Built; tests and typecheck pass** | Not looked at in a browser against a running backend. |
| 9. Editorial layer | **Built and tested with real ffmpeg; off by setting** | No endpoint or storage for a scene's finished cut (a person's decision). |
| 10. A/B and default | **Tools only** | Everything that is judgement: 10 gold scenes unwritten, no A/B judged, weights untuned, no decision on the default. |

## Phase 0: the folders

- **Registry groups.** A layer folder that holds a `group.yaml` is a group (`agents/adam/`); its parts are found by id
  like any other (package `hiru_ai.agents.adam.adam_dramaturg`). A folder with neither `component.yaml` nor `group.yaml`
  is now an **error** (a typo can no longer hide a part), and so are a folder with both, a group inside a group, a group
  whose id differs from its folder, and the same id inside and outside a group. A group whose `group.yaml` says
  `disabled` switches off all its parts in that layer. (`core/registry.py`, `core/manifest.py` `GroupManifest`)
- **`validate` rules.** An id in the group starts with `adam_`; an `adam_` id outside the group is refused; a part of the
  group names only parts of the group; nothing outside names one inside. (`Registry._check_group`)
- **CLI.** `hiru-ai list --group adam`, `hiru-ai new <kind> <id> --group adam` (writes into `<layer>/adam/`, refuses an
  `adam_` id without `--group`), `hiru-ai remove --group adam [--yes]`: deletes the group's folder in each layer plus the
  repo folders its `group.yaml` lists (`systems/adam/group.yaml`: `contracts/adam`, `services/shot_planner_adam`,
  `tests/adam`, `tests/eval/adam`, `docs/adam`), says what is "by hand" (the interface, the build branch, the
  migration), and lists every file outside the group that still names it. It never edits those files.
- **Import rules.** Six new independence contracts in `pyproject.toml` (Adam's parts never import each other); the
  existing layers and independence contracts already cover `hiru_ai.<layer>.adam`. `tests/adam/test_isolation.py` says
  what import-linter cannot: an Adam module imports only its group, a lower layer's group, `hiru_ai.core`, `hiru_ai.rag`
  and `contracts`; nothing outside the group imports into it; `contracts.adam` imports only `contracts.timing`. The
  scanners are tested on source text so they are shown refusing a bad import. `python scripts/lint_imports.py`: 25 kept.
- **The removal test** (`tests/adam/test_removal.py`) holds `group.yaml`'s list to the plan's §5.0 rule 6, word for word.
- **The exit checks:** `hiru-ai validate` passes (109 parts, 0 errors); the registry's ungrouped parts are exactly what a
  plain `<layer>/*/component.yaml` read finds; a scaffolded `adam_example` agent outside `agents/adam/` is refused; a
  grouped part that names an existing part is refused (`tests/adam/test_groups.py`).
- **Not done, on purpose:** adding `shot_planner_adam` to the "migrated function" import-linter contract. The service
  does not exist until Phase 6, and import-linter fails on a missing root package. Add it there.

### The yardstick (`tests/eval/adam/`)

- **5 scenes and 5 masters** in the card format of §5.1: `phone_call` (the test scene, §9, 13 cards, 66 s),
  `father_refuses` (an argument), `silent_morning` (a silent scene), `refuses_money` (a refusal), `arrival`.
  All are `status: draft`. Claude wrote them from §9 and from the 3-episode drama fixture; the Sinhala lines are short
  placeholders for the team to replace. A master that is "good" is a Hiru director's call; the tests only show the
  masters are consistent with the code rules and out-score the classic plan.
- **Baselines** (`baselines/`) are hand estimates of what `script_split` does (5 to 6 shots for the test scene, as §1
  says), marked `source: hand estimate`. **The live baseline is not done**: it needs a person to run `script_split` on
  the gold scenes. Code-scored on the same yardstick the masters reach 100% and the baselines 44% to 64%
  (phone_call 44.2, father_refuses 60.0, silent_morning 64.3, refuses_money 54.5, arrival 50.0). That gap shows the score can tell a
  vivid plan from a flat one; it is not the "baseline scores recorded" of the plan until the baselines are real.
- `RUBRIC.md` (Murch's order, "I felt I was there", the mute test), `ab_form.json` (the blind A/B record),
  `kb_probes.json`, and a `README.md` with the honest status table.

## Phase 1: contracts and code

- **`contracts/adam/`** (`plan.py`, `tiers.py`, `mapping.py`): the plan as pydantic models; the three tiers (and
  `invention`, a tier a model can name so it is refused with a reason instead of failing to parse); the 13 allowed
  elaboration kinds; `ShotCard` → `shots` row (`size` + `arrangement` → the seven `framing` values, `take_s` →
  `duration_s`, the card's moments → `block_start`/`block_end`, `cut_in.link` → `camera_link`).
- **Five steps** in `steps/adam/`, each with its own tests (ADR 0006):
  `adam_fidelity` (refuses a new person, a new line, a kind off the list, an object that does not fit the place, a moment
  that serves nothing, a quoted sentence the script never says; drops an added moment, sends the plan back for a script
  fault), `adam_fit` (the Veo clock; overruns reported, never trimmed), `adam_continuity`, `adam_feasibility`,
  `adam_score` (twelve signals; a fidelity break or an overrun is a loss first; `plans: [...]` picks the best and a
  tie keeps the earlier plan).
- **Exit checks** (`tests/adam/test_gold.py`): every master passes fidelity, fit, continuity and feasibility and beats its
  baseline; the test scene is the §9 plan (13 cards, 66 s, 12/12 signals); a hand-made plan with an invented line,
  person or event is refused with its reason (`new_person`, `invented_line`, `has_line`, `unknown_line`, `invention`,
  `bad_kind`, `new_object`).

### Where the contracts go beyond §5.1 (small additions the checks needed)

`SceneScript` (blocks, cast, place with objects, envelope) is what every step is given. `Moment.objects`; a script
moment names its blocks as `serves: [b3]`; `seconds_need: 0` means the moment plays under the one beside it (a line over a
listener's face). `Beat.reactor`, `PovOwner.handover` (a moment id), `Treatment.pov`, `.sound_concept`, `.ending_moment`,
`.off_speaker`, `Section.size_band` as `[smallest, largest]`. `ShotCard.subject`, `.axis` (A or B side of the line),
`.eyeline`, `.rhythm_break`. All are optional; none changes a rule of the plan.

## Phase 2: knowledge

`knowledge_bases/adam/adam_film_grammar/`: 16 principles (one per book source of §3), 40 devices with the eight fields
of §7 (what to ask, what it does, when to use, when not, allowed kind, Veo feasibility, how to write it on a card, a
Hiru-style example), the house drama notes and the Veo feasibility notes: 58 files, 68 chunks (a `--dry-run` ingest).
`docs/adam/DEVICES.md` indexes the devices and `tests/adam/test_docs.py` keeps it current.

- **Corpus.** `chunks.corpus` is limited by a database check to `craft`, `production_docs`, `canon` and `memory`, and a
  row with no production must be `craft`. So the base uses `corpus: craft` and is kept apart by its **source prefix**
  (`knowledge_base/adam_film_grammar/`; an ingest replaces exactly those rows). One consequence to decide in Phase 6: an
  agent that searches `craft` would also see the older ad-oriented craft notes. Either the Phase 6 migration adds an
  `adam` corpus (then it is one line in the manifest and a re-ingest), or Adam's system retrieves by source prefix and
  passes the passages in (its agents are structured, one call, and cannot search).
- **No `uses:`** in the manifest: the group rule says a grouped part names only its own group, and the shared
  `KnowledgeBase` base reaches the extractor and the chunker by id in code.
- **The 10 probe questions** pass at top-3 with a small BM25 keyword ranker over the chunks (`tests/adam/test_knowledge.py`).
  That is a proxy for the database's full-text half. The real check (the same queries through `search_kb` after
  `hiru-ai ingest adam_film_grammar`) has not been run.

## Phase 3: the thinking

`adam_dramaturg`, `adam_director`, `adam_moment_writer` (agents, `agents/adam/`), and one step, `adam_distinct`.

- **Wire shapes** (`contracts/adam/wire.py`, new). The generic agent contract test requires every `Output` property to be
  required and every object closed (OpenAI strict mode), and the plan's models have defaults, an alias (`break`, `from`)
  and a free-form mapping (`wants`). So each stage has a wire class with no default (`AnalysisWire`, `TreatmentsWire`,
  `MomentsWire`, `StagingWire`, `CardsWire`, `SoundWire`), and a method that turns it into the plan's shape. The
  agents' `Output` classes subclass them. `tests/adam/test_stages.py` holds each one to round-tripping the masters.
- **`adam_dramaturg`** (high). Output: the analysis of §5.1. `finish` drops an entry that names a block the scene does not
  have; the one exception is the key moment, which moves to the break, or failing that to the last block, because every
  later stage needs one (`agent.clean` returns what it dropped or moved).
- **`adam_director`** (high). One call, three treatments (restrained, intimate, heightened), so the model sees all three.
  It cannot know a moment id, so it says where the plant, its payoff and the rhythm break fall **in words**
  (`Plant.plant_when`, `.payoff_when`, `RhythmBreak.when`, new optional contract fields; `Treatment.stance` too) and the
  moment writer binds the ids. `finish` keeps one treatment per stance in order, drops a beat reference the analysis
  does not have and drops a plant of an object that fits neither the script nor the place.
- **`adam_moment_writer`** (high). Output: the moments and a `bindings` object (the moment that is the plant, its payoff,
  the rhythm break, the ending, the POV handover). `MomentsWire.bind` writes them into the analysis and the treatment; an
  id that names no moment stays empty rather than being guessed, so `adam_score` reports it missing. `finish` only tidies
  ids; whether a moment invents story is `adam_fidelity`'s decision, made after the agent so a refusal keeps its reason.
- **`adam_distinct`** (step, **not in the plan's list of six**; the exit asks for "a code check on size arc, POV and sound
  concept" and a step is where the repo puts one). Every pair of treatments must differ on at least two of the three
  axes, and in name and stance. The thresholds (`SAME_ABOVE` 0.6 word overlap, `ARC_SHARE` 0.5, `MIN_AXES` 2) are my
  starting point, all in one place, `logic.py`.
- **Prompts.** Static first, byte-identical, the data last and labelled as data. Each carries one worked example from the
  gold set, `refuses_money`, shown exactly as the agent will see a scene. The examples and the eval cases are
  **generated** from the masters (`tests/adam/stages.py`); a test fails when they drift. `refuses_money` has no eval case:
  its answer is in the prompt, `static_first` refuses a prompt that holds its own user message, and a live pass on it would
  prove nothing.
- **Grammar and devices are input.** The film-grammar passages (dramaturg) and the device library (director, shot
  designer) arrive in the Input as text, fetched by the system in Phase 6 (an agent here is one call and cannot search).
- **Two alternates per gold scene** (`tests/eval/adam/treatments/`): the masters hold one treatment each, so Claude drafted
  the other two stances for the five scenes. They are drafts, like the masters.

## Phase 4: the cards

`adam_blocker` (medium), `adam_shot_designer` (high), `adam_sound_designer` (medium).

- **`adam_blocker`** is a copy of the stager's prompt with an `ORIGIN.md` (source, commit, every change): marks and moves
  belong to a **moment**, a move says why (power, avoidance, approach, need, enter, exit), `holding` is a list. `finish`
  drops a mark or move for a moment or a person the plan does not have. `adam_continuity` finds teleports and unseen props.
- **`adam_shot_designer`** is given **the Veo clock** in its user message: how many seconds each moment takes (the longer
  of the picture's seconds and the speech, plus the lead-in) and each line's speaking time, so it can group moments into 4,
  6 or 8 s takes. The wire allows only `take_s` 4, 6, 8. A line is named by id. It is never told to shorten anything:
  overruns are reported by `adam_fit`, not fixed. The prompt carries the Veo notes (what renders well and badly) and asks
  for `veo_notes` where a card meets one.
- **`adam_sound_designer`** writes the scene's sound map and **every** card's sound as one piece, so the state change at the
  turn is planned once. `SoundWire.apply` writes it onto the cards.
- **The pipeline in test** (`tests/adam/test_stages.py`): the six agents run for real (prompt, user message, wire, `finish`)
  against a scripted model whose answers are the masters', each stage fed what the one before returned. For all five gold
  scenes the analysis, the moments, the staging, the cards and the sound map come out equal to the master; the moments pass
  fidelity, the cards pass fidelity, fit (0 overruns), continuity and feasibility, and the assembled plan scores 100%.
  This shows the wiring loses nothing. It does not show that a model can write those answers.

## What the system (Phase 6) must do that the agents do not

Choose a treatment (a person, or a quick score); on a `send_back` from `adam_fidelity`, `adam_fit` or `adam_continuity`
retry that one stage with the reasons (the agents take no notes yet); fetch the grammar and device passages; bind the
moment ids with `MomentsWire.bind`; drop what `adam_fidelity` says to drop; and fail clearly, naming the classic planner,
when the model is unavailable.

## Phase 5: screening

- **`adam_screening`** (panel, `critics_judge`): four critics in parallel (`adam_critic_audience`, `_editor`, `_opportunity`,
  `_fidelity`, medium), each with one lens, at most four notes (a card number, a severity, what and why) and a 1 to 5 score on
  its own lens. The fidelity critic alone is given the code's report (`adam_notes.report`: fidelity, the Veo clock, continuity,
  what Veo renders badly, the craft score). A critic that fails is left out; if all fail the first plan stands.
- **`adam_reviser`** (high) answers with OPERATIONS on the plan: `replace_card`, `insert_card`, `remove_card`, `add_moment`,
  `remove_moment` (`contracts/adam/screening.py` `RevisionWire.apply`). Numbers always mean the cards as the critics saw them;
  an operation that cannot apply is skipped and the panel records why; a script moment is never removed.
- **`adam_notes`** (step, new; not in the plan's list): merges the notes (most severe first, repeats on a card dropped, at most
  eight) and keeps the lens scores apart for a person; writes the code report.
- **Selection is code.** A revision is made once, `adam_fidelity` drops any added moment that invents story, and `adam_score`
  (a fidelity break or an overrun loses first) keeps the better; a tie keeps the first plan. The critics' scores decide nothing.
- **Shown offline** (`tests/adam/test_screening.py`, 28 tests): a revision that restores unmotivated cuts wins; one that
  invents a person is dropped and cannot win; one that makes the plan worse or breaks the script loses; failed critics and a
  failed reviser leave the first plan. **Not shown:** that a model writes good notes (the exit "the revised plan wins on score
  in >= 60% of gold scenes" needs `scripts/adam_live.py --yes`, which costs model calls).

## Phase 6: the system, storage and the switch

- **`adam_shot_planner`** (system; the plan calls it `shot_planner_adam`, but the group rule makes an id inside the group start
  `adam_`, so the system is `adam_shot_planner` and the function, folder and job kind keep the plan's names). `scene.py` runs a
  scene (analyse, three treatments and `adam_distinct`, the moments, stage, design, sound, screening); `graph.py` is the job:
  waves of four scenes, a time budget with a fresh delivery for the rest, an approved scene never touched, a scene Adam cannot
  plan left as it was and named in the job's warnings, no rules fallback (no model: the job fails and says "use the classic
  planner"). A script fault or an overrun is sent back ONCE with its reasons (the moment writer and shot designer take
  `notes`); overruns that remain are reported, never trimmed.
- **Treatment choice:** a person's stance if given, else the quick score `adam_distinct.choose` (fit to the analysis,
  distinctness, not over-directed); the other two are kept on the scene (`StoredPlan.alternates`). Switching re-plans only the
  cards from the stored analysis.
- **Edits:** `{"remove_moment": id}` takes an added moment out with no model call; the same addition (kind and blocks) is never
  added back by a later plan (`Removed`).
- **`adam_write`, `adam_passages`** (steps): rows, bound lines, the fit report in the classic shape, the stored plan; and the
  film-grammar and device passages picked by a keyword ranker over the base's own files, so a scene is planned the same before
  and after the (waiting) ingest.
- **The function** `services/shot_planner_adam` (echo template, port 8209, `FUNCTIONS`, `deploy-functions.yml`,
  `start-functions.ps1`, import-linter lists). **The build branch:** `contracts.build.build_pipeline(settings.shot_planner)`,
  used by `POST /build`. **API:** `GET …/scenes/{id}/adam`, `POST …/adam/plan` (also switches treatment),
  `POST …/adam/moments/{id}/remove`; `ShotView.planner`. The router reads the stored plan as plain JSON, so nothing outside the
  group imports from it.
- **Schema v11** (`supabase/migrations/20261104100326_adam.sql`, `Database/schema_v11.sql`, `upgrade_v10_to_v11.sql`,
  `supabase/tests/database/011_adam.test.sql`): `shots.card`, `shots.planner`, `scenes.adam`. **Not verified:** no Docker on this
  machine, so the migration, the dump comparison and the pgTAP file were not run, and nothing was applied to the hosted
  database.
- **Shown offline:** the gold scene planned end to end with scripted answers (13 shots, 66 s, 100%), lines bound, a re-plan
  replaces the shots and keeps the classic list for comparing, an approved scene skipped, a script fault sent back and then
  planned, planned twice and failed, an overrun reported not trimmed, a removal that never comes back, a treatment switch that
  skips the dramaturg and director (`tests/adam/test_system.py`, `test_api.py`, `test_service.py`).

## Phase 7: after the plan (the shot producer)

- `adam_write` stores, with each shot, an intent `by = "adam"` made from its card (purpose, what we see, who is in frame, who
  is only heard and from where) and the scene's coverage plan `by = "adam"`. `contracts.staging.AUTHORED = ("person", "adam")`:
  no agent replaces either, so **the intent agent is skipped, even when forced**.
- The DoP is told the card's camera as fixed (`DIRECTOR'S CAMERA, FROM THE SHOT CARD`), the recommendation takes the card's
  angle, lens, movement and aperture where the panel has an exact word (never the size), the card's performance per beat is
  kept like a person's beat note, the card's sound design replaces the generic room tone and a card that asks for silence has
  silence stated. A line played over a listener is a heard-only voice (the existing off-screen machinery) and the shot is a
  voice-over, so the speaker is never shown talking.
- `prompt_lint` checks a card shot: `silence_unstated`, `voice_not_off_screen`, `performance_dropped`, `sound_cue_missing`.
- All of it is in the part (`steps/serialize`, `systems/shot_producer`) **and** the legacy engine, a copy of `card.py` each; the
  parity tests agree on a scene with a card shot (`tests/adam/test_producer.py`). The shared code reads `shots.card` as plain
  JSON (`card.py`), so it imports nothing from the group.
- **Not shown:** the plan's exit "the test scene's 13 prompts render (live) and a person judges them against section 9".

## Phase 8: the interface (`hiru-ai-studio-interface/src/features/adam/`)

`api.ts` / `client.ts` (the seams), `types.ts`, `lib/` (map, cards, treatment, compare: pure, 22 tests) and `components/`
(`AdamPanel`, `TreatmentCard`, `ShotCardView`, `CompareDialog`; 8 tests). Mounted as an "Adam" tab of the Director's shot-list
panel through a `adamSlot` prop composed by the page, so the director feature imports nothing from `adam`. It shows the
treatment (three options, switching re-plans the cards), the cards in a breakdown format (the line rendered with `spoken()`),
chips per moment ("Script", "Implied", "Added by director", the last removable), "Plan with Adam" / "Plan again", the runtime
the treatment needs against the envelope ("Needs 66.0 s · envelope 40.0 s · 26.0 s over"), and **Compare**: the scene's earlier
shot list against Adam's, unlabelled and in a seeded order, scored on the rubric; the key appears only when every lens is
scored, and the record can be copied or downloaded in the `ab_form.json` shape. No credits or costs anywhere.
`npm run lint`, `typecheck` and `test` pass (150 tests); the new files are prettier-clean (the repository already has 61 files
that are not). **Not done:** a look in a browser against a running backend.

## Phase 9: the editorial layer

- `ShotCard.in_s`; `adam_fit` checks the kept part fits its take and **never cuts into words** (`trim_cuts_speech`).
  `contracts/adam/editorial.py` plans the cuts (`plan_cuts`: where each picture starts, how early a pre-lap sound arrives and
  how long a carried one runs, each only as far as the take can spare) and proposes trims by rule (`propose_trims` /
  `adam_trim`: a quiet card trimmed to where its last beat ends, never the last shot, never the one break, never a take with
  words, at least a second saved, at least 2 s kept; a pre-lap card starts its kept part a second in).
- `infra/assemble` `/cut` trims each take to its kept part, joins the pictures and mixes the sounds at their start (picture
  start minus lead), clamped to the footage the take has; a take with no sound is silent there. `HttpAssembler.cut` is the API's
  client. **Tested with real ffmpeg** (`tests/adam/test_editorial.py`): a 2 s reaction cut from a 4 s take; a pre-lap whose tone
  is measured (Goertzel) arriving a second before its picture; a silent take; a kept part longer than the take refused.
- Off unless `settings.final_cut_trim` (default false): then every take plays whole and `trim_not_ready` is the only note.
- **Not built:** an API endpoint that gathers a scene's accepted takes and stores the cut, and a place to store it (a new bucket
  or a path in `takes`): that is a decision for a person, and the take-acceptance flow belongs to the handoff feature.

## Phase 10: the A/B and the default

`scripts/adam_live.py` (every gold scene with the real model, saving `tests/eval/adam/live/<scene>.json` and printing the
numbers the Phase 3 to 5 exits ask for; refuses without `--yes`) and `scripts/adam_ab.py` (counts the blind A/B records against
the plan's targets, and `--tune` suggests weights that agree with a person's picks). **Nothing of Phase 10's judgement is
done:** 10 of the 15 gold scenes are unwritten, no A/B was judged, the weights are still equal, and whether Adam becomes the
default for new productions is a person's decision (D5 keeps `classic` as the default).

## Other changes outside the `adam` folders

- `core/registry.py`, `core/manifest.py`, `cli/main.py`, `cli/scaffold.py`, `cli/tools.py`: group support (above).
  `scaffold.py` also checks, before it writes, that an id is not already a part of another kind in a layer or a group.
- `pyproject.toml`: the six independence contracts, and the mypy exclude for part tests allows one more folder level.
- `docs/AI_CATALOG.md` regenerated (`hiru-ai catalog`).
- `contracts/adam/plan.py`: `SceneScript.listing()` (the scene as an agent reads it, with line ids), `SceneScript.fits()`
  (an object fits the place), `compact()` (a model as one line of JSON for a prompt) and the optional fields named above.
  Every master still validates unchanged.
- Two existing tests assumed a flat layout and now allow a group: `tests/hiru_ai/test_contract.py` (where a part lives)
  and `tests/hiru_ai/test_rag.py` (the set of knowledge bases, excluding the group's).

## Checks run

After Phases 3 and 4: `ruff check src tests scripts`, `mypy` (628 files), `python scripts/lint_imports.py` (25 contracts
kept), `hiru-ai validate` (116 parts, 0 errors), `hiru-ai catalog --check`, `hiru-ai eval` (the six new agents 4/4 each), and
`pytest`: 3096 passed, 6 failed (the six below).

After Phases 0 to 2 (for the record): `mypy` (593 files), `hiru-ai validate` (109 parts), `pytest`: 2943 passed. **6 tests fail and were failing
before this work**: `tests/api/test_handoff.py` (2), `test_looks.py` (1), `test_production.py` (3) expect the media URL on
port 8000 and this machine's `.env` sets 8001. Not touched.

Not run: `npx supabase test db` (no schema change was made), any live model call, `hiru-ai ingest`.

## First live try (2026-11-04, stages 1 to 6 on `phone_call`, outside the pipelines)

A scratch runner chained the six agents on the test scene with the real model (high and medium tiers), fed the
film-grammar files from disk (the base is not ingested), and ran every step on the result. No database, no service.

- **Run 1** found two bugs the scripted tests could not: the moment writer wrote kinds like `"baseline Anudi"` (the wire's
  `kind` was free text), so fidelity dropped 6 moments; and `adam_continuity` said a bag "goes to nobody" when its holder
  walked out (a holder with no mark at the next moment lost what they held). Both fixed, each with a test
  (`tests/adam/test_stages.py`, `adam_continuity` tests). Run 1's plan: 10 cards, 44 s, almost all CUs of Anudi.
- **Two prompt lines added** after run 1: the moment writer gives the face of the person who does not know (the analysis's
  `audience_knows`) a moment of its own and shows each subtext as behaviour; the director's size arc opens on the people
  together and moves away from the face after the break (Block's contrast).
- **Run 2:** fidelity, fit, continuity and feasibility all pass; 0 overruns; score 98.8% (master 100%, hand baseline
  44.2%). 10 cards, 44 s, sizes MS → MCU → CU → MS → INSERT → MS; Dasun's unknowing face gets a card; the rhythm break is
  on the turn. Still short of section 9: no early stake for Dasun, no "it's Dad" look, no mask smile on "See you", and
  the ending is an insert of the phone rather than Dasun beside the empty space. A person's judgement, not a code check.

## What a person does next

1. A Hiru director corrects the 5 draft masters and the scene wording, and flips `status` to `approved` (D6).
2. Run `script_split` live on the 5 gold scenes and store its plans in `baselines/` (Phase 0 step 2).
3. Say go for `hiru-ai ingest adam_film_grammar` (hosted dev database), then run the probes through `search_kb`.
4. Write the house drama notes with the person (the current file is a labelled first draft).
5. Decide the corpus question above before Phase 6.

6. Start the live runs (they cost model calls): `hiru-ai eval adam_dramaturg --live`, and the same for the other five, on the
   four gold scenes that have a case. A live pass only means the answer was valid, with the right stances and break block;
   **whether the treatments are a real director's ideas, and whether the cards read like section 9, is the person's
   judgement.**
7. Decide the thresholds of `adam_distinct` after seeing real treatments.

Then, for Phases 5 to 10:

8. `scripts/adam_live.py --yes` (model calls) for the screening exit and for the Phase 3 and 4 plans a person reads.
9. Run the migration where Docker is available (`npx supabase db reset`, `npx supabase test db`), compare the dumps, then
   `Database/upgrade_v10_to_v11.sql` on the hosted project when you say so; restart the API and the functions.
10. Deploy `hiru-shot-planner-adam` when you say so; set a production's `settings.shot_planner` to `adam`, or use "Plan with
    Adam" on one scene.
11. Judge blind A/B pairs in the interface (Compare) on the 15 gold scenes (10 are still to be written), save the records in
    `tests/eval/adam/ab_results/`, run `scripts/adam_ab.py`, then decide on the weights (`--tune`) and on the default.
12. Decide where a scene's finished cut is stored, then an endpoint can call `HttpAssembler.cut` with `contracts.adam.editorial`;
    switch on `settings.final_cut_trim` when it is proven.
