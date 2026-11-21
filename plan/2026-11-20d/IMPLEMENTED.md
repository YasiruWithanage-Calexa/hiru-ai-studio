# plan/2026-11-20d: what is built (2026-11-20)

Phases 0–6 are built offline in both repos, **uncommitted**. Phase 7: the lab's code is updated (free); its paid run
and the port into the product wait for the person. Phase 8 (live) is the person's. No model was called: every test ran
with `OPENAI__API_KEY=` blank. No enable switch: the agent runs wherever a model can be called.

## Phase 0: who read what (read-only)

| Reader | Before | After |
|---|---|---|
| `design.frame_polish` | `contracts/frame_brief` (polished merge), `steps/frame_compose` (`polished`), API `_polished` / `frame_polished`, `systems/shot_producer/polish.py`, mode `frame_prompt` | gone; `design.shot_prompt` instead (D5) |
| `video_prompter` | `systems/shot_producer` mode `prompt`, tier `video_prompter` | gone; `shot_prompter` (D1, D2) |
| `prompt_writer` / `prompt_polish` | first frame only (since 20b) | gone (D11): nothing else used them |
| `Pins` | `stale_reasons` in `api/services/production`, `core/views`, `serialize/model`, `frame_compose`, legacy engines | + `picture`, `motion` (D8); read by the API service and `frame_compose` |
| "Draw first frame" | `POST …/shots/{id}/frames`, `…/scenes/{id}/frames` → `_start_frames` → `[shot_produce?, frame_render]` | the shot producer runs first when a shot has no current shot prompt (`state.shot_prompts`, D4 a) |
| "Generate video prompt" | `POST …/shots/{id}/prompt`, `…/scenes/{id}/prompts` → mode `prompt` | assembles from the stored shot prompt (D4 b) |
| Scene batch | "Write first-frame prompts" (`/scenes/{id}/frame-prompts`) | "Write prompts for all shots" (`/scenes/{id}/shot-prompts`), kept (Q3 default) |
| A frame's reasons | `FrameView.stale_reasons` → the take card's "Out of date" chip (tooltip) | + the reason text under the card; camera fields named before → after |

## Phases 1–6: where things are

- **1 Contracts.** `contracts/producer.py`: `Pins.picture` / `Pins.motion`, `camera_changes` (named fields, before →
  after), `stale_reasons(..., picture=, motion=)`. `contracts/picture_pins.py`: `picture`, `motion`, `opening_text`,
  `pinned`. `contracts/video_gen.GOOGLE_LINE` last in every Omni prompt with a picture (D10), test holds the attached
  order = the "Image n" order. Tests: `tests/contracts/test_picture_pins.py` (7), `test_video_gen.py` (+1).
- **2 Agent.** `agents/shot_prompter/` (lab system prompt + the video prompter's drama rules and cards, safe-depiction
  line word for word, the new clock/edit rule, video-only mode; schema = the lab's; the scene as its own cached
  message; 5 evals = the lab's five answers). Tier `shot_prompter` (gpt-6.1-sol, medium, 120 s, 1 retry; the caller
  caps output at 12,000). `.env.example` updated.
- **3 Step.** `steps/shot_prompt/` (`camera_facts`, `shot_brief`, `camera_brief`, `check` = the lab's `check()` + D6's
  new checks, `fixed_answer`, `direction`, `frame_parts`, `record`). Fixture: the lab's five shots in product shape.
  D7: `references_block` names no faces when no person sheet is attached; `video_prompt.logic.lower_first`.
  Frame brief (D5): a current shot prompt's words replace the shot+composition, people's places/poses, setting and
  light; code keeps the lead, references, "Who they are" (cards + looks), condition, hands, time, weather, colour,
  mood, unseen and format; a person's lighting change still wins.
- **4 Wiring.** `core/shot_prompts.py` (the one door: facts, `needs` = current / video_only / both, `write` with ONE
  repair). `systems/shot_producer/graph.py`: mode `shot_prompt` ("Rewrite prompts"), `state.shot_prompts` (before a
  frame), mode `prompt` from the stored part (no call while current; video-only when only motion/script moved; both
  otherwise); each video prompt pins picture + motion. `frame_compose.World`: `pins_now`, `shot_prompt_reasons`,
  `shot_prompt`; a frame's picture pin carries the opening it was drawn from. API: `ShotState.shot_prompt(_reasons)`,
  frame / prompt reasons with the camera pins, `ShotProductionView.shot_prompt`, `SceneProductionView.stale_frames`,
  `SceneFramesRequest.only_stale`, `POST …/shots/{id}/shot-prompt`, `POST …/scenes/{id}/shot-prompts`. A Camera agent
  run, an Ask Camera or a camera edit only marks (staleness is computed on read).
  Tests: `tests/hiru_ai/test_shot_prompt_system.py` (12, scripted model), `tests/api/test_production.py` (+5).
