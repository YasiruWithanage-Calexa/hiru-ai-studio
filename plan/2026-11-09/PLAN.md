# Scene state ledger: where people are, what they hold, how they stand, carried into every Raphael shot (plan/2026-11-09)

Status (2026-11-09): **phases 0-8 built offline, uncommitted** (see [IMPLEMENTED.md](IMPLEMENTED.md)). The person agreed
the approach after the report and the diagrams ([Shot Detail Flow](https://claude.ai/artifact/EJhCP9pDyYya5PHivocdTQ)).
Nothing here calls a model until phase 9, and phase 9 needs the person's yes and a budget.

## In plain words

Raphael splits a scene into good clips, but each clip guesses on its own where people stand, which hand holds the phone,
whether someone is lying down or dead. Nothing remembers what the clip before it decided, and the little it does write
(`subjects[].position`) never reaches the Veo prompt. PromptMotion's Nova avoids this: the story of each shot is fixed
before the camera, every shot has an opening and a closing state, and a ledger carries state from shot to shot.

The fix: **one small model call per scene writes a state ledger** (the existing `stager`, given more fields), saved on
the scene (`scenes.staging`, already there). After that, **code** gives the state at any block for free. Raphael reads it
in its script listing, code works out each clip's opening and closing state from it, checks report a clip that
contradicts it, and the write step and the prompt builder put it into the shot and the Veo text.

```
script blocks ──► stager (1 call, extended) ──► scenes.staging  ← the ledger (memory, saved once)
                                                    │  read by code, free:
          ┌─────────────────┬───────────────────────┼──────────────────────┬────────────────────────┐
     Raphael listing   clip opens / ends       state checks          raphael_write            Veo prompt
     "| now: …"        (first / last block)    (report)              intent.story / opens     Subjects + Story + hands
```

## 1. Why (the findings, 2026-11-09)

| # | Where detail is lost | Evidence |
|---|---|---|
| 1 | The Raphael build skips `SCRIPT_SPLIT`, so the `stager` and `scene_reader` never run: `scenes.staging` stays `{}` | `contracts/build.py` `BUILD_PIPELINE_RAPHAEL`; plan/2026-11-08f finding 5 |
| 2 | One call writes story, coverage, camera and repairs: state is invented per clip | `raphael_planner/prompts/system.md` |
| 3 | No opening or closing state on a clip ("Hiru shots carry no `out_state`") | `steps/serialize/continuity.py` docstring |
| 4 | `moment.what` / `feeling` stay in `scenes.raphael`; the shot's `emotional_beat` is saved `""` | `steps/raphael/raphael_write/logic.py` `intent_of` |
| 5 | The Veo Subjects section is `description — action`; `subjects[].position` is dropped | `steps/serialize/logic.py` `build_sections` |
| 6 | `hands_for` reads `scenes.staging`: empty for Raphael, so no hands sentence | `contracts/holding.py` `hands_for` |
| 7 | Raphael's agents have no `production_memory` middleware | `agents/raphael/*/component.yaml` |

Lab run 3 (Episode 1, the roadside, `lab/raphael/runs/3-gpt_5_high_episode1/bin.json`): c05 "accepts the phone" with no
hand giving it; c06 decides "phone now in left" alone; c07 puts Kasun back "by the counter, hand near the flask" after he
ran after Anudi in b6; Anudi's handbag is in her description and never placed.

## 2. What is already there (reuse, do not rebuild)

- `contracts.stagemap.SceneStaging` / `Mark` (zones; per person, from block N on: `zone`, `facing`, `frame_side`,
  `holding`), `validate` (an invalid entry is dropped, not repaired), `mark_at`, `stale`, teleport / line-crossed /
  eyeline checks. Stored in `scenes.staging` (jsonb, `extra="ignore"`).
- The `stager` agent (`model: medium`, structured output) and `steps/scene_prep` `staging_for` (keeps a person's map and a
  map still current for this script version; makes one otherwise), `make_staging`.
- `contracts.holding`: `Ledger.of(marks)` (one holder per prop, handovers as `Change`s), `shot_hands`, `hands_for`
  (reads `scenes.staging` for every planner except Jonathan), `window` (a clip with no block plays the block before).
- `steps/feeling` `positions_text` / `Place` (zone, facing, side, holding) and the serializer's continuity ledger.
- API `GET/DELETE /scenes/{id}/staging`, `SceneView.staging`; interface `features/director/components/staging-map.tsx`.

## 3. Decisions

| # | Question | Recommended | Why |
|---|---|---|---|
| D1 | Extend the existing `stager`, or build a new reader? | **Extend** | one map for every planner; Adam, David, Jonathan get the fields too |
| D2 | Does a clip that contradicts the ledger block `finish`? | **Report only** until the lab (phase 9) | a wrong ledger must not trap Raphael; decide blocking on evidence |
| D3 | For Raphael, insert implied walks into the script (`scene_prep.stage` does for others)? | **No**, map only (`staging_for`); a teleport is a report to Raphael | Raphael never changes the script; his clips can show the walk |
| D4 | Put the opening / closing state into the Veo prompt for all planners or Raphael first? | **Raphael first** (`planner == "raphael"`) | `tests/raphael/test_isolation.py`; other planners' prompts do not move under them |
| D5 | Can a person edit the ledger before planning? | **Later plan** (`PUT /staging`); this plan shows it read-only and re-reads a person's map (`by: "person"`) | keeps this plan small; the hook (`staging_for` keeps a person's map) is already there |
| D6 | Model tier for the stager | **Unchanged** (`medium`) | it is one small structured call; the lab can try `low` |

## 4. Phases

Each phase is offline, tested, and leaves the product working. Order matters: 1 → 2 → 3 → 4/5/6 → 7 → 8.

### Phase 0: gold fixture and baseline ($0)

- `tests/raphael/fixtures/staging.json`: a hand-written ledger for the Episode 1 roadside scene (b0–b22) in the phase 1
  shape: Kasun and Anudi (zone, posture, facing, side, left / right hand, condition), props (phone, umbrella, handbag,
  tea flask). Written by a person's reading of the script, checked against the scene text.
- A second fixture, `staging_body.json`: plan/2026-11-08f scene 1 ("Aruni Finds Nimal's Body"): Nimal `lying`,
  condition `dead`, from block 0. The case the person named (alive or dead, standing or lying).
- `tests/raphael/test_state_baseline.py`: runs phase 6's checks over run 3's stored bin with the gold ledger and pins the
  faults it finds (expected: c05 handover not shown, c07 Kasun's zone, the handbag never placed). This is the "before"
  number phase 9 compares with.

### Phase 1: the contract (`contracts/stagemap.py`, `contracts/holding.py`)

`Mark` gains, all optional with `""` defaults (old stored maps read unchanged, no DB migration):

| Field | Values | Notes |
|---|---|---|
| `posture` | `standing`, `sitting`, `kneeling`, `crouching`, `lying`, `walking`, `running`, `""` | closed list, `POSTURES` |
| `left_hand`, `right_hand` | short text ≤ 60 ("the phone", "") | which hand; `holding` stays as the list of things, for `holding.Ledger` |
| `condition` | short text ≤ 40 ("dead", "unconscious", "injured: left arm", "soaked") | `""` = ordinary, alive |
| `wearing` | short text ≤ 80, only when it changes from the canon look ("jacket off") | |

New `PropMark` (`block`, `anchor`, `prop`, `where` ≤ 60, `state` ≤ 40): a prop that is NOT in a hand ("phone · on the
ground by the three-wheeler", "umbrella · open, on the counter"). `SceneStaging.props: list[PropMark]`, `MAX_PROPS = 30`.

`validate` grows the same way: an unknown posture is dropped to `""`; a `left_hand` / `right_hand` thing is added to
`holding` when missing (so `holding.Ledger` keeps one holder per prop); a `PropMark` must name a block that exists. A prop
put in a hand at block N ends that prop's `PropMark` at N, and the reverse (code, so the two never disagree).

Pure functions (no model), the "memory" every step reads:

- `state_at(staging, items, block) -> SceneState`: for each person their latest mark at or before `block`, for each prop
  its holder (from `holding.Ledger.at`) or its `PropMark`.
- `SceneState.person_text(who)`, `.prop_text(key)`: one short phrase each ("Kasun: running, pavement, phone in right
  hand"), at most `STATE_CHARS = 160` a person.
- `delta_text(before, after) -> str`: only what changed ("Anudi: phone in left hand; phone: Anudi's left hand").
- `clip_state(staging, items, blocks) -> (opens, ends)`: the state at the first block, and after the last block
  (`holding.window` for a clip with no block of its own).

`holding.Hands` sentence says the hand when the mark says it ("the phone in her right hand"); a mark without a side
reads exactly as today (pinned by the existing holding tests).

Tests: `tests/contracts/test_stagemap_state.py` (validation of every new field, old maps unchanged, `state_at` across
handovers and a dropped prop, `delta_text`, `clip_state` with and without blocks); the existing stagemap and holding
tests stay green.

### Phase 2: the stager writes the new fields (`agents/stager`)

- `schema.py`: `Mark` gains `posture` (Literal), `left_hand`, `right_hand`, `condition`, `wearing`; `Output` gains
  `props: list[PropMark]`. Every field required, `""` allowed (OpenAI strict mode).
- `prompts/system.md`, about six lines, the same voice: posture and hands at every mark where they change; a
  hand only when the script says or plainly implies it ("picks it up" → the hand that picks it up, the other hand keeps
  what it held); `condition` from the script ("finds his body" → `dead`, lying, from the block he is first seen);
  props that leave a hand get a `props` row ("drops her phone near the three-wheeler" → phone, on the ground by the
  three-wheeler). Never invent a prop the script and the place card do not give.
- `evals/cases.yaml`: the roadside (handover, dropped phone, umbrella) and the body scene (lying, dead).
- `make_staging` passes the new fields through `validate`. Everything that runs `script_split` (Adam, David, Jonathan's
  pipelines) now gets them too; the kernel score reads only zones and sides, so plans do not change.

Tests: the agent's own test on a scripted model (fields round-trip; a junk posture is dropped), `scene_prep` tests.

### Phase 3: Raphael gets the ledger (`systems/raphael/raphael_shot_planner`)

- In `plan_one`, before the `Planner` is built: `items = sceneplan.items_for(sc.script, lines)`;
  `staging, made = scene_prep.staging_for(sc, items, ask, cast)` with the same `staging_ask` shape as `script_split`
  (`reading_text` from a person's reading when there is one, the place card). A current stored map or a person's map
  costs nothing; otherwise ONE stager call, tagged with the scene id (`replace(ctx, scene_id=…)`). No implied walks (D3).
- A stager failure is not a Raphael failure: plan as today (no ledger), job event "No state map for this scene; planned
  without it".
- The map is saved with the shots in the main thread (`SceneStore`, the same transaction as `replace_shots`), only when
  `made`.
- `Planner.input_hash()` includes the map's marks and props, so a changed (or person-edited) map re-plans.
- The `Planner` and both sessions carry `staging` for phases 4–6.

Tests: `tests/raphael/test_system.py` (a stored current map makes no call; a stale one makes one; a failing stager still
plans; the map is saved; the hash moves with the map).

### Phase 4: Raphael reads the state (`contracts/raphael/scene.py`, `pack.py`, prompts)

- `BlockS.now: str = ""`: `delta_text` of the state before this block → at this block, filled by the system from the
  ledger; `SceneS.opening_state: str`: every person and prop at the first block.
- `listing` prints `At the start: …` under `Present:`, and `| now: …` after a block whose state changes. A block
  with no change prints nothing extra. Cap the whole addition at `STATE_LISTING_CHARS = 2400` (drop prop rows first).
- Both prompts (`raphael_planner`, `raphael_cinematic`) gain three lines in "The design of a clip":
  *"The listing gives each person's place, posture, hands and condition, and where the props are, from the block where
  they change. Your `subjects[].position`, `action`, `beats` and `first_frame` follow it: never put a thing in another
  hand, a lying person on their feet, or a dead person breathing. When a thing passes between hands inside your clip,
  show who gives it and which hand takes it."*
- `tests/raphael/test_lab_parity.py`: allow exactly these lines and the listing addition (as plan/2026-11-08f did).

Tests: listing on the gold scene (golden text), the cap, no change when the scene has no map (old behaviour, byte for
byte).

### Phase 5: each clip's opening and closing state (code)

- `contracts/raphael/state.py`: `clip_states(scene, staging, work) -> dict[clip id, (opens, ends)]` over the blocks a
  clip covers; a stage 2 clip with no blocks uses its anchor's blocks (`anchor`), then `holding.window`.
- The check report (phase 6) and `read_bin` show a clip's `opens` / `ends` when asked for one moment, so Raphael can
  see the state he must meet without it costing every turn.
- Stored on the shot in phase 7; never written by the model, so no output tokens.

### Phase 6: state checks, report only (`contracts/raphael/checks.py`)

`state(scene, staging, work) -> list[Fault]`, owner `raphael`, not blocking (D2), in `check_stage1` and
`check_stage2`. Each fault names the clip, the block, what the ledger says and the fix. Word lists in code, the way
`designs` already scans picture text (`clip_text`, `strings_of`):

| Key | Fires when | Example message |
|---|---|---|
| `state:hand` | a clip puts a prop in a person's hand (or a named hand) the ledger gives to someone else at those blocks | "c06 (b10): 'phone now in left' fits; c05 (b9): the phone is Kasun's (right hand) as the clip opens" |
| `state:handover` | the ledger has a `Change` inside the clip's window and the clip names the prop but not both people or the taking hand | "c05: the phone passes from Kasun to Anudi at b9: show his hand giving it and her left hand taking it" |
| `state:posture` | the clip's subject words say a posture the ledger contradicts (`lying` vs stands / walks; `sitting` vs runs) | "c02: Nimal is lying from b0; 'stands' contradicts it" |
| `state:condition` | a `dead` / `unconscious` person breathes, blinks, speaks, moves on their own, or has `speaks` true | "c03: Nimal is dead; 'his chest rises' contradicts it" |
| `state:off` | a person is in `subjects` while the ledger has them `off` for every block of the clip | |
| `state:zone` | a subject's `position` names one of the map's zones other than the ledger's | "c07 (b12): Kasun is on the pavement; 'by the counter' is the stall: show him walk back or keep him on the pavement" |
| `state:unplaced` | a prop the ledger holds (a handbag) is never in any clip of the moments where its holder is on screen | report once per scene, not per clip |

Tests: mutants for every key on the gold scene and the body scene; no fault on a clip that matches; no check at all
without a map; phase 0's baseline faults pinned.

### Phase 7: into the shot and the Veo prompt (`raphael_write`, `serialize`)

- `contracts.staging.ShotIntent` gains `story` (≤ 300), `opens` (≤ 400), `ends` (≤ 400), `""` defaults (jsonb, no
  migration; `stamp()` includes them so a changed ledger marks the design out of date).
- `raphael_write.intent_of`: `story` = the moment's `what` (and the part, for a long action); `emotional_beat` = the
  moment's `feeling`; `opens` / `ends` from phase 5.
- `serialize/logic.build_sections`, for `planner == "raphael"` (D4):
  - **Subjects**: after `description — action`, the subject's `position`, then `Opens: …` / `Ends: …` from the intent.
  - **Story**: a new section, one sentence, from `intent.story` (rule text in the clip schema YAML, as the other rules).
  - **Hands**: nothing to do: `hands_for` reads `scenes.staging`, now written for Raphael scenes (phase 3).
- `frame_render` (first frames) reads the same `opens` for the image prompt, so the still and the video agree.

Tests: `steps/serialize` golden prompt for a Raphael shot with and without a ledger (without: byte for byte as today);
`raphael_write` tests; `tests/raphael/test_isolation.py` proves Adam / David / Jonathan prompts unchanged.

### Phase 8: production memory and the interface

- Backend: `raphael_planner` and `raphael_cinematic` gain `production_memory` with `memory: [camera, visual, lighting,
  performance]`. If the middleware does not fit the `loop` shape, put the same entries into `<production>`
  (`pack.production_part`) instead: once, in the cached first message.
- API: the scene's Raphael view gives each shot `story`, `opens`, `ends` and the state faults.
- Interface (`hiru-ai-studio-interface`, its rules: TanStack Query, `<Chip tone>`, no `router.refresh()`):
  `src/features/raphael`: each clip card shows **Opens / Ends** (two quiet lines) and state faults as chips; the Raphael
  tab shows the existing `StagingMap` read-only (moved to a shared place, not copied). No editing (D5).

### Phase 9: the lab (the person's yes and budget; nothing paid before)

- Estimate ~$0.60 hard budget: the stager on Episode 1 scenes 1–3 (~$0.03) and Raphael stage 1 + 2 on the same three
  with the ledger (~$0.50, arm C settings).
- Compare with the baseline (phase 0) and lab arm C: state faults per scene, repair turns, cost per scene, and the
  person's read of the c05-like clips' prompts and first frames.
- It decides D2 (blocking) and D6 (stager tier).

## 5. Cost (estimates, unmeasured)

| Item | Extra per scene |
|---|---|
| Stager call (once; free when the stored map is current) | ≈ $0.005–0.01 |
| State in the listing (cached first message, ≤ 2400 chars) | ≈ 300–800 input tokens |
| Opens / ends, checks, write step, prompt | $0 (code) |
| Repair turns | should fall; report-only faults add a few lines to each report |

Target unchanged: about $0.30 a scene (plan/2026-11-08f).

## 6. Risks

- **A wrong ledger makes every clip wrong the same way.** That is still better than each clip wrong differently, and it
  is visible in one place. Mitigation: report-only checks (D2), the map on the Raphael tab, a person's map wins (D5 later).
- **Listing growth.** Capped (phase 4); measured on the gold scene in tests.
- **Word-list checks miss or over-fire.** Report only; mutants pin both directions; the lab decides.
- **Other planners now get more stager fields.** Their plans read zones and sides only; the hands sentence changes only
  where a mark names a hand (phase 1 test).

## 7. Done when

- `ruff`, `mypy`, import-linter clean; `pytest tests/raphael tests/contracts src/libs/hiru_ai/agents/stager
  src/libs/hiru_ai/steps/serialize src/libs/hiru_ai/steps/raphael` green.
- Interface: `npx next typegen && npm run check && npm run format:check`.
- `IMPLEMENTED.md` in this folder lists what was built and what is left; the lab is the person's.

## Open: the person's

- D1–D6 (recommendations above).
- The lab (phase 9): yes and budget.
- Whether to bring the ledger into the Veo prompt for Adam, David and Jonathan after the lab (D4).
