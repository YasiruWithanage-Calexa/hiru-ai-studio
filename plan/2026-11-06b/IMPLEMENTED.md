# Shot Planner Jonathan: what is built (plan/2026-11-06b)

Status 2026-11-06 (later): **Phases 0 to 5 are built and verified offline.** Jonathan is the cinematic lab's planner in the
product: the lab's prompt and worked example, its answer shape, its checks and craft measures, its split fix and its stabiliser
(a draft, then up to two revise passes from the best plan, the best kept), the trial and the blind page, and the interface's
Jonathan tab. Nothing here has called a model, nothing has been applied to the hosted database, and nothing is committed.

## The same quality as the lab: what is proved, and how

`tests/jonathan/test_lab_parity.py` compares Jonathan with the lab's own code (it skips once `lab/` is deleted):

| What | Result |
|---|---|
| The author's system prompt (team prompt + the `refuses_money` worked example) | the lab's, to the letter; the reviser's is the same file |
| The JSON schema the model is held to | the lab's (only one class title differs) |
| The user message for Episode 1, built by `jonathan_pack` from the rows the graph reads | the lab's, to the letter |
| The revise message (the author's message, its draft, the findings, the ask) | the lab's `revise_message`, to the letter |
| Every saved lab answer (runs 1 to 19, five scenes) through Jonathan's mend, checks and measures | the lab's craft gaps on every run; the lab's faults on every run but the end state's place name, which Jonathan's mend now writes from the staging (runs 1, 2, 4 and 9 had it, the lab's own finding) |
| The stabiliser | the lab's `auto`: a score of (faults, craft gaps), at most 2 passes, a pass kept only when lower, the next pass from the best (`tests/jonathan/test_system.py`) |

What is not the lab's, on purpose: the call goes through the product's model layer (LangChain, the `jonathan` tier: the author
model at high effort, strict JSON schema), not the lab's direct Responses API call, so no output-token cap is set. The revise
pass sends the plan as code mended it (the lab sent the raw draft), so the findings' shot numbers match the plan they name. The
time policy is written from the scene's envelope in the budget wording for every scene. A scene with a scene before gets two
more parts, each saying what it is for (the lab's prompt knows no scene before). The `mirror` advisory no longer fires on wet
roads. What the reader gets wrong (the narrator's line, the rain cut into its own scene, the car across the road) is the
reader's, as the plan says.

## What a person does next

| Step | Place | Notes |
|---|---|---|
| 1. Apply the migration | `Database/upgrade_v12_to_v13.sql` (or `schema_v13.sql` on an empty project) | **not run**; the hosted project is the one dev database |
| 2. The live trial (phase 6) | `scripts/jonathan_spike.py --yes --repeat 3 --budget 5` (gold scenes; `--scene-file lab/cinematic/input/reading.yaml` for Episode 1) | costs model calls: about $0.18 to $0.58 a scene; `--budget` is a hard stop |
| 3. The blind read (gate 2) | `scripts/jonathan_compare.py` after pasting ChatGPT's answers into `tests/eval/jonathan/chatgpt/<scene>.txt` | a Hiru director who has not seen the plans |
| 4. A live scene in the app | the Jonathan tab: "Plan with Jonathan" | after the migration |
| 5. The default and David's future | `settings.shot_planner = "jonathan"` | after the gate (plan §8) |

## Phases 1 to 5, what was built

- **Contracts** (`contracts/jonathan`): `wire.py` is the lab's `CinemaWire` (treatment, sequences, eleven sizes, angle, lens,
  `use_s`; `ShotW.framing` gives the nearest shared size); `checks.py` gains the lab's hard checks (speaks, use, sequence, colour,
  heard-in-frame) and drops a problem two checks find; `measures.py` is the lab's eleven craft measures, with `Craft` (people's
  codes, story objects = the production's props the script names, the length guide); `mend.py` is the lab's mend with the split
  fix, plus the end state's places from the staging; `scene.py` has the lab's listing (`[move]`, `a thought`, `heard not seen`)
  and the shared `clean`; `stored.py` keeps the measures.
