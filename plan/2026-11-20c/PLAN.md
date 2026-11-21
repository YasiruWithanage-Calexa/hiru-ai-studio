# The Camera agent designs every shot's camera (plan/2026-11-20c)

Revision 1 (2026-11-20). Agreed with the person in chat on 2026-11-20. Building status: IMPLEMENTED.md (phases 0–6 built offline 2026-11-20; 7's lab and 8 are paid).

Why: takes come out with a static camera. Raphael writes most coverage `locked_off` (19 of 22 clips in the connected
run); the camera panel knows 5 moves and `raphael_write.camera_hint` → `move_of()` turns every other move into "" →
`default_camera()` → **Static**; the video prompt then says "a steady, unmoving frame". On Api Denna E01-S04 today's
panel is Static on **every** clip, including the ones Raphael planned to move.

Proof: `lab/camera_agent` (read its `README.md` first). One reasoning agent designed S04 and S01 from Raphael's saved
plans, then a **fresh Raphael run → Camera agent** connected (`connected.py`): 22 clips, 18 real moves of 8 kinds, 4
motivated holds, 0 check faults, $0.099 a scene. Six Omni takes measured what the video model really does: a forward
push is performed (one face and a two-shot); a float, a handheld shake and a sideways drift come out as still as a
tripod.

## 0. Rules for the chat that builds this

- **No paid call without the person's yes, each time** (model, image, video). Tests run with `OPENAI__API_KEY=` blank.
- **Only Shot Planner Raphael stays.** Do not build for Adam, David, Jonathan or DaVinci; ignore their test failures.
- **The planner owns the story; the Camera agent owns the camera.** It never changes who is in a clip, what happens,
  the lines, the take length or the **shot size** (the size the clip opens on). Lighting is not its job.
- **Never name camera gear in a prompt** (tripod, dolly, slider, crane, jib, gimbal, steadicam, rig, drone, track):
  the video model draws it (render 007).
- **No cost in the UI** (CLAUDE.md), except the existing rules.
- **Both trees have uncommitted work.** Read `git diff` of a file before you edit it. Never stash; use a worktree to
  compare.
- **The lab is the reference.** `lab/camera_agent/system.md`, `omni.md`, `kb.py` and `run.py` (brief, catalogue,
  checks) were proved; port them, do not rewrite them from memory. Where this plan and the lab differ, this plan wins.

## 1. What the person asked for

1. **One Camera agent** (gpt-6.1 with reasoning, no sub-agents, not a multi-AI panel) that does **everything the
   camera does** for every shot: how it is held, the move, its path, speed and timing, what motivates it, angle,
   height, lens, stop, focus, composition, time (slow motion…), axis, and the camera sentence the video model gets.
2. **The whole camera catalogue**, not today's 5 moves: every move the cinematography knowledge base names that the
   video model can use (lab: 51 moves, 15 supports).
3. **The planner chooses the shot size**, not the Camera agent. Lighting stays out.
4. **The cinematography knowledge base** (`knowledge_bases/cinematography`, 629 terms) is the toolbox: what each move
   does and when to use it, and ideas per clip.
5. Raphael + Camera agent **connected as in the product**, giving varied, motivated moves (proved in the lab).
6. **UI additions as needed** (the camera card shows the new fields; a person can still change any field).
7. Address the two issues the connected run showed (§6): every clip at eye level; moves mostly forward/back.

## 2. Decisions

| # | Decision | Why |
|---|---|---|
| D1 | New agent `camera_agent` (`libs/hiru_ai/agents/camera_agent/`) + new pure step `camera_design` (`libs/hiru_ai/steps/camera_design/`: brief, knowledge base menu and ideas, gates, merge into the design row, the sentence template). The agent decides; the step owns every fact and check. Not the old `cinematographer` agent (director board operations, framing codes only): leave it alone | The house pattern (model writes, code checks). The lab's split |
| D2 | Model tier `camera_agent` in `core/models.yaml`: `model_camera_agent` = `gpt-6.1-sol`, `effort_camera_agent` = `medium`, timeout 180 s, retries 1, structured output, `max_output_tokens` 16000 | The lab's model and effort (runs used ~6–7k output, 77–88 s a scene) |
| D3 | **One call per scene**, every clip in cut order (moves are designed across cuts). A **one-shot call** for an edit: the scene's clips and their current camera as context, the answer for that shot only | Lab: scene $0.09–0.10; "Ask Camera" redo $0.04, 16 s |
| D4 | **Size is fixed**: the clip opens on the planner's size (`shots.framing`); the agent reports `end_size` for a push or pull. The bin, board and checks keep the planner's size | The person, 2026-11-20 |
| D5 | **Storage, no migration**: `shots.design.recommended` keeps today's 8 fields (values from the wider lists, D6) and gains the new optional fields (`support`, `height`, `focus`, `composition`, `time`); a new `shots.design.camera` block holds the agent's design (`move`, `direction`, `speed`, `start_s`, `end_s`, `trigger`, `motivation`, `opens_on`, `lands_on`, `end_size`, `rack_*`, `composition_note`, `omni`, `why`, `camera_sentence`, `language` (the scene's camera language), `model`, `job_id`). A person's changes stay in `shots.camera_overrides` | `design` is jsonb and is already where the recommendation lives (`ShotInput.recommended`, `scene_states`). Phase 0 confirms no reader breaks on extra keys |
| D6 | **The catalogue becomes data** in `contracts/camera.py` (new): moves, supports, speeds, sizes (+ `MWS`, `MLS`, `ECU`, `EWS`), angles (+ slightly low/high, worm's-eye, dutch), heights, lenses (18–135 mm incl. 32/40/55/65/75), apertures (+ f/8), focus, composition, time, axis; each move with its knowledge-base term (`kb.MOVE_TERM`), its family (still / forward / back / lateral / around / rotate / vertical / lens / aerial / transition), min seconds, fast or not. `CAMERA_OPTIONS` (producer.py) and the interface's `camera-options.ts` are generated from / mirror it. **Old values map** (`Static`→hold, `Dolly in`→push_in, `Dolly out`→pull_out, `Pan`→pan_right, `Handheld`→handheld_subtle + hold) so stored designs and overrides still validate | One list for agent, panel, checks and prompts |
| D7 | **Omni capability table as data** (`contracts/camera.py` `OMNI`): measured rows (forward push works incl. two-shot; float/shake/sideways drift render still) + provisional rows (lab `omni.md`). Floats count as holds in every check. The table is in the brief | Measured 2026-11-20: 6 takes |
| D8 | **Knowledge base**: the menu (one line per move: effect + use case) is built from `craft_techniques` / the CSVs through the mapping; the per-clip **ideas** come from `TechniqueRetriever` (embedding search, k=4, the clip's purpose, intent, delivery and mood as the query), filtered to moves that fit (no fast move on a speaking face, aerials only on exterior masters, length fits the take). Absent-safe: no search → no ideas, the menu still goes | Lab run 3: the menu widened the moves; keyword ideas were noisy (the "dialogue" tag pointed at a crab shot), so use the embedding search |
| D9 | **Gates** (port `lab/camera_agent/run.py` `check_clip` / `check_scene`): slates complete and in order; move inside the take, long moves have time; speaking face: no fast/whip/shake/orbit, no slow motion; push lands tighter, pull wider, others keep size; sentence: no gear, no line ids/Sinhala, no timid words, no picture rules, no edit/clock words, ≤ 200 chars, agrees with the fields; rack focus complete; holds + floats ≤ 1 in 4; no move on more than about a third of the clips; **angle/height not all eye level in a scene of 6+ clips (new, §6)**. Advisories: three in a row, setup support differs, axis changes | All proved in the lab except the angle gate |
| D10 | **Failure**: ONE repair call with the faults (whole answer). Clips still faulty after it keep today's rule recommendation, marked `design.camera.state = "not designed"` with the faults, and the job adds a WARNING; the rest of the scene keeps the agent's design. No key / models off: today's behaviour, and the job says "the Camera agent needs a model" | A planned scene must still produce shots; a fault in one clip must not lose the other 21 (the person decides otherwise, see §8 Q1) |
| D11 | **Where it runs**: (a) `raphael_shot_planner` after stage 2, before `raphael_write` (its result per clip goes into the entry instead of `camera_hint`); (b) the Zora/Sable row kernel (`core/coverage_rows.py`) for the shots a turn adds or changes, one-shot mode with the scene as context; (c) "Recommend settings for all shots" (`POST …/scenes/{id}/design`): the scene again; (d) **"Ask Camera"** (new `POST …/shots/{id}/camera/ask {note}`): one shot. A person's field change (`PATCH …/camera`) makes **no** call | The lab's four paths |
| D12 | `camera_hint` / `move_of` are removed from `raphael_write`; `default_camera()` stays only as the D10 fallback and for shots no agent has seen | They are what lost the moves |
| D13 | **The camera sentence**: the agent's `camera_sentence` is the camera of every prompt while the person has not changed a camera field; after a change, code writes it from the fields (`contracts/camera_words.py` rewritten for the new fields: a hold says "holds still", a move says "the camera slowly pushes in…", never gear). The video prompter **no longer writes the camera**: the `video_prompt` step puts the sentence in (`Camera:` section); its "keep the planner's camera / locked-off stays locked off" rule and gate go, `facts.locked_off` reads the design's move | One owner of the camera words; the lab swapped only that line and the take moved |
| D14 | **Frame brief**: the first frame is drawn at the move's OPENING: `opens_on`, the planner's size, the design's lens, angle, height and composition (`frame_compose`, `contracts/frame_brief.py`). The last frame (where used) follows `lands_on` | Text-to-video takes opened wider than planned; the first frame fixes it |
| D15 | Raphael is **not changed** in this plan: its `ir.cinematography` stays (frame brief, beats, the agent's hint). A stage-2 cinematic clip whose reason is its technique (a drone reveal, a dolly-out exit) keeps that move family unless the Omni table says avoid; the agent says why in `why` | Lab: the agent kept the crane and the dolly-out exits on its own; make it a rule |
| D16 | Scene camera language stored on each shot's `design.camera.language` (no scene column) | No migration; the UI shows it once |
| D17 | Switch `CAMERA_AGENT__ENABLED` (default **on** once phase 7 passes; off = today's path) | A safe rollout |
| D18 | Cost estimate row `camera` in `contracts/costs.py`: $0.10 a scene, $0.04 an Ask (admin price list only; never in the UI). Langfuse traces it like every agent | The lab's figures |

## 3. The agent

`libs/hiru_ai/agents/camera_agent/`:

- `component.yaml`: `id: camera_agent`, `kind: agent`, `model: camera_agent` (tier), `shape: structured`,
  `phase: camera_agent.design`, middleware as `video_prompter` (`static_first, usage, untrusted_text, absent_safe`),
  `writes_dialogue: false`.
- `prompts/system.md`: `lab/camera_agent/system.md` as of run 4 (dialogue life from real slow creeps/pushes/pull-outs;
  floats count as holds; variety; holds with reasons; the camera sentence rules), plus §6's angle/height line.
- `schema.py`: the lab's `ClipCamera` / `SceneCamera` / `OneClip`, with the Literals taken from `contracts/camera.py`
  (D6) so schema, checks and panel cannot drift. `Input`: `scene` (the scene + script part, cache prefix), `menu`,
  `clips`, `omni`, `focus_slate` (one-shot mode), `note` (an Ask), `repair` (faults).
- `evals/`: 5 cases from the lab's answers (S04 run 4, S01, connected S04): a dialogue single (creep), the father's
  demand (push then hold), the caller display (hold), a closing exit (pull out), an Ask ("visible push").

## 4. The step `camera_design`

`libs/hiru_ai/steps/camera_design/`: `brief.py` (port `clips_brief`, scene part identical for every call of a scene),
`kb.py` (menu + ideas, D8), `gates.py` (D9), `merge.py` (the answer → `design.recommended` + `design.camera`, D5; the
fallback, D10), `words.py` (D13's template). Pure, no database. Fixtures: `tests/fixtures/camera_e01_s04.json` (the
saved Raphael run + lab answers through the product code) and the connected run's 22 clips.

## 5. Phases

| # | What | Done when |
|---|---|---|
| 0 | **Read-only**: what "Recommend settings for all shots" does today for Raphael shots (DoP agent vs `raphael_write` design); every reader of `design.recommended` / `CAMERA_OPTIONS` / the 5 movement values (frame_compose, frame_render pipeline, coverage scene, critic, board note, costs `designed`, interface); old values in the live data (counts only, no write) | A list in IMPLEMENTED.md |
| 1 | `contracts/camera.py` (catalogue, old-value map, Omni table, KB mapping), `CameraSettings` widened with aliases, `camera_words` rewritten | Old designs and overrides validate; tests |
| 2 | Agent `camera_agent` + tier + evals | Offline tests; eval shape checks |
| 3 | Step `camera_design` (brief, kb, gates, merge, words) | The lab's answers pass the gates; good/bad pair per gate |
| 4 | Wiring D11 (Raphael, row kernel, design job, Ask endpoint), D12 removals, D17 switch, D18 cost row | System tests with a fake model |
| 5 | Downstream: `video_prompt` step and `video_prompter` prompt (D13), frame brief (D14), board note ("50mm · slow push in on L4") | Prompt and frame tests updated |
| 6 | **Interface**: `camera-options.ts` mirror; the camera card grouped (Move & timing · Lens & focus · Angle & height · Composition), the agent's *why* and the sentence under it, the scene's camera language once on the scene; an **Ask Camera** box (note → `POST …/camera/ask`, the result put in the cache via the shot actions, no `router.refresh()`); a hold with no reason never shown as "Static" | `next typegen && npm run check && npm run format:check` |
| 7 | **The two issues (§6)** in the lab first, then the prompt and gates | The lab's checks pass on S04 + a moving scene |
| 8 | **Live (paid, the person's yes each time)**: the product's Raphael → Camera agent on S04 and one scene with walking / a reveal; then 3 Omni takes **with the first frame** (`reference_to_video`): a two-shot push, a small "stay in size" creep, a lateral or tracking move | Varied moves in the product; the takes move as designed |

## 6. The two issues from the connected run

1. **Every clip at eye level, height always "eye".** Add to the system prompt: angle and height carry power and
   feeling (a low angle on ambition or authority, a slightly high one on someone diminished, shoulder height for
   intimacy); vary them across a scene with a reason in `why`. Gate: in a scene of 6+ clips not every clip is eye
   level/eye height (repair, not fallback). Check in the lab on S04 and S01 before porting.
2. **Moves mostly forward/back** (15 of 18). Partly right for a standing talk and for what Omni performs. Prove the
   rest: run the lab on a scene with walking, an arrival or a reveal (Api Denna S02/S03, or a scene the person names)
   to see track / lead / follow / arc / crane / tilt reveal chosen where they fit; render one lateral or tracking take
   in phase 8 to move those rows of the Omni table from provisional to measured.

## 7. Not in this plan

- Changing Raphael's own camera vocabulary or prompt (D15).
- The old planners (Adam, David, Jonathan, DaVinci) and the legacy engine (`AI_ENGINE=legacy`).
- Lighting.
- Moving the scene camera language to a scene column (D16 keeps it on the shots).

## 8. Open for the person

- **Q1 (D10)**: a clip whose camera still fails after one repair: keep today's rule recommendation for it (proposed),
  or no camera design at all (the shot waits for a press)?
- **Q2 (D2)**: effort `medium` (proved) or try `high` for bolder choices at ~2× the cost, in phase 7's lab?
- **Q3 (D17)**: switch on for every production once phase 8 passes, or per production first?
- **Q4 (§6.2)**: which scene to use for the moving-scene check (a confrontation, chase or reveal)?