- **5 Removals.** `agents/video_prompter/`, `agents/prompt_writer/`, `steps/prompt_polish/`, `contracts/prompt_polish.py`,
  `systems/shot_producer/polish.py`, `PromptWriterSettings` (`PROMPT_WRITER__ENABLED` is now ignored),
  `tests/hiru_ai/test_video_prompt_system.py`, `test_prompt_writer_system.py`; the `frame-prompt(s)` endpoints. Cost:
  the seeded `prompt` estimate $0.01 → $0.02 (one shot prompt); prompt history reads phase `shot_prompter.write`.
  `docs/AI_CATALOG.md` regenerated; `hiru-ai validate`: 199 parts, 0 errors.
- **6 Interface.** `features/production/client.ts` (`requestShotPrompt`, `requestSceneShotPrompts`,
  `requestStaleFrames`), types + mapping (`ShotPrompt`), the frame-prompt dialog's "Rewrite prompts" / "Write prompts"
  and its chip, bulk actions "Write prompts for all shots" and "Redraw out-of-date frames", the filmstrip's
  "Redraw out-of-date frames (n)" button, the reason text under a stale take card, and `ShotPromptOpening` (opening
  state + frame words, read-only) in the video prompt pane.

## Phase 7 (Camera agent update): lab code only

`lab/camera_moves/run.py`: variety counted by FAMILY (§6.4), "the camera" must be the sentence's subject (§6.3), at
most two clips in three at eye level with a turn or power shift (§6.2, a share). `system.md`: the visible-result and
subject rule, the share. Re-checking the saved answers (free): almost every saved sentence fails the subject rule
(they are imperative: "move slowly toward…"); Ekama S03 fails the family rule (forward 13 of 23). The lab's next run
(paid, ~$1 for the seven scenes at the last run's rate) shows whether the prompt fixes them; the port into
`agents/camera_agent` + `steps/camera_design/gates.py` (schema gains `moment`, `intensity`, `power`, `angle_reason`,
`peak_slate`, `arc`) follows it. Q1 is open; the lab keeps obeying the production's own direction.

## Deviations (decide or accept)

1. **Pins as values, not a hash.** `picture` / `motion` store each field's value (long texts as a 12-character hash)
   so the reason can say "angle eye level → low angle". Older pins without them never go stale on the camera.
2. **A frame's opening.** A frame pins the opening of the shot prompt it was drawn from; it is out of date when that
   opening is rewritten ("Rewrite prompts" or a full rewrite), not when the shot prompt goes stale for a move only.
3. **No packet, no shot prompt** (20b's D5 kept): the frame is then painted from code's words and the job warns.
4. **Cost row name kept** as `prompt` (the seeded row the database already has); its value is the shot prompt's.
5. **The lab's answers and the clock check.** Four of the lab's five answers carry clock words ("three-quarters of a
   second", "two seconds"); the new D6 check flags exactly those (test). The eval replies are kept as the lab wrote
   them.
6. **Legacy engine** (`services/shot_producer`) untouched: it still labels its events `prompt_writer`.

7. **Legacy frame engine** (`services/frame_render`) pins the camera's picture and motion too (parity with the graph);
   it paints no shot prompt. The painter fakes in three test files gained the `quality` keyword the painter has had
   since the quality pick (they failed before this plan). Parity fixtures `frame_render/*` and `shot_producer/*`
   re-recorded: the only differences are the new pins and one renumbered digest placeholder.

## Tests (2026-11-21, the person's tree, `OPENAI__API_KEY=` blank, `API__PUBLIC_URL` at its default)

New or changed and passing: shot_prompter (7), shot_prompt step (21), picture pins (7), frame brief (26), video
prompt step (+1), video_gen (+1), shot prompt system (12), API production (34, +5 new), costs, frame_render system and
service (52), parity frame_render + shot_producer, contract tests of the touched parts (30). `hiru-ai validate` 0
errors; import contracts touched by this plan KEPT (the three broken ones are older: `core/camera.py` → rag from 20c,
`media_thumbs`, David's agents). Full suite: 83 failed before the last fixes; what remains is the known set (Adam,
David, Jonathan, Raphael group and `.env` failures, group removal lists, script_split, the legacy DoP prompt length,
reader ingest, canon extract / structure build parity, scene canon chips) and none names a file of this plan.
`tests/hiru_ai/test_contract.py` hangs at random parts (`knowledge_base/production_docs`, `agent/stager`) in this
machine's environment; the touched parts pass. Interface: `npm run check` 527 of 528 (the Raphael panel cap list,
as in 20c); `format:check` warns on 72 files this plan did not touch, its own files are clean.

## Open for the person

- Q1 (production direction vs cinematic-first), Q2 (proposed default built: video-only keeps the frame), Q3 (default
  built: the scene batch stays).
- Phase 7 lab run (paid) and the port; phase 8 live run (paid).
- The interface was not seen in a browser.

## Running it locally (2026-11-21)

The person's first test ran the LEGACY engines: `.env` has no `AI_ENGINE`, and plans 20b, 20c and 20d live only in
`hiru_ai` (the graph engine). `scripts/start-functions.ps1` now starts `hiru-shot-producer` and `hiru-frame-render` on
`graph` whatever `.env` says (an `Engine` field per function; the rest keep `.env`'s value, legacy by default), and
`-Only <names>` restarts just those (it stops what listens on their ports first). Both were restarted that way; the
interface dev server was restarted with a clean `.next/dev` and the production build rebuilt (it still carried the old
Bulk actions labels). Old frames carry no picture pin, so a camera change marks only frames drawn after this plan.

## Audit and fixes (2026-11-21): "the system does not work like the labs"

The person's test of SCENE 03 (Love Hour 4) did not behave like lab/camera_moves and lab/shot_prompts. Found and fixed,
both repos, uncommitted:

1. **Camera agent was the first lab, not the cinematic one.** Phase 7's port was never done: `agents/camera_agent`
   ran lab/camera_agent run 4 ("teledrama… restraint"). Now: `prompts/system.md` = lab/camera_moves/system.md + the
   one-clip section; schema + `moment`, `intensity`, `power`, `angle_reason`, `arc`, `peak_slate`; gates + the lab's
   checks (intensity, bold only at 4-5, angle_reason, "the camera" as subject, variety by FAMILY, the peak strongest,
   at most two in three at eye level with a turn; `locked` = the production's locked-off direction softens the
   shares); merge stores the new fields (+ arc, peak on the block); the Omni table gains the measured first-frame
   results (push, creep, pull out, arc with its visible result: `measured_works`). Evals and the step fixture are the
   lab's chase / Ekama S03 / Api Denna S04 answers. API `CameraDesignView` + workspace show moment, intensity, power,
   angle reason, peak.
2. **Frames were locked to the old Scene board panel** ("keep its composition exactly", painted before the camera).
   A shot with a current shot prompt is now painted from it and the sheets only (`systems/frame_render`); the board is
   no longer a gate for "Draw first frame" (API `PROMPT_STATE`; the panel is attached only as a fallback). A
   same-setup frame drawn before the shot's camera design (or for another picture) is not attached.
3. **Old frames and legacy prompts never went out of date.** `stale_reasons(..., designed=)`: on a shot the Camera
   agent designed, something pinned with no camera ("tripod, does not move at all" prompts, the 18 Nov frames) gets
   `BEFORE_CAMERA`.
4. **Found in the paid run:** the handoff check compared the script line with its quotes against the prompt's words
   without them (every spoken shot refused) → compared by `contracts.sentences.body`; and the spoken words are back in
   quotes in the video prompt, as both labs sent them.

**Paid run (scripts/camera_live.py, the person's yes, cap $3): $2.36.** Raphael + Camera agent $0.25 (5 clips, all
designed: track alongside ×2, push, push-then-hold, hold; 2 off eye level with reasons; peak 3E-1). Shot prompts + 5
medium frames $0.71 (no board; 3B-1 high, 3C-1 raised wide). 3 takes at 360p (counted at 720p, $1.40): 3D-1 track
199 px, 3A-1 track 104 px, 3C-1 push performed. Files: lab/camera_moves/runs/live/.

**Still open:** the scene-state ledger's "Hands" rule line can contradict the shot prompt (3C-1: "Anudi holds the
smartphone… lets go" when it already lies on the ground; the take showed a second phone); 3B-1 put the phone in her
trouser pocket (the plan says handbag); r2v re-fits the opening slightly (known). Legacy engines untouched.

## Timecodes (2026-11-21, lab/timecodes → product)

The lab showed Google's "[a-bs]" timecodes per flow step + "A single continuous shot, no scene cuts." make Omni place
the line and the beats where asked (3D-1 line spread 1.75-4.65 s for an asked 1-5 s, vs 1.95-3.9 s; 3C-1 beats on
time, no duplicate phone; no cuts). Ported, uncommitted:

- `agents/shot_prompter`: `Step.start_s`, `Step.end_s`; prompt section "Timing" (the lab's rule); times only in those
  fields, the clock-word ban on the text stays. Evals: the lab's five answers with ranges.
- `steps/shot_prompt.logic.timing_faults` (in `check`, ONE repair as before): 0 to the take, in order, no gap, whole or
  half seconds, ≥ 1 s a step, a line ≥ its speech time − 0.5 s, ≤ one step per 1.5 s.
- `steps/video_prompt.logic`: `timecodes()` prints "[a-bs] " before each step when every step has a valid range;
  FORMAT then says `SINGLE_SHOT` instead of "Ends on a cut." A stored shot prompt written before (no ranges) is
  assembled exactly as before.
- Tests: timing good/bad pairs, assembly with/without ranges, the prompt, the system test's scripted model.
Live check (~$1: 2-3 shots at 360p) is the person's.

## One prompts button (2026-11-21, the person's decision)

The first frame and the video come from one agent call, so the screen has ONE button: "Write prompts" / "Rewrite
prompts" in the shot workspace's header (beside the status chip). Uncommitted, both repos:

- Mode `shot_prompt` ("Write prompts"): per shot, `prompter.needs()` decides: only the video when only the video is
  out of date (a camera move, the script, or a shot prompt written before timecodes: `shot_prompts.timed`), keeping the
  opening and the drawn frame; else both. Then the video prompt of each shot with an accepted first frame is assembled
  from the new shot prompt (`video_prompts(..., assemble_only=True)`: code only, never a second call).
- API `ShotPromptView.timed`.
- Interface: the header button (+ an amber "Prompts out of date" chip, also when written before timecodes); accepting a
  first frame assembles the video prompt by itself while the shot prompt is current and timed (code only, no spend);
  the video prompt pane is read-only (no Generate / Regenerate); the first-frame prompt dialog lost its "Rewrite
  prompts". The older Production panel keeps the same one action inside its video pane (it has no shot header).
- Tests: the system test for the write-then-assemble and for the timecode-less record (video only, opening kept); the
  workspace's request budget for the header button; the dialog and pane tests updated.

## 2026-11-21: prompts are their own system; Raphael is the only planner

Agreed with the person in chat: (1) "Write prompts" only writes prompts, (2) a separate `shot_prompts` system,
(3) every planner but Raphael is retired, with the classic splitter and the old DoP panel.

- New system `hiru_ai/systems/shot_prompts` (job kind `shot_prompts`, served by the `hiru-shot-producer` function: one
  function, two kinds, as Raphael and canon). Modes: `write` (the header button: agent call per shot, then the video
  prompt assembled by code where a first frame is accepted), `video` ("Generate video prompt"), `frames` (a hop before
  frame_render; inferred when `shot_prompts` is in the state and no mode is, i.e. after a design hop). It never designs:
  a shot with no IR or a stale design is skipped with "Recommend settings first". The handler always runs it as a graph.
- `shot_producer` is design only: `shot_intent` + the Camera agent (no model: the rule camera and NEEDS_MODEL). A shot
  with no IR is not designed ("Plan this scene with Raphael first"). The DoP panel (`shot_writer`, `shot_review`,
  `craft_articulator`, `shot_critic`), the technique palette and the continuity ledger are no longer called; their code
  stays for a later cleanup. Modes `prompt` / `shot_prompt` raise. The design hop hands `shot_prompts` on.
- API: design / camera-ask / frames refuse a scene or shot with no IR (409 PLAN_FIRST); `/shot-prompt` and
  `/scenes/{id}/shot-prompts` refuse a missing or stale design (409 DESIGN_FIRST); frames run
  `[shot_produce?] → [shot_prompts?] → frame_render`; prompts go to `shot_prompts`. `resplit`, Adam/David/Jonathan plan
  and their remove routes answer 410 ("… is retired. Plan the scene with Raphael."); their GET views stay.
- `contracts.build.build_pipeline` is always Raphael's; `ProductionSettings.shot_planner` defaults to `raphael` (old
  names still read). Zora's "Re-plan the scene" follows (it uses the build's last hop).
- Interface: "Re-split" is "Plan with Raphael"; the planner choice lists Raphael only and any stored name reads as
  Raphael; the director page always reads Raphael and a retired planner only while it holds a plan; the header's
  "Write prompts" is disabled unless the design is current (title says "Recommend settings first"); activity names
  `shot_prompts` "Shot prompt agent".
- Tests: `test_shot_prompt_system.py` runs the new system over planned, designed fixture shots (new: stale design
  refused, no plan refused, mode inferred after the design hop); the camera system test's "no IR goes to the DoP" is now
  "not designed, says Plan with Raphael", plus the rule camera with no model; parity marks the shot_producer cases
  diverged (RETIRED_DOP); API tests seed planned shots and check the new kinds, the 409s and the 410.
- Not done: no deploy step is needed (same function), but the local function must be restarted
  (`scripts/start-functions.ps1 -Only hiru-shot-producer`); deleting the retired code; no browser check.