- **Agents**: `jonathan_author` (the lab's prompt to the letter); `jonathan_revise` answers the whole plan (not a patch) from the
  author's prompt, message, draft and findings. Both on the `jonathan` tier, 900 s.
- **Steps**: `jonathan_pack` writes the lab's production part (style guide, look, voice, who they are) and the time policy;
  `jonathan_check` returns the measures and the score; `jonathan_write` maps sizes to `shots.framing`, puts `use_s` on the card,
  reports the envelope against the seconds kept and writes the coverage plan from the treatment.
- **System**: `Planner.stabilise` (the lab's `auto`); a seam is one more pass with the join counted as faults; a note is one pass
  kept unless it adds a fault. The graph passes each person's essence (canon card summary) and the craft facts.
- **Tools**: `scripts/jonathan_spike.py` is now the live trial of the gate (repeat, hard budget, exact prices, the gate's points
  1 and 3 per scene); `scripts/jonathan_compare.py` prints Jonathan's plan as the lab's shot cards under its sequences.
- **Interface** (other repository): `src/features/jonathan` and a Jonathan tab beside David's on the director page: the
  treatment, the colour script, the sequences with their place in the edit, shot cards under their sequence, the checks
  (fixes, revisions kept or not, what is left, craft notes, staging, end state), Plan again, a note, Remove. No costs.

## Phase 0, what exists

- **The group**, David's folders copied and renamed (`david` to `jonathan`, `david_repair` to `jonathan_revise`, port 8210 to 8211):
  `agents/jonathan` (`jonathan_author`, `jonathan_revise`), `steps/jonathan` (pack, links, check, mend, seams, write),
  `systems/jonathan` (`jonathan_shot_planner`), empty `panels`, `tools`, `knowledge_bases` groups, `contracts/jonathan`,
  `src/services/shot_planner_jonathan`, `tests/jonathan` (125 tests), `tests/eval/jonathan` (the five gold scenes),
  `docs/jonathan`, `scripts/jonathan_spike.py`, `scripts/jonathan_compare.py`. David's measured spike output and pasted ChatGPT
  answers were not copied.
- **The shared lists** (plan §4.2), additions only: job kind `plan_scene_jonathan`, `BUILD_PIPELINE_JONATHAN`,
  `shot_planner` literal and `jonathan_order`, `AUTHORED` and `IntentBy`, the function's registration (`task_manager`,
  `deploy-functions.yml`, `start-functions.ps1`), `settings.jonathan_workers`, `.env.example`, the router (`GET /scenes/{id}/jonathan`,
  `POST .../jonathan/plan`, `POST .../jonathan/added/{n}/remove`), `pyproject.toml` (service names and six independence
  contracts), `CLAUDE.md`, the catalog and `langgraph.json` (regenerated).
- **A tier of its own**, `jonathan` (`OPENAI__MODEL_JONATHAN` at `OPENAI__EFFORT_JONATHAN`, default `high`, 900 s), because the lab
  proved Jonathan at high effort and David's `author` tier defaults to medium. Both agents use it.
- **2026-11-06, the model moved to `gpt-6.1-sol`** (the person's choice): its own setting `model_jonathan`, so David stays on
  `OPENAI__MODEL_AUTHOR`. gpt-5 shuts down 2026-12-11. Sol is $2 / $0.10 / $10 per 1M tokens (gpt-5: $1.25 / $0.125 / $10)
  and supports high effort and strict `json_schema` output. Not yet run live; the lab's results were all on gpt-5 and gpt-5.5,
  so the spike (`scripts/jonathan_spike.py`, Sol priced) is the check.
- **The migration pair**, written and not applied: `supabase/migrations/20261106120000_jonathan.sql`,
  `supabase/tests/database/014_jonathan.test.sql`, `Database/upgrade_v12_to_v13.sql`, `Database/schema_v13.sql` (v12 plus this),
  and two rows in `Database/README.md`.

## Where Phase 1 started (done)

The lab is the spec; each lab file has a destination (plan §4.1):

| Lab file | Destination | What changes |
|---|---|---|
| `prompt/system.md`, `prompt/example.json` | `agents/jonathan/jonathan_author/prompts/system.md` and its example | replace David's prompt; a test already fails if a story name or object is in it |
| `schema.py` (`CinemaWire`) | `contracts/jonathan/wire.py` | the new top shape (treatment, sequences, shots with sequence, angle, lens, `use_s`); David's `ShotW` shape stays as the base the existing checks read (`to_david` in the lab) |
| `checks.py`, `mend.py` | `contracts/jonathan/checks.py`, `measures.py`, `mend.py` | the hard checks, the craft measures (incl. `motion`), the split fix |
| `pack.py` | `steps/jonathan/jonathan_pack` | essence, style, time policy, `[move]`, `a thought` |
| `run.py` (`revise_message`, `auto`, `score`) | `agents/jonathan/jonathan_revise` and the system | `jonathan_revise` returns a whole corrected plan, not a patch; the loop is draft, check, mend, up to 2 revises, best kept |
| `render.py` (`shot_card`) | the interface tab (Phase 5) and `scripts/jonathan_compare.py` | |

Copied tests that assert David's behaviour (patch repair, `PatchWire`) will need to change with the revise agent.

## Where it differs from the plan

- **The `jonathan` tier** replaces "reuse `author` and `repair`" (plan §4.2): see above.
- **Agent manifest timeout** is 900 s, the schema's cap (the plan did not say).
- **The removal scan skips `lab/`** (`cli/tools.py`), the way it skips `plan/`: the lab names David and is deleted when Jonathan lands.
- **Allow-lists** in `tests/adam/test_removal.py` and `tests/david/test_removal.py` gained the new files; Adam's also gained two
  files that already named Adam and were failing it (`scripts/david_compare.py`, `tests/hiru_ai/test_registry_threads.py`).
- **Jonathan's agents contract names its two agents** (`jonathan_author`, `jonathan_revise`) instead of `agents.jonathan.*`,
  because both import the group's `wire_schema` helper, which the wildcard counts as a third sibling.

## Verified

`ruff check src tests scripts`, `mypy` (836 files), `hiru-ai validate` (157 parts, 0 errors; David's 148 plus 9),
`hiru-ai catalog --check`, `scripts/lint_imports.py` (all six `jonathan` contracts kept), `hiru-ai eval jonathan_author` and
`jonathan_revise` (scripted, 2 of 2 each), `tests/jonathan` (125), the agents' own tests, `tests/david`, `tests/hiru_ai/test_core.py`
and `tests/adam/test_removal.py` (274 passed together).

**Not verified, and not caused here:** the SQL (`supabase db reset` and `supabase test db` need Docker); anything that needs a real
model. **Already failing on the original code** (re-run with these changes set aside, the same 21): 11 tests in
`tests/adam/test_system.py`, `tests/adam/test_score_mutations.py` (1), `tests/api/test_handoff.py` (2), `test_looks.py` (1),
`test_production.py` (3), `tests/parity/test_parity.py` (3). And **David's own import-linter contract is broken** in the committed
code (`david_repair` imports the group's `wire_schema`); no David file was changed here.

## Who holds what reaches the frame (2026-11-06, after the first live scene)

The first live Jonathan scene (Episode 1 scene 2, "Kasun Returns Anudi's Phone") painted Anudi on a call before she had
her phone back (S07), Kasun holding her umbrella (S08), Kasun on a call (S11), both her hands on the phone with the
umbrella held up by nothing (S14), a red umbrella (S19) and Kasun beside her as the phone fell (S05). The plan's order
was right; what reached the painter was not. Fixed offline, no model called (`tests/jonathan/test_holding.py` replays it):

| What went wrong | Fix |
|---|---|
| Kasun's shout read as a phone call: `jonathan_write` searched the author's words ("registering the call") | the voice source comes from the script only (`contracts.staging.voice_source`: the line's delivery, then the action) |
| A name in passing put a face in the frame ("Kasun's canopy colour"), and `staging()` added back anyone the action names | `on_screen_of` reads the subjects' descriptions (a body part counts, a possession does not); Jonathan's list is final, like a person's (PromptMotion's `_prune_subjects`) |
| Nothing told the painter who holds what | `contracts/holding.py`: a ledger from the marks, ONE holder per thing (a gift takes it from the giver), a thing's state ("open") from earlier sentences; a `Hands:` line in the frame prompt and the Veo prompt (which also says what passes between hands); close shots keep what is held in frame |
| Jonathan's marks miss changes of hands (10 of the 19 saved lab answers do too) | a `holding` check, fixed by the revise pass: each take, drop and give the script writes must show in the marks at its block (by the thing, never by guessing who "she" is) |
| A prop a person added to every shot was attached to every frame | `references_for`: a known prop is attached only when someone seen holds it or the shot shows it; a held prop with a sheet is added, labelled "held by …"; another place of the production the shot is at (the stall) is attached after the scene's; up to 6 pictures |
| The vision check passed all of it | it is told what each person holds and gives a `Hands · …` chip when the frame differs |

Both frame paths have it (`frame_render/engine/pipeline.py`, the live `AI_ENGINE=legacy`, and the `frame_compose` step), and
both Veo serializers. The lab parity test ignores the new `holding:` faults (the lab never painted). To see it: plan the
scene again with Jonathan, then paint (both cost model calls; the person's decision).
